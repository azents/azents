"""Bind OAuth device sessions to existing integrations for reauthentication."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "841e7188d527"
down_revision: str | Sequence[str] | None = "a32efa82fd63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add nullable targets for new and existing device sessions."""
    for table in ("chatgpt_oauth_sessions", "xai_oauth_sessions"):
        op.add_column(table, sa.Column("integration_id", sa.String(32), nullable=True))
        op.create_foreign_key(
            f"fk_{table}_integration_id",
            table,
            "llm_provider_integrations",
            ["integration_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    """Remove reauthentication targets."""
    for table in ("chatgpt_oauth_sessions", "xai_oauth_sessions"):
        op.drop_constraint(f"fk_{table}_integration_id", table, type_="foreignkey")
        op.drop_column(table, "integration_id")
