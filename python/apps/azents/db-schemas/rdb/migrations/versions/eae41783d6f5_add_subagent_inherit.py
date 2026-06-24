"""add subagent inherit fields

Revision ID: eae41783d6f5
Revises: fba56255d438
Create Date: 2026-04-24 00:00:00.000000

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "eae41783d6f5"
down_revision: str | Sequence[str] | None = "fba56255d438"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add agents.toolkit_inherit_mode column at agent row level, DP1 A, DP2 B
    #    - Default is 'all' opt-out, so new subagents inherit by default.
    #    - CHECK constraint fixes enum values to 'none' or 'all'.
    #    - Existing subagents opt out with 'none' below for compatibility.
    op.add_column(
        "agents",
        sa.Column(
            "toolkit_inherit_mode",
            sa.String(10),
            nullable=False,
            server_default="all",
        ),
    )
    op.create_check_constraint(
        "ck_agents_inherit_mode",
        "agents",
        "toolkit_inherit_mode IN ('none', 'all')",
    )
    # Existing subagents remain opted out for DP2 B compatibility
    op.execute(
        "UPDATE agents SET toolkit_inherit_mode = 'none' WHERE role = 'subagent'"
    )

    # 2. Allow NULL for agents.llm_provider_integration_id and llm_provider_model_id
    #    - subagents with role='subagent' keep NULL and inherit the parent model
    #      at runtime (DP5). role='agent' is guaranteed NOT NULL by CHECK.
    op.alter_column(
        "agents",
        "llm_provider_integration_id",
        existing_type=sa.String(32),
        nullable=True,
    )
    op.alter_column(
        "agents",
        "llm_provider_model_id",
        existing_type=sa.String(32),
        nullable=True,
    )

    # 3. Add model NOT NULL CHECK on agents, enforced only for role='agent'
    op.create_check_constraint(
        "ck_agents_model_not_null_when_role_agent",
        "agents",
        (
            "role = 'subagent' OR ("
            "llm_provider_model_id IS NOT NULL AND "
            "llm_provider_integration_id IS NOT NULL)"
        ),
    )


def downgrade() -> None:
    # Revert in reverse order.
    op.drop_constraint(
        "ck_agents_model_not_null_when_role_agent",
        "agents",
        type_="check",
    )
    op.alter_column(
        "agents",
        "llm_provider_model_id",
        existing_type=sa.String(32),
        nullable=False,
    )
    op.alter_column(
        "agents",
        "llm_provider_integration_id",
        existing_type=sa.String(32),
        nullable=False,
    )
    op.drop_constraint(
        "ck_agents_inherit_mode",
        "agents",
        type_="check",
    )
    op.drop_column("agents", "toolkit_inherit_mode")
