"""Validate answers submitted by authenticated contributors."""

from pydantic import BaseModel, ConfigDict, Field


class CampusResponseCreate(BaseModel):
    """Accept answer text; the server supplies contributor and moderation."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    answer: str = Field(min_length=1, max_length=5000)
