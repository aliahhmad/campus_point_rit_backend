"""Manage native PostgreSQL prepared transactions on dedicated connections.

Ordinary ORM sessions must not commit or roll back these transactions.
The prepared GID includes a payload hash, making retries verifiable even
when the prepared journal row is not visible to other connections yet.
"""

import hashlib
import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from uuid import UUID

import asyncpg
from fastapi import HTTPException
from sqlalchemy.engine import URL, make_url

from app.transactions.schemas import RequestPreparation


def protocol_error(code: str, status_code: int = 409) -> HTTPException:
    """Return a stable business error without exposing database details."""
    return HTTPException(
        status_code,
        detail={"code": code, "message": code.replace("_", " ").capitalize()},
    )


def lock_key(name: str) -> int:
    """Derive a stable signed advisory-lock key across processes."""
    return int.from_bytes(
        hashlib.sha256(name.encode()).digest()[:8], "big", signed=True
    )


@asynccontextmanager
async def connection(
    url: str | URL,
) -> AsyncGenerator[asyncpg.Connection, None]:
    """Open an independent connection with bounded lock and query waits."""
    parsed = make_url(url)
    conn = await asyncpg.connect(
        user=parsed.username,
        password=parsed.password,
        host=parsed.host,
        port=parsed.port,
        database=parsed.database,
        timeout=5,
        command_timeout=12,
        server_settings={"lock_timeout": "5000", "statement_timeout": "10000"},
    )
    try:
        yield conn
    finally:
        await conn.close()


def gid_prefix(service: str, transaction_id: UUID) -> str:
    """Identify this service's native transaction without using client SQL."""
    return f"campuspoint:{service}:{transaction_id.hex}:"


async def prepared_gid(conn: asyncpg.Connection, prefix: str) -> str | None:
    """Find preparation only in this service's current database."""
    value = await conn.fetchval(
        (
            "SELECT gid FROM pg_prepared_xacts WHERE database = "
            "current_database() AND starts_with(gid, $1)"
        ),
        prefix,
    )
    return str(value) if value is not None else None


def quoted_gid(gid: str) -> str:
    """Quote a GID because PostgreSQL requires a literal for 2PC commands."""
    return "'" + gid.replace("'", "''") + "'"


async def prepare(
    url: str | URL,
    service: str,
    transaction_id: UUID,
    payload: RequestPreparation,
    work: Callable[
        [asyncpg.Connection, UUID, RequestPreparation], Awaitable[None]
    ],
) -> None:
    """Vote Yes only after PostgreSQL has durably prepared all local work."""
    fingerprint = hashlib.sha256(
        json.dumps(payload.model_dump(), sort_keys=True).encode()
    ).hexdigest()
    prefix = gid_prefix(service, transaction_id)
    gid = prefix + fingerprint
    async with connection(url) as conn:
        await conn.execute("SELECT pg_advisory_lock($1)", lock_key(prefix))
        record = await conn.fetchrow(
            "SELECT * FROM participant_transactions WHERE transaction_id=$1",
            transaction_id,
        )
        existing = await prepared_gid(conn, prefix)
        if record is not None and record["state"] == "aborted":
            raise protocol_error(code="operation_aborted")
        if existing is not None or record is not None:
            stored_gid = (
                record["local_transaction_id"]
                if record is not None
                else existing
            )
            if stored_gid != gid:
                raise protocol_error(code="idempotency_conflict")
            # A visible journal row proves the business work was committed.
            return
        if int(await conn.fetchval("SHOW max_prepared_transactions")) == 0:
            raise protocol_error(code="service_unavailable", status_code=503)
        await conn.execute("BEGIN")
        try:
            await work(conn, transaction_id, payload)
            await conn.execute(
                (
                    "INSERT INTO participant_transactions (transaction_id, "
                    "local_transaction_id, operation, state) VALUES "
                    "($1,$2,'create_request','prepared')"
                ),
                transaction_id,
                gid,
            )
            await conn.execute("PREPARE TRANSACTION " + quoted_gid(gid))
        except BaseException:
            # ROLLBACK affects only an open transaction, never a prepared one.
            await conn.execute("ROLLBACK")
            raise


async def mark_committed(
    conn: asyncpg.Connection, transaction_id: UUID
) -> None:
    """Close the journal gap after the business transaction is committed."""
    await conn.execute(
        "UPDATE participant_transactions SET state='committed', "
        "updated_at=now() WHERE transaction_id=$1",
        transaction_id,
    )


async def finish(
    url: str | URL, service: str, transaction_id: UUID, decision: str
) -> None:
    """Apply an already verified coordinator decision; repeats are harmless."""
    prefix = gid_prefix(service, transaction_id)
    async with connection(url) as conn:
        await conn.execute("SELECT pg_advisory_lock($1)", lock_key(prefix))
        record = await conn.fetchrow(
            "SELECT * FROM participant_transactions WHERE transaction_id=$1",
            transaction_id,
        )
        gid = await prepared_gid(conn, prefix)
        expected = "committed" if decision == "commit" else "aborted"
        if record is not None:
            state = record["state"]
            if state == expected:
                return
            # A visible 'prepared' row came from COMMIT PREPARED. The process
            # may have crashed before marking that journal row committed.
            if state == "prepared" and decision == "commit":
                await mark_committed(conn, transaction_id)
                return
            raise protocol_error(code="decision_conflict")
        if gid is not None:
            command = (
                "COMMIT PREPARED "
                if decision == "commit"
                else "ROLLBACK PREPARED "
            )
            await conn.execute(command + quoted_gid(gid))
        elif decision == "commit":
            raise protocol_error(code="missing_preparation", status_code=503)
        if decision == "commit":
            await mark_committed(conn, transaction_id)
        else:
            # A tombstone also rejects a delayed prepare after an abort.
            await conn.execute(
                (
                    "INSERT INTO participant_transactions (transaction_id, "
                    "local_transaction_id, operation, state) VALUES "
                    "($1,$2,'create_request','aborted') ON CONFLICT "
                    "(transaction_id) DO NOTHING"
                ),
                transaction_id,
                gid or prefix,
            )


async def unfinished_ids(url: str | URL, service: str) -> list[UUID]:
    """Find native preparations and commit/journal crash gaps after restart."""
    async with connection(url) as conn:
        gids = await conn.fetch(
            (
                "SELECT gid FROM pg_prepared_xacts WHERE "
                "database=current_database() AND starts_with(gid,$1)"
            ),
            f"campuspoint:{service}:",
        )
        ids = {UUID(row["gid"].split(":")[2]) for row in gids}
        ids.update(
            row["transaction_id"]
            for row in await conn.fetch(
                "SELECT transaction_id FROM participant_transactions "
                "WHERE state='prepared'"
            )
        )
        return list(ids)
