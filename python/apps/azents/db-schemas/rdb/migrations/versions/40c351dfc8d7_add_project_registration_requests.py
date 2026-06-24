"""add project registration requests

Revision ID: 40c351dfc8d7
Revises: 8ea9df23f9cc
Create Date: 2026-05-09 05:31:52.447679

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "40c351dfc8d7"
down_revision: str | Sequence[str] | None = "8ea9df23f9cc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the project registration request table."""
    request_status = postgresql.ENUM(
        "pending",
        "approved",
        "rejected",
        name="session_workspace_project_registration_request_status",
    )
    request_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "session_workspace_project_registration_requests",
        sa.Column("agent_runtime_id", sa.String(length=32), nullable=False),
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
            ["agent_runtime_id"],
            ["agent_runtimes.id"],
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
        "ix_swp_registration_requests_runtime_status",
        "session_workspace_project_registration_requests",
        ["agent_runtime_id", "status"],
    )
    op.create_index(
        "ix_swp_registration_requests_pending_path",
        "session_workspace_project_registration_requests",
        ["agent_runtime_id", "path"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_swp_registration_requests_project_id",
        "session_workspace_project_registration_requests",
        ["project_id"],
    )


def downgrade() -> None:
    """Remove the project registration request table."""
    op.drop_table("session_workspace_project_registration_requests")
    op.execute(
        "DROP TYPE IF EXISTS session_workspace_project_registration_request_status"
    )
