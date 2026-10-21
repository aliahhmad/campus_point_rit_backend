"""Define the points ledger for grants, holds, rewards, and refunds."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.points.database import Base
from app.points.models.enums import PointsTransactionType


class PointsTransaction(Base):
    """Record a positive points amount once per logical operation."""

    __tablename__ = "points_transactions"
    __table_args__ = (CheckConstraint("amount > 0", name="amount_positive"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # Callers reuse the operation ID when retrying the same operation.
    operation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        unique=True,
    )
    distributed_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    escrow_id: Mapped[int | None] = mapped_column(
        ForeignKey("escrows.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("wallets.user_id", ondelete="RESTRICT"),
        index=True,
    )
    type: Mapped[PointsTransactionType] = mapped_column(
        Enum(PointsTransactionType, name="points_transaction_type"),
    )
    amount: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
