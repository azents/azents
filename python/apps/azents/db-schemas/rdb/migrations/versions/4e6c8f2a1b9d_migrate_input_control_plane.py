"""migrate input control plane

Revision ID: 4e6c8f2a1b9d
Revises: d8d7847adaf3
Create Date: 2026-06-15 10:30:00.000000

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "4e6c8f2a1b9d"
down_revision: str | Sequence[str] | None = "d8d7847adaf3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


INPUT_BUFFER_KIND_VALUES = (
    "user_message",
    "edited_user_message",
    "background_completion",
)

EVENT_KIND_VALUES = (
    "user_message",
    "background_completion",
    "assistant_message",
    "reasoning",
    "client_tool_call",
    "client_tool_result",
    "provider_tool_call",
    "provider_tool_result",
    "turn_marker",
    "run_marker",
    "compaction_marker",
    "compaction_summary",
    "subagent_start",
    "subagent_end",
    "system_reminder",
    "system_error",
    "unknown_adapter_output",
)

PREVIOUS_EVENT_KIND_VALUES = tuple(
    value for value in EVENT_KIND_VALUES if value != "background_completion"
)


def upgrade() -> None:
    """Switch the input buffer/control-plane schema to the clean-state baseline."""
    bind = op.get_bind()

    postgresql.ENUM(
        *INPUT_BUFFER_KIND_VALUES,
        name="input_buffer_kind",
    ).create(bind, checkfirst=True)
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
              IF EXISTS (
                SELECT 1 FROM pg_type WHERE typname = 'canonical_event_kind'
              ) AND NOT EXISTS (
                SELECT 1 FROM pg_type WHERE typname = 'event_kind'
              ) THEN
                ALTER TYPE canonical_event_kind RENAME TO event_kind;
              END IF;
            END
            $$;
            """
        )
    )
    op.execute(
        sa.text("ALTER TYPE event_kind ADD VALUE IF NOT EXISTS 'background_completion'")
    )

    op.execute(sa.text("DELETE FROM input_buffers"))
    op.drop_constraint(
        "uq_input_buffers_runtime_user_client_request",
        "input_buffers",
        type_="unique",
    )
    op.drop_constraint(
        "fk_input_buffers_user_id_users",
        "input_buffers",
        type_="foreignkey",
    )
    op.drop_column("input_buffers", "headers")
    op.drop_column("input_buffers", "user_id")
    op.drop_column("input_buffers", "client_request_id")
    op.add_column(
        "input_buffers",
        sa.Column(
            "kind",
            postgresql.ENUM(name="input_buffer_kind", create_type=False),
            server_default="user_message",
            nullable=False,
        ),
    )
    op.alter_column("input_buffers", "kind", server_default=None)
    op.add_column(
        "input_buffers",
        sa.Column("actor_user_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "input_buffers",
        sa.Column("idempotency_key", sa.String(length=120), nullable=True),
    )
    op.create_foreign_key(
        "fk_input_buffers_actor_user_id_users",
        "input_buffers",
        "users",
        ["actor_user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_input_buffers_kind", "input_buffers", ["kind"])
    op.create_index(
        "uq_input_buffers_runtime_kind_idempotency",
        "input_buffers",
        ["agent_runtime_id", "kind", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.add_column(
        "agent_runtimes",
        sa.Column("pending_command_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "agent_runtimes",
        sa.Column("pending_command_name", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "agent_runtimes",
        sa.Column(
            "pending_command_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "agent_runtimes",
        sa.Column("pending_command_user_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "agent_runtimes",
        sa.Column(
            "pending_command_created_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "agent_runtimes",
        sa.Column("stop_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "agent_runtimes",
        sa.Column("stop_requested_by", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "agent_runtimes",
        sa.Column("stop_request_id", sa.String(length=32), nullable=True),
    )
    op.create_foreign_key(
        "fk_agent_runtimes_pending_command_user_id_users",
        "agent_runtimes",
        "users",
        ["pending_command_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_agent_runtimes_stop_requested_by_users",
        "agent_runtimes",
        "users",
        ["stop_requested_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_agent_runtimes_pending_command",
        "agent_runtimes",
        ["pending_command_created_at"],
        postgresql_where=sa.text("pending_command_id IS NOT NULL"),
    )
    op.create_index(
        "ix_agent_runtimes_stop_requested_at",
        "agent_runtimes",
        ["stop_requested_at"],
        postgresql_where=sa.text("stop_requested_at IS NOT NULL"),
    )


def downgrade() -> None:
    """Revert the input buffer/control-plane schema to the previous carrier form."""
    bind = op.get_bind()

    op.drop_index("ix_agent_runtimes_stop_requested_at", table_name="agent_runtimes")
    op.drop_index("ix_agent_runtimes_pending_command", table_name="agent_runtimes")
    op.drop_constraint(
        "fk_agent_runtimes_stop_requested_by_users",
        "agent_runtimes",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_agent_runtimes_pending_command_user_id_users",
        "agent_runtimes",
        type_="foreignkey",
    )
    op.drop_column("agent_runtimes", "stop_request_id")
    op.drop_column("agent_runtimes", "stop_requested_by")
    op.drop_column("agent_runtimes", "stop_requested_at")
    op.drop_column("agent_runtimes", "pending_command_created_at")
    op.drop_column("agent_runtimes", "pending_command_user_id")
    op.drop_column("agent_runtimes", "pending_command_payload")
    op.drop_column("agent_runtimes", "pending_command_name")
    op.drop_column("agent_runtimes", "pending_command_id")

    op.execute(sa.text("DELETE FROM input_buffers"))
    op.drop_index(
        "uq_input_buffers_runtime_kind_idempotency",
        table_name="input_buffers",
    )
    op.drop_index("ix_input_buffers_kind", table_name="input_buffers")
    op.drop_constraint(
        "fk_input_buffers_actor_user_id_users",
        "input_buffers",
        type_="foreignkey",
    )
    op.drop_column("input_buffers", "idempotency_key")
    op.drop_column("input_buffers", "actor_user_id")
    op.drop_column("input_buffers", "kind")
    op.add_column(
        "input_buffers",
        sa.Column("client_request_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "input_buffers",
        sa.Column("user_id", sa.String(length=32), nullable=False),
    )
    op.add_column(
        "input_buffers",
        sa.Column("headers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    )
    op.create_foreign_key(
        "fk_input_buffers_user_id_users",
        "input_buffers",
        "users",
        ["user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_input_buffers_runtime_user_client_request",
        "input_buffers",
        ["agent_runtime_id", "user_id", "client_request_id"],
    )

    postgresql.ENUM(name="input_buffer_kind").drop(bind, checkfirst=True)
    op.execute(sa.text("DELETE FROM events WHERE kind = 'background_completion'"))
    op.execute(
        sa.text("ALTER TABLE events ALTER COLUMN kind TYPE text USING kind::text")
    )
    postgresql.ENUM(name="event_kind").drop(bind)
    postgresql.ENUM(
        *PREVIOUS_EVENT_KIND_VALUES,
        name="canonical_event_kind",
    ).create(bind)
    op.execute(
        sa.text(
            "ALTER TABLE events ALTER COLUMN kind TYPE canonical_event_kind "
            "USING kind::canonical_event_kind"
        )
    )
