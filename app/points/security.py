"""Authenticate internal requests from the Campus Service."""

from hmac import compare_digest
from typing import Annotated

from fastapi import Header, HTTPException, status

from app.points.config import get_settings


def require_service_token(
    token: Annotated[str | None, Header(alias="X-Service-Token")] = None,
) -> None:
    """Reject internal calls unless a configured service token matches."""
    expected = get_settings().service_token.get_secret_value()
    if not expected:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Points service authentication is not configured",
        )
    if not token or not compare_digest(token.encode(), expected.encode()):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid service token"
        )
