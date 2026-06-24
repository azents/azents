"""Add shell_environments tables and agent shell columns.

Revision ID: d33eefedef78
Revises: 5baa84aabbb7
Create Date: 2026-03-15

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d33eefedef78"
down_revision: str | Sequence[str] | None = "4fbb63d65cda"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create shell environment tables and add agent columns."""
    op.create_table(
        "shell_environments",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(32),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column(
            "is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "allowed_domains",
            sa.ARRAY(sa.String()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "denied_domains",
            sa.ARRAY(sa.String()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "workspace_id", "name", name="uq_shell_environments_workspace_name"
        ),
    )
    op.create_index(
        "ix_shell_environments_workspace_id",
        "shell_environments",
        ["workspace_id"],
    )
    op.create_index(
        "ix_shell_environments_workspace_default",
        "shell_environments",
        ["workspace_id"],
        unique=True,
        postgresql_where=sa.text("is_default = true"),
    )

    op.create_table(
        "shell_environment_scopes",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "shell_environment_id",
            sa.String(32),
            sa.ForeignKey("shell_environments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "scope_type",
            postgresql.ENUM(
                "team",
                "workspace",
                name="toolkit_scope_type",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("scope_id", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "shell_environment_id",
            "scope_type",
            "scope_id",
            name="uq_shell_environment_scopes_env_scope",
        ),
    )
    op.create_index(
        "ix_shell_environment_scopes_env_id",
        "shell_environment_scopes",
        ["shell_environment_id"],
    )

    op.add_column(
        "agents",
        sa.Column(
            "shell_environment_id",
            sa.String(32),
            sa.ForeignKey("shell_environments.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "agents",
        sa.Column(
            "shell_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    """Drop shell environment tables and remove agent columns."""
    op.drop_column("agents", "shell_enabled")
    op.drop_column("agents", "shell_environment_id")
    op.drop_index("ix_shell_environment_scopes_env_id")
    op.drop_table("shell_environment_scopes")
    op.drop_index("ix_shell_environments_workspace_default")
    op.drop_index("ix_shell_environments_workspace_id")
    op.drop_table("shell_environments")
