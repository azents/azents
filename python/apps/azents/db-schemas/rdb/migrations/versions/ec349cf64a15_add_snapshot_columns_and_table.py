"""add snapshot columns and table

Revision ID: ec349cf64a15
Revises: c93117a5f231
Create Date: 2026-04-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "ec349cf64a15"
down_revision: str | Sequence[str] | None = "c93117a5f231"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("last_state_change_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "agents",
        sa.Column("last_snapshot_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "agents",
        sa.Column("snapshot_deadline_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )

    op.create_table(
        "agent_snapshots",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "agent_id",
            sa.String(32),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("image_ref", sa.String(512), nullable=False),
        sa.Column("base_image_ref", sa.String(512), nullable=False),
        sa.Column("digest", sa.String(128), nullable=True),
        sa.Column("size_bytes", sa.BigInteger, nullable=True),
        sa.Column("metadata_json", postgresql.JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_agent_snapshots_agent_id_created_at",
        "agent_snapshots",
        ["agent_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_snapshots_agent_id_created_at",
        table_name="agent_snapshots",
    )
    op.drop_table("agent_snapshots")
    op.drop_column("agents", "snapshot_deadline_at")
    op.drop_column("agents", "last_snapshot_at")
    op.drop_column("agents", "last_state_change_at")
