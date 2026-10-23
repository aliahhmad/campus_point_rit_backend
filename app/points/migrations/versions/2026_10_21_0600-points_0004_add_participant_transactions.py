"""Add the Points participant's local recovery records.

Revision ID: points_0004
Revises: points_0003
"""

import sqlalchemy as sa
from alembic import op

revision = "points_0004"
down_revision = "points_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create Points recovery records without cross-database foreign keys."""
    op.create_table(
        "participant_transactions",
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("local_transaction_id", sa.String(200), nullable=False),
        sa.Column("operation", sa.String(40), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "prepared",
                "committed",
                "aborted",
                name="participant_transaction_state",
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "transaction_id", name=op.f("pk_participant_transactions")
        ),
    )


def downgrade() -> None:
    """Remove Points recovery records and their enum type."""
    op.drop_table("participant_transactions")
    sa.Enum(name="participant_transaction_state").drop(op.get_bind())
