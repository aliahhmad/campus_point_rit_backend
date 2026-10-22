"""Run workflow tests only against explicitly supplied test databases."""

import os
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.config.settings import get_settings
from app.database.db import Base, get_database_manual
from app.managers.security import get_current_user
from app.models import (  # noqa: F401
    api_key,
    campus_request,
    campus_response,
    participant_transaction,
    transaction_participant,
)
from app.models.user import User
from app.points.config import get_settings as points_settings
from app.points.database import Base as PointsBase
from app.points.database import get_database as get_points_database
from app.points.resources.routes import api_router as points_router
from app.resources.routes import api_router
from app.transactions.postgres import connection, quoted_gid


@dataclass
class Workflow:
    """Keep the HTTP client and separate database addresses together."""

    client: AsyncClient
    campus_url: str
    points_url: str
    campus: FastAPI
    points: FastAPI


@pytest.fixture(autouse=True)
def moderation_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep workflow moderation independent of local configuration."""
    monkeypatch.setattr(get_settings(), "moderation_blocked_words", "shit")


async def clear_database(url: str, tables: list[str]) -> None:
    """Resolve test preparations before clearing the disposable database."""
    async with connection(url) as conn:
        rows = await conn.fetch(
            "SELECT gid FROM pg_prepared_xacts WHERE "
            "database=current_database() AND "
            "starts_with(gid,'campuspoint:')"
        )
        for row in rows:
            await conn.execute("ROLLBACK PREPARED " + quoted_gid(row["gid"]))
        names = ",".join('"' + name + '"' for name in tables)
        await conn.execute("TRUNCATE " + names + " RESTART IDENTITY CASCADE")


def points_database_override(
    engine: AsyncEngine,
) -> Callable[[], AsyncGenerator[AsyncSession, None]]:
    """Keep Points HTTP reads and local transactions on its test database."""
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def database() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session, session.begin():
            yield session

    return database


@pytest_asyncio.fixture
async def workflow(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[Workflow, None]:
    """Use real databases and route service HTTP through real ASGI handlers."""
    campus_url = os.getenv("REQUESTS_TEST_DATABASE_URL")
    points_url = os.getenv("POINTS_TEST_DATABASE_URL")
    if not campus_url or not points_url:
        pytest.skip("Set both database URLs to disposable PostgreSQL databases")
    if campus_url == points_url:
        pytest.fail("Campus and Points test databases must be separate")
    engines = [
        create_async_engine(url, poolclass=NullPool)
        for url in (campus_url, points_url)
    ]
    for engine, metadata in zip(
        engines, (Base.metadata, PointsBase.metadata), strict=True
    ):
        async with engine.begin() as conn:
            await conn.run_sync(metadata.create_all)
    campus_tables = list(Base.metadata.tables)
    points_tables = list(PointsBase.metadata.tables)
    await clear_database(campus_url, campus_tables)
    await clear_database(points_url, points_tables)
    async with connection(campus_url) as conn:
        await conn.execute(
            "INSERT INTO users "
            "(id,email,password,first_name,last_name,banned,verified)"
            " VALUES "
            "(1,'one@example.com','unused','One','Test',false,true),(2,'two@example.com','unused','Two','Test',false,true)"
        )
        await conn.execute(
            "INSERT INTO locations (id,name,building_code) VALUES"
            " (1,'Library','LIB')"
        )
    async with connection(points_url) as conn:
        await conn.execute(
            "INSERT INTO wallets (user_id,available_points) "
            "VALUES (1,100),(2,100)"
        )
    for module in (
        "app.managers.coordinator",
        "app.managers.acceptance_participant",
        "app.managers.request_participant",
        "app.managers.response_participant",
        "app.resources.transactions",
    ):
        monkeypatch.setattr(module + ".get_database_url", lambda: campus_url)
    for module in (
        "app.points.managers.campus_request",
        "app.points.managers.acceptance",
        "app.points.managers.recovery",
    ):
        monkeypatch.setattr(module + ".get_database_url", lambda: points_url)
    token = SecretStr("workflow-test-token")
    monkeypatch.setattr(get_settings(), "points_service_token", token)
    monkeypatch.setattr(get_settings(), "points_api_url", "http://points")
    monkeypatch.setattr(points_settings(), "service_token", token)
    monkeypatch.setattr(
        points_settings(),
        "campus_api_url",
        "http://campus" + get_settings().api_root,
    )
    campus, points = FastAPI(), FastAPI()
    campus.include_router(api_router)
    points.include_router(points_router)
    factory = async_sessionmaker(engines[0], expire_on_commit=False)

    async def database() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            yield session

    async def user() -> User:
        return User(id=1)

    campus.dependency_overrides[get_database_manual] = database
    campus.dependency_overrides[get_current_user] = user
    points.dependency_overrides[get_points_database] = points_database_override(
        engines[1]
    )

    def service_client(*args, **kwargs) -> AsyncClient:  # noqa: ANN002, ANN003
        base = str(kwargs.get("base_url", ""))
        target = points if base.startswith("http://points") else campus
        kwargs["transport"] = ASGITransport(
            app=target, raise_app_exceptions=False
        )
        return AsyncClient(*args, **kwargs)

    monkeypatch.setattr("httpx.AsyncClient", service_client)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=campus), base_url="http://campus"
        ) as client:
            yield Workflow(client, campus_url, points_url, campus, points)
    finally:
        await clear_database(campus_url, campus_tables)
        await clear_database(points_url, points_tables)
        for engine in engines:
            await engine.dispose()
