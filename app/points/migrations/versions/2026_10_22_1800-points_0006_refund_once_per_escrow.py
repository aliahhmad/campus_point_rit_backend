"""Allow at most one refund ledger entry per escrow.

Revision ID: points_0006
Revises: points_0005
"""

import sqlalchemy as sa
from alembic import op

revision = "points_0006"
down_revision = "points_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Guard refunds independently of request holds and response rewards."""
    op.create_index(
        "uq_points_transactions_refund_escrow",
        "points_transactions",
        ["escrow_id"],
        unique=True,
        postgresql_where=sa.text("type = 'refund'"),
    )


def downgrade() -> None:
    """Remove the refund uniqueness guard."""
    op.drop_index(
        "uq_points_transactions_refund_escrow", table_name="points_transactions"
    )
