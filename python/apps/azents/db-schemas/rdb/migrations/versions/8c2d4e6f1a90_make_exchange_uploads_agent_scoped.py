"""make exchange uploads agent scoped

Revision ID: 8c2d4e6f1a90
Revises: 5b270932ce92
Create Date: 2026-05-31 06:10:00.000000

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8c2d4e6f1a90"
down_revision: str | Sequence[str] | None = "5b270932ce92"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Organize ExchangeFile by workspace/agent instead of session/runtime."""
    op.drop_index("ix_exchange_files_agent_runtime_id", table_name="exchange_files")
    op.drop_index("ix_exchange_files_agent_session_id", table_name="exchange_files")
    op.drop_constraint(
        "exchange_files_agent_runtime_id_fkey",
        "exchange_files",
        type_="foreignkey",
    )
    op.drop_constraint(
        "exchange_files_agent_session_id_fkey",
        "exchange_files",
        type_="foreignkey",
    )
    op.drop_column("exchange_files", "agent_runtime_id")
    op.drop_column("exchange_files", "agent_session_id")


def downgrade() -> None:
    """Restore the removed session/runtime association columns.

    Existing rows are treated as agent-scoped uploads, and an active session may
    not exist during restore, so the columns are restored as nullable.
    """
    op.add_column(
        "exchange_files",
        sa.Column("agent_session_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "exchange_files",
        sa.Column("agent_runtime_id", sa.String(length=32), nullable=True),
    )
    op.create_foreign_key(
        "exchange_files_agent_session_id_fkey",
        "exchange_files",
        "agent_sessions",
        ["agent_session_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "exchange_files_agent_runtime_id_fkey",
        "exchange_files",
        "agent_runtimes",
        ["agent_runtime_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_exchange_files_agent_session_id",
        "exchange_files",
        ["agent_session_id"],
    )
    op.create_index(
        "ix_exchange_files_agent_runtime_id",
        "exchange_files",
        ["agent_runtime_id"],
    )
