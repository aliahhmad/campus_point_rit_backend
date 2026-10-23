"""Return an unanswered expired request's held points to its requester."""

from uuid import UUID

import asyncpg

from app.points.database import get_database_url
from app.transactions.postgres import prepare, protocol_error
from app.transactions.schemas import ExpiryPreparation


async def refund_request_points(
    conn: asyncpg.Connection,
    transaction_id: UUID,
    payload: ExpiryPreparation,
) -> None:
    """Credit the owner, settle the held escrow, and record one refund."""
    escrow = await conn.fetchrow(
        "SELECT * FROM escrows WHERE request_id=$1 FOR UPDATE",
        payload.request_id,
    )
    if escrow is None:
        raise protocol_error(code="escrow_not_found")
    if escrow["requester_id"] != payload.owner_id:
        raise protocol_error(code="escrow_mismatch")
    if escrow["status"] != "held":
        raise protocol_error(code="escrow_already_settled")
    wallet = await conn.fetchval(
        "SELECT user_id FROM wallets WHERE user_id=$1 FOR UPDATE",
        payload.owner_id,
    )
    if wallet is None:
        raise protocol_error(code="requester_wallet_missing", status_code=503)
    await conn.execute(
        "UPDATE wallets SET available_points=available_points+$2 "
        "WHERE user_id=$1",
        payload.owner_id,
        escrow["amount"],
    )
    await conn.execute(
        "UPDATE escrows SET status='refunded',settled_at=now() WHERE id=$1",
        escrow["id"],
    )
    await conn.execute(
        "INSERT INTO points_transactions "
        "(operation_id,distributed_transaction_id,"
        "escrow_id,user_id,type,amount) VALUES ($1,$1,$2,$3,'refund',$4)",
        transaction_id,
        escrow["id"],
        payload.owner_id,
        escrow["amount"],
    )


async def prepare_refund(
    transaction_id: UUID, payload: ExpiryPreparation
) -> None:
    """Prepare all refund writes before acknowledging the Points Yes vote."""
    await prepare(
        get_database_url(),
        "points",
        transaction_id,
        payload,
        refund_request_points,
        operation="expire_request",
    )
