"""Verify administrative decisions with real Campus and Points preparations."""

import asyncio
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import status

from app.managers import coordinator
from app.managers.security import get_current_user
from app.models.enums import RoleType
from app.models.user import User
from app.points.managers import acceptance as points_acceptance
from app.points.managers import refund as points_refund
from app.transactions.postgres import connection
from tests_workflow.conftest import Workflow
from tests_workflow.test_acceptance import (
    ROOT,
    Selection,
    SimulatedAcceptanceCrash,
    authenticate,
    selection,  # noqa: F401
)

pytestmark = pytest.mark.asyncio
HEADERS = {"Idempotency-Key": "admin-resolution"}


def authenticate_admin(workflow: Workflow) -> None:
    """Use the real seeded administrator as the HTTP caller."""

    async def user() -> User:
        return User(id=3, role=RoleType.admin)

    workflow.campus.dependency_overrides[get_current_user] = user


@pytest_asyncio.fixture
async def conflict(
    workflow: Workflow,
    selection: Selection,  # noqa: F811
) -> Selection:
    """Expire an answered request and authenticate a separate administrator."""
    async with connection(workflow.campus_url) as conn:
        await conn.execute(
            "INSERT INTO users "
            "(id,email,password,first_name,last_name,role,banned,verified) "
            "VALUES (3,'admin@example.com','unused','Admin','Test',"
            "'admin',false,true)"
        )
        await conn.execute(
            "UPDATE requests SET status='conflicted',"
            "created_at=now()-interval '2 hours',"
            "expires_at=now()-interval '1 hour' WHERE id=$1",
            selection.request_id,
        )
    authenticate_admin(workflow)
    return selection


def action_url(selected: Selection, action: str) -> str:
    """Use the existing acceptance action or the new admin refund action."""
    if action == "award":
        return selected.url
    return ROOT + f"/requests/{selected.request_id}/refund"


async def assert_resolution(
    workflow: Workflow, selected: Selection, outcome: str
) -> None:
    """Verify one settlement, correct financial recipient, and reputation."""
    awarded = outcome == "award"
    refunded = outcome == "refund"
    async with connection(workflow.campus_url) as conn:
        parent = await conn.fetchrow(
            "SELECT * FROM requests WHERE id=$1", selected.request_id
        )
        assert (
            parent["status"]
            == {
                "award": "completed",
                "refund": "expired",
                "held": "conflicted",
            }[outcome]
        )
        assert parent["accepted_response_id"] == (
            selected.response_id if awarded else None
        )
        assert (parent["accepted_at"] is not None) is awarded
    async with connection(workflow.points_url) as conn:
        wallets = await conn.fetch(
            "SELECT available_points,reputation FROM wallets ORDER BY user_id"
        )
        assert [dict(row) for row in wallets] == [
            {"available_points": 100 if refunded else 95, "reputation": 0},
            {
                "available_points": 105 if awarded else 100,
                "reputation": int(awarded),
            },
        ]
        escrow = await conn.fetchrow(
            "SELECT * FROM escrows WHERE request_id=$1", selected.request_id
        )
        assert (
            escrow["status"]
            == {"award": "released", "refund": "refunded", "held": "held"}[
                outcome
            ]
        )
        assert escrow["recipient_id"] == (2 if awarded else None)
        assert escrow["awarded_response_id"] == (
            selected.response_id if awarded else None
        )
        entries = await conn.fetch(
            "SELECT user_id,type,amount FROM points_transactions "
            "WHERE type IN ('reward','refund')"
        )
        expected = (
            []
            if outcome == "held"
            else [
                {
                    "user_id": 2 if awarded else 1,
                    "type": "reward" if awarded else "refund",
                    "amount": 5,
                }
            ]
        )
        assert [dict(row) for row in entries] == expected
        assert (
            sum(row["available_points"] for row in wallets)
            + (5 if outcome == "held" else 0)
            == 200  # noqa: PLR2004
        )


@pytest.mark.parametrize("action", ["award", "refund"])
async def test_resolution_and_retries(
    workflow: Workflow, conflict: Selection, action: str
) -> None:
    """Award or refund the actual participants, auditing the administrator."""
    url = action_url(conflict, action)
    first = await workflow.client.post(url, headers=HEADERS)
    assert first.status_code == status.HTTP_200_OK, first.text
    body = first.json()
    assert body["status"] == "completed"
    for _ in range(2):
        retried = await workflow.client.post(url, headers=HEADERS)
        assert retried.json() == body
    polled = await workflow.client.get(
        ROOT + "/operations/" + body["operation_id"]
    )
    assert polled.json() == body
    async with connection(workflow.campus_url) as conn:
        saved = await conn.fetchrow(
            "SELECT owner_id,payload FROM distributed_transactions WHERE id=$1",
            UUID(body["operation_id"]),
        )
        assert saved["owner_id"] == 3  # noqa: PLR2004
        assert '"requester_id": 1' in saved["payload"]
        participants = await conn.fetch(
            "SELECT vote,acknowledged FROM transaction_participants "
            "WHERE transaction_id=$1",
            UUID(body["operation_id"]),
        )
        assert len(participants) == 2  # noqa: PLR2004
        assert all(
            row["vote"] == "yes" and row["acknowledged"] for row in participants
        )
    await assert_resolution(workflow, conflict, action)
    authenticate(workflow, 1)
    private = await workflow.client.get(
        ROOT + "/operations/" + body["operation_id"]
    )
    assert private.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.parametrize("action", ["award", "refund"])
@pytest.mark.parametrize("user_id", [1, 2])
async def test_regular_users_cannot_resolve(
    workflow: Workflow, conflict: Selection, action: str, user_id: int
) -> None:
    """Neither requester nor contributor may settle an expired conflict."""
    authenticate(workflow, user_id)
    result = await workflow.client.post(
        action_url(conflict, action), headers=HEADERS
    )
    assert result.status_code in {
        status.HTTP_403_FORBIDDEN,
        status.HTTP_409_CONFLICT,
    }
    await assert_resolution(workflow, conflict, "held")


@pytest.mark.parametrize("action", ["award", "refund"])
@pytest.mark.parametrize("request_status", ["open", "expired", "completed"])
async def test_resolution_requires_conflict(
    workflow: Workflow, conflict: Selection, action: str, request_status: str
) -> None:
    """Administrator privileges do not override other lifecycle states."""
    async with connection(workflow.campus_url) as conn:
        await conn.execute("UPDATE requests SET status=$1", request_status)
    result = await workflow.client.post(
        action_url(conflict, action), headers=HEADERS
    )
    assert result.status_code in {
        status.HTTP_403_FORBIDDEN,
        status.HTTP_409_CONFLICT,
    }
    async with connection(workflow.points_url) as conn:
        assert await conn.fetchval("SELECT status FROM escrows") == "held"


@pytest.mark.parametrize("action", ["award", "refund"])
async def test_future_conflict_cannot_settle(
    workflow: Workflow, conflict: Selection, action: str
) -> None:
    """A premature conflicted flag cannot bypass the one-hour deadline."""
    async with connection(workflow.campus_url) as conn:
        await conn.execute(
            "UPDATE requests SET expires_at=now()+interval '1 hour'"
        )
    result = await workflow.client.post(
        action_url(conflict, action), headers=HEADERS
    )
    assert result.status_code == status.HTTP_409_CONFLICT
    assert result.json()["detail"]["code"] == "request_not_expired"
    await assert_resolution(workflow, conflict, "held")


@pytest.mark.parametrize("moderation", ["hidden", "pending"])
async def test_admin_cannot_reward_unpublished_answers(
    workflow: Workflow, conflict: Selection, moderation: str
) -> None:
    """Conflict resolution preserves visible-only answer eligibility."""
    async with connection(workflow.campus_url) as conn:
        await conn.execute(
            "UPDATE responses SET moderation_status=$1", moderation
        )
    result = await workflow.client.post(conflict.url, headers=HEADERS)
    assert result.status_code == status.HTTP_404_NOT_FOUND
    await assert_resolution(workflow, conflict, "held")


@pytest.mark.parametrize("action", ["award", "refund"])
async def test_admin_can_resolve_hidden_parent(
    workflow: Workflow, conflict: Selection, action: str
) -> None:
    """Parent moderation does not strand a conflicted escrow."""
    async with connection(workflow.campus_url) as conn:
        await conn.execute("UPDATE requests SET moderation_status='hidden'")
    result = await workflow.client.post(
        action_url(conflict, action), headers=HEADERS
    )
    assert result.status_code == status.HTTP_200_OK, result.text
    await assert_resolution(workflow, conflict, action)


@pytest.mark.parametrize("action", ["award", "refund"])
@pytest.mark.parametrize(
    "change", ["role='user'", "banned=true", "verified=false"]
)
async def test_prepare_rechecks_admin_permission(
    workflow: Workflow,
    conflict: Selection,
    action: str,
    change: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale authenticated identity cannot settle after access is revoked."""
    name = "prepare_acceptance" if action == "award" else "prepare_expiration"
    original = getattr(coordinator, name)

    async def revoked(*args, **kwargs) -> None:  # noqa: ANN002, ANN003
        async with connection(workflow.campus_url) as conn:
            updates = {
                "role='user'": "UPDATE users SET role='user' WHERE id=3",
                "banned=true": "UPDATE users SET banned=true WHERE id=3",
                "verified=false": "UPDATE users SET verified=false WHERE id=3",
            }
            await conn.execute(updates[change])
        await original(*args, **kwargs)

    monkeypatch.setattr(coordinator, name, revoked)
    result = await workflow.client.post(
        action_url(conflict, action), headers=HEADERS
    )
    assert result.status_code == status.HTTP_403_FORBIDDEN, result.text
    assert result.json()["detail"]["code"] == "admin_required"
    await assert_resolution(workflow, conflict, "held")


@pytest.mark.parametrize("action", ["award", "refund"])
async def test_financial_failure_rolls_back_resolution(
    workflow: Workflow,
    conflict: Selection,
    action: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failure after all financial writes rolls back both participants."""
    module = points_acceptance if action == "award" else points_refund
    name = (
        "award_response_points"
        if action == "award"
        else "refund_request_points"
    )
    original = getattr(module, name)

    async def failed(*args, **kwargs) -> None:  # noqa: ANN002, ANN003
        await original(*args, **kwargs)
        raise OSError

    monkeypatch.setattr(module, name, failed)
    result = await workflow.client.post(
        action_url(conflict, action), headers=HEADERS
    )
    assert result.status_code == status.HTTP_503_SERVICE_UNAVAILABLE, (
        result.text
    )
    await assert_resolution(workflow, conflict, "held")
    monkeypatch.setattr(module, name, original)
    same = await workflow.client.post(
        action_url(conflict, action), headers=HEADERS
    )
    assert same.json() == result.json()
    fresh = await workflow.client.post(
        action_url(conflict, action),
        headers={"Idempotency-Key": "fixed-resolution"},
    )
    assert fresh.status_code == status.HTTP_200_OK, fresh.text
    await assert_resolution(workflow, conflict, action)


@pytest.mark.parametrize("action", ["award", "refund"])
@pytest.mark.parametrize("recorded", [False, True])
async def test_resolution_crash_recovery(
    workflow: Workflow,
    conflict: Selection,
    action: str,
    monkeypatch: pytest.MonkeyPatch,
    *,
    recorded: bool,
) -> None:
    """Prepared payloads survive recovery, including administrator identity."""
    original = coordinator.record_decision

    async def crash(*args, **kwargs) -> None:  # noqa: ANN002, ANN003
        if recorded:
            await original(*args, **kwargs)
        raise SimulatedAcceptanceCrash

    monkeypatch.setattr(coordinator, "record_decision", crash)
    with pytest.raises(SimulatedAcceptanceCrash):
        await workflow.client.post(
            action_url(conflict, action), headers=HEADERS
        )
    await assert_resolution(workflow, conflict, "held")
    monkeypatch.setattr(coordinator, "record_decision", original)
    await coordinator.recover_operations()
    await assert_resolution(workflow, conflict, action)


@pytest.mark.parametrize("action", ["award", "refund"])
async def test_lost_commit_acknowledgement(
    workflow: Workflow,
    conflict: Selection,
    action: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Report processing and finish by polling without duplicate settlement."""
    original = coordinator.call_points

    async def lost(transaction_id, decision, payload=None) -> None:  # noqa: ANN001
        await original(transaction_id, decision, payload)
        if decision == "commit":
            raise OSError

    monkeypatch.setattr(coordinator, "call_points", lost)
    result = await workflow.client.post(
        action_url(conflict, action), headers=HEADERS
    )
    assert result.status_code == status.HTTP_202_ACCEPTED, result.text
    assert result.json()["status"] == "processing"
    assert result.json()["request"] is None
    monkeypatch.setattr(coordinator, "call_points", original)
    polled = await workflow.client.get(
        ROOT + "/operations/" + result.json()["operation_id"]
    )
    assert polled.json()["status"] == "completed", polled.text
    await assert_resolution(workflow, conflict, action)


async def test_award_and_refund_compete(
    workflow: Workflow,
    conflict: Selection,
) -> None:
    """Simultaneous administrator choices produce exactly one settlement."""
    results = await asyncio.gather(
        *(
            workflow.client.post(
                action_url(conflict, action),
                headers={"Idempotency-Key": action},
            )
            for action in ("award", "refund")
        )
    )
    assert sorted(result.status_code for result in results) == [200, 409]
    outcome = (
        "award" if results[0].status_code == status.HTTP_200_OK else "refund"
    )
    await assert_resolution(workflow, conflict, outcome)


@pytest.mark.parametrize("action", ["award", "refund"])
async def test_concurrent_admin_retries(
    workflow: Workflow,
    conflict: Selection,
    action: str,
) -> None:
    """Concurrent calls with one key retain one durable operation."""
    results = await asyncio.gather(
        *(
            workflow.client.post(action_url(conflict, action), headers=HEADERS)
            for _ in range(3)
        )
    )
    assert all(result.status_code in {200, 202} for result in results)
    ids = {result.json()["operation_id"] for result in results}
    assert len(ids) == 1
    final = await coordinator.advance_operation(UUID(ids.pop()))
    assert final.status == "completed"
    await assert_resolution(workflow, conflict, action)


async def test_idempotency_key_cannot_change_resolution(
    workflow: Workflow,
    conflict: Selection,
) -> None:
    """Reusing an award key for refund cannot change the committed decision."""
    awarded = await workflow.client.post(conflict.url, headers=HEADERS)
    assert awarded.status_code == status.HTTP_200_OK
    refund = await workflow.client.post(
        action_url(conflict, "refund"), headers=HEADERS
    )
    assert refund.status_code == status.HTTP_409_CONFLICT
    assert refund.json()["detail"]["code"] == "idempotency_conflict"
    await assert_resolution(workflow, conflict, "award")
