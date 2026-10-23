"""Expose the location dropdown to authenticated Campus users."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.db import get_database_manual
from app.managers.location import list_locations
from app.managers.security import get_current_user
from app.schemas.response.location import LocationResponse

router = APIRouter(tags=["Locations"], dependencies=[Depends(get_current_user)])


@router.get("/locations")
async def get_locations(
    session: Annotated[AsyncSession, Depends(get_database_manual)],
) -> list[LocationResponse]:
    """List active locations that can be selected when creating a request."""
    return await list_locations(session)
