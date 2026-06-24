"""per session sandbox phase 7: drop agent lifecycle + agent_snapshots

Revision ID: 79556eb5d839
Revises: 904e98b31558
Create Date: 2026-04-24 19:37:19.446327

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "79556eb5d839"
down_revision: str | Sequence[str] | None = "904e98b31558"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Cut over to per-session sandbox by removing agent-level lifecycle and snapshots.

    Existing agent-home containers naturally terminate when Phase 7 is deployed.
    This migration is **non-reversible**, and a DB snapshot backup is required
    before deployment.
    """
    op.drop_index(
        op.f("ix_agent_snapshots_agent_id_created_at"),
        table_name="agent_snapshots",
    )
    op.drop_table("agent_snapshots")
    op.drop_column("agents", "snapshot_deadline_at")
    op.drop_column("agents", "last_snapshot_at")
    op.drop_column("agents", "lifecycle_run_id")
    op.drop_column("agents", "lifecycle_claimed_at")
    op.drop_column("agents", "lifecycle_state")
    op.drop_column("agents", "last_state_change_at")


def downgrade() -> None:
    """Test-only downgrade: recreate columns and tables without restoring old data."""
    op.add_column(
        "agents",
        sa.Column(
            "last_state_change_at",
            postgresql.TIMESTAMP(timezone=True),
            autoincrement=False,
            nullable=True,
        ),
    )
    op.add_column(
        "agents",
        sa.Column(
            "lifecycle_state", sa.VARCHAR(length=20), autoincrement=False, nullable=True
        ),
    )
    op.add_column(
        "agents",
        sa.Column(
            "lifecycle_claimed_at",
            postgresql.TIMESTAMP(timezone=True),
            autoincrement=False,
            nullable=True,
        ),
    )
    op.add_column(
        "agents",
        sa.Column(
            "lifecycle_run_id",
            sa.VARCHAR(length=80),
            autoincrement=False,
            nullable=True,
        ),
    )
    op.add_column(
        "agents",
        sa.Column(
            "last_snapshot_at",
            postgresql.TIMESTAMP(timezone=True),
            autoincrement=False,
            nullable=True,
        ),
    )
    op.add_column(
        "agents",
        sa.Column(
            "snapshot_deadline_at",
            postgresql.TIMESTAMP(timezone=True),
            autoincrement=False,
            nullable=True,
        ),
    )
    op.create_table(
        "agent_snapshots",
        sa.Column("id", sa.VARCHAR(length=32), autoincrement=False, nullable=False),
        sa.Column(
            "agent_id", sa.VARCHAR(length=32), autoincrement=False, nullable=False
        ),
        sa.Column(
            "image_ref", sa.VARCHAR(length=512), autoincrement=False, nullable=False
        ),
        sa.Column(
            "base_image_ref",
            sa.VARCHAR(length=512),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column("digest", sa.VARCHAR(length=128), autoincrement=False, nullable=True),
        sa.Column("size_bytes", sa.BIGINT(), autoincrement=False, nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            autoincrement=False,
            nullable=True,
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            autoincrement=False,
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("agent_snapshots_agent_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("agent_snapshots_pkey")),
    )
    op.create_index(
        op.f("ix_agent_snapshots_agent_id_created_at"),
        "agent_snapshots",
        ["agent_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
