"""add session initialization schema

Revision ID: 2bac80165071
Revises: aba66e477971
Create Date: 2026-07-03 18:53:41.791950

"""

import hashlib
from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from azents.core.bip39_english_words import BIP39_ENGLISH_WORDS

# revision identifiers, used by Alembic.
revision: str = "2bac80165071"
down_revision: str | Sequence[str] | None = "aba66e477971"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SESSION_INITIALIZATION_STATUS_VALUES = (
    "pending",
    "running",
    "ready",
    "failed",
    "canceled",
    "cleanup_required",
    "cleaned",
)
SESSION_INITIALIZATION_STEP_STATUS_VALUES = (
    "pending",
    "running",
    "completed",
    "failed",
    "skipped",
    "canceled",
)
SESSION_INITIALIZATION_STEP_TYPE_VALUES = (
    "noop_ready",
    "create_git_worktree",
    "register_workspace_project",
    "upsert_project_catalog",
    "refresh_project_status",
    "run_workspace_setup_script",
    "verify_required_credentials",
)
SESSION_INITIALIZATION_EVENT_KIND_VALUES = (
    "info",
    "command_started",
    "stdout",
    "stderr",
    "command_completed",
    "warning",
    "failed",
)


def _session_handle_for_backfill(session_id: str, used: set[str]) -> str:
    """Build a deterministic BIP-39 session handle for existing rows."""
    word_count = len(BIP39_ENGLISH_WORDS)
    for attempt in range(128):
        digest = hashlib.sha256(f"{session_id}:{attempt}".encode()).digest()
        word_indexes = [
            int.from_bytes(digest[offset : offset + 2], "big") % word_count
            for offset in (0, 2, 4)
        ]
        candidate = "-".join(BIP39_ENGLISH_WORDS[index] for index in word_indexes)
        if candidate not in used:
            used.add(candidate)
            return candidate
    raise RuntimeError("AgentSession handle backfill exhausted retry attempts")


def _backfill_agent_session_handles() -> None:
    """Backfill existing AgentSession handles before adding NOT NULL."""
    bind = op.get_bind()
    session_ids = bind.execute(
        sa.text("SELECT id FROM agent_sessions WHERE handle IS NULL ORDER BY id")
    ).scalars()
    used_handles = set(
        bind.execute(
            sa.text("SELECT handle FROM agent_sessions WHERE handle IS NOT NULL")
        ).scalars()
    )
    for session_id in session_ids:
        handle = _session_handle_for_backfill(str(session_id), used_handles)
        bind.execute(
            sa.text("UPDATE agent_sessions SET handle = :handle WHERE id = :id"),
            {"handle": handle, "id": session_id},
        )


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    postgresql.ENUM(
        *SESSION_INITIALIZATION_STATUS_VALUES,
        name="session_initialization_status",
    ).create(bind)
    postgresql.ENUM(
        *SESSION_INITIALIZATION_STEP_STATUS_VALUES,
        name="session_initialization_step_status",
    ).create(bind)
    postgresql.ENUM(
        *SESSION_INITIALIZATION_STEP_TYPE_VALUES,
        name="session_initialization_step_type",
    ).create(bind)
    postgresql.ENUM(
        *SESSION_INITIALIZATION_EVENT_KIND_VALUES,
        name="session_initialization_event_kind",
    ).create(bind)

    op.add_column(
        "agent_sessions",
        sa.Column("handle", sa.String(length=120), nullable=True),
    )
    _backfill_agent_session_handles()
    op.alter_column("agent_sessions", "handle", nullable=False)
    op.create_unique_constraint(
        "uq_agent_sessions_handle",
        "agent_sessions",
        ["handle"],
    )
    op.create_table(
        "session_initializations",
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                name="session_initialization_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("failure_summary", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cleaned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["agent_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id",
            name="uq_session_initializations_session_id",
        ),
    )
    op.create_index(
        "ix_session_initializations_session_id",
        "session_initializations",
        ["session_id"],
    )
    op.create_index(
        "ix_session_initializations_status",
        "session_initializations",
        ["status"],
    )

    op.create_table(
        "session_initialization_steps",
        sa.Column("initialization_id", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("step_key", sa.String(length=120), nullable=False),
        sa.Column(
            "step_type",
            postgresql.ENUM(
                name="session_initialization_step_type",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("blocking", sa.Boolean(), nullable=False),
        sa.Column("retryable", sa.Boolean(), nullable=False),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                name="session_initialization_step_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("attempt", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "depends_on_step_keys",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "resource_descriptors",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["initialization_id"],
            ["session_initializations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["agent_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "initialization_id",
            "sequence",
            name="uq_session_initialization_steps_initialization_sequence",
        ),
        sa.UniqueConstraint(
            "initialization_id",
            "step_key",
            name="uq_session_initialization_steps_initialization_step_key",
        ),
    )
    op.create_index(
        "ix_session_initialization_steps_initialization_sequence",
        "session_initialization_steps",
        ["initialization_id", "sequence"],
    )
    op.create_index(
        "ix_session_initialization_steps_session_status",
        "session_initialization_steps",
        ["session_id", "status"],
    )

    op.create_table(
        "session_initialization_events",
        sa.Column("initialization_id", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            postgresql.ENUM(
                name="session_initialization_event_kind",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("step_id", sa.String(length=32), nullable=True),
        sa.Column(
            "command_argv",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["initialization_id"],
            ["session_initializations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["agent_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["step_id"],
            ["session_initialization_steps.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "initialization_id",
            "sequence",
            name="uq_session_initialization_events_initialization_sequence",
        ),
    )
    op.create_index(
        "ix_session_initialization_events_initialization_sequence",
        "session_initialization_events",
        ["initialization_id", "sequence"],
    )
    op.create_index(
        "ix_session_initialization_events_session_created",
        "session_initialization_events",
        ["session_id", "created_at"],
    )
    op.create_index(
        "ix_session_initialization_events_step_id",
        "session_initialization_events",
        ["step_id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_session_initialization_events_step_id",
        table_name="session_initialization_events",
    )
    op.drop_index(
        "ix_session_initialization_events_session_created",
        table_name="session_initialization_events",
    )
    op.drop_index(
        "ix_session_initialization_events_initialization_sequence",
        table_name="session_initialization_events",
    )
    op.drop_table("session_initialization_events")

    op.drop_index(
        "ix_session_initialization_steps_session_status",
        table_name="session_initialization_steps",
    )
    op.drop_index(
        "ix_session_initialization_steps_initialization_sequence",
        table_name="session_initialization_steps",
    )
    op.drop_table("session_initialization_steps")

    op.drop_index(
        "ix_session_initializations_status",
        table_name="session_initializations",
    )
    op.drop_index(
        "ix_session_initializations_session_id",
        table_name="session_initializations",
    )
    op.drop_table("session_initializations")

    op.drop_constraint(
        "uq_agent_sessions_handle",
        "agent_sessions",
        type_="unique",
    )
    op.drop_column("agent_sessions", "handle")

    bind = op.get_bind()
    postgresql.ENUM(name="session_initialization_event_kind").drop(bind)
    postgresql.ENUM(name="session_initialization_step_type").drop(bind)
    postgresql.ENUM(name="session_initialization_step_status").drop(bind)
    postgresql.ENUM(name="session_initialization_status").drop(bind)
