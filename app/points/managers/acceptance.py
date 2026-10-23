"""Release a request's held reward to its selected contributor."""

from uuid import UUID

import asyncpg

from app.points.database import get_database_url
from app.transactions.postgres import prepare, protocol_error
from app.transactions.schemas import AcceptancePreparation


async def award_response_points(
    conn: asyncpg.Connection,
    transaction_id: UUID,
    payload: AcceptancePreparation,
) -> None:
    """Settle escrow, credit points and reputation, and record the reward."""
    escrow = await conn.fetchrow(
        "SELECT * FROM escrows WHERE request_id=$1 FOR UPDATE",
        payload.request_id,
    )
    if escrow is None:
        raise protocol_error(code="escrow_not_found")
    if (
        escrow["requester_id"] != payload.owner_id
        or payload.contributor_id == payload.owner_id
    ):
        raise protocol_error(code="escrow_mismatch")
    if escrow["status"] != "held":
        raise protocol_error(code="escrow_already_settled")
    wallet = await conn.fetchval(
        "SELECT user_id FROM wallets WHERE user_id=$1 FOR UPDATE",
        payload.contributor_id,
    )
    if wallet is None:
        raise protocol_error(code="recipient_wallet_missing", status_code=503)
    await conn.execute(
        "UPDATE wallets SET available_points=available_points+$2,"
        "reputation=reputation+1 "
        "WHERE user_id=$1",
        payload.contributor_id,
        escrow["amount"],
    )
    await conn.execute(
        "UPDATE escrows SET status='released',recipient_id=$2,"
        "awarded_response_id=$3,settled_at=now() WHERE id=$1",
        escrow["id"],
        payload.contributor_id,
        payload.response_id,
    )
    await conn.execute(
        "INSERT INTO points_transactions "
        "(operation_id,distributed_transaction_id,"
        "escrow_id,user_id,type,amount) "
        "VALUES ($1,$1,$2,$3,'reward',$4)",
        transaction_id,
        escrow["id"],
        payload.contributor_id,
        escrow["amount"],
    )


async def prepare_acceptance(
    transaction_id: UUID, payload: AcceptancePreparation
) -> None:
    """Vote Yes only after the reward and escrow settlement are prepared."""
    await prepare(
        get_database_url(),
        "points",
        transaction_id,
        payload,
        award_response_points,
        operation="accept_response",
    )
