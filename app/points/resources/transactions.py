"""Expose authenticated Points preparation and decision delivery."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends

from app.points.managers.campus_request import finish_request, prepare_request
from app.points.security import require_service_token
from app.transactions.schemas import RequestPreparation

router = APIRouter(
    prefix="/internal/transactions",
    tags=["Internal transactions"],
    dependencies=[Depends(require_service_token)],
)


@router.post("/{transaction_id}/prepare")
async def prepare_points(
    transaction_id: UUID, payload: RequestPreparation
) -> dict[str, str]:
    """Prepare the deduction, escrow, and hold ledger entry together."""
    await prepare_request(transaction_id, payload)
    return {"result": "yes"}


@router.post("/{transaction_id}/{decision}")
async def finish_points(
    transaction_id: UUID, decision: Literal["commit", "abort"]
) -> dict[str, str]:
    """Check the coordinator's decision before finishing local work."""
    await finish_request(transaction_id, decision)
    return {"result": "committed" if decision == "commit" else "aborted"}
