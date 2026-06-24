"""add model files table

Revision ID: 19c8f7a6b2d4
Revises: c3f5e8a91d27
Create Date: 2026-06-02 20:10:00.000000

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "19c8f7a6b2d4"
down_revision: str | Sequence[str] | None = "c3f5e8a91d27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the ModelFile metadata table."""
    model_file_status = postgresql.ENUM(
        "available",
        "degraded",
        "unreachable",
        "deleted",
        name="model_file_status",
    )
    model_file_status.create(op.get_bind(), checkfirst=True)
    model_file_status_column = postgresql.ENUM(
        "available",
        "degraded",
        "unreachable",
        "deleted",
        name="model_file_status",
        create_type=False,
    )
    op.create_table(
        "model_files",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("media_type", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column(
            "status",
            model_file_status_column,
            server_default="available",
            nullable=False,
        ),
        sa.Column("normalized_format", sa.String(length=32), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("degraded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["session_id"], ["agent_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key", name="uq_model_files_storage_key"),
    )
    op.create_index("ix_model_files_workspace_id", "model_files", ["workspace_id"])
    op.create_index(
        "ix_model_files_session_status",
        "model_files",
        ["session_id", "status"],
    )


def downgrade() -> None:
    """Remove the ModelFile metadata table."""
    op.drop_index("ix_model_files_session_status", table_name="model_files")
    op.drop_index("ix_model_files_workspace_id", table_name="model_files")
    op.drop_table("model_files")
    postgresql.ENUM(name="model_file_status").drop(op.get_bind(), checkfirst=True)
