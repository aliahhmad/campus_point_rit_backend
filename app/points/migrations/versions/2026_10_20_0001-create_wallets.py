"""Create the starter Points wallets table.

Revision ID: points_0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "points_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create wallets without issuing any points."""
    op.create_table(
        "wallets",
        sa.Column("user_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column(
            "available_points",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "reputation", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "available_points >= 0",
            name=op.f("ck_wallets_available_nonnegative"),
        ),
        sa.CheckConstraint(
            "reputation >= 0",
            name=op.f("ck_wallets_reputation_nonnegative"),
        ),
        sa.PrimaryKeyConstraint("user_id", name="pk_wallets"),
    )


def downgrade() -> None:
    """Drop the starter wallets table."""
    op.drop_table("wallets")
