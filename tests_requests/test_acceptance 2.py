"""Validate the acceptance endpoint before any settlement work starts."""

import pytest
from fastapi import FastAPI, status
from httpx import AsyncClient

from app.config.settings import get_settings
from app.managers.security import get_current_user

ROOT = get_settings().api_root
URL = ROOT + "/requests/1/responses/2/accept"
pytestmark = pytest.mark.asyncio


async def test_acceptance_requires_authentication(
    api: FastAPI, client: AsyncClient
) -> None:
    """Anonymous callers cannot select a winner or release an escrow."""
    api.dependency_overrides.pop(get_current_user)
    result = await client.post(URL, headers={"Idempotency-Key": "accept-1"})
    assert result.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.parametrize("key", [None, "", "bad key", "bad/key", "x" * 129])
async def test_invalid_acceptance_key(
    client: AsyncClient, key: str | None
) -> None:
    """Require the same bounded keys used by the other 2PC operations."""
    headers = {} if key is None else {"Idempotency-Key": key}
    result = await client.post(URL, headers=headers)
    assert result.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


@pytest.mark.parametrize(
    "path",
    [
        "/requests/0/responses/2/accept",
        "/requests/1/responses/0/accept",
        "/requests/2147483648/responses/2/accept",
        "/requests/1/responses/2147483648/accept",
    ],
)
async def test_invalid_acceptance_ids(client: AsyncClient, path: str) -> None:
    """Reject invalid IDs before looking up requests or contacting Points."""
    result = await client.post(
        ROOT + path, headers={"Idempotency-Key": "accept-1"}
    )
    assert result.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
