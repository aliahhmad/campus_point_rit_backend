"""Liveness and database readiness probes for the Points Service."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.points.database import get_database

router = APIRouter(tags=["Health"])


@router.get("/heartbeat")
async def heartbeat() -> dict[str, str]:
    """Report that the Points API process is alive."""
    return {"status": "ok", "service": "points"}


@router.get("/ready")
async def ready(
    session: Annotated[AsyncSession, Depends(get_database)],
) -> dict[str, str]:
    """Report readiness only if the Points database can be queried."""
    try:
        await session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Points database is unavailable",
        ) from exc
    return {"status": "ok", "database": "points"}
