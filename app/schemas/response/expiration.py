"""Report automatic expiry separately from confirmed refund completion."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.schemas.response.campus_request import CampusRequestResponse


class RequestExpiryResult(BaseModel):
    """Expose the refund only when Campus and Points have acknowledged."""

    operation: Literal["expire_request"] = "expire_request"
    operation_id: UUID
    status: Literal["processing", "completed", "aborted"] = "processing"
    created_at: datetime
    refund_points: Literal[5] = 5
    request: CampusRequestResponse | None = None
    error_code: str | None = None
