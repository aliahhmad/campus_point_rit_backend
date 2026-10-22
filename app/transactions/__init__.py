"""Shared protocol tools; each service still owns its database."""

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress


@asynccontextmanager
async def running_recovery(
    worker: Callable[[], Awaitable[None]],
) -> AsyncGenerator[None, None]:
    """Start one recovery worker and cancel it when the API shuts down."""
    task = asyncio.ensure_future(worker())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
