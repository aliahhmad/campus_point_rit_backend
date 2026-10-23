"""Check read-only wallet access and authentication on the Points API."""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, status
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.points.config import get_settings
from app.points.database import get_database
from app.points.models.wallet import Wallet
from app.points.resources.wallet import router


@pytest.mark.parametrize("exists", [True, False])
def test_read_existing_wallet(
    monkeypatch: pytest.MonkeyPatch, *, exists: bool
) -> None:
    """A GET reads a balance and never initializes or grants points."""
    monkeypatch.setattr(
        get_settings(), "service_token", SecretStr("wallet-test-token")
    )
    session = AsyncMock(spec=AsyncSession)
    session.get.return_value = (
        Wallet(user_id=7, available_points=95, reputation=12)
        if exists
        else None
    )

    async def database() -> AsyncGenerator[AsyncMock, None]:
        yield session

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_database] = database
    with TestClient(app) as client:
        response = client.get(
            "/internal/wallets/7",
            headers={"X-Service-Token": "wallet-test-token"},
        )
    session.get.assert_awaited_once_with(Wallet, 7)
    session.add.assert_not_called()
    session.execute.assert_not_awaited()
    if exists:
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "user_id": 7,
            "available_points": 95,
            "reputation": 12,
        }
    else:
        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.parametrize("token", [None, "incorrect"])
def test_wallet_read_requires_service_auth(
    monkeypatch: pytest.MonkeyPatch, token: str | None
) -> None:
    """The browser cannot read a wallet directly from the Points service."""
    monkeypatch.setattr(
        get_settings(), "service_token", SecretStr("wallet-test-token")
    )
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.get(
            "/internal/wallets/7",
            headers={"X-Service-Token": token} if token else {},
        )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
