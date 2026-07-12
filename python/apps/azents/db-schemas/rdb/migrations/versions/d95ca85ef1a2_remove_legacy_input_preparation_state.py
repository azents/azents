"""remove legacy input preparation state

Revision ID: d95ca85ef1a2
Revises: 0487105be170
Create Date: 2026-07-11 20:34:19.742497

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d95ca85ef1a2"
down_revision: str | Sequence[str] | None = "0487105be170"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INPUT_BUFFER_KIND_VALUES = (
    "user_message",
    "goal_continuation",
    "action_message",
    "agent_message",
)
_INPUT_BUFFER_KIND_VALUES_WITH_LEGACY = (
    "user_message",
    "edited_user_message",
    "background_completion",
    "goal_continuation",
    "action_message",
    "agent_message",
)
_EVENT_KIND_VALUES = (
    "user_message",
    "goal_continuation",
    "goal_updated",
    "action_message",
    "agent_message",
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
_EVENT_KIND_VALUES_WITH_BACKGROUND = (
    "user_message",
    "background_completion",
    *_EVENT_KIND_VALUES[1:],
)
_ACTION_EXECUTION_STATUS_VALUES = (
    "pending",
    "running",
    "completed",
    "failed",
)
_ACTION_EXECUTION_STATUS_VALUES_WITH_LEGACY = (
    *_ACTION_EXECUTION_STATUS_VALUES,
    "failed_final",
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
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM input_buffers
                    WHERE kind::text = 'edited_user_message'
                ) THEN
                    RAISE EXCEPTION
                        'Cannot remove edited_user_message with pending input';
                END IF;
            END
            $$;
            """
        )
    )
    op.execute(
        sa.text("DELETE FROM input_buffers WHERE kind::text = 'background_completion'")
    )
    op.execute(sa.text("DELETE FROM events WHERE kind::text = 'background_completion'"))
    op.execute(
        sa.text(
            "UPDATE action_executions SET status = 'failed' "
            "WHERE status::text = 'failed_final'"
        )
    )
    _replace_enum_type(
        "input_buffer_kind",
        (("input_buffers", "kind"),),
        _INPUT_BUFFER_KIND_VALUES,
    )
    _replace_enum_type(
        "event_kind",
        (("events", "kind"),),
        _EVENT_KIND_VALUES,
    )
    op.alter_column("action_executions", "status", server_default=None)
    _replace_enum_type(
        "action_execution_status",
        (("action_executions", "status"),),
        _ACTION_EXECUTION_STATUS_VALUES,
    )
    op.alter_column("action_executions", "status", server_default="pending")
    op.drop_column("action_executions", "failed_final_at")
    op.drop_column("action_executions", "attempt")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(
        "action_executions",
        sa.Column("attempt", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "action_executions",
        sa.Column("failed_final_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.alter_column("action_executions", "status", server_default=None)
    _replace_enum_type(
        "action_execution_status",
        (("action_executions", "status"),),
        _ACTION_EXECUTION_STATUS_VALUES_WITH_LEGACY,
    )
    op.alter_column("action_executions", "status", server_default="pending")
    _replace_enum_type(
        "input_buffer_kind",
        (("input_buffers", "kind"),),
        _INPUT_BUFFER_KIND_VALUES_WITH_LEGACY,
    )
    _replace_enum_type(
        "event_kind",
        (("events", "kind"),),
        _EVENT_KIND_VALUES_WITH_BACKGROUND,
    )
