"""Points-only SQLAlchemy metadata and database sessions."""

from collections.abc import AsyncGenerator

from sqlalchemy import URL, MetaData
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.points.config import get_settings


class Base(DeclarativeBase):
    """Base for Points models, independent of Campus metadata."""

    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        },
    )


def get_database_url() -> URL:
    """Build a URL without manually interpolating credentials."""
    settings = get_settings()
    return URL.create(
        "postgresql+asyncpg",
        username=settings.db_user,
        password=settings.db_password.get_secret_value(),
        host=settings.db_address,
        port=settings.db_port,
        database=settings.db_name,
    )


engine = create_async_engine(get_database_url(), pool_pre_ping=True)
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def get_database() -> AsyncGenerator[AsyncSession, None]:
    """Provide a local transaction, separate from distributed preparation."""
    async with async_session() as session, session.begin():
        yield session
