"""Return the ID of an accepted request submission."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class CampusRequestResponse(BaseModel):
    """Return a request only once both participants acknowledge commit."""

    id: int
    requester_id: int
    location_id: int
    title: str
    description: str
    reward_points: int
    status: str
    moderation_status: str
    created_at: datetime
    expires_at: datetime


class CampusRequestCreateResponse(BaseModel):
    """Acknowledge durable intake, pending coordinated request creation."""

    operation_id: UUID
    status: Literal["processing", "completed", "aborted"] = "processing"
    reward_points: Literal[5] = 5
    created_at: datetime
    request: CampusRequestResponse | None = None
    error_code: str | None = None
