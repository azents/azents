"""simplify file lifecycle

Revision ID: 8dfc9b5e1a2c
Revises: 4874ac5aec1b
Create Date: 2026-06-27 16:20:00.000000

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8dfc9b5e1a2c"
down_revision: str | Sequence[str] | None = "4874ac5aec1b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "artifacts",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE artifacts SET expires_at = created_at + interval '7 days'")
    op.alter_column("artifacts", "expires_at", nullable=False)
    op.add_column(
        "artifacts",
        sa.Column("blob_deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "exchange_files",
        sa.Column("blob_deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.drop_index("ix_artifacts_expiration", table_name="artifacts")
    op.create_index(
        "ix_artifacts_status_expires_at",
        "artifacts",
        ["status", "expires_at"],
    )
    op.drop_column("artifacts", "expires_after_run_index")

    op.add_column(
        "agent_sessions",
        sa.Column("model_input_head_model_order", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "agent_sessions",
        sa.Column("model_file_gc_cursor_event_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "agent_sessions",
        sa.Column(
            "model_file_gc_cursor_model_order",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "agent_sessions",
        sa.Column(
            "model_file_gc_updated_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.execute(
        """
        UPDATE agent_sessions AS s
        SET model_input_head_model_order = e.model_order
        FROM events AS e
        WHERE e.id = s.model_input_head_event_id
        """
    )
    op.create_index(
        "ix_agent_sessions_model_file_gc_lag",
        "agent_sessions",
        ["model_file_gc_cursor_model_order", "model_input_head_model_order"],
    )

    op.create_table(
        "model_file_pins",
        sa.Column("model_file_id", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["model_file_id"], ["model_files.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["session_id"], ["agent_sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("model_file_id", "run_id"),
        sa.UniqueConstraint(
            "model_file_id",
            "run_id",
            name="uq_model_file_pins_model_file_run",
        ),
    )
    op.create_index(
        "ix_model_file_pins_model_file_id",
        "model_file_pins",
        ["model_file_id"],
    )
    op.create_index("ix_model_file_pins_run_id", "model_file_pins", ["run_id"])

    op.add_column(
        "model_files",
        sa.Column("blob_deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.drop_index("ix_model_files_expiration", table_name="model_files")
    op.drop_index("ix_model_files_unreachable_gc", table_name="model_files")
    op.drop_column("model_files", "expires_after_run_index")
    op.drop_column("model_files", "degraded_at")
    op.drop_column("model_files", "unreachable_run_index")
    op.drop_column("model_files", "unreachable_at")
    op.execute(
        """
        UPDATE model_files
        SET status = 'available'
        WHERE status IN ('degraded', 'unreachable')
        """
    )
    op.alter_column("model_files", "status", server_default=None)
    op.execute("ALTER TYPE model_file_status RENAME TO model_file_status_old")
    new_status = postgresql.ENUM("available", "deleted", name="model_file_status")
    new_status.create(op.get_bind(), checkfirst=False)
    op.execute(
        """
        ALTER TABLE model_files
        ALTER COLUMN status TYPE model_file_status
        USING status::text::model_file_status
        """
    )
    op.alter_column("model_files", "status", server_default="available")
    op.execute("DROP TYPE model_file_status_old")


def downgrade() -> None:
    """Downgrade schema."""
    old_status = postgresql.ENUM(
        "available",
        "degraded",
        "unreachable",
        "deleted",
        name="model_file_status_old",
    )
    old_status.create(op.get_bind(), checkfirst=False)
    op.alter_column("model_files", "status", server_default=None)
    op.execute(
        """
        ALTER TABLE model_files
        ALTER COLUMN status TYPE model_file_status_old
        USING status::text::model_file_status_old
        """
    )
    op.execute("DROP TYPE model_file_status")
    op.execute("ALTER TYPE model_file_status_old RENAME TO model_file_status")
    op.alter_column("model_files", "status", server_default="available")
    op.add_column(
        "model_files",
        sa.Column("unreachable_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "model_files",
        sa.Column("unreachable_run_index", sa.Integer(), nullable=True),
    )
    op.add_column(
        "model_files",
        sa.Column("degraded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "model_files",
        sa.Column(
            "expires_after_run_index",
            sa.Integer(),
            server_default="3",
            nullable=False,
        ),
    )
    op.alter_column("model_files", "expires_after_run_index", server_default=None)
    op.create_index(
        "ix_model_files_unreachable_gc",
        "model_files",
        ["session_id", "status", "unreachable_run_index"],
    )
    op.create_index(
        "ix_model_files_expiration",
        "model_files",
        ["session_id", "status", "expires_after_run_index"],
    )
    op.drop_column("model_files", "blob_deleted_at")

    op.drop_index("ix_model_file_pins_run_id", table_name="model_file_pins")
    op.drop_index("ix_model_file_pins_model_file_id", table_name="model_file_pins")
    op.drop_table("model_file_pins")

    op.drop_index("ix_agent_sessions_model_file_gc_lag", table_name="agent_sessions")
    op.drop_column("agent_sessions", "model_file_gc_updated_at")
    op.drop_column("agent_sessions", "model_file_gc_cursor_model_order")
    op.drop_column("agent_sessions", "model_file_gc_cursor_event_id")
    op.drop_column("agent_sessions", "model_input_head_model_order")

    op.add_column(
        "artifacts",
        sa.Column(
            "expires_after_run_index",
            sa.Integer(),
            server_default="3",
            nullable=False,
        ),
    )
    op.alter_column("artifacts", "expires_after_run_index", server_default=None)
    op.drop_index("ix_artifacts_status_expires_at", table_name="artifacts")
    op.create_index(
        "ix_artifacts_expiration",
        "artifacts",
        ["session_id", "status", "expires_after_run_index"],
    )
    op.drop_column("exchange_files", "blob_deleted_at")
    op.drop_column("artifacts", "blob_deleted_at")
    op.drop_column("artifacts", "expires_at")
