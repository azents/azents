"""add slug and prompt to toolkits, change agent_toolkits constraint

Revision ID: cd45c5a32e37
Revises: f4f60bbfab05
Create Date: 2026-02-27 12:21:03.489451

"""

# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "cd45c5a32e37"
down_revision: str | Sequence[str] | None = "f4f60bbfab05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add slug and prompt columns to toolkits and change agent_toolkits constraints."""
    # 1. Add slug and prompt columns to the toolkits table
    op.add_column(
        "toolkits",
        sa.Column("slug", sa.String(100), nullable=False, server_default=""),
    )
    op.add_column(
        "toolkits",
        sa.Column("prompt", sa.Text, nullable=True),
    )

    # 2. Existing data: slug = tool_slug
    op.execute("UPDATE toolkits SET slug = tool_slug WHERE slug = ''")

    # 3. Create workspace_id + slug unique index
    op.create_unique_constraint(
        "uq_toolkits_workspace_slug", "toolkits", ["workspace_id", "slug"]
    )

    # 4. agent_toolkits: drop existing (agent_id, tool_slug) constraint
    #    and add the new (agent_id, toolkit_id) constraint
    op.drop_constraint(
        "uq_agent_toolkits_agent_tool_slug", "agent_toolkits", type_="unique"
    )
    op.create_unique_constraint(
        "uq_agent_toolkits_agent_toolkit",
        "agent_toolkits",
        ["agent_id", "toolkit_id"],
    )


def downgrade() -> None:
    """Remove slug and prompt columns and restore agent_toolkits constraints."""
    # Restore agent_toolkits constraints
    op.drop_constraint(
        "uq_agent_toolkits_agent_toolkit", "agent_toolkits", type_="unique"
    )
    op.create_unique_constraint(
        "uq_agent_toolkits_agent_tool_slug",
        "agent_toolkits",
        ["agent_id", "tool_slug"],
    )

    # Remove toolkits columns and indexes
    op.drop_constraint("uq_toolkits_workspace_slug", "toolkits", type_="unique")
    op.drop_column("toolkits", "prompt")
    op.drop_column("toolkits", "slug")
