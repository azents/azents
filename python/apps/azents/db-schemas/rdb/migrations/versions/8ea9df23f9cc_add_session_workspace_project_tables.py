"""add session workspace project tables

Revision ID: 8ea9df23f9cc
Revises: 9c5ccd6bdb1c
Create Date: 2026-05-09 04:09:15.824150

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "8ea9df23f9cc"
down_revision: str | Sequence[str] | None = "9c5ccd6bdb1c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add Project Source and Project load state tables."""
    project_source_type = postgresql.ENUM(
        "archive_upload",
        name="session_workspace_project_source_type",
    )
    project_load_source_type = postgresql.ENUM(
        "empty_folder",
        "archive_upload",
        "agent_request",
        name="session_workspace_project_load_source_type",
    )
    project_source_type.create(op.get_bind(), checkfirst=True)
    project_load_source_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "session_workspace_project_sources",
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "source_type",
            postgresql.ENUM(
                name="session_workspace_project_source_type",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=32), nullable=False),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("media_type", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "object_key",
            name="uq_session_workspace_project_sources_object_key",
        ),
    )
    op.create_index(
        "ix_session_workspace_project_sources_workspace_id",
        "session_workspace_project_sources",
        ["workspace_id"],
    )
    op.create_index(
        "ix_session_workspace_project_sources_source_type",
        "session_workspace_project_sources",
        ["source_type"],
    )

    op.create_table(
        "session_workspace_projects",
        sa.Column("agent_runtime_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column(
            "source_type",
            postgresql.ENUM(
                name="session_workspace_project_load_source_type",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("loaded", sa.Boolean(), nullable=False),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("project_source_id", sa.String(length=32), nullable=True),
        sa.Column("load_error_message", sa.Text(), nullable=True),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["agent_runtime_id"],
            ["agent_runtimes.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_source_id"],
            ["session_workspace_project_sources.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_runtime_id",
            "path",
            name="uq_session_workspace_projects_runtime_path",
        ),
    )
    op.create_index(
        "ix_session_workspace_projects_agent_runtime_id",
        "session_workspace_projects",
        ["agent_runtime_id"],
    )
    op.create_index(
        "ix_session_workspace_projects_loaded",
        "session_workspace_projects",
        ["loaded"],
    )
    op.create_index(
        "ix_session_workspace_projects_project_source_id",
        "session_workspace_projects",
        ["project_source_id"],
    )


def downgrade() -> None:
    """Remove Project Source and Project load state tables."""
    op.drop_table("session_workspace_projects")
    op.drop_table("session_workspace_project_sources")
    op.execute("DROP TYPE IF EXISTS session_workspace_project_load_source_type")
    op.execute("DROP TYPE IF EXISTS session_workspace_project_source_type")
