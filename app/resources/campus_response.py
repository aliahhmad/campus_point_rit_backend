"""Expose authenticated response submission and browsing APIs."""

from typing import Annotated, cast

import asyncpg
from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Path,
    Query,
    Response,
    status,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.db import get_database_manual
from app.managers.campus_response import (
    create_response_transaction,
    get_response,
    list_responses,
)
from app.managers.coordinator import advance_operation
from app.managers.security import get_current_user
from app.models.user import User
from app.schemas.request.campus_response import CampusResponseCreate
from app.schemas.response.campus_response import (
    CampusResponseCreateResult,
    CampusResponseList,
    CampusResponseRead,
)

router = APIRouter(tags=["Responses"])


@router.post(
    "/requests/{request_id}/responses", status_code=status.HTTP_202_ACCEPTED
)
async def create_response(  # noqa: PLR0913
    *,
    request_id: Annotated[int, Path(gt=0, le=2_147_483_647)],
    submission: CampusResponseCreate,
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
) -> CampusResponseCreateResult:
    """Create one moderated answer through Campus-only two-phase commit."""
    try:
        async with session.begin():
            operation = await create_response_transaction(
                request_id,
                submission,
                idempotency_key,
                current_user.id,
                session,
            )
        result = cast(
            "CampusResponseCreateResult", await advance_operation(operation.id)
        )
        if result.status == "completed":
            response.status_code = status.HTTP_201_CREATED
        elif result.status == "aborted":
            code = result.error_code or "service_unavailable"
            failure_status = {
                "request_not_found": 404,
                "self_response_forbidden": 403,
                "duplicate_response": 409,
                "idempotency_conflict": 409,
                "request_not_open": 409,
                "request_expired": 409,
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


@router.get("/requests/{request_id}/responses")
async def get_responses(  # noqa: PLR0913
    *,
    request_id: Annotated[int, Path(gt=0, le=2_147_483_647)],
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_database_manual)],
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
    mine: bool = False,
) -> CampusResponseList:
    """Browse confirmed visible answers and the contributor's own answers."""
    return await list_responses(
        session, request_id, current_user.id, page=page, size=size, mine=mine
    )


@router.get("/responses/{response_id}")
async def get_response_by_id(
    response_id: Annotated[int, Path(gt=0, le=2_147_483_647)],
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_database_manual)],
) -> CampusResponseRead:
    """Retrieve an answer using the same visibility rules as the list."""
    return await get_response(session, response_id, current_user.id)
