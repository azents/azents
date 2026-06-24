"""drop input buffer runtime id

Revision ID: 03710bae417a
Revises: 2ce5426562d5
Create Date: 2026-06-19 23:09:50.290809

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "03710bae417a"
down_revision: str | Sequence[str] | None = "2ce5426562d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Make InputBuffer ownership session-bound."""
    op.drop_index(
        "uq_input_buffers_runtime_kind_idempotency",
        table_name="input_buffers",
    )
    op.drop_index("ix_input_buffers_agent_runtime_id", table_name="input_buffers")
    op.drop_constraint(
        "fk_input_buffers_agent_runtime_id_agent_runtimes",
        "input_buffers",
        type_="foreignkey",
    )
    op.drop_column("input_buffers", "agent_runtime_id")
    op.create_index(
        "uq_input_buffers_session_kind_idempotency",
        "input_buffers",
        ["session_id", "kind", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    """Restore the previous runtime-scoped InputBuffer idempotency key."""
    op.drop_index(
        "uq_input_buffers_session_kind_idempotency",
        table_name="input_buffers",
    )
    op.add_column(
        "input_buffers",
        sa.Column("agent_runtime_id", sa.String(length=32), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE input_buffers
            SET agent_runtime_id = agent_sessions.agent_runtime_id
            FROM agent_sessions
            WHERE input_buffers.session_id = agent_sessions.id
            """
        )
    )
    op.alter_column("input_buffers", "agent_runtime_id", nullable=False)
    op.create_foreign_key(
        "fk_input_buffers_agent_runtime_id_agent_runtimes",
        "input_buffers",
        "agent_runtimes",
        ["agent_runtime_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_input_buffers_agent_runtime_id",
        "input_buffers",
        ["agent_runtime_id"],
    )
    op.create_index(
        "uq_input_buffers_runtime_kind_idempotency",
        "input_buffers",
        ["agent_runtime_id", "kind", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
