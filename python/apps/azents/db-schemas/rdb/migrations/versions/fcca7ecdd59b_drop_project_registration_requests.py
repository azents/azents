"""drop project registration requests

Revision ID: fcca7ecdd59b
Revises: ad8bde4eb6a8
Create Date: 2026-07-07 12:04:20.861683

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "fcca7ecdd59b"
down_revision: str | Sequence[str] | None = "ad8bde4eb6a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop the unused Project registration request table."""
    op.drop_table("session_workspace_project_registration_requests")
    op.execute(
        "DROP TYPE IF EXISTS session_workspace_project_registration_request_status"
    )


def downgrade() -> None:
    """Restore the removed Project registration request table."""
    request_status = postgresql.ENUM(
        "pending",
        "approved",
        "rejected",
        name="session_workspace_project_registration_request_status",
    )
    request_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "session_workspace_project_registration_requests",
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.String(length=32), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                name="session_workspace_project_registration_request_status",
                create_type=False,
            ),
            nullable=False,
        ),
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
            ["session_id"],
            ["agent_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["session_workspace_projects.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_swp_registration_requests_session_status",
        "session_workspace_project_registration_requests",
        ["session_id", "status"],
    )
    op.create_index(
        "ix_swp_registration_requests_pending_session_path",
        "session_workspace_project_registration_requests",
        ["session_id", "path"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_swp_registration_requests_project_id",
        "session_workspace_project_registration_requests",
        ["project_id"],
    )
