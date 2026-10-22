"""Coordinate request and response creation and replay durable decisions."""

import asyncio
import json
import logging
from uuid import UUID

import asyncpg
import httpx
from fastapi import HTTPException, status

from app.config.settings import get_settings
from app.database.db import get_database_url
from app.managers.request_participant import finish_request, prepare_request
from app.managers.response_participant import prepare_response
from app.schemas.response.campus_request import (
    CampusRequestCreateResponse,
    CampusRequestResponse,
)
from app.schemas.response.campus_response import (
    CampusResponseCreateResult,
    CampusResponseRead,
)
from app.schemas.response.operation import OperationResult
from app.transactions.postgres import connection, lock_key, protocol_error
from app.transactions.schemas import RequestPreparation, ResponsePreparation

logger = logging.getLogger(__name__)
FAILURES = (
    asyncpg.PostgresError,
    httpx.HTTPError,
    OSError,
    TimeoutError,
    HTTPException,
)


def operation_participants(operation: str) -> tuple[str, ...]:
    """Responses use Campus only; requests also reserve points."""
    if operation == "create_response":
        return ("campus",)
    if operation == "create_request":
        return ("campus", "points")
    raise protocol_error(code="unsupported_operation", status_code=503)


async def call_points(
    transaction_id: UUID, action: str, payload: RequestPreparation | None = None
) -> None:
    """Use authenticated HTTP to contact the independent Points Service."""
    settings = get_settings()
    token = settings.points_service_token.get_secret_value()
    if not token:
        raise protocol_error(code="service_unavailable", status_code=503)
    async with httpx.AsyncClient(
        base_url=settings.points_api_url.rstrip("/"), timeout=7
    ) as client:
        response = await client.post(
            f"/internal/transactions/{transaction_id}/{action}",
            headers={"X-Service-Token": token},
            json=payload.model_dump() if payload else None,
        )
        try:
            body = response.json()
        except ValueError as exc:
            raise protocol_error(
                code="service_unavailable", status_code=503
            ) from exc
        if response.status_code >= status.HTTP_400_BAD_REQUEST:
            detail = body.get("detail", {})
            code = (
                detail.get("code", "service_unavailable")
                if isinstance(detail, dict)
                else "service_unavailable"
            )
            if code not in {
                "insufficient_points",
                "invalid_location",
                "idempotency_conflict",
            }:
                code = "service_unavailable"
            raise protocol_error(code, response.status_code)
        expected = (
            "yes"
            if action == "prepare"
            else ("committed" if action == "commit" else "aborted")
        )
        if body.get("result") != expected:
            raise protocol_error(code="service_unavailable", status_code=503)


async def record_decision(
    conn: asyncpg.Connection,
    transaction_id: UUID,
    decision: str,
    error_code: str | None = None,
) -> None:
    """Persist before delivery and never replace a recorded decision."""
    state = "commit_decided" if decision == "commit" else "abort_decided"
    await conn.execute(
        (
            "UPDATE distributed_transactions SET "
            "decision=$2,state=$3,error_code=$4,updated_at=now() "
            "WHERE id=$1 AND decision IS NULL"
        ),
        transaction_id,
        decision,
        state,
        error_code,
    )


async def operation_response(
    conn: asyncpg.Connection, transaction_id: UUID
) -> OperationResult:
    """Expose completion only after all acknowledgements are durable."""
    operation = await conn.fetchrow(
        "SELECT * FROM distributed_transactions WHERE id=$1", transaction_id
    )
    if operation is None:
        raise HTTPException(404, "Operation not found")
    result_type = (
        CampusResponseCreateResult
        if operation["operation"] == "create_response"
        else CampusRequestCreateResponse
    )
    result = result_type(
        operation_id=transaction_id,
        created_at=operation["created_at"],
        error_code=operation["error_code"],
    )
    if operation["state"] == "finished":
        if operation["decision"] == "commit":
            if isinstance(result, CampusResponseCreateResult):
                row = await conn.fetchrow(
                    "SELECT * FROM responses WHERE id=$1",
                    operation["response_id"],
                )
            else:
                row = await conn.fetchrow(
                    "SELECT * FROM requests WHERE id=$1",
                    operation["request_id"],
                )
            if row is None:
                raise protocol_error(
                    code="service_unavailable", status_code=503
                )
            result.status = "completed"
            if isinstance(result, CampusResponseCreateResult):
                result.response = CampusResponseRead(**dict(row))
            else:
                result.request = CampusRequestResponse(**dict(row))
        else:
            result.status = "aborted"
    return result


async def preparation_payload(
    conn: asyncpg.Connection, transaction_id: UUID, operation: asyncpg.Record
) -> RequestPreparation | ResponsePreparation:
    """Reserve the entity ID once and reconstruct the original submission."""
    details = (
        json.loads(operation["payload"])
        if isinstance(operation["payload"], str)
        else operation["payload"]
    )
    if operation["operation"] == "create_response":
        response_id = operation["response_id"]
        if response_id is None:
            response_id = await conn.fetchval(
                "UPDATE distributed_transactions SET "
                "response_id=nextval(pg_get_serial_sequence('responses','id')),"
                "updated_at=now() WHERE id=$1 RETURNING response_id",
                transaction_id,
            )
        return ResponsePreparation(
            **details, owner_id=operation["owner_id"], response_id=response_id
        )
    request_id = operation["request_id"]
    if request_id is None:
        request_id = await conn.fetchval(
            (
                "UPDATE distributed_transactions SET "
                "request_id=nextval(pg_get_serial_sequence('requests','id')),updated_at=now()"
                " WHERE id=$1 RETURNING request_id"
            ),
            transaction_id,
        )
    return RequestPreparation(
        **details, owner_id=operation["owner_id"], request_id=request_id
    )


async def prepare_and_decide(
    conn: asyncpg.Connection, transaction_id: UUID, operation: asyncpg.Record
) -> None:
    """Collect durable Yes votes and save one decision before delivery."""
    payload = await preparation_payload(conn, transaction_id, operation)
    decision, error_code = "commit", None
    for participant in operation_participants(operation["operation"]):
        try:
            if participant == "campus":
                if isinstance(payload, ResponsePreparation):
                    await prepare_response(transaction_id, payload)
                else:
                    await prepare_request(transaction_id, payload)
            else:
                if not isinstance(payload, RequestPreparation):
                    raise protocol_error(
                        code="unsupported_operation", status_code=503
                    )
                await call_points(transaction_id, "prepare", payload)
        except FAILURES as exc:
            decision = "abort"
            error_code = (
                exc.detail.get("code", "service_unavailable")
                if isinstance(exc, HTTPException)
                and isinstance(exc.detail, dict)
                else "service_unavailable"
            )
            await conn.execute(
                (
                    "UPDATE transaction_participants SET vote='no' WHERE "
                    "transaction_id=$1 AND participant=$2"
                ),
                transaction_id,
                participant,
            )
            break
        await conn.execute(
            (
                "UPDATE transaction_participants SET vote='yes' WHERE "
                "transaction_id=$1 AND participant=$2"
            ),
            transaction_id,
            participant,
        )
    await record_decision(conn, transaction_id, decision, error_code)


async def deliver_decision(
    conn: asyncpg.Connection, transaction_id: UUID
) -> None:
    """Repeat the durable decision until all participants acknowledge."""
    # Recovery must finish COMMIT; it cannot substitute an ABORT.
    decision = await conn.fetchval(
        "SELECT decision FROM distributed_transactions WHERE id=$1",
        transaction_id,
    )
    participants = await conn.fetch(
        "SELECT participant,acknowledged FROM transaction_participants "
        "WHERE transaction_id=$1 ORDER BY participant DESC",
        transaction_id,
    )
    for record in participants:
        participant = record["participant"]
        if record["acknowledged"]:
            continue
        try:
            if participant == "points":
                await call_points(transaction_id, decision)
            else:
                await finish_request(transaction_id, decision)
        except FAILURES:
            continue
        await conn.execute(
            (
                "UPDATE transaction_participants SET acknowledged=true "
                "WHERE transaction_id=$1 AND participant=$2"
            ),
            transaction_id,
            participant,
        )
    remaining = await conn.fetchval(
        (
            "SELECT count(*) FROM transaction_participants WHERE "
            "transaction_id=$1 AND NOT acknowledged"
        ),
        transaction_id,
    )
    if remaining == 0:
        await conn.execute(
            (
                "UPDATE distributed_transactions SET "
                "state='finished',updated_at=now() WHERE id=$1"
            ),
            transaction_id,
        )


async def advance_operation(
    transaction_id: UUID,
) -> OperationResult:
    """Serialize one coordinator and resume from its durable state."""
    async with connection(get_database_url()) as conn:
        locked = await conn.fetchval(
            "SELECT pg_try_advisory_lock($1)",
            lock_key(f"coordinator:{transaction_id}"),
        )
        if not locked:
            return await operation_response(conn, transaction_id)
        operation = await conn.fetchrow(
            "SELECT * FROM distributed_transactions WHERE id=$1", transaction_id
        )
        if operation is None:
            raise HTTPException(404, "Operation not found")
        if operation["state"] == "finished":
            return await operation_response(conn, transaction_id)
        for participant in operation_participants(operation["operation"]):
            await conn.execute(
                (
                    "INSERT INTO transaction_participants "
                    "(transaction_id,participant) VALUES ($1,$2) ON "
                    "CONFLICT DO NOTHING"
                ),
                transaction_id,
                participant,
            )
        if operation["decision"] is None:
            await prepare_and_decide(conn, transaction_id, operation)
        await deliver_decision(conn, transaction_id)
        return await operation_response(conn, transaction_id)


async def recover_operations() -> None:
    """Retry unfinished operations under cross-process coordinator locks."""
    async with connection(get_database_url()) as conn:
        rows = await conn.fetch(
            "SELECT id FROM distributed_transactions WHERE state !="
            " 'finished' ORDER BY created_at LIMIT 100"
        )
    for row in rows:
        try:
            await advance_operation(row["id"])
        except FAILURES:  # noqa: PERF203 - recover other operations after a failure
            logger.warning("Campus operation %s awaits recovery", row["id"])


async def recovery_loop() -> None:
    """Recover on startup and continue while the Campus API is running."""
    while True:
        try:
            await recover_operations()
        except FAILURES:
            logger.warning("Campus coordinator is waiting for its database")
        await asyncio.sleep(5)
