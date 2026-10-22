"""Add moderated responses and their reserved coordinator IDs.

Revision ID: add_responses
Revises: add_coordinator_decisions
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "add_responses"
down_revision = "add_coordinator_decisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Reuse the existing moderation enum and create response constraints."""
    op.create_table(
        "responses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "request_id",
            sa.Integer(),
            sa.ForeignKey("requests.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "contributor_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column(
            "moderation_status",
            postgresql.ENUM(
                "pending",
                "visible",
                "hidden",
                name="moderation_status",
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "request_id",
            "contributor_id",
            name="uq_responses_request_contributor",
        ),
        sa.CheckConstraint("length(trim(answer)) > 0", name="answer_not_blank"),
        sa.CheckConstraint("length(answer) <= 5000", name="answer_max_length"),
    )
    op.create_index(
        "ix_responses_contributor_id", "responses", ["contributor_id"]
    )
    op.add_column(
        "distributed_transactions",
        sa.Column("response_id", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    """Remove responses while preserving the shared moderation enum."""
    op.drop_column("distributed_transactions", "response_id")
    op.drop_index("ix_responses_contributor_id", table_name="responses")
    op.drop_table("responses")
