"""add toolkit tables

Revision ID: f4f60bbfab05
Revises: abd59068d224
Create Date: 2026-02-25 01:23:16.123371

"""

# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f4f60bbfab05"
down_revision: str | Sequence[str] | None = "abd59068d224"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create toolkit-related tables."""
    # Create toolkit_scope_type ENUM
    toolkit_scope_type_enum = postgresql.ENUM(
        "team", "workspace", name="toolkit_scope_type", create_type=False
    )
    toolkit_scope_type_enum.create(op.get_bind(), checkfirst=True)

    # toolkits table
    op.create_table(
        "toolkits",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(32),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tool_slug", sa.String(100), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("config", postgresql.JSONB, nullable=False),
        sa.Column(
            "enabled", sa.Boolean, nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_toolkits_workspace_id", "toolkits", ["workspace_id"])

    # toolkit_scopes table
    op.create_table(
        "toolkit_scopes",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "toolkit_id",
            sa.String(32),
            sa.ForeignKey("toolkits.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "scope_type",
            postgresql.ENUM(
                "team", "workspace", name="toolkit_scope_type", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("scope_id", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "toolkit_id",
            "scope_type",
            "scope_id",
            name="uq_toolkit_scopes_toolkit_scope_id",
        ),
    )
    op.create_index("ix_toolkit_scopes_toolkit_id", "toolkit_scopes", ["toolkit_id"])

    # agent_toolkits table
    op.create_table(
        "agent_toolkits",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "agent_id",
            sa.String(32),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "toolkit_id",
            sa.String(32),
            sa.ForeignKey("toolkits.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tool_slug", sa.String(100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "agent_id",
            "tool_slug",
            name="uq_agent_toolkits_agent_tool_slug",
        ),
    )
    op.create_index("ix_agent_toolkits_agent_id", "agent_toolkits", ["agent_id"])


def downgrade() -> None:
    """Drop toolkit-related tables."""
    op.drop_index("ix_agent_toolkits_agent_id", table_name="agent_toolkits")
    op.drop_table("agent_toolkits")

    op.drop_index("ix_toolkit_scopes_toolkit_id", table_name="toolkit_scopes")
    op.drop_table("toolkit_scopes")

    op.drop_index("ix_toolkits_workspace_id", table_name="toolkits")
    op.drop_table("toolkits")

    postgresql.ENUM(name="toolkit_scope_type").drop(op.get_bind(), checkfirst=True)
