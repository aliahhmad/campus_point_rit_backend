"""Recover Points work only after obtaining a coordinator decision."""

import asyncio
import logging

import asyncpg
import httpx
from fastapi import HTTPException

from app.points.database import get_database_url
from app.points.managers.campus_request import (
    coordinator_decision,
    finish_request,
)
from app.transactions.postgres import unfinished_ids

logger = logging.getLogger(__name__)
FAILURES = (
    asyncpg.PostgresError,
    httpx.HTTPError,
    OSError,
    TimeoutError,
    HTTPException,
)


async def recover_transactions() -> None:
    """Wait when Campus has not decided or is offline."""
    for transaction_id in await unfinished_ids(get_database_url(), "points"):
        try:
            decision = await coordinator_decision(transaction_id)
            if decision in {"commit", "abort"}:
                await finish_request(transaction_id, decision)
        except FAILURES:  # noqa: PERF203 - recover other transactions as well
            logger.warning(
                "Points transaction %s awaits its coordinator", transaction_id
            )


async def recovery_loop() -> None:
    """Retry on startup and after temporary communication failures."""
    while True:
        try:
            await recover_transactions()
        except FAILURES:
            logger.warning("Points preparation is waiting for its coordinator")
        await asyncio.sleep(5)
