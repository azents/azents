"""drop project source provisioning

Revision ID: 2a67b2860503
Revises: cd91953fae06
Create Date: 2026-06-11 01:42:28.598791

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "2a67b2860503"
down_revision: str | Sequence[str] | None = "cd91953fae06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_index(
        "ix_session_workspace_projects_project_source_id",
        table_name="session_workspace_projects",
    )
    op.drop_index(
        "ix_session_workspace_projects_loaded",
        table_name="session_workspace_projects",
    )
    op.drop_column("session_workspace_projects", "loaded_at")
    op.drop_column("session_workspace_projects", "load_error_message")
    op.drop_column("session_workspace_projects", "project_source_id")
    op.drop_column("session_workspace_projects", "loaded")
    op.drop_column("session_workspace_projects", "source_type")
    op.drop_table("session_workspace_project_sources")
    op.execute("DROP TYPE IF EXISTS session_workspace_project_source_type")
    op.execute("DROP TYPE IF EXISTS session_workspace_project_load_source_type")


def downgrade() -> None:
    """Downgrade schema."""
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
                "archive_upload",
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
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
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
        "ix_session_workspace_project_sources_source_type",
        "session_workspace_project_sources",
        ["source_type"],
    )
    op.create_index(
        "ix_session_workspace_project_sources_workspace_id",
        "session_workspace_project_sources",
        ["workspace_id"],
    )

    op.add_column(
        "session_workspace_projects",
        sa.Column(
            "source_type",
            postgresql.ENUM(
                "empty_folder",
                "archive_upload",
                "agent_request",
                name="session_workspace_project_load_source_type",
                create_type=False,
            ),
            server_default="agent_request",
            nullable=False,
        ),
    )
    op.add_column(
        "session_workspace_projects",
        sa.Column(
            "loaded",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )
    op.add_column(
        "session_workspace_projects",
        sa.Column("project_source_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "session_workspace_projects",
        sa.Column("load_error_message", sa.Text(), nullable=True),
    )
    op.add_column(
        "session_workspace_projects",
        sa.Column("loaded_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "session_workspace_projects_project_source_id_fkey",
        "session_workspace_projects",
        "session_workspace_project_sources",
        ["project_source_id"],
        ["id"],
        ondelete="SET NULL",
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
    op.alter_column("session_workspace_projects", "source_type", server_default=None)
    op.alter_column("session_workspace_projects", "loaded", server_default=None)
