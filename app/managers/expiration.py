"""Classify overdue requests and coordinate refunds for unanswered ones."""

import asyncio
import json
import logging
from uuid import UUID, uuid4

from app.config.settings import get_settings
from app.database.db import get_database_url
from app.managers.coordinator import FAILURES, advance_operation
from app.transactions.postgres import connection

logger = logging.getLogger(__name__)


async def queue_expirations() -> tuple[list[UUID], int]:
    """Lock due requests, flag answered ones, and persist refund operations."""
    operations = []
    conflicted = 0
    async with connection(get_database_url()) as conn, conn.transaction():
        rows = await conn.fetch(
            "SELECT r.id,r.requester_id,EXISTS ("
            "SELECT 1 FROM responses a WHERE a.request_id=r.id) AS answered "
            "FROM requests r "
            "WHERE r.status IN ('open','under_review','expired') "
            "AND r.expires_at <= CURRENT_TIMESTAMP "
            "AND r.accepted_response_id IS NULL AND r.accepted_at IS NULL "
            "AND NOT EXISTS (SELECT 1 FROM distributed_transactions d "
            "WHERE d.request_id=r.id AND d.operation='expire_request' "
            "AND (d.state != 'finished' OR d.decision='commit')) "
            "ORDER BY r.expires_at,r.id LIMIT 100 FOR UPDATE OF r SKIP LOCKED"
        )
        for row in rows:
            if row["answered"]:
                await conn.execute(
                    "UPDATE requests SET status='conflicted' WHERE id=$1",
                    row["id"],
                )
                conflicted += 1
                continue
            transaction_id = uuid4()
            created = await conn.fetchval(
                "INSERT INTO distributed_transactions "
                "(id,owner_id,idempotency_key,operation,payload,request_id) "
                "VALUES ($1,$2,$3,'expire_request',$4,$5) "
                "ON CONFLICT DO NOTHING RETURNING id",
                transaction_id,
                row["requester_id"],
                f"expiry:{row['id']}:{transaction_id.hex}",
                json.dumps({"request_id": row["id"]}),
                row["id"],
            )
            if created is not None:
                operations.append(created)
    # Parent locks must be released before a native participant prepares.
    return operations, conflicted


async def expire_requests() -> int:
    """Finish due classifications and resume durable refunds through 2PC."""
    operations, completed = await queue_expirations()
    for transaction_id in operations:
        try:
            result = await advance_operation(transaction_id)
            if result.status == "completed":
                completed += 1
            else:
                logger.warning(
                    "Request expiry operation %s is %s (%s)",
                    transaction_id,
                    result.status,
                    result.error_code,
                )
        except FAILURES:  # noqa: PERF203 - other requests must still progress
            logger.exception(
                "Request expiry operation %s awaits recovery", transaction_id
            )
    return completed


async def expiration_loop() -> None:
    """Scan immediately on startup, then wait the configured interval."""
    interval = get_settings().request_expiry_scan_interval_seconds
    while True:
        try:
            count = await expire_requests()
            logger.info("Request expiry scan completed: %s settled", count)
        except FAILURES:
            logger.exception(
                "Request expiry scan failed; retrying next interval"
            )
        await asyncio.sleep(interval)
