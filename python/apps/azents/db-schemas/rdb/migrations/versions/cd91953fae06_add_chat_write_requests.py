"""add chat write requests

Revision ID: cd91953fae06
Revises: ec89bacbbeb7
Create Date: 2026-06-05 07:15:23.866071

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "cd91953fae06"
down_revision: str | Sequence[str] | None = "ec89bacbbeb7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add REST write idempotency records."""
    chat_write_request_type = postgresql.ENUM(
        "edit_message",
        "command",
        name="chat_write_request_type",
        create_type=False,
    )
    chat_write_request_type.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "chat_write_requests",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("agent_runtime_id", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("client_request_id", sa.String(length=64), nullable=False),
        sa.Column(
            "write_type",
            postgresql.ENUM(
                name="chat_write_request_type",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "accepted_type",
            postgresql.ENUM(
                name="chat_write_request_type",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("accepted_id", sa.String(length=128), nullable=False),
        sa.Column("history_reload_required", sa.Boolean(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["agent_runtime_id"],
            ["agent_runtimes.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["agent_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_runtime_id",
            "user_id",
            "client_request_id",
            name="uq_chat_write_requests_runtime_user_client_request",
        ),
    )
    op.create_index(
        "ix_chat_write_requests_session_id",
        "chat_write_requests",
        ["session_id"],
    )


def downgrade() -> None:
    """Remove REST write idempotency records."""
    op.drop_index("ix_chat_write_requests_session_id", table_name="chat_write_requests")
    op.drop_table("chat_write_requests")
    postgresql.ENUM(name="chat_write_request_type").drop(
        op.get_bind(),
        checkfirst=True,
    )
