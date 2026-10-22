"""Validate the public response API before database work starts."""

import pytest
from fastapi import FastAPI, status
from httpx import AsyncClient

from app.config.settings import get_settings
from app.managers.security import get_current_user

ROOT = get_settings().api_root
URL = ROOT + "/requests/1/responses"
HEADERS = {"Idempotency-Key": "response-validation"}
pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"answer": " \t\n "},
        {"answer": "x" * 5001},
        {"answer": 123},
        {"answer": "Seats are free", "contributor_id": 2},
        {"answer": "Seats are free", "request_id": 2},
        {"answer": "Seats are free", "moderation_status": "visible"},
    ],
)
async def test_invalid_response_body(
    client: AsyncClient, body: dict[str, str | int]
) -> None:
    """Reject blank, oversized, and client-supplied server fields."""
    result = await client.post(URL, json=body, headers=HEADERS)
    assert result.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


@pytest.mark.parametrize("key", [None, "", "bad key", "bad/key", "x" * 129])
async def test_invalid_response_key(
    client: AsyncClient, key: str | None
) -> None:
    """Use the same bounded idempotency keys as request creation."""
    headers = {} if key is None else {"Idempotency-Key": key}
    result = await client.post(URL, json={"answer": "Seats?"}, headers=headers)
    assert result.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


@pytest.mark.parametrize(
    "path",
    [
        "/requests/0/responses",
        "/requests/2147483648/responses",
        "/requests/1/responses?page=0",
        "/requests/1/responses?size=101",
        "/responses/0",
        "/responses/2147483648",
    ],
)
async def test_invalid_response_filters(client: AsyncClient, path: str) -> None:
    """Validate path IDs and bound pagination before any database query."""
    result = await client.get(ROOT + path)
    assert result.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/requests/1/responses"),
        ("GET", "/requests/1/responses"),
        ("GET", "/responses/1"),
    ],
)
async def test_responses_require_authentication(
    api: FastAPI, client: AsyncClient, method: str, path: str
) -> None:
    """Never allow anonymous response creation or browsing."""
    api.dependency_overrides.pop(get_current_user)
    result = await client.request(
        method, ROOT + path, json={"answer": "Seats?"}, headers=HEADERS
    )
    assert result.status_code == status.HTTP_401_UNAUTHORIZED
