"""Describe response creation, browsing, and recovery results."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.enums import ModerationStatus


class CampusResponseRead(BaseModel):
    """Expose a response after its creation operation has finished."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    request_id: int
    contributor_id: int
    answer: str
    moderation_status: ModerationStatus
    created_at: datetime


class CampusResponseCreateResult(BaseModel):
    """Report a Campus-only 2PC operation without any points fields."""

    operation_id: UUID
    status: Literal["processing", "completed", "aborted"] = "processing"
    created_at: datetime
    response: CampusResponseRead | None = None
    error_code: str | None = None


class CampusResponseList(BaseModel):
    """Return one page of answers visible to the authenticated user."""

    items: list[CampusResponseRead]
    page: int
    size: int
    has_more: bool
