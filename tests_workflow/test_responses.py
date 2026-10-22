"""Exercise Campus-only response 2PC against disposable PostgreSQL."""

import asyncio
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import status

from app.config.settings import get_settings
from app.managers import coordinator, response_participant
from app.managers.security import get_current_user
from app.models.user import User
from app.transactions.postgres import connection
from tests_workflow.conftest import Workflow

ROOT = get_settings().api_root
BODY = {"answer": "There are free tables on the second floor."}
HEADERS = {"Idempotency-Key": "answer-1"}
CONTRIBUTOR_ID = 2
pytestmark = pytest.mark.asyncio


def authenticate(workflow: Workflow, user_id: int) -> None:
    """Switch the controlled identity without bypassing route authorization."""

    async def user() -> User:
        return User(id=user_id)

    workflow.campus.dependency_overrides[get_current_user] = user


@pytest_asyncio.fixture
async def response_request(workflow: Workflow) -> int:
    """Create a real parent with a hold, then authenticate another user."""
    created = await workflow.client.post(
        ROOT + "/requests",
        json={"location_id": 1, "title": "Library", "description": "Seats?"},
        headers={"Idempotency-Key": "parent-for-responses"},
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    authenticate(workflow, 2)
    return created.json()["request"]["id"]


async def test_response_creation_and_retry_without_points(
    workflow: Workflow, response_request: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Commit once with a Campus vote and leave all Points data unchanged."""
    points = AsyncMock(
        side_effect=AssertionError("Responses must not call Points")
    )
    monkeypatch.setattr(coordinator, "call_points", points)
    url = ROOT + f"/requests/{response_request}/responses"
    first = await workflow.client.post(url, json=BODY, headers=HEADERS)
    assert first.status_code == status.HTTP_201_CREATED, first.text
    body = first.json()
    assert body["status"] == "completed"
    assert body["response"]["contributor_id"] == CONTRIBUTOR_ID
    assert body["response"]["request_id"] == response_request
    assert body["response"]["moderation_status"] == "visible"
    assert "reward_points" not in body
    retry = await workflow.client.post(url, json=BODY, headers=HEADERS)
    assert retry.json() == body
    polled = await workflow.client.get(
        ROOT + "/operations/" + body["operation_id"]
    )
    assert polled.json() == body
    points.assert_not_awaited()
    async with connection(workflow.campus_url) as conn:
        rows = await conn.fetch(
            "SELECT participant,vote,acknowledged "
            "FROM transaction_participants "
            "WHERE transaction_id=$1",
            UUID(body["operation_id"]),
        )
        assert [dict(row) for row in rows] == [
            {"participant": "campus", "vote": "yes", "acknowledged": True}
        ]
        assert await conn.fetchval("SELECT count(*) FROM responses") == 1
        assert (
            await conn.fetchval(
                "SELECT operation FROM participant_transactions "
                "WHERE transaction_id=$1",
                UUID(body["operation_id"]),
            )
            == "create_response"
        )
    async with connection(workflow.points_url) as conn:
        wallets = await conn.fetch(
            "SELECT available_points FROM wallets ORDER BY user_id"
        )
        assert [row["available_points"] for row in wallets] == [95, 100]
        assert await conn.fetchval("SELECT count(*) FROM escrows") == 1
        assert (
            await conn.fetchval("SELECT count(*) FROM points_transactions") == 1
        )


@pytest.mark.parametrize(
    ("answer", "expected"),
    [("Seats available.", "visible"), ("This is SHIT!", "hidden")],
)
async def test_response_moderation_visibility(
    workflow: Workflow, response_request: int, answer: str, expected: str
) -> None:
    """Contributors can see their hidden answers; other users cannot."""
    url = ROOT + f"/requests/{response_request}/responses"
    created = await workflow.client.post(
        url, json={"answer": answer}, headers=HEADERS
    )
    assert created.status_code == status.HTTP_201_CREATED, created.text
    response = created.json()["response"]
    assert response["moderation_status"] == expected
    own = await workflow.client.get(ROOT + f"/responses/{response['id']}")
    assert own.json() == response
    own_list = await workflow.client.get(url)
    assert own_list.json()["items"] == [response]
    mine = await workflow.client.get(url + "?mine=true&size=1")
    assert mine.json()["items"] == [response]
    authenticate(workflow, 1)
    other_list = await workflow.client.get(url)
    assert other_list.json()["items"] == (
        [response] if expected == "visible" else []
    )
    other_mine = await workflow.client.get(url + "?mine=true")
    assert other_mine.json()["items"] == []
    other = await workflow.client.get(ROOT + f"/responses/{response['id']}")
    assert other.status_code == (200 if expected == "visible" else 404)
    operation = await workflow.client.get(
        ROOT + "/operations/" + created.json()["operation_id"]
    )
    assert operation.status_code == status.HTTP_404_NOT_FOUND


async def test_failed_moderation_saves_pending_response(
    workflow: Workflow, response_request: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A local moderation failure persists a contributor-only pending answer."""
    monkeypatch.setattr(
        "app.managers.moderation.get_settings", Mock(side_effect=OSError)
    )
    url = ROOT + f"/requests/{response_request}/responses"
    created = await workflow.client.post(url, json=BODY, headers=HEADERS)
    assert created.status_code == status.HTTP_201_CREATED, created.text
    assert created.json()["response"]["moderation_status"] == "pending"
    own = await workflow.client.get(url)
    assert len(own.json()["items"]) == 1
    authenticate(workflow, 1)
    other = await workflow.client.get(url)
    assert other.json()["items"] == []


@pytest.mark.parametrize(
    ("condition", "expected_status", "code"),
    [
        ("self", 403, "self_response_forbidden"),
        ("missing", 404, "request_not_found"),
        ("hidden", 404, "request_not_found"),
        ("pending", 404, "request_not_found"),
        ("unconfirmed", 404, "request_not_found"),
        ("closed", 409, "request_not_open"),
        ("expired", 409, "request_expired"),
    ],
)
async def test_response_parent_eligibility(
    workflow: Workflow,
    response_request: int,
    condition: str,
    expected_status: int,
    code: str,
) -> None:
    """Require an accessible, committed, open parent and a different author."""
    if condition == "self":
        authenticate(workflow, 1)
    elif condition == "missing":
        response_request += 100
    else:
        async with connection(workflow.campus_url) as conn:
            if condition in {"hidden", "pending"}:
                await conn.execute(
                    "UPDATE requests SET moderation_status=$2 WHERE id=$1",
                    response_request,
                    condition,
                )
            elif condition == "unconfirmed":
                await conn.execute(
                    "UPDATE distributed_transactions "
                    "SET state='commit_decided' WHERE request_id=$1",
                    response_request,
                )
            elif condition == "closed":
                await conn.execute(
                    "UPDATE requests SET status='completed' WHERE id=$1",
                    response_request,
                )
            else:
                await conn.execute(
                    "UPDATE requests SET created_at=now()-interval '2 hours',"
                    "expires_at=now()-interval '1 hour' WHERE id=$1",
                    response_request,
                )
    result = await workflow.client.post(
        ROOT + f"/requests/{response_request}/responses",
        json=BODY,
        headers=HEADERS,
    )
    assert result.status_code == expected_status, result.text
    assert result.json()["detail"]["code"] == code
    async with connection(workflow.campus_url) as conn:
        assert await conn.fetchval("SELECT count(*) FROM responses") == 0
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM distributed_transactions "
                "WHERE operation='create_response'"
            )
            == 0
        )


async def test_response_duplicate_and_idempotency_conflicts(
    workflow: Workflow, response_request: int
) -> None:
    """Reject duplicate answers and keys reused for other submissions."""
    url = ROOT + f"/requests/{response_request}/responses"
    created = await workflow.client.post(url, json=BODY, headers=HEADERS)
    assert created.status_code == status.HTTP_201_CREATED
    duplicate = await workflow.client.post(
        url, json=BODY, headers={"Idempotency-Key": "second-answer"}
    )
    assert duplicate.status_code == status.HTTP_409_CONFLICT
    assert duplicate.json()["detail"]["code"] == "duplicate_response"
    for body, key in (
        ({"answer": "Changed"}, "answer-1"),
        (BODY, "parent-for-responses"),
    ):
        result = await workflow.client.post(
            url, json=body, headers={"Idempotency-Key": key}
        )
        assert result.status_code == status.HTTP_409_CONFLICT
        assert result.json()["detail"]["code"] == "idempotency_conflict"
    authenticate(workflow, 1)
    conflict = await workflow.client.post(url, json=BODY, headers=HEADERS)
    assert conflict.status_code == status.HTTP_409_CONFLICT


async def test_concurrent_responses_same_contributor(
    workflow: Workflow, response_request: int
) -> None:
    """The database unique constraint protects simultaneous different keys."""
    url = ROOT + f"/requests/{response_request}/responses"
    results = await asyncio.gather(
        *(
            workflow.client.post(
                url, json=BODY, headers={"Idempotency-Key": f"race-{i}"}
            )
            for i in range(2)
        )
    )
    assert sorted(result.status_code for result in results) == [201, 409]
    async with connection(workflow.campus_url) as conn:
        assert await conn.fetchval("SELECT count(*) FROM responses") == 1


async def test_concurrent_response_retries(
    workflow: Workflow, response_request: int
) -> None:
    """One key identifies one operation during parallel retries."""
    url = ROOT + f"/requests/{response_request}/responses"
    results = await asyncio.gather(
        *(
            workflow.client.post(url, json=BODY, headers=HEADERS)
            for _ in range(3)
        )
    )
    assert all(result.status_code in {201, 202} for result in results)
    operation_ids = {result.json()["operation_id"] for result in results}
    assert len(operation_ids) == 1
    final = await coordinator.advance_operation(UUID(operation_ids.pop()))
    assert final.status == "completed"
    async with connection(workflow.campus_url) as conn:
        assert await conn.fetchval("SELECT count(*) FROM responses") == 1


async def test_response_retry_after_parent_closes(
    workflow: Workflow, response_request: int
) -> None:
    """Replaying completed work keeps its result even if eligibility changes."""
    url = ROOT + f"/requests/{response_request}/responses"
    first = await workflow.client.post(url, json=BODY, headers=HEADERS)
    async with connection(workflow.campus_url) as conn:
        await conn.execute(
            "UPDATE requests SET status='completed' WHERE id=$1",
            response_request,
        )
    retry = await workflow.client.post(url, json=BODY, headers=HEADERS)
    assert retry.status_code == status.HTTP_201_CREATED
    assert retry.json() == first.json()


async def test_response_lost_prepare_rolls_back(
    workflow: Workflow, response_request: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed Yes delivery aborts and records the correct operation."""
    original = coordinator.prepare_response

    async def lost(*args, **kwargs) -> None:  # noqa: ANN002, ANN003
        await original(*args, **kwargs)
        raise OSError

    monkeypatch.setattr(coordinator, "prepare_response", lost)
    result = await workflow.client.post(
        ROOT + f"/requests/{response_request}/responses",
        json=BODY,
        headers=HEADERS,
    )
    assert result.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    async with connection(workflow.campus_url) as conn:
        assert await conn.fetchval("SELECT count(*) FROM responses") == 0
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM pg_prepared_xacts "
                "WHERE database=current_database()"
            )
            == 0
        )
        journal = await conn.fetchrow(
            "SELECT operation,state FROM participant_transactions "
            "WHERE transaction_id=$1",
            UUID(result.json()["detail"]["operation_id"]),
        )
        assert dict(journal) == {
            "operation": "create_response",
            "state": "aborted",
        }


async def test_response_lost_commit_acknowledgement(
    workflow: Workflow, response_request: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Expose a response only after the coordinator records acknowledgement."""
    original = coordinator.finish_request

    async def lost(*args, **kwargs) -> None:  # noqa: ANN002, ANN003
        await original(*args, **kwargs)
        raise OSError

    monkeypatch.setattr(coordinator, "finish_request", lost)
    url = ROOT + f"/requests/{response_request}/responses"
    result = await workflow.client.post(url, json=BODY, headers=HEADERS)
    assert result.status_code == status.HTTP_202_ACCEPTED
    assert result.json()["response"] is None
    listed = await workflow.client.get(url)
    assert listed.json()["items"] == []
    monkeypatch.setattr(coordinator, "finish_request", original)
    recovered = await workflow.client.get(
        ROOT + "/operations/" + result.json()["operation_id"]
    )
    assert recovered.json()["status"] == "completed"
    assert recovered.json()["response"]["answer"] == BODY["answer"]
    assert "reward_points" not in recovered.json()


class SimulatedResponseCrash(BaseException):
    """Stop coordination without entering its failure handling."""


@pytest.mark.parametrize("recorded", [False, True])
async def test_response_crash_recovery(
    workflow: Workflow,
    response_request: int,
    monkeypatch: pytest.MonkeyPatch,
    *,
    recorded: bool,
) -> None:
    """Recover prepared responses with or without a recorded commit decision."""
    original = coordinator.record_decision

    async def crash(*args, **kwargs) -> None:  # noqa: ANN002, ANN003
        if recorded:
            await original(*args, **kwargs)
        raise SimulatedResponseCrash

    monkeypatch.setattr(coordinator, "record_decision", crash)
    with pytest.raises(SimulatedResponseCrash):
        await workflow.client.post(
            ROOT + f"/requests/{response_request}/responses",
            json=BODY,
            headers=HEADERS,
        )
    async with connection(workflow.campus_url) as conn:
        assert await conn.fetchval("SELECT count(*) FROM responses") == 0
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM pg_prepared_xacts "
                "WHERE database=current_database()"
            )
            == 1
        )
    monkeypatch.setattr(coordinator, "record_decision", original)
    await coordinator.recover_operations()
    listed = await workflow.client.get(
        ROOT + f"/requests/{response_request}/responses"
    )
    assert len(listed.json()["items"]) == 1


async def test_response_local_write_rollback(
    workflow: Workflow, response_request: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Roll back insertion if local work fails before preparation."""
    original = response_participant.insert_response

    async def fail(*args, **kwargs) -> None:  # noqa: ANN002, ANN003
        await original(*args, **kwargs)
        raise OSError

    monkeypatch.setattr(response_participant, "insert_response", fail)
    result = await workflow.client.post(
        ROOT + f"/requests/{response_request}/responses",
        json=BODY,
        headers=HEADERS,
    )
    assert result.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    async with connection(workflow.campus_url) as conn:
        assert await conn.fetchval("SELECT count(*) FROM responses") == 0


async def test_response_rechecks_parent_during_prepare(
    workflow: Workflow, response_request: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject a parent closed after intake but before local preparation."""
    original = coordinator.prepare_response

    async def close(*args, **kwargs) -> None:  # noqa: ANN002, ANN003
        async with connection(workflow.campus_url) as conn:
            await conn.execute(
                "UPDATE requests SET status='completed' WHERE id=$1",
                response_request,
            )
        await original(*args, **kwargs)

    monkeypatch.setattr(coordinator, "prepare_response", close)
    result = await workflow.client.post(
        ROOT + f"/requests/{response_request}/responses",
        json=BODY,
        headers=HEADERS,
    )
    assert result.status_code == status.HTTP_409_CONFLICT
    assert result.json()["detail"]["code"] == "request_not_open"


async def test_response_list_pagination_and_parent_visibility(
    workflow: Workflow, response_request: int
) -> None:
    """Page confirmed answers and prevent disclosure through hidden parents."""
    async with connection(workflow.campus_url) as conn:
        await conn.execute(
            "INSERT INTO users "
            "(id,email,password,first_name,last_name,banned,verified) VALUES "
            "(3,'three@example.com','unused','Three','Test',false,true)"
        )
    url = ROOT + f"/requests/{response_request}/responses"
    created = []
    for contributor in (2, 3):
        authenticate(workflow, contributor)
        result = await workflow.client.post(
            url,
            json=BODY,
            headers={"Idempotency-Key": f"contributor-{contributor}"},
        )
        assert result.status_code == status.HTTP_201_CREATED, result.text
        created.append(result.json()["response"])
    mine = await workflow.client.get(url + "?mine=true&size=1")
    assert mine.json()["items"] == created[1:]
    authenticate(workflow, 1)
    first = await workflow.client.get(url + "?size=1")
    second = await workflow.client.get(url + "?size=1&page=2")
    assert first.json()["items"] == created[:1]
    assert first.json()["has_more"] is True
    assert second.json()["items"] == created[1:]
    assert second.json()["has_more"] is False
    async with connection(workflow.campus_url) as conn:
        assert (
            await conn.fetchval(
                "SELECT status FROM requests WHERE id=$1", response_request
            )
            == "open"
        )
        await conn.execute(
            "UPDATE requests SET moderation_status='hidden' WHERE id=$1",
            response_request,
        )
    # The requester retains access to their own parent and visible answers.
    owner = await workflow.client.get(url)
    assert owner.json()["items"] == created
    authenticate(workflow, 2)
    inaccessible = await workflow.client.get(url)
    assert inaccessible.status_code == status.HTTP_404_NOT_FOUND
    direct = await workflow.client.get(ROOT + f"/responses/{created[0]['id']}")
    assert direct.status_code == status.HTTP_404_NOT_FOUND


async def test_response_read_after_parent_expiry(
    workflow: Workflow, response_request: int
) -> None:
    """Expiry stops new answers while existing answers remain readable."""
    url = ROOT + f"/requests/{response_request}/responses"
    created = await workflow.client.post(url, json=BODY, headers=HEADERS)
    async with connection(workflow.campus_url) as conn:
        await conn.execute(
            "UPDATE requests SET created_at=now()-interval '2 hours',"
            "expires_at=now()-interval '1 hour' WHERE id=$1",
            response_request,
        )
    listed = await workflow.client.get(url)
    assert listed.json()["items"] == [created.json()["response"]]
