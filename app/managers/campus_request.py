"""Validate and store request submissions."""

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campus_request import CampusRequest
from app.models.distributed_transaction import DistributedTransaction
from app.models.enums import (
    ModerationStatus,
    RequestStatus,
    TransactionDecision,
    TransactionState,
)
from app.models.location import Location
from app.schemas.request.campus_request import CampusRequestCreate
from app.schemas.response.campus_request import (
    CampusRequestListItem,
    CampusRequestListResponse,
    CampusRequestResponse,
)


async def list_requests(  # noqa: PLR0913
    session: AsyncSession,
    owner_id: int,
    *,
    page: int,
    size: int,
    search: str,
    location_id: int | None,
    request_status: RequestStatus | None,
    mine: bool,
) -> CampusRequestListResponse:
    """List confirmed creations; unpublished content is owner-only."""
    query = (
        select(CampusRequest, Location.name, Location.building_code)
        .join(Location, CampusRequest.location_id == Location.id)
        .join(
            DistributedTransaction,
            DistributedTransaction.request_id == CampusRequest.id,
        )
        .where(
            DistributedTransaction.operation == "create_request",
            DistributedTransaction.state == TransactionState.finished,
            DistributedTransaction.decision == TransactionDecision.commit,
            or_(
                CampusRequest.moderation_status == ModerationStatus.visible,
                CampusRequest.requester_id == owner_id,
            ),
        )
    )
    if mine:
        query = query.where(CampusRequest.requester_id == owner_id)
    if location_id is not None:
        query = query.where(CampusRequest.location_id == location_id)
    if request_status is not None:
        query = query.where(CampusRequest.status == request_status)
    if search.strip():
        query = query.where(
            CampusRequest.title.icontains(search.strip(), autoescape=True)
        )
    rows = (
        await session.execute(
            query.order_by(
                CampusRequest.created_at.desc(), CampusRequest.id.desc()
            )
            .offset((page - 1) * size)
            .limit(size + 1)
        )
    ).all()
    items = [
        CampusRequestListItem(
            **CampusRequestResponse.model_validate(request).model_dump(),
            location_name=name,
            building_code=code,
        )
        for request, name, code in rows[:size]
    ]
    return CampusRequestListResponse(
        items=items, page=page, size=size, has_more=len(rows) > size
    )


async def create_request_transaction(
    submission: CampusRequestCreate,
    idempotency_key: str,
    owner_id: int,
    session: AsyncSession,
) -> DistributedTransaction:
    """Store one operation per key; the caller commits the transaction."""
    details = submission.model_dump()
    # The unique key makes simultaneous retries safe.
    operation: DistributedTransaction | None = await session.scalar(
        insert(DistributedTransaction)
        .values(
            owner_id=owner_id,
            idempotency_key=idempotency_key,
            operation="create_request",
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
            or operation.owner_id != owner_id
            or operation.operation != "create_request"
            or operation.payload != details
        ):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "code": "idempotency_conflict",
                    "message": "This key belongs to another submission.",
                },
            )
        return operation

    # Check locations only for new submissions; retries keep their old result.
    location = await session.scalar(
        select(Location.id).where(
            Location.id == submission.location_id,
            Location.is_active.is_(True),
        )
    )
    if location is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "invalid_location",
                "message": "Select an existing, active campus location.",
            },
        )
    return operation
