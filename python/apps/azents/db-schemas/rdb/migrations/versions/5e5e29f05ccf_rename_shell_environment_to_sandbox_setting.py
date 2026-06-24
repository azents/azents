"""Rename shell environment to sandbox setting.

Revision ID: 5e5e29f05ccf
Revises: 9e4c85806f1a
Create Date: 2026-05-22 16:18:49.661947

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5e5e29f05ccf"
down_revision: str | Sequence[str] | None = "9e4c85806f1a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Rename shell environment tables and columns to sandbox setting."""
    op.drop_constraint(
        "agents_shell_environment_id_fkey",
        "agents",
        type_="foreignkey",
    )
    op.drop_constraint(
        "shell_environment_scopes_shell_environment_id_fkey",
        "shell_environment_scopes",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_shell_environment_scopes_env_scope",
        "shell_environment_scopes",
        type_="unique",
    )
    op.drop_index(
        "ix_shell_environment_scopes_env_id",
        table_name="shell_environment_scopes",
    )
    op.drop_constraint(
        "uq_shell_environments_workspace_name",
        "shell_environments",
        type_="unique",
    )
    op.drop_index(
        "ix_shell_environments_workspace_default",
        table_name="shell_environments",
    )
    op.drop_index(
        "ix_shell_environments_workspace_id",
        table_name="shell_environments",
    )

    op.rename_table("shell_environments", "sandbox_settings")
    op.rename_table("shell_environment_scopes", "sandbox_setting_scopes")
    op.alter_column(
        "sandbox_setting_scopes",
        "shell_environment_id",
        new_column_name="sandbox_setting_id",
        existing_type=sa.String(length=32),
        existing_nullable=False,
    )
    op.alter_column(
        "agents",
        "shell_environment_id",
        new_column_name="sandbox_setting_id",
        existing_type=sa.String(length=32),
        existing_nullable=True,
    )

    op.create_unique_constraint(
        "uq_sandbox_settings_workspace_name",
        "sandbox_settings",
        ["workspace_id", "name"],
    )
    op.create_index(
        "ix_sandbox_settings_workspace_id",
        "sandbox_settings",
        ["workspace_id"],
    )
    op.create_index(
        "ix_sandbox_settings_workspace_default",
        "sandbox_settings",
        ["workspace_id"],
        unique=True,
        postgresql_where=sa.text("is_default = true"),
    )
    op.create_foreign_key(
        "sandbox_setting_scopes_sandbox_setting_id_fkey",
        "sandbox_setting_scopes",
        "sandbox_settings",
        ["sandbox_setting_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_sandbox_setting_scopes_setting_scope",
        "sandbox_setting_scopes",
        ["sandbox_setting_id", "scope_type", "scope_id"],
    )
    op.create_index(
        "ix_sandbox_setting_scopes_setting_id",
        "sandbox_setting_scopes",
        ["sandbox_setting_id"],
    )
    op.create_foreign_key(
        "agents_sandbox_setting_id_fkey",
        "agents",
        "sandbox_settings",
        ["sandbox_setting_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "sandbox_settings",
        sa.Column("sandbox_provider_id", sa.String(length=120), nullable=True),
    )
    op.create_index(
        "ix_sandbox_settings_sandbox_provider_id",
        "sandbox_settings",
        ["sandbox_provider_id"],
    )


def downgrade() -> None:
    """Rename sandbox setting tables and columns back to shell environment."""
    op.drop_index(
        "ix_sandbox_settings_sandbox_provider_id",
        table_name="sandbox_settings",
    )
    op.drop_column("sandbox_settings", "sandbox_provider_id")

    op.drop_constraint(
        "agents_sandbox_setting_id_fkey",
        "agents",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_sandbox_setting_scopes_setting_id",
        table_name="sandbox_setting_scopes",
    )
    op.drop_constraint(
        "uq_sandbox_setting_scopes_setting_scope",
        "sandbox_setting_scopes",
        type_="unique",
    )
    op.drop_constraint(
        "sandbox_setting_scopes_sandbox_setting_id_fkey",
        "sandbox_setting_scopes",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_sandbox_settings_workspace_default",
        table_name="sandbox_settings",
    )
    op.drop_index(
        "ix_sandbox_settings_workspace_id",
        table_name="sandbox_settings",
    )
    op.drop_constraint(
        "uq_sandbox_settings_workspace_name",
        "sandbox_settings",
        type_="unique",
    )

    op.alter_column(
        "agents",
        "sandbox_setting_id",
        new_column_name="shell_environment_id",
        existing_type=sa.String(length=32),
        existing_nullable=True,
    )
    op.alter_column(
        "sandbox_setting_scopes",
        "sandbox_setting_id",
        new_column_name="shell_environment_id",
        existing_type=sa.String(length=32),
        existing_nullable=False,
    )
    op.rename_table("sandbox_setting_scopes", "shell_environment_scopes")
    op.rename_table("sandbox_settings", "shell_environments")

    op.create_unique_constraint(
        "uq_shell_environments_workspace_name",
        "shell_environments",
        ["workspace_id", "name"],
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
    op.create_foreign_key(
        "shell_environment_scopes_shell_environment_id_fkey",
        "shell_environment_scopes",
        "shell_environments",
        ["shell_environment_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_shell_environment_scopes_env_scope",
        "shell_environment_scopes",
        ["shell_environment_id", "scope_type", "scope_id"],
    )
    op.create_index(
        "ix_shell_environment_scopes_env_id",
        "shell_environment_scopes",
        ["shell_environment_id"],
    )
    op.create_foreign_key(
        "agents_shell_environment_id_fkey",
        "agents",
        "shell_environments",
        ["shell_environment_id"],
        ["id"],
        ondelete="SET NULL",
    )
