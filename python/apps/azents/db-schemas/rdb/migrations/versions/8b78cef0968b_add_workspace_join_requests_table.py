"""add workspace_join_requests table.

Revision ID: 8b78cef0968b
Revises: fea922c9bf44
Create Date: 2026-03-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8b78cef0968b"
down_revision: str | None = "fea922c9bf44"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# New enum definition
join_request_status = postgresql.ENUM(
    "pending", "muted", name="join_request_status", create_type=False
)


def upgrade() -> None:
    """Create the workspace_join_requests table and join_request_status enum."""
    join_request_status.create(op.get_bind())

    op.create_table(
        "workspace_join_requests",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(32),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(32),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("message", sa.Text, nullable=True),
        sa.Column(
            "status",
            join_request_status,
            nullable=False,
            server_default="pending",
        ),
        sa.Column("last_notified_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint(
            "workspace_id",
            "user_id",
            name="uq_workspace_join_requests_workspace_user",
        ),
    )

    op.create_index(
        "ix_workspace_join_requests_workspace_id",
        "workspace_join_requests",
        ["workspace_id"],
    )
    op.create_index(
        "ix_workspace_join_requests_user_id",
        "workspace_join_requests",
        ["user_id"],
    )


def downgrade() -> None:
    """Drop the workspace_join_requests table and join_request_status enum."""
    op.drop_index(
        "ix_workspace_join_requests_user_id",
        table_name="workspace_join_requests",
    )
    op.drop_index(
        "ix_workspace_join_requests_workspace_id",
        table_name="workspace_join_requests",
    )
    op.drop_table("workspace_join_requests")

    join_request_status.drop(op.get_bind())
