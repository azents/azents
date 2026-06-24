"""create workspace_invitations table

Revision ID: a3c7f2e91b04
Revises: 74fb22803d00
Create Date: 2026-02-19 12:00:00.000000

"""

# ruff: noqa: E501
# pyright: reportUnknownArgumentType=false

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a3c7f2e91b04"
down_revision: str | Sequence[str] | None = "74fb22803d00"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Existing enum reference, created in a previous migration
workspace_user_role = postgresql.ENUM(name="workspace_user_role", create_type=False)

# New enum definition
invitation_status = postgresql.ENUM(
    "pending", "accepted", "declined", name="invitation_status", create_type=False
)


def upgrade() -> None:
    """Create the workspace_invitations table and invitation_status enum."""
    invitation_status.create(op.get_bind())

    op.create_table(
        "workspace_invitations",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(32),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("role", workspace_user_role, nullable=False),
        sa.Column(
            "invited_by",
            sa.String(32),
            sa.ForeignKey("workspace_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            invitation_status,
            nullable=False,
            server_default="pending",
        ),
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
            "email",
            name="uq_workspace_invitations_workspace_email",
        ),
    )

    op.create_index(
        "ix_workspace_invitations_email",
        "workspace_invitations",
        ["email"],
    )


def downgrade() -> None:
    """Drop the workspace_invitations table."""
    op.drop_index("ix_workspace_invitations_email", table_name="workspace_invitations")
    op.drop_table("workspace_invitations")
    invitation_status.drop(op.get_bind())
