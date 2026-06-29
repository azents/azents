"""add agent project presets

Revision ID: fe0e32010308
Revises: 1a2b3c4d5e6f
Create Date: 2026-06-29 12:10:47.609557

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fe0e32010308"
down_revision: str | Sequence[str] | None = "1a2b3c4d5e6f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "agent_project_presets",
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("id", sa.String(length=32), nullable=False),
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
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_id",
            "path",
            name="uq_agent_project_presets_agent_path",
        ),
    )
    op.create_index(
        "ix_agent_project_presets_agent_updated",
        "agent_project_presets",
        ["agent_id", "updated_at"],
        unique=False,
    )
    op.execute(
        sa.text(
            """
            INSERT INTO agent_project_presets (
                id,
                agent_id,
                path,
                created_at,
                updated_at
            )
            SELECT
                md5(agent_sessions.agent_id || ':' || session_workspace_projects.path),
                agent_sessions.agent_id,
                session_workspace_projects.path,
                min(session_workspace_projects.created_at),
                max(session_workspace_projects.updated_at)
            FROM session_workspace_projects
            JOIN agent_sessions
                ON agent_sessions.id = session_workspace_projects.session_id
            GROUP BY agent_sessions.agent_id, session_workspace_projects.path
            """
        )
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_agent_project_presets_agent_updated",
        table_name="agent_project_presets",
    )
    op.drop_table("agent_project_presets")
