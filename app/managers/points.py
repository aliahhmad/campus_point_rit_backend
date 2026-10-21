"""Call the Points Service when creating a Campus account."""

import httpx
from fastapi import HTTPException, status

from app.config.settings import get_settings


async def initialize_wallet(user_id: int) -> None:
    """Wait for Points to create the wallet and its one-time opening grant."""
    settings = get_settings()
    token = settings.points_service_token.get_secret_value()
    if not token:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Wallet service authentication is not configured",
        )
    try:
        async with httpx.AsyncClient(
            base_url=settings.points_api_url.rstrip("/"),
            timeout=5,
        ) as client:
            response = await client.put(
                f"/internal/wallets/{user_id}/initialize",
                headers={"X-Service-Token": token},
            )
            response.raise_for_status()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Could not initialize your wallet. Please try registering again.",
        ) from exc
