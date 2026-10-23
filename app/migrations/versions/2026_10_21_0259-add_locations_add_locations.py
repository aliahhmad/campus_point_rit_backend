"""Add predefined campus locations.

Revision ID: add_locations
Revises: add_last_used_at
Create Date: 2026-10-21 02:59:25.664035

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "add_locations"
down_revision = "add_last_used_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create locations with unique names and building codes."""
    op.create_table(
        "locations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("building_code", sa.String(length=20), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_locations")),
        sa.UniqueConstraint(
            "building_code", name=op.f("uq_locations_building_code")
        ),
        sa.UniqueConstraint("name", name=op.f("uq_locations_name")),
    )


def downgrade() -> None:
    """Remove the locations table."""
    op.drop_table("locations")
