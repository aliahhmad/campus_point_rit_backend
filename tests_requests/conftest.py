"""Use an isolated SQLite database, or an explicitly supplied test database."""

import os
from collections.abc import AsyncGenerator
from pathlib import Path
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database.db import Base, get_database_manual
from app.managers.security import get_current_user
from app.models.distributed_transaction import DistributedTransaction
from app.models.location import Location
from app.models.transaction_participant import TransactionParticipant
from app.models.user import User
from app.resources.routes import api_router
from app.schemas.response.campus_request import CampusRequestCreateResponse

os.environ.setdefault("POINTS_DB_PASSWORD", "points-test-unused-password")


@pytest_asyncio.fixture
async def sessions(
    tmp_path: Path,
) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    """Create only intake tables in a disposable test database."""
    url = os.getenv(
        "REQUESTS_TEST_DATABASE_URL",
        f"sqlite+aiosqlite:///{tmp_path / 'requests.db'}",
    )
    engine = create_async_engine(url)
    tables = [
        User.__table__,
        Location.__table__,
        DistributedTransaction.__table__,
        TransactionParticipant.__table__,
    ]
    async with engine.begin() as connection:
        if engine.dialect.name == "sqlite":
            await connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        await connection.run_sync(
            lambda sync: Base.metadata.create_all(sync, tables=tables)
        )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        session.add_all(
            [
                User(
                    id=user_id,
                    email=f"user{user_id}@example.com",
                    password="unused-test-password",  # noqa: S106
                    first_name="Test",
                    last_name="User",
                )
                for user_id in (1, 2)
            ]
        )
        session.add_all(
            [
                Location(id=1, name="Library", building_code="LIB"),
                Location(
                    id=2, name="Closed", building_code="OFF", is_active=False
                ),
            ]
        )
    try:
        yield factory
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda sync: Base.metadata.drop_all(sync, tables=tables)
            )
        await engine.dispose()


@pytest.fixture
def api(
    sessions: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> FastAPI:
    """Use the real Campus router with controlled identity and database."""
    app = FastAPI()
    app.include_router(api_router)

    async def database() -> AsyncGenerator[AsyncSession, None]:
        async with sessions() as session:
            yield session

    async def user() -> User:
        return User(id=1)

    app.dependency_overrides[get_database_manual] = database
    app.dependency_overrides[get_current_user] = user

    async def processing(operation_id: UUID) -> CampusRequestCreateResponse:
        async with sessions() as session:
            operation = await session.get(DistributedTransaction, operation_id)
            assert operation is not None
            return CampusRequestCreateResponse(
                operation_id=operation.id, created_at=operation.created_at
            )

    # Isolate intake here; tests_workflow exercises actual two-phase commit.
    monkeypatch.setattr(
        "app.resources.campus_request.advance_operation", processing
    )
    return app


@pytest_asyncio.fixture
async def client(api: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Exercise HTTP parsing, authentication wiring, and serialization."""
    async with AsyncClient(
        transport=ASGITransport(app=api), base_url="http://test"
    ) as client:
        yield client
