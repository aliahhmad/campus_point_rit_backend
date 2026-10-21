"""Define predefined campus locations."""

from sqlalchemy import String, true
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base


class Location(Base):
    """Store campus locations that users can select for a request."""

    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    building_code: Mapped[str] = mapped_column(String(20), unique=True)
    is_active: Mapped[bool] = mapped_column(server_default=true())
