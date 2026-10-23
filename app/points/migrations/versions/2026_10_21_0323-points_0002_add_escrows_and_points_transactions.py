"""Add escrow reservations and the points ledger.

Revision ID: points_0002
Revises: points_0001
Create Date: 2026-10-21 03:23:06.872491
"""

import sqlalchemy as sa
from alembic import op

revision = "points_0002"
down_revision = "points_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create escrows and ledger entries with local foreign keys."""
    op.create_table(
        "escrows",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.Integer(), nullable=False),
        sa.Column("requester_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Integer(), server_default="5", nullable=False),
        sa.Column(
            "status",
            sa.Enum("held", "released", "refunded", name="escrow_status"),
            server_default="held",
            nullable=False,
        ),
        sa.Column("recipient_id", sa.Integer(), nullable=True),
        sa.Column("awarded_response_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "amount = 5", name=op.f("ck_escrows_amount_fixed_five")
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id"],
            ["wallets.user_id"],
            name=op.f("fk_escrows_recipient_id_wallets"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requester_id"],
            ["wallets.user_id"],
            name=op.f("fk_escrows_requester_id_wallets"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_escrows")),
        sa.UniqueConstraint("request_id", name=op.f("uq_escrows_request_id")),
    )
    op.create_index(
        op.f("ix_escrows_requester_id"),
        "escrows",
        ["requester_id"],
        unique=False,
    )
    op.create_table(
        "points_transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("operation_id", sa.UUID(), nullable=False),
        sa.Column("distributed_transaction_id", sa.UUID(), nullable=True),
        sa.Column("escrow_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "type",
            sa.Enum(
                "opening_grant",
                "hold",
                "reward",
                "refund",
                name="points_transaction_type",
            ),
            nullable=False,
        ),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "amount > 0", name=op.f("ck_points_transactions_amount_positive")
        ),
        sa.ForeignKeyConstraint(
            ["escrow_id"],
            ["escrows.id"],
            name=op.f("fk_points_transactions_escrow_id_escrows"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["wallets.user_id"],
            name=op.f("fk_points_transactions_user_id_wallets"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_points_transactions")),
        sa.UniqueConstraint(
            "operation_id", name=op.f("uq_points_transactions_operation_id")
        ),
    )
    op.create_index(
        op.f("ix_points_transactions_distributed_transaction_id"),
        "points_transactions",
        ["distributed_transaction_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_points_transactions_escrow_id"),
        "points_transactions",
        ["escrow_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_points_transactions_user_id"),
        "points_transactions",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove the ledger, escrows, and their PostgreSQL enum types."""
    op.drop_index(
        op.f("ix_points_transactions_user_id"), table_name="points_transactions"
    )
    op.drop_index(
        op.f("ix_points_transactions_escrow_id"),
        table_name="points_transactions",
    )
    op.drop_index(
        op.f("ix_points_transactions_distributed_transaction_id"),
        table_name="points_transactions",
    )
    op.drop_table("points_transactions")
    op.drop_index(op.f("ix_escrows_requester_id"), table_name="escrows")
    op.drop_table("escrows")
    sa.Enum(name="points_transaction_type").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="escrow_status").drop(op.get_bind(), checkfirst=True)
