"""Count committed requests and responses hidden by moderation.

Revision ID: add_user_violations
Revises: add_expiry_refunds
"""

import sqlalchemy as sa
from alembic import op

revision = "add_user_violations"
down_revision = "add_expiry_refunds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Initialize existing users at zero and prevent negative counts."""
    op.add_column(
        "users",
        sa.Column(
            "violations", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.create_check_constraint(
        "violations_nonnegative", "users", "violations >= 0"
    )


def downgrade() -> None:
    """Remove the counter and its constraint."""
    op.drop_constraint(
        op.f("ck_users_violations_nonnegative"), "users", type_="check"
    )
    op.drop_column("users", "violations")
