"""add team session admission provenance

Revision ID: 1ce295000a20
Revises: 995d915ed6d6
Create Date: 2026-07-24 07:00:56.953078

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "1ce295000a20"
down_revision: str | Sequence[str] | None = "995d915ed6d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _drop_fk_by_column(table_name: str, column_name: str) -> None:
    """Drop the foreign key that constrains one column."""
    inspector = sa.inspect(op.get_bind())
    for foreign_key in inspector.get_foreign_keys(table_name):
        if foreign_key["constrained_columns"] == [column_name]:
            name = foreign_key["name"]
            if name is None:
                break
            op.drop_constraint(name, table_name, type_="foreignkey")
            return
    raise RuntimeError(f"Foreign key for {table_name}.{column_name} not found")


def upgrade() -> None:
    """Add durable requester audit and Human sender provenance."""
    op.execute("ALTER TYPE chat_write_request_type ADD VALUE IF NOT EXISTS 'message'")
    op.execute(
        "ALTER TYPE chat_write_request_type ADD VALUE IF NOT EXISTS 'turn_action'"
    )

    _drop_fk_by_column("input_buffers", "actor_user_id")
    op.alter_column(
        "input_buffers",
        "actor_user_id",
        new_column_name="sender_user_id",
    )
    op.create_foreign_key(
        "fk_input_buffers_sender_user_id_users",
        "input_buffers",
        "users",
        ["sender_user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_input_buffers_sender_user_kind",
        "input_buffers",
        "sender_user_id IS NULL OR kind IN ('user_message', 'action_message')",
    )

    op.drop_constraint(
        "uq_chat_write_requests_session_user_client_request",
        "chat_write_requests",
        type_="unique",
    )
    _drop_fk_by_column("chat_write_requests", "user_id")
    op.alter_column(
        "chat_write_requests",
        "user_id",
        new_column_name="requester_user_id",
    )
    op.create_foreign_key(
        "fk_chat_write_requests_requester_user_id_users",
        "chat_write_requests",
        "users",
        ["requester_user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.add_column(
        "chat_write_requests",
        sa.Column("creation_agent_id", sa.String(length=32), nullable=True),
    )
    op.create_foreign_key(
        "fk_chat_write_requests_creation_agent_id_agents",
        "chat_write_requests",
        "agents",
        ["creation_agent_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_chat_write_requests_session_requester_client_request",
        "chat_write_requests",
        ["session_id", "requester_user_id", "client_request_id"],
    )
    op.create_index(
        "uq_chat_write_requests_creation_agent_requester_client",
        "chat_write_requests",
        ["creation_agent_id", "requester_user_id", "client_request_id"],
        unique=True,
        postgresql_where=sa.text("creation_agent_id IS NOT NULL"),
    )

    _drop_fk_by_column("agent_sessions", "pending_command_user_id")
    op.alter_column(
        "agent_sessions",
        "pending_command_user_id",
        new_column_name="pending_command_requester_user_id",
    )
    op.create_foreign_key(
        "fk_agent_sessions_pending_command_requester_user_id_users",
        "agent_sessions",
        "users",
        ["pending_command_requester_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    _drop_fk_by_column("agent_sessions", "stop_requested_by")
    op.alter_column(
        "agent_sessions",
        "stop_requested_by",
        new_column_name="stop_requester_user_id",
    )
    op.create_foreign_key(
        "fk_agent_sessions_stop_requester_user_id_users",
        "agent_sessions",
        "users",
        ["stop_requester_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "action_executions",
        sa.Column("sender_user_id", sa.String(length=32), nullable=True),
    )
    op.create_foreign_key(
        "fk_action_executions_sender_user_id_users",
        "action_executions",
        "users",
        ["sender_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.execute(
        """
        UPDATE events
        SET payload = jsonb_set(payload, '{sender_user_id}', 'null'::jsonb, true)
        WHERE kind IN (
            'user_message',
            'goal_continuation',
            'goal_updated',
            'action_message'
        )
          AND NOT payload ? 'sender_user_id'
        """
    )


def downgrade() -> None:
    """Reject rollback across the coordinated forward-only cutover."""
    raise RuntimeError(
        "1ce295000a20 is an irreversible forward-only migration because PostgreSQL "
        "enum expansion and durable provenance cutover require restoring the "
        "pre-cutover backup"
    )
