"""Expose authenticated, idempotent campus request intake."""

from typing import Annotated
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.db import get_database_manual
from app.managers.campus_request import create_request_transaction
from app.managers.coordinator import advance_operation
from app.managers.security import get_current_user
from app.models.distributed_transaction import DistributedTransaction
from app.models.user import User
from app.schemas.request.campus_request import CampusRequestCreate
from app.schemas.response.campus_request import CampusRequestCreateResponse

router = APIRouter(tags=["Requests"])


@router.post("/requests", status_code=status.HTTP_202_ACCEPTED)
async def create_request(
    submission: CampusRequestCreate,
    response: Response,
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=1,
            max_length=128,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
        ),
    ],
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[
        AsyncSession, Depends(get_database_manual, scope="function")
    ],
) -> CampusRequestCreateResponse:
    """Create a request and its five-point hold through two-phase commit."""
    try:
        async with session.begin():
            operation = await create_request_transaction(
                submission, idempotency_key, current_user.id, session
            )
        result = await advance_operation(operation.id)
        if result.status == "completed":
            response.status_code = status.HTTP_201_CREATED
        elif result.status == "aborted":
            code = result.error_code or "service_unavailable"
            failure_status = (
                409
                if code in {"insufficient_points", "idempotency_conflict"}
                else (422 if code == "invalid_location" else 503)
            )
            raise HTTPException(
                failure_status,
                detail={
                    "code": code,
                    "message": code.replace("_", " ").capitalize(),
                    "operation_id": str(result.operation_id),
                },
            )
    except (
        SQLAlchemyError,
        asyncpg.PostgresError,
        OSError,
        TimeoutError,
    ) as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "service_unavailable",
                "message": "Service unavailable. Retry with the same key.",
            },
            headers={"Retry-After": "5"},
        ) from exc
    else:
        return result


@router.get("/operations/{operation_id}")
async def get_operation(
    operation_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_database_manual)],
) -> CampusRequestCreateResponse:
    """Authorize the owner, then retry and report unfinished coordination."""
    try:
        operation = await session.get(DistributedTransaction, operation_id)
        if operation is None or operation.owner_id != current_user.id:
            raise HTTPException(404, "Operation not found")
        result = await advance_operation(operation_id)
    except (
        SQLAlchemyError,
        asyncpg.PostgresError,
        OSError,
        TimeoutError,
    ) as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "service_unavailable",
                "message": "Service unavailable. Retry this operation.",
            },
            headers={"Retry-After": "5"},
        ) from exc
    else:
        return result
