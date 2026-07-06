"""remove subagent surfaces

Revision ID: ad8bde4eb6a8
Revises: 31dc0ec1a60f
Create Date: 2026-07-06 10:57:25.510350

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ad8bde4eb6a8"
down_revision: str | Sequence[str] | None = "31dc0ec1a60f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVENT_KIND_VALUES = (
    "user_message",
    "background_completion",
    "goal_continuation",
    "goal_updated",
    "action_message",
    "action_execution_result",
    "skill_loaded",
    "goal_briefing",
    "assistant_message",
    "reasoning",
    "client_tool_call",
    "client_tool_result",
    "provider_tool_call",
    "provider_tool_result",
    "turn_marker",
    "run_marker",
    "interrupted",
    "compaction_marker",
    "compaction_summary",
    "system_reminder",
    "system_error",
    "unknown_adapter_output",
)
_EVENT_KIND_VALUES_WITH_SUBAGENT = (
    *_EVENT_KIND_VALUES[:18],
    "subagent_start",
    "subagent_end",
    *_EVENT_KIND_VALUES[18:],
)


def _replace_enum_type(
    type_name: str,
    table_column_pairs: Sequence[tuple[str, str]],
    values: Sequence[str],
) -> None:
    quoted_values = ", ".join(f"'{value}'" for value in values)
    temporary_type_name = f"{type_name}_new"
    op.execute(sa.text(f"CREATE TYPE {temporary_type_name} AS ENUM ({quoted_values})"))
    for table_name, column_name in table_column_pairs:
        op.execute(
            sa.text(
                f"ALTER TABLE {table_name} ALTER COLUMN {column_name} "
                f"TYPE {temporary_type_name} "
                f"USING {column_name}::text::{temporary_type_name}"
            )
        )
    op.execute(sa.text(f"DROP TYPE {type_name}"))
    op.execute(sa.text(f"ALTER TYPE {temporary_type_name} RENAME TO {type_name}"))


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_table("agent_subagents")
    op.drop_column("agents", "toolkit_inherit_mode")
    op.drop_column("agents", "role")
    op.execute(sa.text("DROP TYPE agent_role"))
    _replace_enum_type("event_kind", (("events", "kind"),), _EVENT_KIND_VALUES)


def downgrade() -> None:
    """Downgrade schema."""
    _replace_enum_type(
        "event_kind",
        (("events", "kind"),),
        _EVENT_KIND_VALUES_WITH_SUBAGENT,
    )
    op.execute(sa.text("CREATE TYPE agent_role AS ENUM ('agent', 'subagent')"))
    op.add_column(
        "agents",
        sa.Column(
            "role",
            sa.Enum("agent", "subagent", name="agent_role", create_type=False),
            nullable=False,
            server_default="agent",
        ),
    )
    op.alter_column("agents", "role", server_default=None)
    op.add_column(
        "agents",
        sa.Column(
            "toolkit_inherit_mode",
            sa.String(length=10),
            nullable=False,
            server_default="all",
        ),
    )
    op.create_check_constraint(
        "ck_agents_inherit_mode",
        "agents",
        "toolkit_inherit_mode IN ('none', 'all')",
    )
    op.alter_column("agents", "toolkit_inherit_mode", server_default=None)
    op.create_table(
        "agent_subagents",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column("subagent_id", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subagent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_id",
            "subagent_id",
            name="uq_agent_subagents_agent_subagent",
        ),
        sa.CheckConstraint(
            "agent_id != subagent_id",
            name="ck_agent_subagents_no_self_ref",
        ),
    )
    op.create_index("ix_agent_subagents_agent_id", "agent_subagents", ["agent_id"])
    op.create_index(
        "ix_agent_subagents_subagent_id",
        "agent_subagents",
        ["subagent_id"],
    )
