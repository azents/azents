"""add exchange files table

Revision ID: c7f99dfd374e
Revises: e2cb6cd69d7f
Create Date: 2026-05-05 19:57:49.491796

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c7f99dfd374e"
down_revision: str | Sequence[str] | None = "e2cb6cd69d7f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the exchange file metadata table."""
    exchange_file_origin = postgresql.ENUM(
        "upload",
        "artifact",
        name="exchange_file_origin",
    )
    bind = op.get_bind()
    exchange_file_origin.create(bind, checkfirst=True)

    op.create_table(
        "exchange_files",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("agent_session_id", sa.String(length=32), nullable=False),
        sa.Column("agent_runtime_id", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column(
            "origin_type",
            postgresql.ENUM(name="exchange_file_origin", create_type=False),
            nullable=False,
        ),
        sa.Column("object_key", sa.String(length=1024), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["agent_runtime_id"], ["agent_runtimes.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["agent_session_id"], ["agent_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key", name="uq_exchange_files_object_key"),
    )
    op.create_index(
        "ix_exchange_files_workspace_id",
        "exchange_files",
        ["workspace_id"],
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
    op.create_index("ix_exchange_files_origin_type", "exchange_files", ["origin_type"])


def downgrade() -> None:
    """Remove the exchange file metadata table."""
    op.drop_index("ix_exchange_files_origin_type", table_name="exchange_files")
    op.drop_index("ix_exchange_files_agent_runtime_id", table_name="exchange_files")
    op.drop_index("ix_exchange_files_agent_session_id", table_name="exchange_files")
    op.drop_index("ix_exchange_files_workspace_id", table_name="exchange_files")
    op.drop_table("exchange_files")
    postgresql.ENUM(name="exchange_file_origin").drop(op.get_bind(), checkfirst=True)
