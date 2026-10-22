"""Store submissions in the coordinator table described in the notes."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.models.enums import TransactionDecision, TransactionState


class DistributedTransaction(Base):
    """Store an operation, its owner, and its idempotency details."""

    __tablename__ = "distributed_transactions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    operation: Mapped[str] = mapped_column(
        String(40), server_default="create_request"
    )
    payload: Mapped[dict[str, str | int]] = mapped_column(JSON)
    # Reserve the request ID before preparation; its row is not visible yet.
    request_id: Mapped[int | None] = mapped_column(nullable=True)
    state: Mapped[TransactionState] = mapped_column(
        Enum(TransactionState, name="transaction_state"),
        server_default=TransactionState.preparing.value,
    )
    decision: Mapped[TransactionDecision | None] = mapped_column(
        Enum(TransactionDecision, name="transaction_decision"), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
