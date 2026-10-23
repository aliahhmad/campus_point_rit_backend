"""Validate the public browsing API before any database query runs."""

import pytest
from fastapi import FastAPI, status
from httpx import AsyncClient

from app.config.settings import get_settings
from app.managers.security import get_current_user


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/locations", "/requests", "/requests/1"])
async def test_browsing_requires_authentication(
    api: FastAPI, client: AsyncClient, path: str
) -> None:
    """Anonymous visitors cannot browse authenticated campus content."""
    api.dependency_overrides.pop(get_current_user)
    response = await client.get(get_settings().api_root + path)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        "page=0",
        "size=101",
        "location_id=-1",
        "status=unknown",
        "search=" + "x" * 201,
    ],
)
async def test_invalid_feed_filters(client: AsyncClient, query: str) -> None:
    """Reject invalid filters and excessive page sizes."""
    response = await client.get(get_settings().api_root + "/requests?" + query)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


@pytest.mark.asyncio
@pytest.mark.parametrize("request_id", ["0", "2147483648", "invalid"])
async def test_invalid_request_detail_id(
    client: AsyncClient, request_id: str
) -> None:
    """Bound direct request IDs before querying the database."""
    response = await client.get(
        get_settings().api_root + f"/requests/{request_id}"
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
