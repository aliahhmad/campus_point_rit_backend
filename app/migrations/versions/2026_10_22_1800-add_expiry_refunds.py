"""Add conflicted requests and one active or committed expiry per request.

Revision ID: add_expiry_refunds
Revises: add_response_acceptance
"""

import sqlalchemy as sa
from alembic import op

revision = "add_expiry_refunds"
down_revision = "add_response_acceptance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Allow conflicted status and prevent competing automatic refunds."""
    op.execute("ALTER TYPE request_status ADD VALUE IF NOT EXISTS 'conflicted'")
    op.create_index(
        "uq_distributed_transactions_expiry_request",
        "distributed_transactions",
        ["request_id"],
        unique=True,
        postgresql_where=sa.text(
            "operation = 'expire_request' AND "
            "(state != 'finished' OR decision = 'commit')"
        ),
    )


def downgrade() -> None:
    """Drop the guard while retaining the additive PostgreSQL enum label."""
    op.drop_index(
        "uq_distributed_transactions_expiry_request",
        table_name="distributed_transactions",
    )
