"""Enforce one opening grant per user.

Revision ID: points_0003
Revises: points_0002
Create Date: 2026-10-21 03:32:38.223329
"""

import sqlalchemy as sa
from alembic import op

revision = "points_0003"
down_revision = "points_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Allow each user one opening grant while retaining other ledger types."""
    op.create_index(
        "uq_points_transactions_opening_grant_user",
        "points_transactions",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("type = 'opening_grant'"),
    )


def downgrade() -> None:
    """Remove the opening-grant uniqueness index."""
    op.drop_index(
        "uq_points_transactions_opening_grant_user",
        table_name="points_transactions",
    )
