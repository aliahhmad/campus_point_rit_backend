"""Starter wallet table; opening grants require a separate ledger operation."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.points.database import Base


class Wallet(Base):
    """Store balances for external Campus users without cross-database FKs."""

    __tablename__ = "wallets"
    __table_args__ = (
        CheckConstraint("available_points >= 0", name="available_nonnegative"),
        CheckConstraint("reputation >= 0", name="reputation_nonnegative"),
    )

    user_id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=False,
    )
    available_points: Mapped[int] = mapped_column(server_default="0")
    reputation: Mapped[int] = mapped_column(server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
