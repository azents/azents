"""add external binding wake pending activation

Revision ID: c51a9e8c6815
Revises: 6c42043df81f
Create Date: 2026-07-28 04:39:48.802118

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c51a9e8c6815"
down_revision: str | Sequence[str] | None = "6c42043df81f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the durable wake-claim activation phase."""
    op.execute(
        "ALTER TYPE external_channel_binding_activation_status "
        "ADD VALUE IF NOT EXISTS 'wake_pending'"
    )
    op.add_column(
        "external_channel_bindings",
        sa.Column(
            "activation_wake_claimed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Remove the wake claim timestamp; PostgreSQL enum values are retained."""
    op.drop_column("external_channel_bindings", "activation_wake_claimed_at")
