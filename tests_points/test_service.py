"""Basic checks for the Points API health endpoints."""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.points.config import get_settings
from app.points.database import get_database
from app.points.main import app


def test_heartbeat() -> None:
    """Check that the Points API responds."""
    with TestClient(app) as client:
        response = client.get("/heartbeat")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"status": "ok", "service": "points"}


def test_ready() -> None:
    """Check readiness using a mocked database session."""
    session = AsyncMock(spec=AsyncSession)

    async def mock_database() -> AsyncGenerator[AsyncMock, None]:
        yield session

    app.dependency_overrides[get_database] = mock_database
    try:
        with TestClient(app) as client:
            response = client.get("/ready")
    finally:
        app.dependency_overrides.pop(get_database)

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"status": "ok", "database": "points"}
    session.execute.assert_awaited_once()


@pytest.mark.parametrize("token", [None, "incorrect"])
def test_wallet_initialization_requires_service_auth(
    monkeypatch: pytest.MonkeyPatch,
    token: str | None,
) -> None:
    """Reject unauthenticated callers before they can issue any points."""
    monkeypatch.setattr(
        get_settings(),
        "service_token",
        SecretStr("test-service-token"),
    )
    headers = {"X-Service-Token": token} if token else {}
    with TestClient(app) as client:
        response = client.put("/internal/wallets/1/initialize", headers=headers)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
