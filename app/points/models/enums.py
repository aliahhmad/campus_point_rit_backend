"""Define statuses and ledger entry types owned by the Points Service."""

from enum import Enum


class EscrowStatus(Enum):
    """Track whether a request's reserved points have been settled."""

    held = "held"
    released = "released"
    refunded = "refunded"


class PointsTransactionType(Enum):
    """Describe how a ledger entry affects a user's points."""

    opening_grant = "opening_grant"
    hold = "hold"
    reward = "reward"
    refund = "refund"


class ParticipantState(Enum):
    """Track the Points participant's local transaction outcome."""

    prepared = "prepared"
    committed = "committed"
    aborted = "aborted"
