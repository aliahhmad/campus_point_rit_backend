"""Describe authenticated messages between the coordinator and participants."""

from pydantic import Field

from app.schemas.request.campus_request import CampusRequestCreate


class RequestPreparation(CampusRequestCreate):
    """Carry validated content plus coordinator-assigned identifiers."""

    owner_id: int = Field(gt=0, le=2_147_483_647, strict=True)
    request_id: int = Field(gt=0, le=2_147_483_647, strict=True)
