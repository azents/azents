"""Add durable AgentRun parent result delivery state."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a4d69bcc02e2"
down_revision: str | Sequence[str] | None = "b96607c4c3db"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PARENT_RESULT_DELIVERY_STATE = postgresql.ENUM(
    "suppressed",
    "enqueued",
    name="agent_run_parent_result_delivery_state",
    create_type=False,
)
_TERMINAL_STATUSES = (
    "completed",
    "failed",
    "stopped",
    "interrupted",
    "cancelled",
)


def upgrade() -> None:
    """Add delivery markers and suppress historical subagent results."""
    bind = op.get_bind()
    postgresql.ENUM(
        "suppressed",
        "enqueued",
        name="agent_run_parent_result_delivery_state",
    ).create(bind, checkfirst=True)
    op.add_column(
        "agent_runs",
        sa.Column(
            "parent_result_delivery_state",
            _PARENT_RESULT_DELIVERY_STATE,
            nullable=True,
        ),
    )
    op.add_column(
        "agent_runs",
        sa.Column(
            "parent_result_input_buffer_id",
            sa.String(length=32),
            nullable=True,
        ),
    )
    op.add_column(
        "agent_runs",
        sa.Column(
            "parent_result_enqueued_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    terminal_statuses = ", ".join(f"'{status}'" for status in _TERMINAL_STATUSES)
    op.execute(
        sa.text(
            f"""
            UPDATE agent_runs AS run
            SET parent_result_delivery_state =
                'suppressed'::agent_run_parent_result_delivery_state
            FROM session_agents AS session_agent
            WHERE session_agent.agent_session_id = run.session_id
              AND session_agent.kind = 'subagent'
              AND run.status IN ({terminal_statuses})
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            WITH latest_terminal_run AS (
                SELECT DISTINCT ON (run.session_id)
                    run.session_id,
                    run.run_index,
                    run.terminal_result_event_id
                FROM agent_runs AS run
                JOIN session_agents AS session_agent
                  ON session_agent.agent_session_id = run.session_id
                WHERE session_agent.kind = 'subagent'
                  AND run.status IN ({terminal_statuses})
                ORDER BY run.session_id, run.run_index DESC
            )
            UPDATE session_agents AS session_agent
            SET parent_observed_run_index = latest.run_index,
                parent_observed_event_id = latest.terminal_result_event_id
            FROM latest_terminal_run AS latest
            WHERE session_agent.agent_session_id = latest.session_id
              AND (
                  session_agent.parent_observed_run_index IS NULL
                  OR session_agent.parent_observed_run_index < latest.run_index
              )
            """
        )
    )


def downgrade() -> None:
    """Remove durable parent result delivery fields."""
    op.drop_column("agent_runs", "parent_result_enqueued_at")
    op.drop_column("agent_runs", "parent_result_input_buffer_id")
    op.drop_column("agent_runs", "parent_result_delivery_state")
    postgresql.ENUM(name="agent_run_parent_result_delivery_state").drop(
        op.get_bind(),
        checkfirst=True,
    )
