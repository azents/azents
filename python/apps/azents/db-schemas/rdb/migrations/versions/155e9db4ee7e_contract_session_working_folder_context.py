"""contract session working folder context

Revision ID: 155e9db4ee7e
Revises: 5ffa2fdb4e51
Create Date: 2026-08-04 09:17:21.612652

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "155e9db4ee7e"
down_revision: str | Sequence[str] | None = "5ffa2fdb4e51"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Tighten the verified Session working-folder persistence contract."""
    op.alter_column(
        "session_agent_contexts",
        "working_folder_path",
        existing_type=sa.Text(),
        nullable=False,
    )
    op.alter_column(
        "session_agent_contexts",
        "working_folder_cleanup_status",
        existing_type=postgresql.ENUM(
            "not_attempted",
            "pending",
            "succeeded",
            "failed",
            name="session_working_folder_cleanup_status",
        ),
        nullable=False,
    )
    op.drop_index(
        "ix_session_agent_contexts_working_folder_path",
        table_name="session_agent_contexts",
    )
    op.create_unique_constraint(
        "uq_session_agent_contexts_working_folder_path",
        "session_agent_contexts",
        ["working_folder_path"],
    )


def downgrade() -> None:
    """Restore the expand-stage nullable contract and partial unique index."""
    op.drop_constraint(
        "uq_session_agent_contexts_working_folder_path",
        "session_agent_contexts",
        type_="unique",
    )
    op.create_index(
        "ix_session_agent_contexts_working_folder_path",
        "session_agent_contexts",
        ["working_folder_path"],
        unique=True,
        postgresql_where=sa.text("working_folder_path IS NOT NULL"),
    )
    op.alter_column(
        "session_agent_contexts",
        "working_folder_cleanup_status",
        existing_type=postgresql.ENUM(
            "not_attempted",
            "pending",
            "succeeded",
            "failed",
            name="session_working_folder_cleanup_status",
        ),
        nullable=True,
    )
    op.alter_column(
        "session_agent_contexts",
        "working_folder_path",
        existing_type=sa.Text(),
        nullable=True,
    )
