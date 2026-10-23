"""Let owners accept responses and administrators resolve conflicts."""

from typing import Annotated, cast

import asyncpg
from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Path,
    Response,
    status,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.db import get_database_manual
from app.managers.acceptance import create_acceptance_transaction
from app.managers.coordinator import advance_operation
from app.managers.security import get_current_user
from app.models.enums import RoleType
from app.models.user import User
from app.schemas.response.acceptance import ResponseAcceptanceResult

router = APIRouter(tags=["Response acceptance"])


@router.post(
    "/requests/{request_id}/responses/{response_id}/accept",
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        200: {
            "model": ResponseAcceptanceResult,
            "description": "Both participants acknowledged completion.",
        },
    },
)
async def accept_response(  # noqa: PLR0913
    *,
    request_id: Annotated[int, Path(gt=0, le=2_147_483_647)],
    response_id: Annotated[int, Path(gt=0, le=2_147_483_647)],
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
) -> ResponseAcceptanceResult:
    """Coordinate request completion and reward release through native 2PC."""
    try:
        async with session.begin():
            operation = await create_acceptance_transaction(
                request_id,
                response_id,
                idempotency_key,
                current_user.id,
                session,
                is_admin=current_user.role == RoleType.admin,
            )
        result = cast(
            "ResponseAcceptanceResult", await advance_operation(operation.id)
        )
        if result.status == "completed":
            response.status_code = status.HTTP_200_OK
        elif result.status == "aborted":
            code = result.error_code or "service_unavailable"
            failure_status = {
                "request_owner_required": 403,
                "admin_required": 403,
                "self_response_forbidden": 403,
                "request_not_found": 404,
                "response_not_found": 404,
                "request_already_accepted": 409,
                "request_not_open": 409,
                "request_not_visible": 409,
                "request_expired": 409,
                "request_not_conflicted": 409,
                "request_not_expired": 409,
                "idempotency_conflict": 409,
                "escrow_not_found": 409,
                "escrow_mismatch": 409,
                "escrow_already_settled": 409,
            }.get(code, 503)
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
            503,
            detail={
                "code": "service_unavailable",
                "message": "Service unavailable. Retry with the same key.",
            },
            headers={"Retry-After": "5"},
        ) from exc
    else:
        return result
