"""Expose acceptance only after Campus and Points acknowledge completion."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.schemas.response.campus_request import CampusRequestResponse
from app.schemas.response.campus_response import CampusResponseRead


class ResponseAcceptanceResult(BaseModel):
    """Report progress separately from the committed request and reward."""

    operation: Literal["accept_response"] = "accept_response"
    operation_id: UUID
    status: Literal["processing", "completed", "aborted"] = "processing"
    created_at: datetime
    reward_points: Literal[5] = 5
    request: CampusRequestResponse | None = None
    accepted_response: CampusResponseRead | None = None
    recipient_id: int | None = None
    error_code: str | None = None
