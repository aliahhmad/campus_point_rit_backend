"""Define questions posted about campus locations."""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.models.enums import ModerationStatus, RequestStatus


class CampusRequest(Base):
    """Store request content and lifecycle state in the Campus database."""

    __tablename__ = "requests"
    __table_args__ = (
        CheckConstraint("reward_points = 5", name="reward_fixed_five"),
        CheckConstraint(
            "expires_at > created_at", name="expiry_after_creation"
        ),
        CheckConstraint("length(btrim(title)) > 0", name="title_not_blank"),
        CheckConstraint(
            "length(btrim(description)) > 0",
            name="description_not_blank",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    requester_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
    )
    location_id: Mapped[int] = mapped_column(
        ForeignKey("locations.id", ondelete="RESTRICT"),
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    reward_points: Mapped[int] = mapped_column(server_default="5")
    status: Mapped[RequestStatus] = mapped_column(
        Enum(RequestStatus, name="request_status"),
        server_default=RequestStatus.open.value,
        index=True,
    )
    moderation_status: Mapped[ModerationStatus] = mapped_column(
        Enum(ModerationStatus, name="moderation_status"),
        server_default=ModerationStatus.pending.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("(CURRENT_TIMESTAMP + INTERVAL '1 hour')"),
        index=True,
    )
