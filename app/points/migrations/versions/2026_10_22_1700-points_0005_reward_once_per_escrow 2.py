"""Protect each escrow from more than one reward ledger entry.

Revision ID: points_0005
Revises: points_0004
"""

import sqlalchemy as sa
from alembic import op

revision = "points_0005"
down_revision = "points_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Allow the existing hold entry and at most one reward per escrow."""
    op.create_index(
        "uq_points_transactions_reward_escrow",
        "points_transactions",
        ["escrow_id"],
        unique=True,
        postgresql_where=sa.text("type = 'reward'"),
    )


def downgrade() -> None:
    """Remove only the reward uniqueness guard."""
    op.drop_index(
        "uq_points_transactions_reward_escrow", table_name="points_transactions"
    )
