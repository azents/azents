"""add platform runtime system setting section

Revision ID: 48bc633b2746
Revises: 41c9f7fe1060
Create Date: 2026-07-22 23:41:41.708107

"""

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "48bc633b2746"
down_revision: str | Sequence[str] | None = "41c9f7fe1060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the Platform Runtime System Settings section."""
    op.execute(
        "ALTER TYPE system_setting_section ADD VALUE IF NOT EXISTS 'platform_runtime'"
    )


def downgrade() -> None:
    """Retain the PostgreSQL enum value on downgrade."""
    pass
