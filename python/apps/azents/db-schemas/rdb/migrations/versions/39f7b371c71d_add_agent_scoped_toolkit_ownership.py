"""add agent scoped toolkit ownership

Revision ID: 39f7b371c71d
Revises: 4ab7015e39b5
Create Date: 2026-09-07 16:23:54.217603

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "39f7b371c71d"
down_revision: str | Sequence[str] | None = "4ab7015e39b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "toolkit_configs",
        sa.Column("owner_agent_id", sa.String(32), nullable=True),
    )
    op.create_foreign_key(
        "fk_toolkit_configs_owner_agent_id_agents",
        "toolkit_configs",
        "agents",
        ["owner_agent_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_toolkit_configs_owner_agent_id",
        "toolkit_configs",
        ["owner_agent_id"],
    )
    op.drop_constraint(
        "uq_toolkit_configs_workspace_slug",
        "toolkit_configs",
        type_="unique",
    )
    op.create_index(
        "uq_toolkit_configs_shared_workspace_slug",
        "toolkit_configs",
        ["workspace_id", "slug"],
        unique=True,
        postgresql_where=sa.text("owner_agent_id IS NULL"),
    )
    op.create_index(
        "uq_toolkit_configs_owner_agent_slug",
        "toolkit_configs",
        ["owner_agent_id", "slug"],
        unique=True,
        postgresql_where=sa.text("owner_agent_id IS NOT NULL"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    owner_count = op.get_bind().scalar(
        sa.text(
            """
            SELECT count(*)
            FROM toolkit_configs
            WHERE owner_agent_id IS NOT NULL
            """
        )
    )
    if owner_count:
        raise RuntimeError(
            "Agent-scoped Toolkit ownership downgrade is irreversible while "
            "Agent-owned Toolkits exist"
        )

    op.drop_index(
        "uq_toolkit_configs_owner_agent_slug",
        table_name="toolkit_configs",
    )
    op.drop_index(
        "uq_toolkit_configs_shared_workspace_slug",
        table_name="toolkit_configs",
    )
    op.create_unique_constraint(
        "uq_toolkit_configs_workspace_slug",
        "toolkit_configs",
        ["workspace_id", "slug"],
    )
    op.drop_index(
        "ix_toolkit_configs_owner_agent_id",
        table_name="toolkit_configs",
    )
    op.drop_constraint(
        "fk_toolkit_configs_owner_agent_id_agents",
        "toolkit_configs",
        type_="foreignkey",
    )
    op.drop_column("toolkit_configs", "owner_agent_id")
