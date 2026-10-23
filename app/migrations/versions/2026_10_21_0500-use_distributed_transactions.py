"""Use the notes' coordinator table without losing accepted submissions.

Revision ID: use_distributed_transactions
Revises: add_request_operations
"""

import sqlalchemy as sa
from alembic import op

revision = "use_distributed_transactions"
down_revision = "add_request_operations"
branch_labels = None
depends_on = None


def _rename_table(old: str, new: str) -> None:
    """Rename the table and the constraints created by the earlier revision."""
    op.rename_table(old, new)
    for prefix, suffix in (
        ("pk", ""),
        ("fk", "_owner_id_users"),
        ("uq", "_idempotency_key"),
    ):
        op.execute(
            f'ALTER TABLE "{new}" RENAME CONSTRAINT '
            f'"{prefix}_{old}{suffix}" TO "{prefix}_{new}{suffix}"'
        )
    op.execute(f'ALTER INDEX "ix_{old}_owner_id" RENAME TO "ix_{new}_owner_id"')


def upgrade() -> None:
    """Move existing submissions into distributed_transactions."""
    _rename_table("request_operations", "distributed_transactions")
    op.alter_column(
        "distributed_transactions",
        "submitted_details",
        new_column_name="payload",
    )
    op.add_column(
        "distributed_transactions",
        sa.Column(
            "operation",
            sa.String(40),
            server_default="create_request",
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Restore the previous submission table and column names."""
    op.drop_column("distributed_transactions", "operation")
    op.alter_column(
        "distributed_transactions",
        "payload",
        new_column_name="submitted_details",
    )
    _rename_table("distributed_transactions", "request_operations")
