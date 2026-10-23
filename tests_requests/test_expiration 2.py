"""Check expiry scheduling, configuration, and application lifecycle."""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from app.config.settings import Settings, get_settings
from app.managers import expiration


@pytest.mark.parametrize("interval", [0, -1])
def test_expiry_interval_must_be_positive(interval: int) -> None:
    """Reject a schedule that would spin without a positive delay."""
    values = get_settings().model_dump()
    values["request_expiry_scan_interval_seconds"] = interval
    with pytest.raises(ValidationError, match="greater than 0"):
        Settings(**values)


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_first_scan", [False, True])
async def test_expiry_loop_repeats_and_recovers(
    monkeypatch: pytest.MonkeyPatch, *, failed_first_scan: bool
) -> None:
    """Scan before sleeping, retry failures, and propagate cancellation."""
    scan = AsyncMock(side_effect=[OSError if failed_first_scan else 0, 2])
    monkeypatch.setattr(expiration, "expire_requests", scan)
    monkeypatch.setattr(
        get_settings(), "request_expiry_scan_interval_seconds", 123
    )
    delays = []

    async def sleep(seconds: float) -> None:
        assert scan.await_count == len(delays) + 1
        delays.append(seconds)
        if len(delays) == 2:  # noqa: PLR2004
            raise asyncio.CancelledError

    monkeypatch.setattr(expiration.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        await expiration.expiration_loop()
    assert scan.await_count == 2  # noqa: PLR2004
    assert delays == [123, 123]


@pytest.mark.asyncio
async def test_lifespan_starts_and_stops_expiry_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Start expiry with Campus and await its cancellation on shutdown."""
    from app import main  # noqa: PLC0415

    started, stopped = asyncio.Event(), asyncio.Event()

    async def worker() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    session = AsyncMock()
    context = AsyncMock()
    context.__aenter__.return_value = session
    monkeypatch.setattr(main, "async_session", Mock(return_value=context))
    monkeypatch.setattr(main, "expiration_loop", worker)
    monkeypatch.setattr(main, "recovery_loop", asyncio.Event().wait)
    monkeypatch.setattr(get_settings(), "cache_enabled", False)
    async with main.lifespan(FastAPI()):
        await asyncio.wait_for(started.wait(), timeout=1)
        assert not stopped.is_set()
    assert stopped.is_set()
