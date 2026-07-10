"""Add the xAI API key provider enum value."""

from typing import Sequence

from alembic import op

revision: str = "25a661df4ff6"
down_revision: str | Sequence[str] | None = "9fa56656fede"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the stable xAI API key provider."""
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE llm_provider ADD VALUE IF NOT EXISTS 'xai'")


def downgrade() -> None:
    """Keep the PostgreSQL enum value because enum values are not removable safely."""
