"""Prepare request expiry together with the Points refund participant."""

from uuid import UUID

import asyncpg

from app.database.db import get_database_url
from app.managers.conflict_resolution import (
    check_conflict_resolution_allowed,
    verify_resolution_admin,
)
from app.transactions.postgres import prepare, protocol_error
from app.transactions.schemas import AdminExpiryPreparation, ExpiryPreparation


async def expire_unanswered_request(
    conn: asyncpg.Connection,
    _transaction_id: UUID,
    payload: ExpiryPreparation,
) -> None:
    """Guard automatic refunds or validate an administrator resolution."""
    parent = await conn.fetchrow(
        "SELECT *,expires_at <= CURRENT_TIMESTAMP AS overdue "
        "FROM requests WHERE id=$1 FOR UPDATE",
        payload.request_id,
    )
    if parent is None:
        raise protocol_error(code="request_not_found", status_code=404)
    if parent["requester_id"] != payload.owner_id:
        raise protocol_error(code="request_owner_required", status_code=403)
    if (
        parent["status"]
        not in {"open", "under_review", "expired", "conflicted"}
        or parent["accepted_response_id"] is not None
        or parent["accepted_at"] is not None
    ):
        raise protocol_error(code="request_not_open")
    if not parent["overdue"]:
        raise protocol_error(code="request_not_expired")
    if isinstance(payload, AdminExpiryPreparation):
        await verify_resolution_admin(conn, payload.admin_id)
        check_conflict_resolution_allowed(
            request_status=parent["status"],
            expires_at=parent["expires_at"],
            accepted_response_id=parent["accepted_response_id"],
        )
    elif await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM responses WHERE request_id=$1 "
        "AND moderation_status='visible')",
        payload.request_id,
    ):
        raise protocol_error(code="request_has_responses")
    await conn.execute(
        "UPDATE requests SET status='expired' WHERE id=$1", payload.request_id
    )


async def prepare_expiration(
    transaction_id: UUID, payload: ExpiryPreparation
) -> None:
    """Vote Yes only after the guarded expiry is durably prepared."""
    await prepare(
        get_database_url(),
        "campus",
        transaction_id,
        payload,
        expire_unanswered_request,
        operation="expire_request",
    )
