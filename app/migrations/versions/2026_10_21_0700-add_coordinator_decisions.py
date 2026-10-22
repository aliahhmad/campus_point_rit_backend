"""Add durable coordinator decisions and reserved request IDs.

Revision ID: add_coordinator_decisions
Revises: add_participant_records
"""

import sqlalchemy as sa
from alembic import op

revision = "add_coordinator_decisions"
down_revision = "add_participant_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Extend existing submissions without changing their IDs or keys."""
    state = sa.Enum(
        "preparing",
        "commit_decided",
        "abort_decided",
        "finished",
        name="transaction_state",
    )
    decision = sa.Enum("commit", "abort", name="transaction_decision")
    state.create(op.get_bind())
    decision.create(op.get_bind())
    op.add_column(
        "distributed_transactions",
        sa.Column("request_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "distributed_transactions",
        sa.Column("state", state, server_default="preparing", nullable=False),
    )
    op.add_column(
        "distributed_transactions",
        sa.Column("decision", decision, nullable=True),
    )
    op.add_column(
        "distributed_transactions",
        sa.Column("error_code", sa.String(40), nullable=True),
    )
    op.add_column(
        "distributed_transactions",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Remove coordinator progress fields."""
    for name in ("updated_at", "error_code", "decision", "state", "request_id"):
        op.drop_column("distributed_transactions", name)
    sa.Enum(name="transaction_decision").drop(op.get_bind())
    sa.Enum(name="transaction_state").drop(op.get_bind())
