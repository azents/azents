"""make chat write requests session owned

Revision ID: 507bf6d9321d
Revises: c19064bb1bd4
Create Date: 2026-06-25 17:46:49.677196

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "507bf6d9321d"
down_revision: str | Sequence[str] | None = "c19064bb1bd4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _drop_fk_by_column(table_name: str, column_name: str) -> None:
    """Drop FK constraint for a constrained column."""
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
    """Move REST write idempotency ownership to AgentSession."""
    op.drop_constraint(
        "uq_chat_write_requests_runtime_user_client_request",
        "chat_write_requests",
        type_="unique",
    )
    _drop_fk_by_column("chat_write_requests", "agent_runtime_id")
    op.create_unique_constraint(
        "uq_chat_write_requests_session_user_client_request",
        "chat_write_requests",
        ["session_id", "user_id", "client_request_id"],
    )
    op.drop_column("chat_write_requests", "agent_runtime_id")


def downgrade() -> None:
    """Restore legacy runtime-owned REST write idempotency ownership."""
    op.add_column(
        "chat_write_requests",
        sa.Column("agent_runtime_id", sa.String(length=32), nullable=True),
    )
    op.execute(
        """
        UPDATE chat_write_requests AS cwr
        SET agent_runtime_id = ar.id
        FROM agent_sessions AS s
        JOIN agent_runtimes AS ar ON ar.agent_id = s.agent_id
        WHERE cwr.session_id = s.id
        """
    )
    op.execute("DELETE FROM chat_write_requests WHERE agent_runtime_id IS NULL")
    op.execute(
        """
        DELETE FROM chat_write_requests AS cwr
        WHERE cwr.id NOT IN (
            SELECT DISTINCT ON (agent_runtime_id, user_id, client_request_id) id
            FROM chat_write_requests
            ORDER BY agent_runtime_id, user_id, client_request_id, created_at, id
        )
        """
    )
    op.drop_constraint(
        "uq_chat_write_requests_session_user_client_request",
        "chat_write_requests",
        type_="unique",
    )
    op.alter_column("chat_write_requests", "agent_runtime_id", nullable=False)
    op.create_foreign_key(
        "chat_write_requests_agent_runtime_id_fkey",
        "chat_write_requests",
        "agent_runtimes",
        ["agent_runtime_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_chat_write_requests_runtime_user_client_request",
        "chat_write_requests",
        ["agent_runtime_id", "user_id", "client_request_id"],
    )
