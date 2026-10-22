"""Validate public campus request submissions."""

from pydantic import BaseModel, ConfigDict, Field


class CampusRequestCreate(BaseModel):
    """Accept only client-owned content; Campus fixes the reward at five."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    location_id: int = Field(gt=0, le=2_147_483_647, strict=True)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=5000)
