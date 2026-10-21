"""Basic checks for the Points API health endpoints."""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock

from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

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
