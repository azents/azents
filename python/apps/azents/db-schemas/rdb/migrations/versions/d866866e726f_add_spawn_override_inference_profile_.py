"""add spawn override inference profile source

Revision ID: d866866e726f
Revises: 3865d27c9b0a
Create Date: 2026-07-11 11:51:20.922427

"""

from typing import Sequence

from alembic import op

revision: str = "d866866e726f"
down_revision: str | Sequence[str] | None = "3865d27c9b0a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add spawn_override to the inference profile source ENUM."""
    op.execute(
        "ALTER TYPE inference_profile_source ADD VALUE IF NOT EXISTS 'spawn_override'"
    )


def downgrade() -> None:
    """No-op because values cannot be removed from PostgreSQL ENUMs."""
