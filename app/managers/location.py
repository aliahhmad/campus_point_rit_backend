"""Read the predefined locations available for new requests."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.location import Location
from app.schemas.response.location import LocationResponse


async def list_locations(session: AsyncSession) -> list[LocationResponse]:
    """Return active locations in a stable alphabetical order."""
    locations = await session.scalars(
        select(Location)
        .where(Location.is_active.is_(True))
        .order_by(Location.name)
    )
    return [LocationResponse.model_validate(location) for location in locations]
