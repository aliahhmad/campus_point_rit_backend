"""Add coordinator participants and Campus participant recovery records.

Revision ID: add_participant_records
Revises: use_distributed_transactions
"""

import sqlalchemy as sa
from alembic import op

revision = "add_participant_records"
down_revision = "use_distributed_transactions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create coordinator tracking and the Campus-local recovery table."""
    op.create_table(
        "transaction_participants",
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column(
            "participant",
            sa.Enum("campus", "points", name="transaction_participant_type"),
            nullable=False,
        ),
        sa.Column(
            "vote",
            sa.Enum("yes", "no", name="transaction_participant_vote"),
            nullable=True,
        ),
        sa.Column(
            "acknowledged",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["distributed_transactions.id"],
            name=op.f(
                "fk_transaction_participants_transaction_id_distributed_transactions"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "transaction_id",
            "participant",
            name=op.f("pk_transaction_participants"),
        ),
    )
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
    """Remove Campus participant tables and their enum types."""
    op.drop_table("participant_transactions")
    op.drop_table("transaction_participants")
    sa.Enum(name="participant_transaction_state").drop(op.get_bind())
    sa.Enum(name="transaction_participant_vote").drop(op.get_bind())
    sa.Enum(name="transaction_participant_type").drop(op.get_bind())
