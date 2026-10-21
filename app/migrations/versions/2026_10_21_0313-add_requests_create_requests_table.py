"""Create campus requests with lifecycle and moderation state.

Revision ID: add_requests
Revises: add_locations
Create Date: 2026-10-21 03:13:47.377118

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "add_requests"
down_revision = "add_locations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create requests, constraints, and lookup indexes."""
    op.create_table(
        "requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("requester_id", sa.Integer(), nullable=False),
        sa.Column("location_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "reward_points", sa.Integer(), server_default="5", nullable=False
        ),
        sa.Column(
            "status",
            sa.Enum(
                "open",
                "under_review",
                "completed",
                "expired",
                name="request_status",
            ),
            server_default="open",
            nullable=False,
        ),
        sa.Column(
            "moderation_status",
            sa.Enum("pending", "visible", "hidden", name="moderation_status"),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP + INTERVAL '1 hour')"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name=op.f("ck_requests_expiry_after_creation"),
        ),
        sa.CheckConstraint(
            "length(btrim(description)) > 0",
            name=op.f("ck_requests_description_not_blank"),
        ),
        sa.CheckConstraint(
            "length(btrim(title)) > 0", name=op.f("ck_requests_title_not_blank")
        ),
        sa.CheckConstraint(
            "reward_points = 5", name=op.f("ck_requests_reward_fixed_five")
        ),
        sa.ForeignKeyConstraint(
            ["location_id"],
            ["locations.id"],
            name=op.f("fk_requests_location_id_locations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requester_id"],
            ["users.id"],
            name=op.f("fk_requests_requester_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_requests")),
    )
    op.create_index(
        op.f("ix_requests_expires_at"), "requests", ["expires_at"], unique=False
    )
    op.create_index(
        op.f("ix_requests_location_id"),
        "requests",
        ["location_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_requests_requester_id"),
        "requests",
        ["requester_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_requests_status"), "requests", ["status"], unique=False
    )


def downgrade() -> None:
    """Remove requests and their PostgreSQL enum types."""
    op.drop_index(op.f("ix_requests_status"), table_name="requests")
    op.drop_index(op.f("ix_requests_requester_id"), table_name="requests")
    op.drop_index(op.f("ix_requests_location_id"), table_name="requests")
    op.drop_index(op.f("ix_requests_expires_at"), table_name="requests")
    op.drop_table("requests")
    sa.Enum(name="moderation_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="request_status").drop(op.get_bind(), checkfirst=True)
