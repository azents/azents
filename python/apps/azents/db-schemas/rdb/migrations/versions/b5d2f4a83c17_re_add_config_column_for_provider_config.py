"""re_add_config_column_for_provider_config

Revision ID: b5d2f4a83c17
Revises: a7c3e8f1b904
Create Date: 2026-02-21 18:00:00.000000

"""

# pyright: reportUnknownArgumentType=false

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b5d2f4a83c17"
down_revision: str | Sequence[str] | None = "a7c3e8f1b904"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Delete existing data and add a nullable JSONB config column."""
    op.execute("TRUNCATE TABLE llm_provider_integrations")
    op.add_column(
        "llm_provider_integrations",
        sa.Column("config", postgresql.JSONB, nullable=True),
    )


def downgrade() -> None:
    """Remove the config column."""
    op.drop_column("llm_provider_integrations", "config")
