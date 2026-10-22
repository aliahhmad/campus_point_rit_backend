"""Check durable intake, validation, retry ownership, and concurrency."""

import asyncio
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from fastapi import FastAPI, status
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.settings import get_settings
from app.database.db import get_database_manual
from app.managers.security import get_current_user
from app.models.distributed_transaction import DistributedTransaction
from app.models.location import Location
from app.models.user import User

pytestmark = pytest.mark.asyncio

PAYLOAD = {
    "location_id": 1,
    "title": "Library crowding",
    "description": "Are there seats available on the second floor?",
}
HEADERS = {"Idempotency-Key": "submission-123"}
REWARD_POINTS = 5
URL = f"{get_settings().api_root}/requests"


async def count_operations(sessions: async_sessionmaker[AsyncSession]) -> int:
    """Count committed operations using a separate connection."""
    async with sessions() as session:
        count = await session.scalar(
            select(func.count(DistributedTransaction.id))
        )
        return count or 0


async def test_durable_acceptance(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """Acknowledge only after the owner and exact normalized content commit."""
    response = await client.post(URL, json=PAYLOAD, headers=HEADERS)
    assert response.status_code == status.HTTP_202_ACCEPTED
    body = response.json()
    assert body["status"] == "processing"
    assert body["reward_points"] == REWARD_POINTS
    async with sessions() as session:
        operation = await session.get(
            DistributedTransaction, UUID(body["operation_id"])
        )
        assert operation is not None
        assert operation.owner_id == 1
        assert operation.idempotency_key == HEADERS["Idempotency-Key"]
        assert operation.operation == "create_request"
        assert operation.payload == PAYLOAD
    assert await count_operations(sessions) == 1


async def test_retry_survives_deactivated_location(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """Replay the same operation even after the location becomes inactive."""
    first = await client.post(URL, json=PAYLOAD, headers=HEADERS)
    async with sessions() as session, session.begin():
        location = await session.get(Location, 1)
        assert location is not None
        location.is_active = False
    second = await client.post(URL, json=PAYLOAD, headers=HEADERS)
    assert first.status_code == second.status_code == status.HTTP_202_ACCEPTED
    assert first.json() == second.json()
    assert await count_operations(sessions) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"title": "Different"},
        {"description": "Different"},
        {"location_id": 2},
    ],
)
async def test_key_reuse_with_changed_details(
    client: AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    change: dict[str, str | int],
) -> None:
    """Never modify an existing submission when the same key is reused."""
    await client.post(URL, json=PAYLOAD, headers=HEADERS)
    response = await client.post(URL, json=PAYLOAD | change, headers=HEADERS)
    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json()["detail"]["code"] == "idempotency_conflict"
    assert await count_operations(sessions) == 1


async def test_key_reuse_by_different_owner(
    client: AsyncClient, api: FastAPI
) -> None:
    """Reject another owner without exposing the original operation ID."""
    first = await client.post(URL, json=PAYLOAD, headers=HEADERS)

    async def another_user() -> User:
        return User(id=2)

    api.dependency_overrides[get_current_user] = another_user
    response = await client.post(URL, json=PAYLOAD, headers=HEADERS)
    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json()["detail"]["code"] == "idempotency_conflict"
    assert first.json()["operation_id"] not in response.text


@pytest.mark.parametrize("location_id", [2, 999])
async def test_invalid_location_rolls_back_key(
    client: AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    location_id: int,
) -> None:
    """Missing and inactive locations fail without reserving a key."""
    response = await client.post(
        URL, json=PAYLOAD | {"location_id": location_id}, headers=HEADERS
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert response.json()["detail"]["code"] == "invalid_location"
    assert await count_operations(sessions) == 0
    retry = await client.post(URL, json=PAYLOAD, headers=HEADERS)
    assert retry.status_code == status.HTTP_202_ACCEPTED


@pytest.mark.parametrize(
    "change",
    [
        {"title": " "},
        {"title": "x" * 201},
        {"description": "\t\n"},
        {"description": "x" * 5001},
        {"location_id": 0},
        {"location_id": 2_147_483_648},
        {"location_id": True},
        {"location_id": "1"},
        {"requester_id": 2},
        {"reward_points": 0},
        {"status": "open"},
    ],
)
async def test_invalid_body(
    client: AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    change: dict[str, str | int],
) -> None:
    """Reject invalid text, coerced IDs, and server-owned fields."""
    response = await client.post(URL, json=PAYLOAD | change, headers=HEADERS)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert await count_operations(sessions) == 0


@pytest.mark.parametrize("key", [None, "", "x" * 129, "bad key", "bad/key"])
async def test_invalid_key(client: AsyncClient, key: str | None) -> None:
    """Require a bounded ASCII key without spaces or path characters."""
    headers = {} if key is None else {"Idempotency-Key": key}
    response = await client.post(URL, json=PAYLOAD, headers=headers)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


async def test_text_limits_and_normalization(client: AsyncClient) -> None:
    """Accept maximum lengths and normalize whitespace on retries."""
    payload = PAYLOAD | {"title": "x" * 200, "description": "y" * 5000}
    first = await client.post(URL, json=payload, headers=HEADERS)
    second = await client.post(
        URL,
        json=payload | {"title": f"  {payload['title']}  "},
        headers=HEADERS,
    )
    assert first.status_code == second.status_code == status.HTTP_202_ACCEPTED
    assert first.json() == second.json()


async def test_new_key_starts_new_submission(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """Identical content can be submitted intentionally under a fresh key."""
    first = await client.post(URL, json=PAYLOAD, headers=HEADERS)
    second = await client.post(
        URL, json=PAYLOAD, headers={"Idempotency-Key": "new-submission"}
    )
    assert first.status_code == second.status_code == status.HTTP_202_ACCEPTED
    assert first.json()["operation_id"] != second.json()["operation_id"]
    expected_count = 2
    assert await count_operations(sessions) == expected_count


async def test_concurrent_retries(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """Independent transactions competing for a key create one operation."""
    responses = await asyncio.gather(
        *(client.post(URL, json=PAYLOAD, headers=HEADERS) for _ in range(6))
    )
    assert all(r.status_code == status.HTTP_202_ACCEPTED for r in responses)
    assert len({r.json()["operation_id"] for r in responses}) == 1
    assert await count_operations(sessions) == 1


async def test_concurrent_conflict(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """Only one of two competing payloads can own the key."""
    responses = await asyncio.gather(
        client.post(URL, json=PAYLOAD, headers=HEADERS),
        client.post(URL, json=PAYLOAD | {"title": "Other"}, headers=HEADERS),
    )
    assert sorted(r.status_code for r in responses) == [202, 409]
    assert await count_operations(sessions) == 1


async def test_authentication_required(
    client: AsyncClient, api: FastAPI
) -> None:
    """Exercise the existing authentication dependency without an override."""
    api.dependency_overrides.pop(get_current_user)
    response = await client.post(URL, json=PAYLOAD, headers=HEADERS)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


async def test_database_unavailable(client: AsyncClient, api: FastAPI) -> None:
    """Hide database internals and tell callers to retry with the same key."""
    session = AsyncMock(spec=AsyncSession)
    session.begin.side_effect = OperationalError(
        "private-query", {}, RuntimeError("private-database-host")
    )

    async def unavailable() -> AsyncGenerator[AsyncSession, None]:
        yield session

    api.dependency_overrides[get_database_manual] = unavailable
    response = await client.post(URL, json=PAYLOAD, headers=HEADERS)
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.json()["detail"]["code"] == "service_unavailable"
    assert response.headers["Retry-After"] == "5"
    assert "private" not in response.text


async def test_commit_failure_is_not_accepted(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """A failed commit must return 503 and roll back the key reservation."""
    with patch(
        "sqlalchemy.orm.session.SessionTransaction.commit",
        side_effect=OperationalError("COMMIT", {}, RuntimeError("offline")),
    ):
        response = await client.post(URL, json=PAYLOAD, headers=HEADERS)
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert await count_operations(sessions) == 0


async def test_polling_unavailable(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Return the same service error contract when progress checks fail."""
    created = await client.post(URL, json=PAYLOAD, headers=HEADERS)
    operation_id = created.json()["operation_id"]
    monkeypatch.setattr(
        "app.resources.campus_request.advance_operation",
        AsyncMock(side_effect=OSError),
    )
    response = await client.get(
        f"{get_settings().api_root}/operations/{operation_id}"
    )
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.json()["detail"]["code"] == "service_unavailable"
