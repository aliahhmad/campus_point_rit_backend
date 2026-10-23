"""Authenticate internal Campus preparation and decision lookup."""

from hmac import compare_digest
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException

from app.config.settings import get_settings
from app.database.db import get_database_url
from app.managers.acceptance_participant import prepare_acceptance
from app.managers.expiration_participant import prepare_expiration
from app.managers.request_participant import finish_request, prepare_request
from app.transactions.postgres import connection, protocol_error
from app.transactions.schemas import (
    AcceptancePreparation,
    ExpiryPreparation,
    RequestPreparation,
)


def require_service_token(
    token: Annotated[str | None, Header(alias="X-Service-Token")] = None,
) -> None:
    """Allow only the configured service-to-service credential."""
    expected = get_settings().points_service_token.get_secret_value()
    if not expected:
        raise protocol_error(code="service_unavailable", status_code=503)
    if not token or not compare_digest(token.encode(), expected.encode()):
        raise HTTPException(401, "Invalid service token")


router = APIRouter(
    prefix="/internal/transactions",
    tags=["Internal transactions"],
    dependencies=[Depends(require_service_token)],
)


@router.get("/{transaction_id}/decision")
async def get_decision(transaction_id: UUID) -> dict[str, str | None]:
    """Let a prepared participant obtain the durable decision."""
    async with connection(get_database_url()) as conn:
        row = await conn.fetchrow(
            "SELECT decision,state,operation FROM distributed_transactions "
            "WHERE id=$1",
            transaction_id,
        )
    if row is None:
        raise HTTPException(404, "Operation not found")
    return dict(row)


@router.post("/{transaction_id}/prepare")
async def prepare_campus(
    transaction_id: UUID, payload: RequestPreparation
) -> dict[str, str]:
    """Vote Yes after durable Campus preparation."""
    await prepare_request(transaction_id, payload)
    return {"result": "yes"}


@router.post("/{transaction_id}/prepare-acceptance")
async def prepare_campus_acceptance(
    transaction_id: UUID, payload: AcceptancePreparation
) -> dict[str, str]:
    """Prepare one validated response selection in the Campus database."""
    await prepare_acceptance(transaction_id, payload)
    return {"result": "yes"}


@router.post("/{transaction_id}/prepare-expiry")
async def prepare_campus_expiry(
    transaction_id: UUID, payload: ExpiryPreparation
) -> dict[str, str]:
    """Prepare guarded expiry as Campus's part of an automatic refund."""
    await prepare_expiration(transaction_id, payload)
    return {"result": "yes"}


@router.post("/{transaction_id}/{decision}")
async def finish_campus(
    transaction_id: UUID, decision: Literal["commit", "abort"]
) -> dict[str, str]:
    """Apply a matching durable decision, including repeated deliveries."""
    await finish_request(transaction_id, decision)
    return {"result": "committed" if decision == "commit" else "aborted"}
