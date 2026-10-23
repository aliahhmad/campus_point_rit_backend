"""Track votes and acknowledgements in the Campus coordinator."""

from uuid import UUID

from sqlalchemy import Boolean, Enum, ForeignKey, Uuid, false
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.models.enums import ParticipantType, ParticipantVote


class TransactionParticipant(Base):
    """Store one vote and acknowledgement per transaction and service."""

    __tablename__ = "transaction_participants"

    transaction_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("distributed_transactions.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    participant: Mapped[ParticipantType] = mapped_column(
        Enum(ParticipantType, name="transaction_participant_type"),
        primary_key=True,
    )
    vote: Mapped[ParticipantVote | None] = mapped_column(
        Enum(ParticipantVote, name="transaction_participant_vote"),
        nullable=True,
    )
    acknowledged: Mapped[bool] = mapped_column(Boolean, server_default=false())
