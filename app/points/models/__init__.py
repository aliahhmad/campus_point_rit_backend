"""Import every Points model here so Alembic discovers its table."""

from app.points.models.wallet import Wallet

__all__ = ["Wallet"]
