"""Describe the results returned by the shared operation polling API."""

from app.schemas.response.acceptance import ResponseAcceptanceResult
from app.schemas.response.campus_request import CampusRequestCreateResponse
from app.schemas.response.campus_response import CampusResponseCreateResult

OperationResult = (
    CampusRequestCreateResponse
    | CampusResponseCreateResult
    | ResponseAcceptanceResult
)
