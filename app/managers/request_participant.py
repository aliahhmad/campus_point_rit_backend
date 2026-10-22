"""Prepare the Campus request without publishing an incomplete operation."""

from uuid import UUID

import asyncpg

from app.database.db import get_database_url
from app.managers.moderation import auto_moderate_request
from app.transactions.postgres import (
    connection,
    finish,
    prepare,
    protocol_error,
)
from app.transactions.schemas import RequestPreparation


async def insert_request(
    conn: asyncpg.Connection, _transaction_id: UUID, payload: RequestPreparation
) -> None:
    """Validate and insert content within the participant transaction."""
    location = await conn.fetchval(
        "SELECT id FROM locations WHERE id=$1 AND is_active FOR SHARE",
        payload.location_id,
    )
    if location is None:
        raise protocol_error(code="invalid_location", status_code=422)
    await conn.execute(
        (
            "INSERT INTO requests "
            "(id,requester_id,location_id,title,description,moderation_status) "
            "VALUES ($1,$2,$3,$4,$5,$6)"
        ),
        payload.request_id,
        payload.owner_id,
        payload.location_id,
        payload.title,
        payload.description,
        auto_moderate_request(payload.title, payload.description).value,
    )


async def prepare_request(
    transaction_id: UUID, payload: RequestPreparation
) -> None:
    """Prepare Campus changes on a dedicated transaction-management path."""
    await prepare(
        get_database_url(), "campus", transaction_id, payload, insert_request
    )


async def finish_request(transaction_id: UUID, decision: str) -> None:
    """Verify the decision before finishing any prepared Campus operation."""
    async with connection(get_database_url()) as conn:
        recorded = await conn.fetchrow(
            "SELECT decision,operation FROM distributed_transactions "
            "WHERE id=$1",
            transaction_id,
        )
    if recorded is None or recorded["decision"] != decision:
        raise protocol_error(code="decision_conflict")
    await finish(
        get_database_url(),
        "campus",
        transaction_id,
        decision,
        operation=recorded["operation"],
    )
