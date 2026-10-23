"""Verify automatic refund accounting, conflict classification, and recovery."""

from uuid import UUID, uuid4

import asyncpg
import pytest
from fastapi import status
from httpx import ASGITransport, AsyncClient

from app.managers import coordinator, expiration, expiration_participant
from app.points.managers import refund
from app.points.managers.recovery import recover_transactions
from app.transactions import postgres
from app.transactions.postgres import connection
from tests_workflow.conftest import Workflow
from tests_workflow.test_acceptance import authenticate
from tests_workflow.test_expiration import ROOT, seed_request

pytestmark = pytest.mark.asyncio
HELD_BALANCE = 95
EXISTING_REPUTATION = 7


async def assert_refund(
    workflow: Workflow, request_id: int, *, refunded: bool
) -> None:
    """Check identity, wallet conservation, escrow, ledger, and reputation."""
    async with connection(workflow.campus_url) as conn:
        assert await conn.fetchval(
            "SELECT status FROM requests WHERE id=$1", request_id
        ) == ("expired" if refunded else "open")
    async with connection(workflow.points_url) as conn:
        wallets = await conn.fetch(
            "SELECT available_points,reputation FROM wallets ORDER BY user_id"
        )
        assert [row["available_points"] for row in wallets] == [
            100 if refunded else 95,
            100,
        ]
        assert [row["reputation"] for row in wallets] == [0, 0]
        escrow = await conn.fetchrow(
            "SELECT * FROM escrows WHERE request_id=$1", request_id
        )
        assert escrow["status"] == ("refunded" if refunded else "held")
        assert (escrow["settled_at"] is not None) is refunded
        assert escrow["recipient_id"] is None
        assert escrow["awarded_response_id"] is None
        entries = await conn.fetch(
            "SELECT * FROM points_transactions WHERE type='refund'"
        )
        assert len(entries) == int(refunded)
        if refunded:
            assert entries[0]["amount"] == escrow["amount"]
            assert entries[0]["escrow_id"] == escrow["id"]
            assert entries[0]["user_id"] == escrow["requester_id"]
        held = escrow["amount"] if escrow["status"] == "held" else 0
        assert sum(row["available_points"] for row in wallets) + held == 200  # noqa: PLR2004


async def expiry_id(workflow: Workflow) -> UUID:
    """Find the most recent automatic expiry operation in this test."""
    async with connection(workflow.campus_url) as conn:
        return await conn.fetchval(
            "SELECT id FROM distributed_transactions WHERE "
            "operation='expire_request' ORDER BY created_at DESC LIMIT 1"
        )


@pytest.mark.parametrize(
    "moderation", ["visible", "hidden", "pending", "unconfirmed"]
)
@pytest.mark.parametrize("previous_status", ["open", "expired"])
async def test_answered_expiry_becomes_conflicted(
    workflow: Workflow,
    monkeypatch: pytest.MonkeyPatch,
    moderation: str,
    previous_status: str,
) -> None:
    """Every saved answer prevents refund, even if hidden or unconfirmed."""
    request_id = await seed_request(workflow, overdue=False)
    authenticate(workflow, 2)
    answered = await workflow.client.post(
        ROOT + f"/requests/{request_id}/responses",
        json={"answer": "Second floor."},
        headers={"Idempotency-Key": "conflict-answer"},
    )
    assert answered.status_code == status.HTTP_201_CREATED, answered.text
    async with connection(workflow.campus_url) as conn:
        await conn.execute(
            "UPDATE requests SET status=$2,expires_at=now()-interval '1 hour' "
            "WHERE id=$1",
            request_id,
            previous_status,
        )
        if moderation == "unconfirmed":
            await conn.execute(
                "UPDATE distributed_transactions SET state='commit_decided' "
                "WHERE operation='create_response'"
            )
        else:
            await conn.execute(
                "UPDATE responses SET moderation_status=$1", moderation
            )

    async def no_points(*_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
        pytest.fail("Classifying a conflict must not contact Points")

    monkeypatch.setattr(coordinator, "call_points", no_points)
    assert await expiration.expire_requests() == 1
    assert await expiration.expire_requests() == 0
    listing = await workflow.client.get(ROOT + "/requests?status=conflicted")
    assert listing.status_code == status.HTTP_200_OK
    assert listing.json()["items"][0]["status"] == "conflicted"
    async with connection(workflow.points_url) as conn:
        assert (
            await conn.fetchval(
                "SELECT available_points FROM wallets WHERE user_id=1"
            )
            == HELD_BALANCE
        )
        assert (
            await conn.fetchval(
                "SELECT status FROM escrows WHERE request_id=$1", request_id
            )
            == "held"
        )
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM points_transactions WHERE type='refund'"
            )
            == 0
        )


async def test_refund_journals_polling_and_idempotency(
    workflow: Workflow,
) -> None:
    """Finish both participants and expose one owner-only refund result."""
    request_id = await seed_request(workflow)
    assert await expiration.expire_requests() == 1
    transaction_id = await expiry_id(workflow)
    for _ in range(2):
        result = await coordinator.advance_operation(transaction_id)
        assert result.operation == "expire_request"
        assert result.status == "completed"
        assert result.request.id == request_id
        assert await expiration.expire_requests() == 0
        await assert_refund(workflow, request_id, refunded=True)
    polled = await workflow.client.get(ROOT + f"/operations/{transaction_id}")
    assert polled.json()["operation"] == "expire_request"
    assert polled.json()["refund_points"] == 5  # noqa: PLR2004
    authenticate(workflow, 2)
    forbidden = await workflow.client.get(
        ROOT + f"/operations/{transaction_id}"
    )
    assert forbidden.status_code == status.HTTP_404_NOT_FOUND
    for url in (workflow.campus_url, workflow.points_url):
        async with connection(url) as conn:
            journal = await conn.fetchrow(
                "SELECT operation,state FROM participant_transactions "
                "WHERE transaction_id=$1",
                transaction_id,
            )
            assert dict(journal) == {
                "operation": "expire_request",
                "state": "committed",
            }


async def test_refund_recovery_after_intake(workflow: Workflow) -> None:
    """Startup recovery resumes a persisted job if the scanner crashes."""
    request_id = await seed_request(workflow)
    queued, conflicts = await expiration.queue_expirations()
    assert len(queued) == 1
    assert conflicts == 0
    await assert_refund(workflow, request_id, refunded=False)
    await coordinator.recover_operations()
    await assert_refund(workflow, request_id, refunded=True)
    assert await expiration.expire_requests() == 0


@pytest.mark.parametrize("participant", ["campus", "points"])
async def test_refund_rolls_back_and_retries(
    workflow: Workflow, monkeypatch: pytest.MonkeyPatch, participant: str
) -> None:
    """Roll back both sides after a write failure, then allow a new attempt."""
    request_id = await seed_request(workflow)
    module = expiration_participant if participant == "campus" else refund
    name = (
        "expire_unanswered_request"
        if participant == "campus"
        else "refund_request_points"
    )
    original = getattr(module, name)

    async def fail(*args, **kwargs) -> None:  # noqa: ANN002, ANN003
        await original(*args, **kwargs)
        raise OSError

    monkeypatch.setattr(module, name, fail)
    assert await expiration.expire_requests() == 0
    old = await expiry_id(workflow)
    aborted = await coordinator.advance_operation(old)
    assert aborted.status == "aborted"
    await assert_refund(workflow, request_id, refunded=False)
    monkeypatch.setattr(module, name, original)
    assert await expiration.expire_requests() == 1
    assert await expiry_id(workflow) != old
    await assert_refund(workflow, request_id, refunded=True)


@pytest.mark.parametrize("action", ["prepare", "commit"])
async def test_refund_lost_points_acknowledgement(
    workflow: Workflow, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    """A lost Yes aborts safely; a lost commit ack replays the same decision."""
    request_id = await seed_request(workflow)
    original = coordinator.call_points

    async def lost(transaction_id, sent, payload=None) -> None:  # noqa: ANN001
        await original(transaction_id, sent, payload)
        if sent == action:
            raise OSError

    monkeypatch.setattr(coordinator, "call_points", lost)
    assert await expiration.expire_requests() == 0
    transaction_id = await expiry_id(workflow)
    if action == "commit":
        pending = await coordinator.advance_operation(transaction_id)
        assert pending.status == "processing"
        assert pending.request is None
    else:
        await assert_refund(workflow, request_id, refunded=False)
    monkeypatch.setattr(coordinator, "call_points", original)
    if action == "prepare":
        assert await expiration.expire_requests() == 1
    else:
        assert (
            await coordinator.advance_operation(transaction_id)
        ).status == "completed"
    await assert_refund(workflow, request_id, refunded=True)


class SimulatedExpiryCrash(BaseException):
    """Interrupt the coordinator without converting the crash into an abort."""


@pytest.mark.parametrize("recorded", [False, True])
async def test_refund_crash_recovery(
    workflow: Workflow, monkeypatch: pytest.MonkeyPatch, *, recorded: bool
) -> None:
    """Prepared voters wait for a decision; recovery never credits twice."""
    request_id = await seed_request(workflow)
    original = coordinator.record_decision

    async def crash(*args, **kwargs) -> None:  # noqa: ANN002, ANN003
        if recorded:
            await original(*args, **kwargs)
        raise SimulatedExpiryCrash

    monkeypatch.setattr(coordinator, "record_decision", crash)
    with pytest.raises(SimulatedExpiryCrash):
        await expiration.expire_requests()
    transaction_id = await expiry_id(workflow)
    await assert_refund(workflow, request_id, refunded=False)
    await recover_transactions()
    if not recorded:
        await assert_refund(workflow, request_id, refunded=False)
    monkeypatch.setattr(coordinator, "record_decision", original)
    await coordinator.recover_operations()
    assert (
        await coordinator.advance_operation(transaction_id)
    ).status == "completed"
    await assert_refund(workflow, request_id, refunded=True)


async def test_refund_commit_journal_gap(
    workflow: Workflow, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crash after COMMIT PREPARED cannot replay the wallet increment."""
    request_id = await seed_request(workflow)
    original = postgres.mark_committed

    async def fail(*_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
        raise OSError

    monkeypatch.setattr(postgres, "mark_committed", fail)
    assert await expiration.expire_requests() == 0
    transaction_id = await expiry_id(workflow)
    monkeypatch.setattr(postgres, "mark_committed", original)
    await recover_transactions()
    assert (
        await coordinator.advance_operation(transaction_id)
    ).status == "completed"
    await assert_refund(workflow, request_id, refunded=True)


async def test_refund_rechecks_answers_before_prepare(
    workflow: Workflow, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An answer appearing after intake aborts the refund and flags conflict."""
    request_id = await seed_request(workflow)
    original = coordinator.prepare_expiration

    async def add_answer(*args, **kwargs) -> None:  # noqa: ANN002, ANN003
        async with connection(workflow.campus_url) as conn:
            await conn.execute(
                "INSERT INTO responses (request_id,contributor_id,answer) "
                "VALUES ($1,2,'Late stored answer')",
                request_id,
            )
        await original(*args, **kwargs)

    monkeypatch.setattr(coordinator, "prepare_expiration", add_answer)
    assert await expiration.expire_requests() == 0
    await assert_refund(workflow, request_id, refunded=False)
    monkeypatch.setattr(coordinator, "prepare_expiration", original)
    assert await expiration.expire_requests() == 1
    async with connection(workflow.campus_url) as conn:
        assert (
            await conn.fetchval(
                "SELECT status FROM requests WHERE id=$1", request_id
            )
            == "conflicted"
        )


@pytest.mark.parametrize(
    "condition", ["missing", "mismatch", "released", "refunded"]
)
async def test_invalid_escrow_cannot_refund(
    workflow: Workflow, condition: str
) -> None:
    """Never create points when the hold is missing or already settled."""
    await seed_request(workflow)
    async with connection(workflow.points_url) as conn:
        if condition == "missing":
            await conn.execute("DELETE FROM points_transactions")
            await conn.execute("DELETE FROM escrows")
        elif condition == "mismatch":
            await conn.execute("UPDATE escrows SET requester_id=2")
        else:
            await conn.execute("UPDATE escrows SET status=$1", condition)
    assert await expiration.expire_requests() == 0
    async with connection(workflow.points_url) as conn:
        assert (
            await conn.fetchval(
                "SELECT available_points FROM wallets WHERE user_id=1"
            )
            == HELD_BALANCE
        )
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM points_transactions WHERE type='refund'"
            )
            == 0
        )


async def test_unique_refund_and_expiry_guards(workflow: Workflow) -> None:
    """Different IDs cannot bypass one refund and one committed expiry."""
    request_id = await seed_request(workflow)
    assert await expiration.expire_requests() == 1
    async with connection(workflow.points_url) as conn:
        with pytest.raises(asyncpg.UniqueViolationError):
            await conn.execute(
                "INSERT INTO points_transactions "
                "(operation_id,escrow_id,user_id,"
                "type,amount) SELECT $1,escrow_id,user_id,type,amount FROM "
                "points_transactions WHERE type='refund'",
                uuid4(),
            )
    async with connection(workflow.campus_url) as conn:
        with pytest.raises(asyncpg.UniqueViolationError):
            await conn.execute(
                "INSERT INTO distributed_transactions "
                "(id,owner_id,idempotency_key,operation,payload,request_id) "
                "VALUES ($1,1,$2,'expire_request','{}',$3)",
                uuid4(),
                str(uuid4()),
                request_id,
            )
    await assert_refund(workflow, request_id, refunded=True)


async def test_refund_keeps_existing_reputation(workflow: Workflow) -> None:
    """Refunds restore held points without changing either user's reputation."""
    await seed_request(workflow)
    async with connection(workflow.points_url) as conn:
        await conn.execute("UPDATE wallets SET reputation=7 WHERE user_id=1")
    assert await expiration.expire_requests() == 1
    async with connection(workflow.points_url) as conn:
        assert (
            await conn.fetchval(
                "SELECT reputation FROM wallets WHERE user_id=1"
            )
            == EXISTING_REPUTATION
        )


async def test_refund_internal_endpoints_require_auth(
    workflow: Workflow,
) -> None:
    """Public callers cannot prepare automatic expiries or refunds."""
    for app, root, action in (
        (workflow.campus, ROOT, "prepare-expiry"),
        (workflow.points, "", "prepare-refund"),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                root + f"/internal/transactions/{uuid4()}/{action}", json={}
            )
            assert response.status_code == status.HTTP_401_UNAUTHORIZED
