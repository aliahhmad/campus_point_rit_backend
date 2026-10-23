"""Check expiry against PostgreSQL, row locks, and prepared transactions."""

import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import status

from app.config.settings import get_settings
from app.managers.expiration import expire_requests
from app.transactions.postgres import connection, quoted_gid
from tests_workflow.conftest import Workflow
from tests_workflow.test_acceptance import authenticate

ROOT = get_settings().api_root
pytestmark = pytest.mark.asyncio


async def seed_request(
    workflow: Workflow,
    request_status: str = "open",
    moderation: str = "visible",
    *,
    overdue: bool = True,
) -> int:
    """Create a funded request and set its clock and moderation for a scan."""
    created = await workflow.client.post(
        ROOT + "/requests",
        json={
            "location_id": 1,
            "title": "Expiry test",
            "description": "A request",
        },
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    request_id = created.json()["request"]["id"]
    async with connection(workflow.campus_url) as conn:
        await conn.execute(
            "UPDATE requests SET status=$1,moderation_status=$2,"
            "created_at=CURRENT_TIMESTAMP-interval '2 hours',"
            "expires_at=CURRENT_TIMESTAMP+$3::interval WHERE id=$4",
            request_status,
            moderation,
            timedelta(hours=-1 if overdue else 1),
            request_id,
        )
    return request_id


@pytest.mark.parametrize(
    ("request_status", "moderation", "overdue", "expected"),
    [
        ("open", "visible", True, "expired"),
        ("under_review", "visible", True, "expired"),
        ("open", "hidden", True, "expired"),
        ("open", "pending", True, "expired"),
        ("open", "visible", False, "open"),
        ("under_review", "visible", False, "under_review"),
        ("completed", "visible", True, "completed"),
        ("expired", "visible", True, "expired"),
    ],
)
async def test_expire_only_overdue_active_requests(
    workflow: Workflow,
    request_status: str,
    moderation: str,
    *,
    overdue: bool,
    expected: str,
) -> None:
    """Persist expiry for every moderation state and make rescans harmless."""
    request_id = await seed_request(
        workflow, request_status, moderation, overdue=overdue
    )
    assert await expire_requests() == int(expected == "expired")
    assert await expire_requests() == 0
    async with connection(workflow.campus_url) as conn:
        row = await conn.fetchrow(
            "SELECT * FROM requests WHERE id=$1", request_id
        )
        assert row["status"] == expected
        assert row["moderation_status"] == moderation
        assert row["title"] == "Expiry test"
        assert row["accepted_response_id"] is None
        assert row["accepted_at"] is None


async def test_concurrent_expiry_scans(workflow: Workflow) -> None:
    """Multiple workers expire each request once without blocking each other."""
    for _ in range(6):
        await seed_request(workflow)
    results = await asyncio.gather(*(expire_requests() for _ in range(3)))
    assert sum(results) == 6  # noqa: PLR2004
    assert await expire_requests() == 0
    async with connection(workflow.campus_url) as conn:
        assert await conn.fetchval(
            "SELECT bool_and(status='expired') FROM requests"
        )


@pytest.mark.parametrize("lock", ["SHARE", "UPDATE"])
async def test_expiry_skips_locked_rows(workflow: Workflow, lock: str) -> None:
    """A busy request does not stop other requests expiring in the scan."""
    busy = await seed_request(workflow)
    ready = await seed_request(workflow)
    query = (
        "SELECT id FROM requests WHERE id=$1 FOR SHARE"
        if lock == "SHARE"
        else "SELECT id FROM requests WHERE id=$1 FOR UPDATE"
    )
    async with connection(workflow.campus_url) as conn, conn.transaction():
        await conn.fetchrow(query, busy)
        assert await expire_requests() == 1
        rows = await conn.fetch("SELECT id,status FROM requests ORDER BY id")
        assert {row["id"]: row["status"] for row in rows} == {
            busy: "open",
            ready: "expired",
        }
    assert await expire_requests() == 1


@pytest.mark.parametrize("decision", ["COMMIT", "ROLLBACK"])
async def test_expiry_respects_prepared_transactions(
    workflow: Workflow, decision: str
) -> None:
    """Prepared locks persist; expiry preserves commit and revisits abort."""
    request_id = await seed_request(workflow)
    gid = f"campuspoint:expiry-test:{uuid4().hex}"
    async with connection(workflow.campus_url) as conn:
        await conn.execute("BEGIN")
        await conn.execute(
            "UPDATE requests SET status='completed' WHERE id=$1", request_id
        )
        await conn.execute("PREPARE TRANSACTION " + quoted_gid(gid))
    try:
        assert await expire_requests() == 0
        async with connection(workflow.campus_url) as conn:
            await conn.execute(decision + " PREPARED " + quoted_gid(gid))
        assert await expire_requests() == int(decision == "ROLLBACK")
        async with connection(workflow.campus_url) as conn:
            assert await conn.fetchval(
                "SELECT status FROM requests WHERE id=$1", request_id
            ) == ("completed" if decision == "COMMIT" else "expired")
    finally:
        async with connection(workflow.campus_url) as conn:
            if await conn.fetchval(
                "SELECT 1 FROM pg_prepared_xacts WHERE gid=$1", gid
            ):
                await conn.execute("ROLLBACK PREPARED " + quoted_gid(gid))


async def test_expiry_refunds_unanswered_requests(workflow: Workflow) -> None:
    """Expose expired status and return the existing hold through 2PC."""
    created = await workflow.client.post(
        ROOT + "/requests",
        json={"location_id": 1, "title": "Seats", "description": "Available?"},
        headers={"Idempotency-Key": "expiry-parent"},
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    request_id = created.json()["request"]["id"]
    async with connection(workflow.campus_url) as conn:
        await conn.execute(
            "UPDATE requests SET created_at=now()-interval '2 hours',"
            "expires_at=now()-interval '1 hour' WHERE id=$1",
            request_id,
        )
        count = await conn.fetchval(
            "SELECT count(*) FROM distributed_transactions"
        )
    assert await expire_requests() == 1
    detail = await workflow.client.get(ROOT + f"/requests/{request_id}")
    assert detail.json()["status"] == "expired"
    authenticate(workflow, 2)
    response = await workflow.client.post(
        ROOT + f"/requests/{request_id}/responses",
        json={"answer": "Second floor."},
        headers={"Idempotency-Key": "expired-answer"},
    )
    assert response.status_code == status.HTTP_409_CONFLICT
    async with connection(workflow.campus_url) as conn:
        assert (
            await conn.fetchval("SELECT count(*) FROM distributed_transactions")
            == count + 1
        )
    async with connection(workflow.points_url) as conn:
        wallet = await conn.fetchrow("SELECT * FROM wallets WHERE user_id=1")
        assert wallet["available_points"] == 100  # noqa: PLR2004
        assert wallet["reputation"] == 0
        assert (
            await conn.fetchval(
                "SELECT status FROM escrows WHERE request_id=$1", request_id
            )
            == "refunded"
        )
        assert (
            await conn.fetchval("SELECT count(*) FROM points_transactions") == 2  # noqa: PLR2004
        )
