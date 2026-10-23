"""Count hidden submissions atomically with their native Campus transactions."""

import asyncio
from dataclasses import dataclass
from unittest.mock import Mock
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import Request, status
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend

from app.config.settings import get_settings
from app.database.db import get_database, get_database_manual
from app.managers import coordinator, request_participant, response_participant
from app.managers.security import get_current_user
from app.models.user import User
from app.transactions.postgres import connection
from tests_workflow.conftest import Workflow
from tests_workflow.test_responses import authenticate

ROOT = get_settings().api_root
HEADERS = {"Idempotency-Key": "violation-submission"}
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.parametrize("kind", ["request", "response"]),
]


@dataclass
class Submission:
    """Identify a hidden request or an answer to a clean funded request."""

    kind: str
    url: str
    body: dict[str, str | int]
    author_id: int


@pytest_asyncio.fixture
async def submission(workflow: Workflow, kind: str) -> Submission:
    """Prepare the authenticated author and request/response route."""
    if kind == "request":
        return Submission(
            kind,
            ROOT + "/requests",
            {"location_id": 1, "title": "SHIT!", "description": "shit again"},
            1,
        )
    parent = await workflow.client.post(
        ROOT + "/requests",
        json={"location_id": 1, "title": "Library", "description": "Seats?"},
        headers={"Idempotency-Key": "violation-parent"},
    )
    assert parent.status_code == status.HTTP_201_CREATED, parent.text
    authenticate(workflow, 2)
    return Submission(
        kind,
        ROOT + f"/requests/{parent.json()['request']['id']}/responses",
        {"answer": "SHIT! shit again"},
        2,
    )


async def assert_counts(
    workflow: Workflow, submission: Submission, count: int
) -> None:
    """Only the author gains violations; the other user remains at zero."""
    async with connection(workflow.campus_url) as conn:
        users = await conn.fetch("SELECT id,violations FROM users ORDER BY id")
        assert [row["violations"] for row in users] == [
            count if row["id"] == submission.author_id else 0 for row in users
        ]


async def test_hidden_submission_counts_once(
    workflow: Workflow,
    submission: Submission,
) -> None:
    """Multiple bad words, exact retries, and polling still count one item."""
    await assert_counts(workflow, submission, 0)
    first = await workflow.client.post(
        submission.url, json=submission.body, headers=HEADERS
    )
    assert first.status_code == status.HTTP_201_CREATED, first.text
    assert first.json()[submission.kind]["moderation_status"] == "hidden"
    for _ in range(2):
        repeated = await workflow.client.post(
            submission.url, json=submission.body, headers=HEADERS
        )
        assert repeated.json() == first.json()
    polled = await workflow.client.get(
        ROOT + "/operations/" + first.json()["operation_id"]
    )
    assert polled.json()["status"] == "completed"
    await assert_counts(workflow, submission, 1)


@pytest.mark.parametrize("moderation_fails", [False, True])
async def test_visible_and_pending_do_not_count(
    workflow: Workflow,
    submission: Submission,
    monkeypatch: pytest.MonkeyPatch,
    *,
    moderation_fails: bool,
) -> None:
    """Clean content and failed checks never penalize the author."""
    if moderation_fails:
        monkeypatch.setattr(
            "app.managers.moderation.get_settings", Mock(side_effect=OSError)
        )
    else:
        submission.body = (
            {"location_id": 1, "title": "Library", "description": "Seats?"}
            if submission.kind == "request"
            else {"answer": "Second floor."}
        )
    result = await workflow.client.post(
        submission.url, json=submission.body, headers=HEADERS
    )
    assert result.status_code == status.HTTP_201_CREATED, result.text
    assert result.json()[submission.kind]["moderation_status"] == (
        "pending" if moderation_fails else "visible"
    )
    await assert_counts(workflow, submission, 0)


async def test_different_submissions_accumulate_without_counting_duplicates(
    workflow: Workflow,
    submission: Submission,
) -> None:
    """New bad requests count separately; duplicate answers do not count."""
    first = await workflow.client.post(
        submission.url, json=submission.body, headers=HEADERS
    )
    assert first.status_code == status.HTTP_201_CREATED
    second = await workflow.client.post(
        submission.url,
        json=submission.body,
        headers={"Idempotency-Key": "another-hidden-item"},
    )
    if submission.kind == "request":
        assert second.status_code == status.HTTP_201_CREATED
        await assert_counts(workflow, submission, 2)
    else:
        assert second.status_code == status.HTTP_409_CONFLICT
        assert second.json()["detail"]["code"] == "duplicate_response"
        await assert_counts(workflow, submission, 1)


async def test_counter_rolls_back_with_failed_local_work(
    workflow: Workflow,
    submission: Submission,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure after incrementing removes both the item and increment."""
    module = (
        request_participant
        if submission.kind == "request"
        else response_participant
    )
    name = (
        "insert_request" if submission.kind == "request" else "insert_response"
    )
    original = getattr(module, name)

    async def failed(*args, **kwargs) -> None:  # noqa: ANN002, ANN003
        await original(*args, **kwargs)
        raise OSError

    monkeypatch.setattr(module, name, failed)
    result = await workflow.client.post(
        submission.url, json=submission.body, headers=HEADERS
    )
    assert result.status_code == status.HTTP_503_SERVICE_UNAVAILABLE, (
        result.text
    )
    await assert_counts(workflow, submission, 0)
    monkeypatch.setattr(module, name, original)
    retried = await workflow.client.post(
        submission.url, json=submission.body, headers=HEADERS
    )
    assert retried.json() == result.json()
    fresh = await workflow.client.post(
        submission.url,
        json=submission.body,
        headers={"Idempotency-Key": "fixed-hidden-item"},
    )
    assert fresh.status_code == status.HTTP_201_CREATED, fresh.text
    await assert_counts(workflow, submission, 1)


class SimulatedCrash(BaseException):
    """Interrupt coordination while native transactions remain prepared."""


@pytest.mark.parametrize("recorded", [False, True])
async def test_counter_survives_crash_recovery_once(
    workflow: Workflow,
    submission: Submission,
    monkeypatch: pytest.MonkeyPatch,
    *,
    recorded: bool,
) -> None:
    """A durable preparation or decision recovers one violation increment."""
    original = coordinator.record_decision

    async def crashed(*args, **kwargs) -> None:  # noqa: ANN002, ANN003
        if recorded:
            await original(*args, **kwargs)
        raise SimulatedCrash

    monkeypatch.setattr(coordinator, "record_decision", crashed)
    with pytest.raises(SimulatedCrash):
        await workflow.client.post(
            submission.url, json=submission.body, headers=HEADERS
        )
    await assert_counts(workflow, submission, 0)
    monkeypatch.setattr(coordinator, "record_decision", original)
    await coordinator.recover_operations()
    await coordinator.recover_operations()
    await assert_counts(workflow, submission, 1)


async def test_lost_commit_acknowledgement_does_not_count_twice(
    workflow: Workflow,
    submission: Submission,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Committed increments remain exactly once while acknowledgements retry."""
    original = coordinator.finish_request

    async def lost(*args, **kwargs) -> None:  # noqa: ANN002, ANN003
        await original(*args, **kwargs)
        raise OSError

    monkeypatch.setattr(coordinator, "finish_request", lost)
    result = await workflow.client.post(
        submission.url, json=submission.body, headers=HEADERS
    )
    assert result.status_code == status.HTTP_202_ACCEPTED, result.text
    await assert_counts(workflow, submission, 1)
    monkeypatch.setattr(coordinator, "finish_request", original)
    final = await coordinator.advance_operation(
        UUID(result.json()["operation_id"])
    )
    assert final.status == "completed"
    await assert_counts(workflow, submission, 1)


async def test_concurrent_retries_count_once(
    workflow: Workflow,
    submission: Submission,
) -> None:
    """Concurrent submissions sharing one key never double-increment."""
    results = await asyncio.gather(
        *(
            workflow.client.post(
                submission.url, json=submission.body, headers=HEADERS
            )
            for _ in range(3)
        )
    )
    assert all(result.status_code in {201, 202} for result in results)
    ids = {result.json()["operation_id"] for result in results}
    assert len(ids) == 1
    final = await coordinator.advance_operation(UUID(ids.pop()))
    assert final.status == "completed"
    await assert_counts(workflow, submission, 1)


async def test_profile_exposes_counter(
    workflow: Workflow,
    submission: Submission,
) -> None:
    """The existing profile API makes the count available without a new API."""
    result = await workflow.client.post(
        submission.url, json=submission.body, headers=HEADERS
    )
    assert result.status_code == status.HTTP_201_CREATED

    async def author(request: Request) -> User:
        request.state.user = User(id=submission.author_id)
        return request.state.user

    workflow.campus.dependency_overrides[get_current_user] = author
    workflow.campus.dependency_overrides[get_database] = (
        workflow.campus.dependency_overrides[get_database_manual]
    )
    FastAPICache.reset()
    FastAPICache.init(InMemoryBackend())
    profile = await workflow.client.get(ROOT + "/users/me")
    assert profile.status_code == status.HTTP_200_OK, profile.text
    assert profile.json()["violations"] == 1


async def test_separate_concurrent_items_both_count(
    workflow: Workflow,
    submission: Submission,
) -> None:
    """Atomic updates preserve both increments from independent operations."""
    other_url = submission.url
    if submission.kind == "response":
        authenticate(workflow, 1)
        parent = await workflow.client.post(
            ROOT + "/requests",
            json={
                "location_id": 1,
                "title": "Another request",
                "description": "Seats?",
            },
            headers={"Idempotency-Key": "another-violation-parent"},
        )
        assert parent.status_code == status.HTTP_201_CREATED
        other_url = (
            ROOT + f"/requests/{parent.json()['request']['id']}/responses"
        )
        authenticate(workflow, 2)
    results = await asyncio.gather(
        *(
            workflow.client.post(
                url,
                json=submission.body,
                headers={"Idempotency-Key": f"hidden-item-{index}"},
            )
            for index, url in enumerate((submission.url, other_url))
        )
    )
    assert all(result.status_code in {201, 202} for result in results), [
        result.text for result in results
    ]
    ids = {result.json()["operation_id"] for result in results}
    assert len(ids) == 2  # noqa: PLR2004
    for operation_id in ids:
        result = await coordinator.advance_operation(UUID(operation_id))
        assert result.status == "completed"
    await assert_counts(workflow, submission, 2)
