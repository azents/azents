"""add agent role and subagent tables

Revision ID: 8c5ae715eef4
Revises: a1b2c3d4e5f6
Create Date: 2026-03-06 06:46:37.742091

"""

# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "8c5ae715eef4"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the agent_role enum, agents.role column, agent_subagents table,
    and conversation_sessions.parent_session_id column.
    """
    # Create agent_role ENUM
    agent_role_enum = postgresql.ENUM(
        "agent", "subagent", name="agent_role", create_type=False
    )
    agent_role_enum.create(op.get_bind(), checkfirst=True)

    # Add role column to the agents table
    op.add_column(
        "agents",
        sa.Column(
            "role",
            postgresql.ENUM("agent", "subagent", name="agent_role", create_type=False),
            nullable=False,
            server_default="agent",
        ),
    )

    # Create the agent_subagents junction table
    op.create_table(
        "agent_subagents",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "agent_id",
            sa.String(32),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "subagent_id",
            sa.String(32),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("description", sa.Text, nullable=False),
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
        sa.UniqueConstraint(
            "agent_id", "subagent_id", name="uq_agent_subagents_agent_subagent"
        ),
        sa.CheckConstraint(
            "agent_id != subagent_id", name="ck_agent_subagents_no_self_ref"
        ),
    )
    op.create_index("ix_agent_subagents_agent_id", "agent_subagents", ["agent_id"])
    op.create_index(
        "ix_agent_subagents_subagent_id", "agent_subagents", ["subagent_id"]
    )

    # Add parent_session_id column to the conversation_sessions table
    op.add_column(
        "conversation_sessions",
        sa.Column(
            "parent_session_id",
            sa.String(32),
            sa.ForeignKey("conversation_sessions.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_conversation_sessions_parent_session_id",
        "conversation_sessions",
        ["parent_session_id"],
    )


def downgrade() -> None:
    """Remove the added columns and tables."""
    op.drop_index(
        "ix_conversation_sessions_parent_session_id",
        table_name="conversation_sessions",
    )
    op.drop_column("conversation_sessions", "parent_session_id")

    op.drop_index("ix_agent_subagents_subagent_id", table_name="agent_subagents")
    op.drop_index("ix_agent_subagents_agent_id", table_name="agent_subagents")
    op.drop_table("agent_subagents")

    op.drop_column("agents", "role")

    postgresql.ENUM(name="agent_role").drop(op.get_bind(), checkfirst=True)
