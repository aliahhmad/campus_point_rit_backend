"""Verify reward settlement and native 2PC failures in two real databases."""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import asyncpg
import pytest
import pytest_asyncio
from fastapi import status
from httpx import ASGITransport, AsyncClient

from app.config.settings import get_settings
from app.managers import acceptance, acceptance_participant, coordinator
from app.managers.security import get_current_user
from app.models.user import User
from app.points.managers import acceptance as points_acceptance
from app.points.managers.recovery import recover_transactions
from app.transactions import postgres
from app.transactions.postgres import connection, protocol_error
from tests_workflow.conftest import Workflow

ROOT = get_settings().api_root
HEADERS = {"Idempotency-Key": "accept-one"}
REQUESTER_BALANCE = 95
INITIAL_BALANCE = 100
REWARDED_BALANCE = 105
pytestmark = pytest.mark.asyncio


@dataclass
class Selection:
    """Identify a real committed request and a response by another user."""

    request_id: int
    response_id: int

    @property
    def url(self) -> str:
        """Return the public owner-only action URL."""
        return (
            ROOT
            + f"/requests/{self.request_id}/responses/{self.response_id}/accept"
        )


def authenticate(workflow: Workflow, user_id: int) -> None:
    """Switch controlled HTTP identities while keeping authorization active."""

    async def user() -> User:
        return User(id=user_id)

    workflow.campus.dependency_overrides[get_current_user] = user


@pytest_asyncio.fixture
async def selection(workflow: Workflow) -> Selection:
    """Reserve the reward, create a visible answer, and restore the owner."""
    created = await workflow.client.post(
        ROOT + "/requests",
        json={"location_id": 1, "title": "Library", "description": "Seats?"},
        headers={"Idempotency-Key": "accept-parent"},
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    request_id = created.json()["request"]["id"]
    authenticate(workflow, 2)
    answered = await workflow.client.post(
        ROOT + f"/requests/{request_id}/responses",
        json={"answer": "Second floor."},
        headers={"Idempotency-Key": "accept-answer"},
    )
    assert answered.status_code == status.HTTP_201_CREATED, answered.text
    authenticate(workflow, 1)
    return Selection(request_id, answered.json()["response"]["id"])


async def assert_settlement(
    workflow: Workflow, selected: Selection, *, rewarded: bool
) -> None:
    """Check committed state, identity, ledger, balances, and conservation."""
    async with connection(workflow.campus_url) as conn:
        parent = await conn.fetchrow(
            "SELECT * FROM requests WHERE id=$1", selected.request_id
        )
        assert parent["status"] == ("completed" if rewarded else "open")
        assert parent["accepted_response_id"] == (
            selected.response_id if rewarded else None
        )
        assert (parent["accepted_at"] is not None) is rewarded
    async with connection(workflow.points_url) as conn:
        wallets = await conn.fetch(
            "SELECT available_points,reputation FROM wallets ORDER BY user_id"
        )
        assert [row["available_points"] for row in wallets] == [
            REQUESTER_BALANCE,
            REWARDED_BALANCE if rewarded else INITIAL_BALANCE,
        ]
        assert [row["reputation"] for row in wallets] == [0, 0]
        escrow = await conn.fetchrow(
            "SELECT * FROM escrows WHERE request_id=$1", selected.request_id
        )
        assert escrow["status"] == ("released" if rewarded else "held")
        assert escrow["recipient_id"] == (2 if rewarded else None)
        assert escrow["awarded_response_id"] == (
            selected.response_id if rewarded else None
        )
        assert (escrow["settled_at"] is not None) is rewarded
        rewards = await conn.fetch(
            "SELECT * FROM points_transactions WHERE type='reward'"
        )
        assert len(rewards) == (1 if rewarded else 0)
        if rewarded:
            assert rewards[0]["user_id"] == escrow["recipient_id"]
            assert rewards[0]["escrow_id"] == escrow["id"]
            assert rewards[0]["amount"] == escrow["amount"]
        held = await conn.fetchval(
            "SELECT coalesce(sum(amount),0) FROM escrows WHERE status='held'"
        )
        assert (
            sum(row["available_points"] for row in wallets) + held
            == INITIAL_BALANCE * 2
        )


async def test_acceptance_and_exact_retries(
    workflow: Workflow, selection: Selection
) -> None:
    """Complete the request and pay its existing hold exactly once."""
    first = await workflow.client.post(selection.url, headers=HEADERS)
    assert first.status_code == status.HTTP_200_OK, first.text
    body = first.json()
    assert body["status"] == "completed"
    assert body["operation"] == "accept_response"
    assert body["request"]["accepted_response_id"] == selection.response_id
    assert body["accepted_response"]["id"] == selection.response_id
    assert body["recipient_id"] == body["accepted_response"]["contributor_id"]
    await assert_settlement(workflow, selection, rewarded=True)
    for _ in range(2):
        repeated = await workflow.client.post(selection.url, headers=HEADERS)
        assert repeated.status_code == status.HTTP_200_OK
        assert repeated.json() == body
    polled = await workflow.client.get(
        ROOT + "/operations/" + body["operation_id"]
    )
    assert polled.json() == body
    # Retries keep the saved decision even after the acceptance deadline passes.
    async with connection(workflow.campus_url) as conn:
        await conn.execute(
            "UPDATE requests SET created_at=now()-interval '2 "
            "hours',expires_at=now()-interval '1 hour' WHERE id=$1",
            selection.request_id,
        )
        rows = await conn.fetch(
            "SELECT participant,vote,acknowledged FROM "
            "transaction_participants WHERE transaction_id=$1 ORDER BY "
            "participant",
            UUID(body["operation_id"]),
        )
        assert [dict(row) for row in rows] == [
            {"participant": name, "vote": "yes", "acknowledged": True}
            for name in ("campus", "points")
        ]
    retry = await workflow.client.post(selection.url, headers=HEADERS)
    assert retry.json()["status"] == "completed"
    await assert_settlement(workflow, selection, rewarded=True)
    for url in (workflow.campus_url, workflow.points_url):
        async with connection(url) as conn:
            journal = await conn.fetchrow(
                "SELECT operation,state FROM participant_transactions WHERE "
                "transaction_id=$1",
                UUID(body["operation_id"]),
            )
            assert dict(journal) == {
                "operation": "accept_response",
                "state": "committed",
            }


@pytest.mark.parametrize(
    ("condition", "expected_status", "code"),
    [
        ("other_user", 403, "request_owner_required"),
        ("expired", 409, "request_expired"),
        ("closed", 409, "request_not_open"),
        ("hidden_request", 409, "request_not_visible"),
        ("pending_request", 409, "request_not_visible"),
        ("hidden_response", 404, "response_not_found"),
        ("pending_response", 404, "response_not_found"),
        ("unconfirmed_response", 404, "response_not_found"),
        ("unconfirmed_request", 404, "request_not_found"),
        ("missing_response", 404, "response_not_found"),
        ("missing_request", 404, "request_not_found"),
        ("self_response", 403, "self_response_forbidden"),
    ],
)
async def test_acceptance_eligibility(
    workflow: Workflow,
    selection: Selection,
    condition: str,
    expected_status: int,
    code: str,
) -> None:
    """Reject ineligible selections before transferring points."""
    request_id, response_id = selection.request_id, selection.response_id
    if condition == "other_user":
        authenticate(workflow, 2)
    elif condition == "missing_request":
        request_id += 100
    elif condition == "missing_response":
        response_id += 100
    else:
        async with connection(workflow.campus_url) as conn:
            if condition == "expired":
                await conn.execute(
                    "UPDATE requests SET created_at=now()-interval '2 "
                    "hours',expires_at=now()-interval '1 hour' WHERE id=$1",
                    request_id,
                )
            elif condition == "closed":
                await conn.execute(
                    "UPDATE requests SET status='completed' WHERE id=$1",
                    request_id,
                )
            elif condition in {"hidden_request", "pending_request"}:
                await conn.execute(
                    "UPDATE requests SET moderation_status=$2 WHERE id=$1",
                    request_id,
                    condition.split("_", maxsplit=1)[0],
                )
            elif condition in {"hidden_response", "pending_response"}:
                await conn.execute(
                    "UPDATE responses SET moderation_status=$2 WHERE id=$1",
                    response_id,
                    condition.split("_", maxsplit=1)[0],
                )
            elif condition == "unconfirmed_request":
                await conn.execute(
                    "UPDATE distributed_transactions SET "
                    "state='commit_decided' WHERE operation='create_request'"
                )
            elif condition == "unconfirmed_response":
                await conn.execute(
                    "UPDATE distributed_transactions SET "
                    "state='commit_decided' WHERE operation='create_response'"
                )
            else:
                await conn.execute(
                    "UPDATE responses SET contributor_id=1 WHERE id=$1",
                    response_id,
                )
    result = await workflow.client.post(
        ROOT + f"/requests/{request_id}/responses/{response_id}/accept",
        headers=HEADERS,
    )
    assert result.status_code == expected_status, result.text
    assert result.json()["detail"]["code"] == code
    async with connection(workflow.campus_url) as conn:
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM distributed_transactions WHERE "
                "operation='accept_response'"
            )
            == 0
        )
    async with connection(workflow.points_url) as conn:
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM points_transactions WHERE type='reward'"
            )
            == 0
        )
        assert (
            await conn.fetchval(
                "SELECT status FROM escrows WHERE request_id=$1",
                selection.request_id,
            )
            == "held"
        )


async def test_acceptance_conflicts_and_owner_only_polling(
    workflow: Workflow, selection: Selection
) -> None:
    """Key conflicts and additional selections cannot create another payout."""
    first = await workflow.client.post(selection.url, headers=HEADERS)
    assert first.status_code == status.HTTP_200_OK
    duplicate = await workflow.client.post(
        selection.url, headers={"Idempotency-Key": "accept-again"}
    )
    assert duplicate.status_code == status.HTTP_409_CONFLICT
    assert duplicate.json()["detail"]["code"] == "request_already_accepted"
    for path, key in (
        (
            selection.url.replace(
                f"responses/{selection.response_id}", "responses/2147483647"
            ),
            "accept-one",
        ),
        (selection.url, "accept-parent"),
    ):
        conflict = await workflow.client.post(
            path, headers={"Idempotency-Key": key}
        )
        assert conflict.status_code == status.HTTP_409_CONFLICT
        assert conflict.json()["detail"]["code"] == "idempotency_conflict"
    authenticate(workflow, 2)
    forbidden = await workflow.client.get(
        ROOT + "/operations/" + first.json()["operation_id"]
    )
    assert forbidden.status_code == status.HTTP_404_NOT_FOUND
    reused = await workflow.client.post(selection.url, headers=HEADERS)
    assert reused.status_code == status.HTTP_409_CONFLICT
    await assert_settlement(workflow, selection, rewarded=True)


async def test_acceptance_cannot_change_recipient_or_amount(
    workflow: Workflow, selection: Selection
) -> None:
    """Extra JSON cannot change the server-derived recipient or reward."""
    result = await workflow.client.post(
        selection.url,
        headers=HEADERS,
        json={"contributor_id": 1, "reward_points": 1000000},
    )
    assert result.status_code == status.HTTP_200_OK, result.text
    await assert_settlement(workflow, selection, rewarded=True)


async def test_acceptance_rechecks_during_prepare(
    workflow: Workflow, selection: Selection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A response moderated after intake cannot receive the reward."""
    original = coordinator.prepare_acceptance

    async def hide(*args, **kwargs) -> None:  # noqa: ANN002, ANN003
        async with connection(workflow.campus_url) as conn:
            await conn.execute(
                "UPDATE responses SET moderation_status='hidden' WHERE id=$1",
                selection.response_id,
            )
        await original(*args, **kwargs)

    monkeypatch.setattr(coordinator, "prepare_acceptance", hide)
    result = await workflow.client.post(selection.url, headers=HEADERS)
    assert result.status_code == status.HTTP_404_NOT_FOUND
    await assert_settlement(workflow, selection, rewarded=False)


async def test_acceptance_points_unavailable(
    workflow: Workflow, selection: Selection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Points No vote rolls back Campus's prepared completion."""

    async def unavailable(*_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
        raise protocol_error(code="service_unavailable", status_code=503)

    monkeypatch.setattr(points_acceptance, "award_response_points", unavailable)
    result = await workflow.client.post(selection.url, headers=HEADERS)
    assert result.status_code == status.HTTP_503_SERVICE_UNAVAILABLE, (
        result.text
    )
    await assert_settlement(workflow, selection, rewarded=False)


@pytest.mark.parametrize("participant", ["campus", "points"])
async def test_acceptance_local_write_rollback(
    workflow: Workflow,
    selection: Selection,
    monkeypatch: pytest.MonkeyPatch,
    participant: str,
) -> None:
    """Failures after local writes roll back the complete request or payout."""
    module = (
        acceptance_participant if participant == "campus" else points_acceptance
    )
    name = (
        "accept_response"
        if participant == "campus"
        else "award_response_points"
    )
    original = getattr(module, name)

    async def fail(*args, **kwargs) -> None:  # noqa: ANN002, ANN003
        await original(*args, **kwargs)
        raise OSError

    monkeypatch.setattr(module, name, fail)
    result = await workflow.client.post(selection.url, headers=HEADERS)
    assert result.status_code == status.HTTP_503_SERVICE_UNAVAILABLE, (
        result.text
    )
    await assert_settlement(workflow, selection, rewarded=False)


async def test_lost_acceptance_prepare_ack_and_retry(
    workflow: Workflow, selection: Selection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Abort an unacknowledged Yes and retry without duplicate transfers."""
    original = coordinator.call_points

    async def lost(transaction_id, action, payload=None) -> None:  # noqa: ANN001
        await original(transaction_id, action, payload)
        if action == "prepare":
            raise OSError

    monkeypatch.setattr(coordinator, "call_points", lost)
    aborted = await workflow.client.post(selection.url, headers=HEADERS)
    assert aborted.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    await assert_settlement(workflow, selection, rewarded=False)
    monkeypatch.setattr(coordinator, "call_points", original)
    retry = await workflow.client.post(selection.url, headers=HEADERS)
    assert retry.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert retry.json() == aborted.json()
    for url in (workflow.campus_url, workflow.points_url):
        async with connection(url) as conn:
            row = await conn.fetchrow(
                "SELECT operation,state FROM participant_transactions WHERE "
                "transaction_id=$1",
                UUID(aborted.json()["detail"]["operation_id"]),
            )
            assert dict(row) == {
                "operation": "accept_response",
                "state": "aborted",
            }
    fresh = await workflow.client.post(
        selection.url, headers={"Idempotency-Key": "accept-recovered"}
    )
    assert fresh.status_code == status.HTTP_200_OK, fresh.text
    await assert_settlement(workflow, selection, rewarded=True)


@pytest.mark.parametrize("participant", ["campus", "points"])
async def test_lost_acceptance_commit_acknowledgement(
    workflow: Workflow,
    selection: Selection,
    monkeypatch: pytest.MonkeyPatch,
    participant: str,
) -> None:
    """Lost acknowledgements remain processing until safely replayed."""
    if participant == "points":
        original = coordinator.call_points

        async def lost(transaction_id, action, payload=None) -> None:  # noqa: ANN001
            await original(transaction_id, action, payload)
            if action == "commit":
                raise OSError

        monkeypatch.setattr(coordinator, "call_points", lost)
    else:
        original = coordinator.finish_request

        async def lost_campus(*args, **kwargs) -> None:  # noqa: ANN002, ANN003
            await original(*args, **kwargs)
            raise OSError

        monkeypatch.setattr(coordinator, "finish_request", lost_campus)
    pending = await workflow.client.post(selection.url, headers=HEADERS)
    assert pending.status_code == status.HTTP_202_ACCEPTED, pending.text
    assert pending.json()["status"] == "processing"
    assert pending.json()["accepted_response"] is None
    assert pending.json()["recipient_id"] is None
    assert pending.json()["request"] is None
    monkeypatch.setattr(
        coordinator,
        "call_points" if participant == "points" else "finish_request",
        original,
    )
    polled = await workflow.client.get(
        ROOT + "/operations/" + pending.json()["operation_id"]
    )
    assert polled.json()["status"] == "completed", polled.text
    await assert_settlement(workflow, selection, rewarded=True)


class SimulatedAcceptanceCrash(BaseException):
    """Stop coordination without converting a process crash into a No vote."""


@pytest.mark.parametrize("recorded", [False, True])
async def test_acceptance_crash_recovery(
    workflow: Workflow,
    selection: Selection,
    monkeypatch: pytest.MonkeyPatch,
    *,
    recorded: bool,
) -> None:
    """Prepared Yes votes survive crashes and finish only one payout."""
    original = coordinator.record_decision

    async def crash(*args, **kwargs) -> None:  # noqa: ANN002, ANN003
        if recorded:
            await original(*args, **kwargs)
        raise SimulatedAcceptanceCrash

    monkeypatch.setattr(coordinator, "record_decision", crash)
    with pytest.raises(SimulatedAcceptanceCrash):
        await workflow.client.post(selection.url, headers=HEADERS)
    await assert_settlement(workflow, selection, rewarded=False)
    for url in (workflow.campus_url, workflow.points_url):
        async with connection(url) as conn:
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM pg_prepared_xacts WHERE "
                    "database=current_database()"
                )
                == 1
            )
    # Points waits rather than unilaterally aborting an undecided preparation.
    await recover_transactions()
    monkeypatch.setattr(coordinator, "record_decision", original)
    await coordinator.recover_operations()
    await assert_settlement(workflow, selection, rewarded=True)


async def test_recorded_commit_finishes_after_deadline(
    workflow: Workflow, selection: Selection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Expiry cannot replace a durable COMMIT with ABORT during recovery."""
    original = coordinator.record_decision

    async def crash(*args, **kwargs) -> None:  # noqa: ANN002, ANN003
        await original(*args, **kwargs)
        raise SimulatedAcceptanceCrash

    monkeypatch.setattr(coordinator, "record_decision", crash)
    with pytest.raises(SimulatedAcceptanceCrash):
        await workflow.client.post(selection.url, headers=HEADERS)

    class LaterClock:
        @staticmethod
        def now(tz: timezone) -> datetime:
            return datetime.now(tz) + timedelta(hours=2)

    monkeypatch.setattr(acceptance, "datetime", LaterClock)
    monkeypatch.setattr(coordinator, "record_decision", original)
    await coordinator.recover_operations()
    await assert_settlement(workflow, selection, rewarded=True)


async def test_acceptance_commit_journal_gap(
    workflow: Workflow, selection: Selection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Recovery recognizes committed business writes without paying again."""
    original = postgres.mark_committed

    async def fail(*_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
        raise OSError

    monkeypatch.setattr(postgres, "mark_committed", fail)
    pending = await workflow.client.post(selection.url, headers=HEADERS)
    assert pending.status_code == status.HTTP_202_ACCEPTED
    monkeypatch.setattr(postgres, "mark_committed", original)
    await recover_transactions()
    result = await coordinator.advance_operation(
        UUID(pending.json()["operation_id"])
    )
    assert result.status == "completed"
    await assert_settlement(workflow, selection, rewarded=True)


async def test_concurrent_acceptance_retries(
    workflow: Workflow, selection: Selection
) -> None:
    """One key coordinates simultaneous HTTP retries without extra transfers."""
    results = await asyncio.gather(
        *(
            workflow.client.post(selection.url, headers=HEADERS)
            for _ in range(3)
        )
    )
    assert all(result.status_code in {200, 202} for result in results)
    ids = {result.json()["operation_id"] for result in results}
    assert len(ids) == 1
    final = await coordinator.advance_operation(UUID(ids.pop()))
    assert final.status == "completed"
    await assert_settlement(workflow, selection, rewarded=True)


async def test_competing_response_selections(
    workflow: Workflow, selection: Selection
) -> None:
    """Different keys and different contributors still produce one winner."""
    async with connection(workflow.campus_url) as conn:
        await conn.execute(
            "INSERT INTO users "
            "(id,email,password,first_name,last_name,banned,verified) VALUES "
            "(3,'three@example.com','unused','Third','User',false,true)"
        )
    async with connection(workflow.points_url) as conn:
        await conn.execute(
            "INSERT INTO wallets (user_id,available_points) VALUES (3,100)"
        )
    authenticate(workflow, 3)
    other = await workflow.client.post(
        ROOT + f"/requests/{selection.request_id}/responses",
        json={"answer": "Third floor."},
        headers={"Idempotency-Key": "second-answer"},
    )
    assert other.status_code == status.HTTP_201_CREATED
    authenticate(workflow, 1)
    urls = [
        selection.url,
        ROOT
        + f"/requests/{selection.request_id}/responses/"
        + f"{other.json()['response']['id']}/accept",
    ]
    results = await asyncio.gather(
        *(
            workflow.client.post(
                url, headers={"Idempotency-Key": f"select-{index}"}
            )
            for index, url in enumerate(urls)
        )
    )
    assert sorted(result.status_code for result in results) == [200, 409]
    async with connection(workflow.campus_url) as conn:
        winner = await conn.fetchval(
            "SELECT accepted_response_id FROM requests WHERE id=$1",
            selection.request_id,
        )
    async with connection(workflow.points_url) as conn:
        escrow = await conn.fetchrow(
            "SELECT * FROM escrows WHERE request_id=$1", selection.request_id
        )
        assert escrow["awarded_response_id"] == winner
        rewards = await conn.fetch(
            "SELECT user_id,amount FROM points_transactions WHERE type='reward'"
        )
        assert len(rewards) == 1
        assert rewards[0]["user_id"] == escrow["recipient_id"]
        assert (
            await conn.fetchval("SELECT sum(available_points) FROM wallets")
            == INITIAL_BALANCE * 3
        )


async def test_missing_recipient_wallet_aborts(
    workflow: Workflow, selection: Selection
) -> None:
    """A missing wallet cannot consume the hold or complete the request."""
    async with connection(workflow.points_url) as conn:
        await conn.execute("DELETE FROM wallets WHERE user_id=2")
    result = await workflow.client.post(selection.url, headers=HEADERS)
    assert result.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert result.json()["detail"]["code"] == "recipient_wallet_missing"
    async with connection(workflow.campus_url) as conn:
        assert (
            await conn.fetchval(
                "SELECT accepted_response_id FROM requests WHERE id=$1",
                selection.request_id,
            )
            is None
        )
    async with connection(workflow.points_url) as conn:
        assert (
            await conn.fetchval(
                "SELECT status FROM escrows WHERE request_id=$1",
                selection.request_id,
            )
            == "held"
        )
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM points_transactions WHERE type='reward'"
            )
            == 0
        )


async def test_reward_unique_per_escrow(
    workflow: Workflow, selection: Selection
) -> None:
    """A different operation ID cannot bypass the one-reward constraint."""
    result = await workflow.client.post(selection.url, headers=HEADERS)
    assert result.status_code == status.HTTP_200_OK
    async with connection(workflow.points_url) as conn:
        with pytest.raises(asyncpg.UniqueViolationError):
            await conn.execute(
                "INSERT INTO points_transactions "
                "(operation_id,escrow_id,user_id,type,amount) SELECT "
                "$1,escrow_id,user_id,type,amount FROM points_transactions "
                "WHERE type='reward'",
                uuid4(),
            )
    await assert_settlement(workflow, selection, rewarded=True)


async def test_acceptance_internal_endpoints_require_auth(
    workflow: Workflow,
) -> None:
    """No unauthenticated caller can prepare or commit a reward payout."""
    for app, root in ((workflow.campus, ROOT), (workflow.points, "")):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            result = await client.post(
                root + f"/internal/transactions/{uuid4()}/prepare-acceptance",
                json={},
            )
            assert result.status_code == status.HTTP_401_UNAUTHORIZED


async def test_response_must_belong_to_selected_request(
    workflow: Workflow, selection: Selection
) -> None:
    """An owner cannot use another request's answer as this request's winner."""
    other = await workflow.client.post(
        ROOT + "/requests",
        json={
            "location_id": 1,
            "title": "Another request",
            "description": "Seats?",
        },
        headers={"Idempotency-Key": "other-parent"},
    )
    assert other.status_code == status.HTTP_201_CREATED
    other_id = other.json()["request"]["id"]
    result = await workflow.client.post(
        ROOT + f"/requests/{other_id}/responses/{selection.response_id}/accept",
        headers=HEADERS,
    )
    assert result.status_code == status.HTTP_404_NOT_FOUND
    async with connection(workflow.points_url) as conn:
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM points_transactions WHERE type='reward'"
            )
            == 0
        )


async def test_request_under_review_can_be_completed(
    workflow: Workflow, selection: Selection
) -> None:
    """A visible, unexpired request under review can settle its reward."""
    async with connection(workflow.campus_url) as conn:
        await conn.execute(
            "UPDATE requests SET status='under_review' WHERE id=$1",
            selection.request_id,
        )
    result = await workflow.client.post(selection.url, headers=HEADERS)
    assert result.status_code == status.HTTP_200_OK, result.text
    await assert_settlement(workflow, selection, rewarded=True)


async def test_acceptance_rechecks_expiry_during_prepare(
    workflow: Workflow, selection: Selection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Intake before expiry does not bypass the participant's deadline check."""
    original = coordinator.prepare_acceptance

    async def expire(*args, **kwargs) -> None:  # noqa: ANN002, ANN003
        async with connection(workflow.campus_url) as conn:
            await conn.execute(
                "UPDATE requests SET created_at=now()-interval '2 hours',"
                "expires_at=now()-interval '1 hour' WHERE id=$1",
                selection.request_id,
            )
        await original(*args, **kwargs)

    monkeypatch.setattr(coordinator, "prepare_acceptance", expire)
    result = await workflow.client.post(selection.url, headers=HEADERS)
    assert result.status_code == status.HTTP_409_CONFLICT
    assert result.json()["detail"]["code"] == "request_expired"
    await assert_settlement(workflow, selection, rewarded=False)


async def test_payout_uses_hold_without_another_requester_debit(
    workflow: Workflow, selection: Selection
) -> None:
    """The owner can spend their remaining balance without losing the escrow."""
    async with connection(workflow.points_url) as conn:
        await conn.execute(
            "UPDATE wallets SET available_points=0 WHERE user_id=1"
        )
    result = await workflow.client.post(selection.url, headers=HEADERS)
    assert result.status_code == status.HTTP_200_OK, result.text
    async with connection(workflow.points_url) as conn:
        assert (
            await conn.fetchval(
                "SELECT available_points FROM wallets WHERE user_id=1"
            )
            == 0
        )
        assert (
            await conn.fetchval(
                "SELECT available_points FROM wallets WHERE user_id=2"
            )
            == REWARDED_BALANCE
        )


@pytest.mark.parametrize("condition", ["mismatched_owner", "settled"])
async def test_points_validates_escrow_before_release(
    workflow: Workflow, selection: Selection, condition: str
) -> None:
    """Escrow ownership and settlement state are checked under its row lock."""
    async with connection(workflow.points_url) as conn:
        if condition == "mismatched_owner":
            await conn.execute(
                "UPDATE escrows SET requester_id=2 WHERE request_id=$1",
                selection.request_id,
            )
        else:
            await conn.execute(
                "UPDATE escrows SET status='refunded' WHERE request_id=$1",
                selection.request_id,
            )
    result = await workflow.client.post(selection.url, headers=HEADERS)
    assert result.status_code == status.HTTP_409_CONFLICT
    assert result.json()["detail"]["code"] == (
        "escrow_mismatch"
        if condition == "mismatched_owner"
        else "escrow_already_settled"
    )
    async with connection(workflow.campus_url) as conn:
        assert (
            await conn.fetchval(
                "SELECT status FROM requests WHERE id=$1", selection.request_id
            )
            == "open"
        )
    async with connection(workflow.points_url) as conn:
        assert (
            await conn.fetchval(
                "SELECT available_points FROM wallets WHERE user_id=2"
            )
            == INITIAL_BALANCE
        )
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM points_transactions WHERE type='reward'"
            )
            == 0
        )
