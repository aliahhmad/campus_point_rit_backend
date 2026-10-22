"""Describe selectable campus locations."""

from pydantic import BaseModel, ConfigDict


class LocationResponse(BaseModel):
    """Return the ID and label of an active location."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    building_code: str
