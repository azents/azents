"""per session sandbox: add runtime columns and session_snapshots

Revision ID: 904e98b31558
Revises: eae41783d6f5
Create Date: 2026-04-24 17:20:22.858864

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

import azents.rdb.types.datetime as ni_dt

revision: str = "904e98b31558"
down_revision: str | Sequence[str] | None = "eae41783d6f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # New ENUM types: session_runtime_state for per-session lifecycle state and
    # snapshot_kind to distinguish hibernate/debounce snapshots.
    sa.Enum("hibernate", "debounce", name="snapshot_kind").create(op.get_bind())
    sa.Enum(
        "active", "hibernated", "expired", "wiped", name="session_runtime_state"
    ).create(op.get_bind())

    # session_snapshots: session container OCI image metadata.
    op.create_table(
        "session_snapshots",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("image_ref", sa.String(length=512), nullable=False),
        sa.Column("base_image_ref", sa.String(length=512), nullable=False),
        sa.Column(
            "kind",
            postgresql.ENUM(
                "hibernate", "debounce", name="snapshot_kind", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("digest", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            ni_dt.TimeZoneDateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["conversation_sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_session_snapshots_session_id"),
        "session_snapshots",
        ["session_id"],
        unique=False,
    )
    op.create_index(
        "ix_session_snapshots_session_id_created_at",
        "session_snapshots",
        ["session_id", sa.literal_column("created_at DESC")],
        unique=False,
    )

    # conversation_sessions: five nullable per-session sandbox runtime columns.
    op.add_column(
        "conversation_sessions",
        sa.Column("runtime_run_id", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "conversation_sessions",
        sa.Column(
            "runtime_state",
            postgresql.ENUM(
                "active",
                "hibernated",
                "expired",
                "wiped",
                name="session_runtime_state",
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "conversation_sessions",
        sa.Column(
            "runtime_claimed_at",
            ni_dt.TimeZoneDateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "conversation_sessions",
        sa.Column(
            "last_runtime_change_at",
            ni_dt.TimeZoneDateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "conversation_sessions",
        sa.Column(
            "snapshot_deadline_at",
            ni_dt.TimeZoneDateTime(timezone=True),
            nullable=True,
        ),
    )

    # Partial index for stale lease detection.
    # Only scans sessions with runtime_run_id set.
    op.create_index(
        "ix_conversation_sessions_runtime_claimed_at",
        "conversation_sessions",
        ["runtime_claimed_at"],
        unique=False,
        postgresql_where=sa.text("runtime_run_id IS NOT NULL"),
    )
    # Partial index for hibernate candidate scans; only scans active sessions
    # by snapshot_deadline_at.
    op.create_index(
        "ix_conversation_sessions_runtime_state_deadline",
        "conversation_sessions",
        ["runtime_state", "snapshot_deadline_at"],
        unique=False,
        postgresql_where=sa.text("runtime_state = 'active'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_conversation_sessions_runtime_state_deadline",
        table_name="conversation_sessions",
        postgresql_where=sa.text("runtime_state = 'active'"),
    )
    op.drop_index(
        "ix_conversation_sessions_runtime_claimed_at",
        table_name="conversation_sessions",
        postgresql_where=sa.text("runtime_run_id IS NOT NULL"),
    )
    op.drop_column("conversation_sessions", "snapshot_deadline_at")
    op.drop_column("conversation_sessions", "last_runtime_change_at")
    op.drop_column("conversation_sessions", "runtime_claimed_at")
    op.drop_column("conversation_sessions", "runtime_state")
    op.drop_column("conversation_sessions", "runtime_run_id")
    op.drop_index(
        "ix_session_snapshots_session_id_created_at", table_name="session_snapshots"
    )
    op.drop_index(
        op.f("ix_session_snapshots_session_id"), table_name="session_snapshots"
    )
    op.drop_table("session_snapshots")
    sa.Enum(
        "active", "hibernated", "expired", "wiped", name="session_runtime_state"
    ).drop(op.get_bind())
    sa.Enum("hibernate", "debounce", name="snapshot_kind").drop(op.get_bind())
