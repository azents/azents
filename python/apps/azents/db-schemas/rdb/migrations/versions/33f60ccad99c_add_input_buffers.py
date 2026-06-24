"""add input buffers

Revision ID: 33f60ccad99c
Revises: 5022328fd325
Create Date: 2026-05-19 17:41:53.620558

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "33f60ccad99c"
down_revision: str | Sequence[str] | None = "5022328fd325"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the input_buffers table."""
    op.create_table(
        "input_buffers",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("agent_runtime_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("headers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "attachments", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("images", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["agent_runtime_id"],
            ["agent_runtimes.id"],
            name="fk_input_buffers_agent_runtime_id_agent_runtimes",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["agent_sessions.id"],
            name="fk_input_buffers_session_id_agent_sessions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_input_buffers_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_input_buffers"),
    )
    op.create_index(
        "ix_input_buffers_agent_runtime_id",
        "input_buffers",
        ["agent_runtime_id"],
        unique=False,
    )
    op.create_index(
        "ix_input_buffers_session_id",
        "input_buffers",
        ["session_id"],
        unique=False,
    )
    op.create_index(
        "ix_input_buffers_session_id_id",
        "input_buffers",
        ["session_id", "id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove the input_buffers table."""
    op.drop_index("ix_input_buffers_session_id_id", table_name="input_buffers")
    op.drop_index("ix_input_buffers_session_id", table_name="input_buffers")
    op.drop_index("ix_input_buffers_agent_runtime_id", table_name="input_buffers")
    op.drop_table("input_buffers")
