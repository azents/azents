"""rename tool_slug to toolkit_type

Revision ID: bfbf8c91d809
Revises: ed756a005def
Create Date: 2026-03-11 14:04:39.787150

"""

from typing import Sequence

from alembic import op

revision: str = "bfbf8c91d809"
down_revision: str | Sequence[str] | None = "ed756a005def"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column("toolkits", "tool_slug", new_column_name="toolkit_type")
    op.alter_column("agent_toolkits", "tool_slug", new_column_name="toolkit_type")


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column("toolkits", "toolkit_type", new_column_name="tool_slug")
    op.alter_column("agent_toolkits", "toolkit_type", new_column_name="tool_slug")
