"""Authorize, store, and browse answers to campus requests."""

from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.models.campus_request import CampusRequest
from app.models.campus_response import CampusResponse
from app.models.distributed_transaction import DistributedTransaction
from app.models.enums import (
    ModerationStatus,
    RequestStatus,
    TransactionDecision,
    TransactionState,
)
from app.schemas.request.campus_response import CampusResponseCreate
from app.schemas.response.campus_response import (
    CampusResponseList,
    CampusResponseRead,
)
from app.transactions.postgres import protocol_error


def check_response_allowed(
    requester_id: int,
    contributor_id: int,
    request_status: str,
    expires_at: datetime,
) -> None:
    """Reject self-responses and requests that no longer accept answers."""
    if requester_id == contributor_id:
        raise protocol_error(code="self_response_forbidden", status_code=403)
    if request_status != RequestStatus.open.value:
        raise protocol_error(code="request_not_open")
    if expires_at <= datetime.now(timezone.utc):
        raise protocol_error(code="request_expired")


async def accessible_request(
    session: AsyncSession, request_id: int, user_id: int
) -> CampusRequest:
    """Require a confirmed parent that the current user is allowed to see."""
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
            or_(
                CampusRequest.moderation_status == ModerationStatus.visible,
                CampusRequest.requester_id == user_id,
            ),
        )
    )
    if parent is None:
        raise protocol_error(code="request_not_found", status_code=404)
    return parent


async def create_response_transaction(
    request_id: int,
    submission: CampusResponseCreate,
    idempotency_key: str,
    contributor_id: int,
    session: AsyncSession,
) -> DistributedTransaction:
    """Durably accept one operation per key; replay before revalidating."""
    details = {"request_id": request_id, **submission.model_dump()}
    operation = await session.scalar(
        insert(DistributedTransaction)
        .values(
            owner_id=contributor_id,
            idempotency_key=idempotency_key,
            operation="create_response",
            payload=details,
        )
        .on_conflict_do_nothing(
            index_elements=[DistributedTransaction.idempotency_key]
        )
        .returning(DistributedTransaction)
    )
    if operation is None:
        operation = await session.scalar(
            select(DistributedTransaction).where(
                DistributedTransaction.idempotency_key == idempotency_key
            )
        )
        if (
            operation is None
            or operation.owner_id != contributor_id
            or operation.operation != "create_response"
            or operation.payload != details
        ):
            raise protocol_error(code="idempotency_conflict")
        return operation

    parent = await accessible_request(session, request_id, contributor_id)
    check_response_allowed(
        parent.requester_id,
        contributor_id,
        parent.status.value,
        parent.expires_at,
    )
    existing = await session.scalar(
        select(CampusResponse.id).where(
            CampusResponse.request_id == request_id,
            CampusResponse.contributor_id == contributor_id,
        )
    )
    if existing is not None:
        raise protocol_error(code="duplicate_response")
    return operation


def visible_responses(user_id: int) -> Select[tuple[CampusResponse]]:
    """Show confirmed answers, with unpublished answers contributor-only."""
    return (
        select(CampusResponse)
        .join(
            DistributedTransaction,
            DistributedTransaction.response_id == CampusResponse.id,
        )
        .where(
            DistributedTransaction.operation == "create_response",
            DistributedTransaction.state == TransactionState.finished,
            DistributedTransaction.decision == TransactionDecision.commit,
            or_(
                CampusResponse.moderation_status == ModerationStatus.visible,
                CampusResponse.contributor_id == user_id,
            ),
        )
    )


async def list_responses(  # noqa: PLR0913
    session: AsyncSession,
    request_id: int,
    user_id: int,
    *,
    page: int,
    size: int,
    mine: bool = False,
) -> CampusResponseList:
    """List answers to an accessible request, oldest first."""
    await accessible_request(session, request_id, user_id)
    query = visible_responses(user_id).where(
        CampusResponse.request_id == request_id
    )
    if mine:
        query = query.where(CampusResponse.contributor_id == user_id)
    rows = (
        await session.scalars(
            query.order_by(CampusResponse.created_at, CampusResponse.id)
            .offset((page - 1) * size)
            .limit(size + 1)
        )
    ).all()
    return CampusResponseList(
        items=[CampusResponseRead.model_validate(row) for row in rows[:size]],
        page=page,
        size=size,
        has_more=len(rows) > size,
    )


async def get_response(
    session: AsyncSession, response_id: int, user_id: int
) -> CampusResponseRead:
    """Apply the same parent and answer visibility checks to direct lookup."""
    row = await session.scalar(
        visible_responses(user_id).where(CampusResponse.id == response_id)
    )
    if row is None:
        raise protocol_error(code="response_not_found", status_code=404)
    await accessible_request(session, row.request_id, user_id)
    return CampusResponseRead.model_validate(row)
