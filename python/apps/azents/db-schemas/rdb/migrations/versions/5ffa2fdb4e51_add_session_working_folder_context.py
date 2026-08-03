"""add session working folder context

Revision ID: 5ffa2fdb4e51
Revises: f6a2c5c503aa
Create Date: 2026-08-03 15:28:06.636761

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "5ffa2fdb4e51"
down_revision: str | Sequence[str] | None = "f6a2c5c503aa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CLEANUP_STATUS_VALUES = (
    "not_attempted",
    "pending",
    "succeeded",
    "failed",
)
_CLEANUP_STATUS_ENUM_NAME = "session_working_folder_cleanup_status"
_WORKING_FOLDER_ROOT = "/workspace/agent/.azents/sessions/"
_ROOT_SESSION_HANDLE_PATTERN = r"^[a-z]+-[a-z]+-[a-z]+$"


def _validate_backfill_inputs() -> None:
    """Reject context rows that cannot safely receive an owned folder path."""
    invalid_context = (
        op.get_bind()
        .execute(
            sa.text(
                """
            SELECT context.id
            FROM session_agent_contexts AS context
            LEFT JOIN session_agents AS root_agent
              ON root_agent.id = context.root_session_agent_id
            LEFT JOIN agent_sessions AS root_session
              ON root_session.id = root_agent.agent_session_id
            WHERE context.root_session_agent_id IS NULL
               OR root_agent.id IS NULL
               OR root_agent.context_id != context.id
               OR root_agent.root_session_agent_id != root_agent.id
               OR root_agent.kind::text != 'root'
               OR root_session.id IS NULL
               OR root_session.session_kind::text != 'root'
               OR root_session.handle !~ :handle_pattern
            LIMIT 1
            """
            ),
            {"handle_pattern": _ROOT_SESSION_HANDLE_PATTERN},
        )
        .scalar_one_or_none()
    )
    if invalid_context is not None:
        raise RuntimeError(
            "Session working-folder backfill requires a valid root Session link"
        )


def _assert_unique_backfill_paths() -> None:
    """Reject duplicate paths before adding the populated-path unique index."""
    duplicate_path = (
        op.get_bind()
        .execute(
            sa.text(
                """
            SELECT working_folder_path
            FROM session_agent_contexts
            WHERE working_folder_path IS NOT NULL
            GROUP BY working_folder_path
            HAVING COUNT(*) > 1
            LIMIT 1
            """
            )
        )
        .scalar_one_or_none()
    )
    if duplicate_path is not None:
        raise RuntimeError("Session working-folder backfill generated duplicate paths")


def upgrade() -> None:
    """Expand SessionAgentContext with owned working-folder metadata."""
    bind = op.get_bind()
    cleanup_status_enum = postgresql.ENUM(
        *_CLEANUP_STATUS_VALUES,
        name=_CLEANUP_STATUS_ENUM_NAME,
    )
    cleanup_status_enum.create(bind)
    cleanup_status_column = postgresql.ENUM(
        name=_CLEANUP_STATUS_ENUM_NAME,
        create_type=False,
    )

    op.add_column(
        "session_agent_contexts",
        sa.Column("working_folder_path", sa.Text(), nullable=True),
    )
    op.add_column(
        "session_agent_contexts",
        sa.Column(
            "working_folder_cleanup_status",
            cleanup_status_column,
            nullable=True,
        ),
    )
    op.add_column(
        "session_agent_contexts",
        sa.Column("working_folder_cleanup_summary", sa.Text(), nullable=True),
    )
    op.add_column(
        "session_agent_contexts",
        sa.Column(
            "working_folder_cleanup_completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    _validate_backfill_inputs()
    bind.execute(
        sa.text(
            """
            UPDATE session_agent_contexts AS context
            SET
                working_folder_path = :working_folder_root || root_session.handle,
                working_folder_cleanup_status =
                    'not_attempted'::session_working_folder_cleanup_status
            FROM session_agents AS root_agent
            JOIN agent_sessions AS root_session
              ON root_session.id = root_agent.agent_session_id
            WHERE root_agent.id = context.root_session_agent_id
            """
        ),
        {"working_folder_root": _WORKING_FOLDER_ROOT},
    )
    _assert_unique_backfill_paths()
    op.create_index(
        "ix_session_agent_contexts_working_folder_path",
        "session_agent_contexts",
        ["working_folder_path"],
        unique=True,
        postgresql_where=sa.text("working_folder_path IS NOT NULL"),
    )


def downgrade() -> None:
    """Remove Session working-folder metadata."""
    op.drop_index(
        "ix_session_agent_contexts_working_folder_path",
        table_name="session_agent_contexts",
    )
    op.drop_column("session_agent_contexts", "working_folder_cleanup_completed_at")
    op.drop_column("session_agent_contexts", "working_folder_cleanup_summary")
    op.drop_column("session_agent_contexts", "working_folder_cleanup_status")
    op.drop_column("session_agent_contexts", "working_folder_path")
    postgresql.ENUM(name=_CLEANUP_STATUS_ENUM_NAME).drop(
        op.get_bind(),
        checkfirst=True,
    )
