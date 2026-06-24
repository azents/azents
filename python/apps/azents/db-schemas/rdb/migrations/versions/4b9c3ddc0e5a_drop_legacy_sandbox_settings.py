"""drop legacy sandbox settings

Revision ID: 4b9c3ddc0e5a
Revises: 1524a89eb0e2
Create Date: 2026-05-25 18:08:00.000000

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "4b9c3ddc0e5a"
down_revision: str | Sequence[str] | None = "1524a89eb0e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove legacy sandbox setting source-of-truth tables."""
    op.drop_constraint(
        "agents_sandbox_setting_id_fkey",
        "agents",
        type_="foreignkey",
    )
    op.drop_column("agents", "sandbox_setting_id")
    op.drop_index(
        "ix_sandbox_setting_scopes_setting_id",
        table_name="sandbox_setting_scopes",
    )
    op.drop_constraint(
        "uq_sandbox_setting_scopes_setting_scope",
        "sandbox_setting_scopes",
        type_="unique",
    )
    op.drop_table("sandbox_setting_scopes")
    op.drop_index(
        "ix_sandbox_settings_sandbox_provider_id",
        table_name="sandbox_settings",
    )
    op.drop_index(
        "ix_sandbox_settings_workspace_default",
        table_name="sandbox_settings",
    )
    op.drop_index("ix_sandbox_settings_workspace_id", table_name="sandbox_settings")
    op.drop_constraint(
        "uq_sandbox_settings_workspace_name",
        "sandbox_settings",
        type_="unique",
    )
    op.drop_table("sandbox_settings")
    op.drop_index("ix_sandbox_providers_workspace_id", table_name="sandbox_providers")
    op.drop_index("ix_sandbox_providers_enabled_scope", table_name="sandbox_providers")
    op.drop_constraint(
        "uq_sandbox_providers_provider_id",
        "sandbox_providers",
        type_="unique",
    )
    op.drop_constraint(
        "ck_sandbox_providers_workspace_scope",
        "sandbox_providers",
        type_="check",
    )
    op.drop_table("sandbox_providers")
    op.execute("DROP TYPE IF EXISTS sandbox_provider_kind")
    op.execute("DROP TYPE IF EXISTS sandbox_provider_scope")


def downgrade() -> None:
    """Restore legacy tables for rollback only."""
    op.execute("CREATE TYPE sandbox_provider_kind AS ENUM ('k8s', 'docker', 'local')")
    op.execute("CREATE TYPE sandbox_provider_scope AS ENUM ('system', 'workspace')")
    sandbox_provider_kind = postgresql.ENUM(
        "k8s",
        "docker",
        "local",
        name="sandbox_provider_kind",
        create_type=False,
    )
    sandbox_provider_scope = postgresql.ENUM(
        "system",
        "workspace",
        name="sandbox_provider_scope",
        create_type=False,
    )
    op.create_table(
        "sandbox_providers",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("provider_id", sa.String(length=120), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=True),
        sa.Column("scope", sandbox_provider_scope, nullable=False),
        sa.Column("kind", sandbox_provider_kind, nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("draining", sa.Boolean(), nullable=False),
        sa.Column("capabilities", postgresql.JSONB(), nullable=False),
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
        sa.CheckConstraint(
            "(scope = 'system' AND workspace_id IS NULL) OR "
            "(scope = 'workspace' AND workspace_id IS NOT NULL)",
            name="ck_sandbox_providers_workspace_scope",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_id", name="uq_sandbox_providers_provider_id"),
    )
    op.create_index(
        "ix_sandbox_providers_enabled_scope",
        "sandbox_providers",
        ["enabled", "scope"],
    )
    op.create_index(
        "ix_sandbox_providers_workspace_id",
        "sandbox_providers",
        ["workspace_id"],
    )
    op.create_table(
        "sandbox_settings",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("allowed_domains", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("denied_domains", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("environment_variables", postgresql.JSONB(), nullable=False),
        sa.Column("sandbox_provider_id", sa.String(length=120), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False),
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
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "name",
            name="uq_sandbox_settings_workspace_name",
        ),
    )
    op.create_index(
        "ix_sandbox_settings_workspace_id",
        "sandbox_settings",
        ["workspace_id"],
    )
    op.create_index(
        "ix_sandbox_settings_workspace_default",
        "sandbox_settings",
        ["workspace_id", "is_default"],
    )
    op.create_index(
        "ix_sandbox_settings_sandbox_provider_id",
        "sandbox_settings",
        ["sandbox_provider_id"],
    )
    op.create_table(
        "sandbox_setting_scopes",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("sandbox_setting_id", sa.String(length=32), nullable=False),
        sa.Column("scope_type", sa.String(length=20), nullable=False),
        sa.Column("scope_id", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["sandbox_setting_id"],
            ["sandbox_settings.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "sandbox_setting_id",
            "scope_type",
            "scope_id",
            name="uq_sandbox_setting_scopes_setting_scope",
        ),
    )
    op.create_index(
        "ix_sandbox_setting_scopes_setting_id",
        "sandbox_setting_scopes",
        ["sandbox_setting_id"],
    )
    op.add_column(
        "agents",
        sa.Column("sandbox_setting_id", sa.String(length=32), nullable=True),
    )
    op.create_foreign_key(
        "agents_sandbox_setting_id_fkey",
        "agents",
        "sandbox_settings",
        ["sandbox_setting_id"],
        ["id"],
        ondelete="SET NULL",
    )
