"""Define points reserved for requests in the Campus Service."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.points.database import Base
from app.points.models.enums import EscrowStatus


class Escrow(Base):
    """Hold one five-point reward per external Campus request."""

    __tablename__ = "escrows"
    __table_args__ = (CheckConstraint("amount = 5", name="amount_fixed_five"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # Campus references have no foreign keys across the service boundary.
    request_id: Mapped[int] = mapped_column(unique=True)
    requester_id: Mapped[int] = mapped_column(
        ForeignKey("wallets.user_id", ondelete="RESTRICT"),
        index=True,
    )
    amount: Mapped[int] = mapped_column(server_default="5")
    status: Mapped[EscrowStatus] = mapped_column(
        Enum(EscrowStatus, name="escrow_status"),
        server_default=EscrowStatus.held.value,
    )
    recipient_id: Mapped[int | None] = mapped_column(
        ForeignKey("wallets.user_id", ondelete="RESTRICT"),
        nullable=True,
    )
    awarded_response_id: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    settled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
