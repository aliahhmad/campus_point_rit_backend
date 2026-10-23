"""Authorize response selection and durably accept an idempotent operation."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.managers.campus_response import accessible_request, visible_responses
from app.managers.conflict_resolution import (
    check_conflict_resolution_allowed,
    resolution_request,
)
from app.models.campus_response import CampusResponse
from app.models.distributed_transaction import DistributedTransaction
from app.models.enums import ModerationStatus, RequestStatus
from app.transactions.postgres import protocol_error


def check_acceptance_allowed(  # noqa: PLR0913
    *,
    requester_id: int,
    owner_id: int,
    request_status: str,
    moderation_status: str,
    expires_at: datetime,
    accepted_response_id: int | None,
) -> None:
    """Allow only the owner to settle a visible, live, unaccepted request."""
    if requester_id != owner_id:
        raise protocol_error(code="request_owner_required", status_code=403)
    if accepted_response_id is not None:
        raise protocol_error(code="request_already_accepted")
    if moderation_status != ModerationStatus.visible.value:
        raise protocol_error(code="request_not_visible")
    if request_status not in {
        RequestStatus.open.value,
        RequestStatus.under_review.value,
    }:
        raise protocol_error(code="request_not_open")
    if expires_at <= datetime.now(timezone.utc):
        raise protocol_error(code="request_expired")


async def create_acceptance_transaction(  # noqa: PLR0913
    request_id: int,
    response_id: int,
    idempotency_key: str,
    owner_id: int,
    session: AsyncSession,
    *,
    is_admin: bool = False,
) -> DistributedTransaction:
    """Persist an owner selection or administrator resolution for retries."""
    details = {"request_id": request_id, "response_id": response_id}
    operation = await session.scalar(
        insert(DistributedTransaction)
        .values(
            owner_id=owner_id,
            idempotency_key=idempotency_key,
            operation="accept_response",
            payload=details,
            request_id=request_id,
            response_id=response_id,
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
            or operation.operation != "accept_response"
            or operation.payload.get("request_id") != request_id
            or operation.payload.get("response_id") != response_id
        ):
            raise protocol_error(code="idempotency_conflict")
        return operation

    parent = (
        await resolution_request(session, request_id)
        if is_admin
        else await accessible_request(session, request_id, owner_id)
    )
    resolving = is_admin and parent.status == RequestStatus.conflicted
    if resolving:
        check_conflict_resolution_allowed(
            request_status=parent.status.value,
            expires_at=parent.expires_at,
            accepted_response_id=parent.accepted_response_id,
        )
    else:
        check_acceptance_allowed(
            requester_id=parent.requester_id,
            owner_id=owner_id,
            request_status=parent.status.value,
            moderation_status=parent.moderation_status.value,
            expires_at=parent.expires_at,
            accepted_response_id=parent.accepted_response_id,
        )
    selected = await session.scalar(
        visible_responses(owner_id).where(
            CampusResponse.id == response_id,
            CampusResponse.request_id == request_id,
            CampusResponse.moderation_status == ModerationStatus.visible,
        )
    )
    if selected is None:
        raise protocol_error(code="response_not_found", status_code=404)
    if selected.contributor_id == parent.requester_id:
        raise protocol_error(code="self_response_forbidden", status_code=403)
    operation.payload = {**details, "contributor_id": selected.contributor_id}
    if resolving:
        operation.payload = {
            **operation.payload,
            "requester_id": parent.requester_id,
            "admin_id": owner_id,
        }
    return operation
