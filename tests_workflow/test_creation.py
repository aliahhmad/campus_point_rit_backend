"""Verify creation, atomic holds, idempotency, concurrency, and recovery."""

import asyncio
import os
import shlex
import subprocess
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import HTTPException, status
from httpx import ASGITransport, AsyncClient

from app.config.settings import get_settings
from app.managers import coordinator
from app.managers.security import get_current_user
from app.models.user import User
from app.points.managers import campus_request as points_participant
from app.points.managers.recovery import recover_transactions
from app.transactions import postgres
from app.transactions.postgres import connection, protocol_error
from tests_workflow.conftest import Workflow

pytestmark = pytest.mark.asyncio
URL = get_settings().api_root + "/requests"
BODY = {
    "location_id": 1,
    "title": "Library crowding",
    "description": "Are tables available?",
}
HEADER = {"Idempotency-Key": "create-test"}


async def assert_counts(workflow: Workflow, balance: int, count: int) -> None:
    """Check both databases, not only the HTTP acknowledgement."""
    async with connection(workflow.points_url) as conn:
        assert (
            await conn.fetchval(
                "SELECT available_points FROM wallets WHERE user_id=1"
            )
            == balance
        )
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM escrows WHERE amount=5 AND status='held'"
            )
            == count
        )
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM points_transactions WHERE "
                "type='hold' AND amount=5"
            )
            == count
        )
    async with connection(workflow.campus_url) as conn:
        assert await conn.fetchval("SELECT count(*) FROM requests") == count


async def test_creation_and_retry(workflow: Workflow) -> None:
    """One submission commits one request, one hold, and one ledger entry."""
    first = await workflow.client.post(URL, json=BODY, headers=HEADER)
    assert first.status_code == status.HTTP_201_CREATED, first.text
    assert first.json()["status"] == "completed"
    assert first.json()["request"]["title"] == BODY["title"]
    second = await workflow.client.post(URL, json=BODY, headers=HEADER)
    assert second.status_code == status.HTTP_201_CREATED
    assert second.json() == first.json()
    await assert_counts(workflow, 95, 1)
    changed = await workflow.client.post(
        URL, json=BODY | {"title": "Different"}, headers=HEADER
    )
    assert changed.status_code == status.HTTP_409_CONFLICT


async def test_insufficient_points(workflow: Workflow) -> None:
    """A No vote rolls back Campus preparation and leaves Points unchanged."""
    async with connection(workflow.points_url) as conn:
        await conn.execute(
            "UPDATE wallets SET available_points=4 WHERE user_id=1"
        )
    first = await workflow.client.post(URL, json=BODY, headers=HEADER)
    assert first.status_code == status.HTTP_409_CONFLICT, first.text
    assert first.json()["detail"]["code"] == "insufficient_points"
    retry = await workflow.client.post(URL, json=BODY, headers=HEADER)
    assert retry.json() == first.json()
    await assert_counts(workflow, 4, 0)


async def test_concurrent_last_five_points(workflow: Workflow) -> None:
    """Competing submissions cannot spend the same five available points."""
    async with connection(workflow.points_url) as conn:
        await conn.execute(
            "UPDATE wallets SET available_points=5 WHERE user_id=1"
        )
    responses = await asyncio.gather(
        *(
            workflow.client.post(
                URL, json=BODY, headers={"Idempotency-Key": f"compete-{i}"}
            )
            for i in range(2)
        )
    )
    assert sorted(r.status_code for r in responses) == [201, 409]
    await assert_counts(workflow, 0, 1)


async def test_lost_prepare_response(
    workflow: Workflow, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Roll back a prepared hold when the coordinator chooses ABORT."""
    original = coordinator.call_points

    async def lost(transaction_id, action, payload=None) -> None:  # noqa: ANN001
        await original(transaction_id, action, payload)
        if action == "prepare":
            raise httpx.ReadTimeout(message="simulated response loss")

    monkeypatch.setattr(coordinator, "call_points", lost)
    response = await workflow.client.post(URL, json=BODY, headers=HEADER)
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE, (
        response.text
    )
    await assert_counts(workflow, 100, 0)


async def test_lost_commit_acknowledgement(
    workflow: Workflow, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wait for both acknowledgements, then replay safely."""
    original = coordinator.call_points

    async def lost(transaction_id, action, payload=None) -> None:  # noqa: ANN001
        await original(transaction_id, action, payload)
        if action == "commit":
            raise httpx.ReadTimeout(message="simulated response loss")

    monkeypatch.setattr(coordinator, "call_points", lost)
    first = await workflow.client.post(URL, json=BODY, headers=HEADER)
    assert first.status_code == status.HTTP_202_ACCEPTED, first.text
    assert first.json()["request"] is None
    monkeypatch.setattr(coordinator, "call_points", original)
    operation_id = first.json()["operation_id"]
    result = await workflow.client.get(
        get_settings().api_root + f"/operations/{operation_id}"
    )
    assert result.status_code == status.HTTP_200_OK
    assert result.json()["status"] == "completed"
    await assert_counts(workflow, 95, 1)


class SimulatedCrash(BaseException):
    """Interrupt the process without running coordinator business recovery."""


async def test_crash_after_commit_decision(
    workflow: Workflow, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Durable preparations survive a PostgreSQL restart and finish COMMIT."""
    original = coordinator.record_decision

    async def crash(*args, **kwargs) -> None:  # noqa: ANN002, ANN003
        await original(*args, **kwargs)
        raise SimulatedCrash

    monkeypatch.setattr(coordinator, "record_decision", crash)
    with pytest.raises(SimulatedCrash):
        await workflow.client.post(URL, json=BODY, headers=HEADER)
    monkeypatch.setattr(coordinator, "record_decision", original)
    async with connection(workflow.campus_url) as conn:
        row = await conn.fetchrow(
            "SELECT id,decision FROM distributed_transactions"
        )
        assert row["decision"] == "commit"
        operation_id = row["id"]
    # No participant exposes committed business changes before phase two.
    await assert_counts(workflow, 100, 0)
    data, binary = os.getenv("WORKFLOW_PG_DATA"), os.getenv("WORKFLOW_PG_BIN")
    if data and binary:
        saved_options = await asyncio.to_thread(
            Path(data, "postmaster.opts").read_text
        )
        options = shlex.split(saved_options)[3:]
        await asyncio.to_thread(
            subprocess.run,
            [binary + "/pg_ctl", "-D", data, "-m", "fast", "-w", "stop"],
            check=True,
        )
        await asyncio.to_thread(
            subprocess.run,
            [
                binary + "/pg_ctl",
                "-D",
                data,
                "-l",
                data + "/restart.log",
                "-o",
                shlex.join(options),
                "-w",
                "start",
            ],
            check=True,
        )
    # Re-run with fresh connections as startup recovery does.
    await recover_transactions()
    await coordinator.recover_operations()
    result = await coordinator.advance_operation(operation_id)
    assert result.status == "completed"
    await assert_counts(workflow, 95, 1)


async def test_local_work_rollback(
    workflow: Workflow, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure after all local writes rolls back the whole Points change."""
    original = points_participant.hold_request_points

    async def fail(conn, transaction_id, payload) -> None:  # noqa: ANN001
        await original(conn, transaction_id, payload)
        raise protocol_error(code="service_unavailable", status_code=503)

    monkeypatch.setattr(points_participant, "hold_request_points", fail)
    response = await workflow.client.post(URL, json=BODY, headers=HEADER)
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE, (
        response.text
    )
    await assert_counts(workflow, 100, 0)


async def test_operations_are_owner_only(workflow: Workflow) -> None:
    """Do not disclose another user's operation through the progress API."""
    response = await workflow.client.post(URL, json=BODY, headers=HEADER)
    operation_id = response.json()["operation_id"]

    async def other_user() -> User:
        return User(id=2)

    workflow.campus.dependency_overrides[get_current_user] = other_user
    response = await workflow.client.get(
        get_settings().api_root + f"/operations/{operation_id}"
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND


async def test_internal_authentication(workflow: Workflow) -> None:
    """Both participant APIs reject unauthenticated decision messages."""
    for app, prefix in (
        (workflow.campus, get_settings().api_root),
        (workflow.points, ""),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                prefix + f"/internal/transactions/{uuid4()}/commit"
            )
            assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.usefixtures("workflow")
async def test_commit_requires_durable_decision() -> None:
    """A service token alone cannot commit an unknown coordinator decision."""
    with pytest.raises(HTTPException):
        await points_participant.finish_request(UUID(int=1), "commit")


async def test_concurrent_retries(workflow: Workflow) -> None:
    """Concurrent HTTP retries share one operation and one five-point hold."""
    responses = await asyncio.gather(
        *(
            workflow.client.post(URL, json=BODY, headers=HEADER)
            for _ in range(4)
        )
    )
    assert all(r.status_code in {201, 202} for r in responses)
    ids = {r.json()["operation_id"] for r in responses}
    assert len(ids) == 1
    result = await coordinator.advance_operation(UUID(ids.pop()))
    assert result.status == "completed"
    await assert_counts(workflow, 95, 1)


async def test_participants_wait_for_decision(
    workflow: Workflow, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Yes voter retains preparation while the coordinator is unavailable."""
    original = coordinator.record_decision

    async def crash(*_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
        raise SimulatedCrash

    monkeypatch.setattr(coordinator, "record_decision", crash)
    with pytest.raises(SimulatedCrash):
        await workflow.client.post(URL, json=BODY, headers=HEADER)
    await recover_transactions()
    async with connection(workflow.points_url) as conn:
        count = await conn.fetchval(
            "SELECT count(*) FROM pg_prepared_xacts "
            "WHERE database=current_database()"
        )
        assert count == 1
    await assert_counts(workflow, 100, 0)
    monkeypatch.setattr(coordinator, "record_decision", original)
    await coordinator.recover_operations()
    await assert_counts(workflow, 95, 1)


async def test_commit_journal_crash_gap(
    workflow: Workflow, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Recover a commit that completed before its journal was finalized."""
    original = postgres.mark_committed

    async def crash(*_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
        raise OSError

    monkeypatch.setattr(postgres, "mark_committed", crash)
    response = await workflow.client.post(URL, json=BODY, headers=HEADER)
    assert response.status_code == status.HTTP_202_ACCEPTED
    assert response.json()["request"] is None
    await assert_counts(workflow, 95, 1)
    monkeypatch.setattr(postgres, "mark_committed", original)
    await recover_transactions()
    result = await coordinator.advance_operation(
        UUID(response.json()["operation_id"])
    )
    assert result.status == "completed"
    await assert_counts(workflow, 95, 1)


async def test_prepare_payload_conflict(workflow: Workflow) -> None:
    """A repeated participant message cannot change the work it identifies."""
    created = await workflow.client.post(URL, json=BODY, headers=HEADER)
    result = created.json()
    payload = BODY | {
        "owner_id": 1,
        "request_id": result["request"]["id"],
        "title": "Different",
    }
    async with AsyncClient(
        transport=ASGITransport(app=workflow.points), base_url="http://points"
    ) as client:
        response = await client.post(
            f"/internal/transactions/{result['operation_id']}/prepare",
            json=payload,
            headers={"X-Service-Token": "workflow-test-token"},
        )
    assert response.status_code == status.HTTP_409_CONFLICT
    await assert_counts(workflow, 95, 1)
