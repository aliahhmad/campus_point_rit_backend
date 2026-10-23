"""Validate administrative resolutions and persist escrow refund intents."""

from datetime import datetime, timezone

import asyncpg
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campus_request import CampusRequest
from app.models.distributed_transaction import DistributedTransaction
from app.models.enums import TransactionDecision, TransactionState
from app.transactions.postgres import protocol_error


def check_conflict_resolution_allowed(
    *,
    request_status: str,
    expires_at: datetime,
    accepted_response_id: int | None,
) -> None:
    """Require an overdue conflict with its escrow still unsettled."""
    if accepted_response_id is not None:
        raise protocol_error(code="request_already_accepted")
    if request_status != "conflicted":
        raise protocol_error(code="request_not_conflicted")
    if expires_at > datetime.now(timezone.utc):
        raise protocol_error(code="request_not_expired")


async def verify_resolution_admin(
    conn: asyncpg.Connection, admin_id: int
) -> None:
    """Recheck and lock the administrator's permission during preparation."""
    allowed = await conn.fetchrow(
        "SELECT role,banned,verified FROM users WHERE id=$1 FOR SHARE",
        admin_id,
    )
    if (
        allowed is None
        or allowed["role"] != "admin"
        or allowed["banned"]
        or not allowed["verified"]
    ):
        raise protocol_error(code="admin_required", status_code=403)


async def resolution_request(
    session: AsyncSession, request_id: int
) -> CampusRequest:
    """Load a confirmed request for an administrator, including hidden ones."""
    parent = await session.scalar(
        select(CampusRequest)
        .join(
            DistributedTransaction,
            DistributedTransaction.request_id == CampusRequest.id,
        )
        .where(
            CampusRequest.id == request_id,
            DistributedTransaction.operation == "create_request",
            DistributedTransaction.state == TransactionState.finished,
            DistributedTransaction.decision == TransactionDecision.commit,
        )
    )
    if parent is None:
        raise protocol_error(code="request_not_found", status_code=404)
    return parent


async def create_admin_refund_transaction(
    request_id: int,
    idempotency_key: str,
    admin_id: int,
    session: AsyncSession,
) -> DistributedTransaction:
    """Reuse expiry settlement while auditing the initiating administrator."""
    operation = await session.scalar(
        insert(DistributedTransaction)
        .values(
            owner_id=admin_id,
            idempotency_key=idempotency_key,
            operation="expire_request",
            payload={"request_id": request_id, "admin_id": admin_id},
            request_id=request_id,
        )
        .on_conflict_do_nothing()
        .returning(DistributedTransaction)
    )
    if operation is None:
        operation = await session.scalar(
            select(DistributedTransaction).where(
                DistributedTransaction.idempotency_key == idempotency_key
            )
        )
        if operation is None:
            raise protocol_error(code="resolution_in_progress")
        if (
            operation.owner_id != admin_id
            or operation.operation != "expire_request"
            or operation.request_id != request_id
            or operation.payload.get("admin_id") != admin_id
        ):
            raise protocol_error(code="idempotency_conflict")
        return operation

    parent = await resolution_request(session, request_id)
    check_conflict_resolution_allowed(
        request_status=parent.status.value,
        expires_at=parent.expires_at,
        accepted_response_id=parent.accepted_response_id,
    )
    operation.payload = {
        "request_id": request_id,
        "requester_id": parent.requester_id,
        "admin_id": admin_id,
    }
    return operation
