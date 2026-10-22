"""Store recovery information owned by the Campus participant."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Enum, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.models.enums import ParticipantState


class ParticipantTransaction(Base):
    """Identify local work and its last recorded protocol state."""

    __tablename__ = "participant_transactions"

    transaction_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    local_transaction_id: Mapped[str] = mapped_column(String(200))
    operation: Mapped[str] = mapped_column(String(40))
    # The preparation protocol must set this explicitly after durable work.
    state: Mapped[ParticipantState] = mapped_column(
        Enum(ParticipantState, name="participant_transaction_state")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
