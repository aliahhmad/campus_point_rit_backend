"""Lock and complete the request as Campus's part of reward settlement."""

from uuid import UUID

import asyncpg

from app.database.db import get_database_url
from app.managers.acceptance import check_acceptance_allowed
from app.transactions.postgres import prepare, protocol_error
from app.transactions.schemas import AcceptancePreparation


async def accept_response(
    conn: asyncpg.Connection,
    _transaction_id: UUID,
    payload: AcceptancePreparation,
) -> None:
    """Revalidate under locks so competing selections choose one winner."""
    parent = await conn.fetchrow(
        "SELECT r.* FROM requests r WHERE r.id=$1 AND EXISTS ("
        "SELECT 1 FROM distributed_transactions d WHERE d.request_id=r.id "
        "AND d.operation='create_request' AND d.state='finished' "
        "AND d.decision='commit') FOR UPDATE OF r",
        payload.request_id,
    )
    if parent is None:
        raise protocol_error(code="request_not_found", status_code=404)
    check_acceptance_allowed(
        requester_id=parent["requester_id"],
        owner_id=payload.owner_id,
        request_status=parent["status"],
        moderation_status=parent["moderation_status"],
        expires_at=parent["expires_at"],
        accepted_response_id=parent["accepted_response_id"],
    )
    selected = await conn.fetchrow(
        "SELECT r.* FROM responses r WHERE r.id=$1 AND r.request_id=$2 "
        "AND r.moderation_status='visible' AND EXISTS ("
        "SELECT 1 FROM distributed_transactions d WHERE d.response_id=r.id "
        "AND d.operation='create_response' AND d.state='finished' "
        "AND d.decision='commit') FOR SHARE OF r",
        payload.response_id,
        payload.request_id,
    )
    if selected is None:
        raise protocol_error(code="response_not_found", status_code=404)
    if selected["contributor_id"] == payload.owner_id:
        raise protocol_error(code="self_response_forbidden", status_code=403)
    if selected["contributor_id"] != payload.contributor_id:
        raise protocol_error(code="idempotency_conflict")
    await conn.execute(
        "UPDATE requests SET status='completed',accepted_response_id=$2,"
        "accepted_at=now() WHERE id=$1",
        payload.request_id,
        payload.response_id,
    )


async def prepare_acceptance(
    transaction_id: UUID, payload: AcceptancePreparation
) -> None:
    """Vote Yes after request completion and its journal are prepared."""
    await prepare(
        get_database_url(),
        "campus",
        transaction_id,
        payload,
        accept_response,
        operation="accept_response",
    )
