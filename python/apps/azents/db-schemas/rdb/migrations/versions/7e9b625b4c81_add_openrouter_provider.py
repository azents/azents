"""Add the OpenRouter provider enum value."""

from typing import Sequence

from alembic import op

revision: str = "7e9b625b4c81"
down_revision: str | Sequence[str] | None = "e95f7e9143c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the OpenRouter API-key provider."""
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE llm_provider ADD VALUE IF NOT EXISTS 'openrouter'")


def downgrade() -> None:
    """Keep the PostgreSQL enum value because it cannot be removed safely."""
