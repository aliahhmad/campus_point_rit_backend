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
    conflicted = "conflicted"


class ModerationStatus(Enum):
    """Track whether campus content is awaiting review or can be displayed."""

    pending = "pending"
    visible = "visible"
    hidden = "hidden"


class ParticipantType(Enum):
    """Identify the two participants tracked by the Campus coordinator."""

    campus = "campus"
    points = "points"


class ParticipantVote(Enum):
    """Record a participant's preparation vote."""

    yes = "yes"
    no = "no"


class ParticipantState(Enum):
    """Track the Campus participant's local transaction outcome."""

    prepared = "prepared"
    committed = "committed"
    aborted = "aborted"


class TransactionState(Enum):
    """Track the coordinator's durable progress."""

    preparing = "preparing"
    commit_decided = "commit_decided"
    abort_decided = "abort_decided"
    finished = "finished"


class TransactionDecision(Enum):
    """Record the coordinator's immutable decision."""

    commit = "commit"
    abort = "abort"
