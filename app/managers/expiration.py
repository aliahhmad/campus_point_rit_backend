"""Persist overdue request statuses without changing Points balances."""

import asyncio
import logging

import asyncpg

from app.config.settings import get_settings
from app.database.db import get_database_url
from app.transactions.postgres import connection

logger = logging.getLogger(__name__)


async def expire_requests() -> int:
    """Expire overdue active requests, skipping rows locked by other work."""
    async with connection(get_database_url()) as conn:
        rows = await conn.fetch(
            "WITH due AS ("
            "SELECT id FROM requests "
            "WHERE status IN ('open','under_review') "
            "AND expires_at <= CURRENT_TIMESTAMP "
            "AND accepted_response_id IS NULL AND accepted_at IS NULL "
            "FOR UPDATE SKIP LOCKED"
            ") UPDATE requests r SET status='expired' FROM due "
            "WHERE r.id=due.id RETURNING r.id"
        )
    return len(rows)


async def expiration_loop() -> None:
    """Scan immediately on startup, then wait the configured interval."""
    interval = get_settings().request_expiry_scan_interval_seconds
    while True:
        try:
            count = await expire_requests()
            logger.info("Request expiry scan completed: %s expired", count)
        except (
            asyncpg.PostgresError,
            asyncpg.InterfaceError,
            OSError,
            TimeoutError,
        ):
            logger.exception(
                "Request expiry scan failed; retrying next interval"
            )
        await asyncio.sleep(interval)
