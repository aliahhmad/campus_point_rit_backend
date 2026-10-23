"""Check coordinator tracking and each service's independent recovery data."""

import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.models.distributed_transaction import DistributedTransaction
from app.models.enums import ParticipantState as CampusState
from app.models.enums import ParticipantType, ParticipantVote
from app.models.participant_transaction import (
    ParticipantTransaction as CampusTransaction,
)
from app.models.transaction_participant import TransactionParticipant
from app.points.models.enums import ParticipantState as PointsState
from app.points.models.participant_transaction import (
    ParticipantTransaction as PointsTransaction,
)

pytestmark = pytest.mark.asyncio


async def test_coordinator_participants(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Allow both services, initially without votes or acknowledgements."""
    transaction_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(
            DistributedTransaction(
                id=transaction_id,
                owner_id=1,
                idempotency_key="participant-test",
                payload={},
            )
        )
        await session.flush()
        session.add_all(
            [
                TransactionParticipant(
                    transaction_id=transaction_id, participant=participant
                )
                for participant in ParticipantType
            ]
        )

    async with sessions() as session, session.begin():
        for participant in ParticipantType:
            record = await session.get(
                TransactionParticipant, (transaction_id, participant)
            )
            assert record is not None
            assert record.vote is None
            assert record.acknowledged is False
            record.vote = ParticipantVote.yes
            record.acknowledged = True

    async with sessions() as session:
        record = await session.get(
            TransactionParticipant, (transaction_id, ParticipantType.campus)
        )
        assert record is not None
        assert record.vote is ParticipantVote.yes
        assert record.acknowledged is True

    with pytest.raises(IntegrityError):
        async with sessions() as session, session.begin():
            session.add(
                TransactionParticipant(
                    transaction_id=transaction_id,
                    participant=ParticipantType.campus,
                )
            )


async def test_participant_requires_coordinator_transaction(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Reject coordinator tracking records without a parent transaction."""
    with pytest.raises(IntegrityError):
        async with sessions() as session, session.begin():
            session.add(
                TransactionParticipant(
                    transaction_id=uuid4(), participant=ParticipantType.points
                )
            )


@pytest.mark.parametrize("service", ["campus", "points"])
@pytest.mark.parametrize("outcome", ["committed", "aborted"])
async def test_local_recovery_records(
    tmp_path: Path, service: str, outcome: str
) -> None:
    """Persist local identifiers, reject duplicates, and timestamp decisions."""
    model = CampusTransaction if service == "campus" else PointsTransaction
    states = CampusState if service == "campus" else PointsState
    variable = (
        "REQUESTS_TEST_DATABASE_URL"
        if service == "campus"
        else "POINTS_TEST_DATABASE_URL"
    )
    engine = create_async_engine(
        os.getenv(variable, f"sqlite+aiosqlite:///{tmp_path / 'recovery.db'}")
    )
    async with engine.begin() as connection:
        await connection.run_sync(model.__table__.create)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    transaction_id = uuid4()
    try:
        async with factory() as session, session.begin():
            record = model(
                transaction_id=transaction_id,
                local_transaction_id=f"{service}:{transaction_id}",
                operation="create_request",
                state=states.prepared,
            )
            session.add(record)
            await session.flush()
            assert record.created_at is not None
            assert record.updated_at is not None

        with pytest.raises(IntegrityError):
            async with factory() as session, session.begin():
                session.add(
                    model(
                        transaction_id=transaction_id,
                        local_transaction_id="duplicate",
                        operation="create_request",
                        state=states.prepared,
                    )
                )

        async with factory() as session, session.begin():
            record = await session.get(model, transaction_id)
            assert record is not None
            assert record.local_transaction_id == f"{service}:{transaction_id}"
            assert record.state is states.prepared
            # Force an older value so no sleep is needed to test onupdate.
            record.updated_at = datetime(2000, 1, 1, tzinfo=timezone.utc)

        async with factory() as session, session.begin():
            record = await session.get(model, transaction_id)
            assert record is not None
            record.state = states(outcome)

        async with factory() as session:
            record = await session.get(model, transaction_id)
            assert record is not None
            assert record.state.value == outcome
            old_year = 2000
            assert record.updated_at.year > old_year

        # Recovery records do not depend on another service's schema.
        assert not model.__table__.foreign_keys
        assert CampusTransaction.metadata is not PointsTransaction.metadata
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(model.__table__.drop)
        await engine.dispose()
