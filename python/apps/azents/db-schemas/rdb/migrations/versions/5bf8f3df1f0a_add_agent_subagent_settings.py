"""add agent subagent settings

Revision ID: 5bf8f3df1f0a
Revises: f79809732650
Create Date: 2026-07-09 09:40:21.467068

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "5bf8f3df1f0a"
down_revision: str | Sequence[str] | None = "9274b83c64d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULT_SUBAGENT_SETTINGS = '{"max_subagents": 3, "max_depth": 1}'


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "agents",
        sa.Column(
            "subagent_settings",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text(f"'{_DEFAULT_SUBAGENT_SETTINGS}'::jsonb"),
        ),
    )
    op.create_check_constraint(
        "ck_agents_subagent_settings_shape",
        "agents",
        "jsonb_typeof(subagent_settings) = 'object' "
        "AND (subagent_settings ? 'max_subagents') "
        "AND (subagent_settings ? 'max_depth') "
        "AND jsonb_typeof(subagent_settings->'max_subagents') = 'number' "
        "AND jsonb_typeof(subagent_settings->'max_depth') = 'number' "
        "AND (subagent_settings->>'max_subagents')::integer >= 0 "
        "AND (subagent_settings->>'max_depth')::integer >= 0",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "ck_agents_subagent_settings_shape",
        "agents",
        type_="check",
    )
    op.drop_column("agents", "subagent_settings")
