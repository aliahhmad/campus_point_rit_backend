"""Store contributors' answers to campus requests."""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.models.enums import ModerationStatus


class CampusResponse(Base):
    """Allow one moderated answer per contributor and request."""

    __tablename__ = "responses"
    __table_args__ = (
        UniqueConstraint(
            "request_id",
            "contributor_id",
            name="uq_responses_request_contributor",
        ),
        CheckConstraint("length(trim(answer)) > 0", name="answer_not_blank"),
        CheckConstraint("length(answer) <= 5000", name="answer_max_length"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(
        ForeignKey("requests.id", ondelete="RESTRICT")
    )
    contributor_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    answer: Mapped[str] = mapped_column(Text)
    moderation_status: Mapped[ModerationStatus] = mapped_column(
        Enum(ModerationStatus, name="moderation_status"),
        server_default=ModerationStatus.pending.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
