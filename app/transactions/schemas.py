"""Describe authenticated messages between the coordinator and participants."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.request.campus_request import CampusRequestCreate
from app.schemas.request.campus_response import CampusResponseCreate


class RequestPreparation(CampusRequestCreate):
    """Carry validated content plus coordinator-assigned identifiers."""

    owner_id: int = Field(gt=0, le=2_147_483_647, strict=True)
    request_id: int = Field(gt=0, le=2_147_483_647, strict=True)


class ResponsePreparation(CampusResponseCreate):
    """Carry the parent request and server-assigned contributor and response."""

    owner_id: int = Field(gt=0, le=2_147_483_647, strict=True)
    request_id: int = Field(gt=0, le=2_147_483_647, strict=True)
    response_id: int = Field(gt=0, le=2_147_483_647, strict=True)


class AcceptancePreparation(BaseModel):
    """Carry server-verified identities for releasing an existing escrow."""

    model_config = ConfigDict(extra="forbid")

    operation: Literal["accept_response"] = "accept_response"
    owner_id: int = Field(gt=0, le=2_147_483_647, strict=True)
    request_id: int = Field(gt=0, le=2_147_483_647, strict=True)
    response_id: int = Field(gt=0, le=2_147_483_647, strict=True)
    contributor_id: int = Field(gt=0, le=2_147_483_647, strict=True)
