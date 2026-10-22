"""Record one accepted response and completion time on each request.

Revision ID: add_response_acceptance
Revises: add_responses
"""

import sqlalchemy as sa
from alembic import op

revision = "add_response_acceptance"
down_revision = "add_responses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add nullable acceptance fields without changing existing requests."""
    op.add_column(
        "requests",
        sa.Column("accepted_response_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "requests",
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_requests_accepted_response_id_responses",
        "requests",
        "responses",
        ["accepted_response_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "accepted_response_completed",
        "requests",
        "(accepted_response_id IS NULL AND accepted_at IS NULL) OR "
        "(accepted_response_id IS NOT NULL AND accepted_at IS NOT NULL "
        "AND status = 'completed')",
    )


def downgrade() -> None:
    """Remove acceptance fields and their constraints."""
    op.drop_constraint(
        op.f("ck_requests_accepted_response_completed"),
        "requests",
        type_="check",
    )
    op.drop_constraint(
        "fk_requests_accepted_response_id_responses",
        "requests",
        type_="foreignkey",
    )
    op.drop_column("requests", "accepted_at")
    op.drop_column("requests", "accepted_response_id")
