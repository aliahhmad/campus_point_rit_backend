"""Persist request submission ownership and idempotency details.

Revision ID: add_request_operations
Revises: add_requests
"""

import sqlalchemy as sa
from alembic import op

revision = "add_request_operations"
down_revision = "add_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create durable request intake records with globally unique keys."""
    op.create_table(
        "request_operations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("submitted_details", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_request_operations_owner_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_request_operations")),
        sa.UniqueConstraint(
            "idempotency_key",
            name=op.f("uq_request_operations_idempotency_key"),
        ),
    )
    op.create_index(
        op.f("ix_request_operations_owner_id"),
        "request_operations",
        ["owner_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove request intake records."""
    op.drop_index(
        op.f("ix_request_operations_owner_id"), table_name="request_operations"
    )
    op.drop_table("request_operations")
