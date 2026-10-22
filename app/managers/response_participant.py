"""Prepare an answer in Campus without involving the Points service."""

from uuid import UUID

import asyncpg

from app.database.db import get_database_url
from app.managers.campus_response import check_response_allowed
from app.managers.moderation import auto_moderate_request
from app.transactions.postgres import prepare, protocol_error
from app.transactions.schemas import ResponsePreparation


async def insert_response(
    conn: asyncpg.Connection,
    _transaction_id: UUID,
    payload: ResponsePreparation,
) -> None:
    """Recheck parent eligibility under a lock, moderate, and insert once."""
    parent = await conn.fetchrow(
        "SELECT r.* FROM requests r WHERE r.id=$1 "
        "AND r.moderation_status='visible' AND EXISTS ("
        "SELECT 1 FROM distributed_transactions d WHERE d.request_id=r.id "
        "AND d.operation='create_request' AND d.state='finished' "
        "AND d.decision='commit') FOR SHARE OF r",
        payload.request_id,
    )
    if parent is None:
        raise protocol_error(code="request_not_found", status_code=404)
    check_response_allowed(
        parent["requester_id"],
        payload.owner_id,
        parent["status"],
        parent["expires_at"],
    )
    response_id = await conn.fetchval(
        "INSERT INTO responses "
        "(id,request_id,contributor_id,answer,moderation_status) "
        "VALUES ($1,$2,$3,$4,$5) "
        "ON CONFLICT (request_id,contributor_id) DO NOTHING RETURNING id",
        payload.response_id,
        payload.request_id,
        payload.owner_id,
        payload.answer,
        auto_moderate_request("", payload.answer).value,
    )
    if response_id is None:
        raise protocol_error(code="duplicate_response")


async def prepare_response(
    transaction_id: UUID, payload: ResponsePreparation
) -> None:
    """Vote Yes after PostgreSQL durably prepares the response and journal."""
    await prepare(
        get_database_url(),
        "campus",
        transaction_id,
        payload,
        insert_response,
        operation="create_response",
    )
