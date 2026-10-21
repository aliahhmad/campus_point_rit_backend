# pylint: disable=invalid-name
"""Define Enums for this project."""

from enum import Enum


class RoleType(Enum):
    """Contains the different Role types Users can have."""

    user = "user"
    admin = "admin"


class RequestStatus(Enum):
    """Track the lifecycle of a campus request."""

    open = "open"
    under_review = "under_review"
    completed = "completed"
    expired = "expired"


class ModerationStatus(Enum):
    """Track whether campus content is awaiting review or can be displayed."""

    pending = "pending"
    visible = "visible"
    hidden = "hidden"
