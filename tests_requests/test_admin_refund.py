"""Reject unauthorized and invalid refund actions before settlement starts."""

import pytest
from fastapi import FastAPI, status
from httpx import AsyncClient

from app.config.settings import get_settings
from app.managers.security import get_current_user
from app.models.enums import RoleType
from app.models.user import User

ROOT = get_settings().api_root
URL = ROOT + "/requests/1/refund"
pytestmark = pytest.mark.asyncio


async def test_refund_requires_authentication(
    api: FastAPI, client: AsyncClient
) -> None:
    """Anonymous callers cannot initiate a refund."""
    api.dependency_overrides.pop(get_current_user)
    result = await client.post(URL, headers={"Idempotency-Key": "refund-1"})
    assert result.status_code == status.HTTP_401_UNAUTHORIZED


async def test_refund_requires_admin(client: AsyncClient) -> None:
    """Ordinary authenticated users cannot initiate a refund."""
    result = await client.post(URL, headers={"Idempotency-Key": "refund-1"})
    assert result.status_code == status.HTTP_403_FORBIDDEN
    assert result.json()["detail"]["code"] == "admin_required"


@pytest.mark.parametrize("key", [None, "", "bad key", "bad/key", "x" * 129])
async def test_refund_requires_valid_key(
    api: FastAPI, client: AsyncClient, key: str | None
) -> None:
    """Administrators must use a bounded idempotency key for retries."""

    async def admin() -> User:
        return User(id=1, role=RoleType.admin)

    api.dependency_overrides[get_current_user] = admin
    headers = {} if key is None else {"Idempotency-Key": key}
    result = await client.post(URL, headers=headers)
    assert result.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
