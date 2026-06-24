"""add artifacts table"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e36b419c66b2"
down_revision: str | Sequence[str] | None = "8c2d4e6f1a90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    artifact_status = postgresql.ENUM(
        "available",
        "expired",
        name="artifact_status",
    )
    artifact_status.create(op.get_bind(), checkfirst=True)
    artifact_status_column = postgresql.ENUM(
        "available",
        "expired",
        name="artifact_status",
        create_type=False,
    )
    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column("created_run_id", sa.String(length=32), nullable=False),
        sa.Column("created_run_index", sa.Integer(), nullable=False),
        sa.Column("expires_after_run_index", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column(
            "status",
            artifact_status_column,
            server_default="available",
            nullable=False,
        ),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("source_tool_name", sa.String(length=255), nullable=True),
        sa.Column("source_call_id", sa.String(length=255), nullable=True),
        sa.Column("source_part_index", sa.Integer(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
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
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["session_id"], ["agent_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key", name="uq_artifacts_storage_key"),
    )
    op.create_index("ix_artifacts_workspace_id", "artifacts", ["workspace_id"])
    op.create_index(
        "ix_artifacts_session_status", "artifacts", ["session_id", "status"]
    )
    op.create_index(
        "ix_artifacts_expiration",
        "artifacts",
        ["session_id", "status", "expires_after_run_index"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_artifacts_expiration", table_name="artifacts")
    op.drop_index("ix_artifacts_session_status", table_name="artifacts")
    op.drop_index("ix_artifacts_workspace_id", table_name="artifacts")
    op.drop_table("artifacts")
    postgresql.ENUM(name="artifact_status").drop(op.get_bind(), checkfirst=True)
