"""drop_config_from_llm_provider_integrations

Revision ID: a7c3e8f1b904
Revises: 754ff39d34e0
Create Date: 2026-02-21 16:00:00.000000

"""

# pyright: reportUnknownArgumentType=false

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a7c3e8f1b904"
down_revision: str | Sequence[str] | None = "754ff39d34e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove the config column from the llm_provider_integrations table."""
    op.execute("TRUNCATE TABLE llm_provider_integrations")
    op.drop_column("llm_provider_integrations", "config")


def downgrade() -> None:
    """Restore the config column to the llm_provider_integrations table."""
    op.add_column(
        "llm_provider_integrations",
        sa.Column("config", postgresql.JSONB, nullable=False, server_default="{}"),
    )
