"""Prepare a five-point hold as one protected Points transaction."""

from uuid import UUID

import asyncpg
import httpx

from app.points.config import get_settings
from app.points.database import get_database_url
from app.transactions.postgres import finish, prepare, protocol_error
from app.transactions.schemas import RequestPreparation

REQUEST_REWARD = 5


async def hold_request_points(
    conn: asyncpg.Connection, transaction_id: UUID, payload: RequestPreparation
) -> None:
    """Lock, check, deduct, reserve, and record the reward together."""
    wallet = await conn.fetchrow(
        "SELECT available_points FROM wallets WHERE user_id=$1 FOR UPDATE",
        payload.owner_id,
    )
    if wallet is None:
        raise protocol_error(code="service_unavailable", status_code=503)
    if wallet["available_points"] < REQUEST_REWARD:
        raise protocol_error(code="insufficient_points")
    await conn.execute(
        (
            "UPDATE wallets SET "
            "available_points=available_points-$2 WHERE user_id=$1"
        ),
        payload.owner_id,
        REQUEST_REWARD,
    )
    escrow_id = await conn.fetchval(
        (
            "INSERT INTO escrows "
            "(request_id,requester_id,amount,status) VALUES "
            "($1,$2,$3,'held') RETURNING id"
        ),
        payload.request_id,
        payload.owner_id,
        REQUEST_REWARD,
    )
    await conn.execute(
        (
            "INSERT INTO points_transactions "
            "(operation_id,distributed_transaction_id,escrow_id,user_id,type,amount)"
            " VALUES ($1,$1,$2,$3,'hold',$4)"
        ),
        transaction_id,
        escrow_id,
        payload.owner_id,
        REQUEST_REWARD,
    )


async def prepare_request(
    transaction_id: UUID, payload: RequestPreparation
) -> None:
    """Return only after the wallet, escrow, and ledger are durably prepared."""
    await prepare(
        get_database_url(),
        "points",
        transaction_id,
        payload,
        hold_request_points,
    )


async def coordinator_record(transaction_id: UUID) -> dict[str, str | None]:
    """Read the durable decision and operation over authenticated HTTP."""
    settings = get_settings()
    async with httpx.AsyncClient(
        base_url=settings.campus_api_url.rstrip("/"), timeout=7
    ) as client:
        response = await client.get(
            f"/internal/transactions/{transaction_id}/decision",
            headers={
                "X-Service-Token": settings.service_token.get_secret_value()
            },
        )
        try:
            response.raise_for_status()
            body = response.json()
            decision = body["decision"]
            operation = body.get("operation", "create_request")
            if (
                decision is None or decision in {"commit", "abort"}
            ) and operation in {
                "create_request",
                "accept_response",
                "expire_request",
            }:
                return {"decision": decision, "operation": operation}
            raise protocol_error(code="service_unavailable", status_code=503)
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise protocol_error(
                code="service_unavailable", status_code=503
            ) from exc


async def coordinator_decision(transaction_id: UUID) -> str | None:
    """Let recovery wait while the coordinator has no recorded decision."""
    return (await coordinator_record(transaction_id))["decision"]


async def finish_request(transaction_id: UUID, decision: str) -> None:
    """Wait for the coordinator rather than deciding after a timeout."""
    record = await coordinator_record(transaction_id)
    if record["decision"] != decision:
        raise protocol_error(code="decision_conflict")
    await finish(
        get_database_url(),
        "points",
        transaction_id,
        decision,
        operation=record["operation"] or "create_request",
    )
