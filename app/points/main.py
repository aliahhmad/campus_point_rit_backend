"""FastAPI entry point for the independent Points Service."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.points.database import engine
from app.points.resources.routes import api_router


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Release database connections when the service stops."""
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(title="CampusPoint Points API", lifespan=lifespan)
app.include_router(api_router)
