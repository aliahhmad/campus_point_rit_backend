"""Store recovery information owned by the Points participant."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Enum, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.points.database import Base
from app.points.models.enums import ParticipantState


class ParticipantTransaction(Base):
    """Identify local work independently of the Campus database."""

    __tablename__ = "participant_transactions"

    # The coordinator supplies this ID; it is not a cross-database foreign key.
    transaction_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    local_transaction_id: Mapped[str] = mapped_column(String(200))
    operation: Mapped[str] = mapped_column(String(40))
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
