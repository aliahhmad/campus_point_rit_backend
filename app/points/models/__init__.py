"""Import every Points model here so Alembic discovers its table."""

from app.points.models.escrow import Escrow
from app.points.models.participant_transaction import ParticipantTransaction
from app.points.models.points_transaction import PointsTransaction
from app.points.models.wallet import Wallet

__all__ = ["Escrow", "ParticipantTransaction", "PointsTransaction", "Wallet"]
