"""Verify that profiles read only their authenticated user's Points wallet."""

import httpx
import pytest
from fastapi import FastAPI, status
from httpx import AsyncClient
from pydantic import SecretStr

from app.config.settings import get_settings
from app.managers.security import get_current_user


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    ["balance", "zero", "wrong_owner", "invalid_balance", "outage", "timeout"],
)
async def test_wallet_proxy(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    """Validate balances and keep service credentials server-side."""
    monkeypatch.setattr(
        get_settings(), "points_service_token", SecretStr("wallet-test-token")
    )
    payload = {
        "user_id": 2 if case == "wrong_owner" else 1,
        "available_points": 0
        if case == "zero"
        else (-1 if case == "invalid_balance" else 95),
    }

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/internal/wallets/1"
        assert request.headers["X-Service-Token"] == "wallet-test-token"
        if case == "timeout":
            raise httpx.ReadTimeout(
                message="Test service timeout", request=request
            )
        return httpx.Response(503 if case == "outage" else 200, json=payload)

    def points_client(**kwargs) -> AsyncClient:  # noqa: ANN003
        return AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr("app.managers.points.httpx.AsyncClient", points_client)
    # Client-supplied IDs cannot select another user's wallet.
    response = await client.get(
        f"{get_settings().api_root}/wallet/me?user_id=2"
    )
    if case in {"balance", "zero"}:
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == payload
    else:
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.json() == {
            "detail": (
                "Your points are temporarily unavailable. Please try again."
            )
        }


@pytest.mark.asyncio
async def test_wallet_requires_authentication(
    client: AsyncClient, api: FastAPI
) -> None:
    """Do not let anonymous clients read a profile balance."""
    api.dependency_overrides.pop(get_current_user)
    response = await client.get(f"{get_settings().api_root}/wallet/me")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
