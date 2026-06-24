"""add sandbox provider state

Revision ID: 9e4c85806f1a
Revises: 33f60ccad99c
Create Date: 2026-05-21 17:36:47.370065

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "9e4c85806f1a"
down_revision: str | Sequence[str] | None = "33f60ccad99c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add sandbox provider state tables."""
    sandbox_provider_kind = postgresql.ENUM(
        "k8s",
        "local_docker",
        name="sandbox_provider_kind",
        create_type=False,
    )
    sandbox_provider_scope = postgresql.ENUM(
        "system",
        "workspace",
        name="sandbox_provider_scope",
        create_type=False,
    )
    sandbox_runtime_lease_state = postgresql.ENUM(
        "allocating",
        "starting",
        "running",
        "hibernating",
        "hibernated",
        "deleting",
        "lost",
        name="sandbox_runtime_lease_state",
        create_type=False,
    )
    sandbox_provider_kind.create(op.get_bind())
    sandbox_provider_scope.create(op.get_bind())
    sandbox_runtime_lease_state.create(op.get_bind())

    op.create_table(
        "sandbox_providers",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("provider_id", sa.String(length=120), nullable=False),
        sa.Column("scope", sandbox_provider_scope, nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=True),
        sa.Column("kind", sandbox_provider_kind, nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("draining", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "capabilities",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
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
        sa.CheckConstraint(
            "(scope = 'workspace' AND workspace_id IS NOT NULL) OR "
            "(scope = 'system' AND workspace_id IS NULL)",
            name="ck_sandbox_providers_workspace_scope",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
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
        "sandbox_runtime_leases",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("agent_runtime_id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("provider_id", sa.String(length=120), nullable=False),
        sa.Column("provider_runtime_id", sa.String(length=160), nullable=True),
        sa.Column("allocation_generation", sa.BigInteger(), nullable=False),
        sa.Column("state", sandbox_runtime_lease_state, nullable=False),
        sa.Column("lease_owner", sa.String(length=120), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["agent_runtime_id", "workspace_id"],
            ["agent_runtimes.id", "agent_runtimes.workspace_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_runtime_id",
            "allocation_generation",
            name="uq_sandbox_runtime_leases_runtime_generation",
        ),
    )
    op.create_index(
        "ix_sandbox_runtime_leases_active_runtime",
        "sandbox_runtime_leases",
        ["agent_runtime_id"],
        unique=True,
        postgresql_where=sa.text(
            "state IN ('allocating', 'starting', 'running', 'hibernating', 'deleting')"
        ),
    )
    op.create_index(
        "ix_sandbox_runtime_leases_provider_state",
        "sandbox_runtime_leases",
        ["provider_id", "state"],
    )
    op.create_index(
        "ix_sandbox_runtime_leases_stale",
        "sandbox_runtime_leases",
        ["state", "expires_at"],
        postgresql_where=sa.text("expires_at IS NOT NULL"),
    )
    op.create_index(
        "ix_sandbox_runtime_leases_workspace_id",
        "sandbox_runtime_leases",
        ["workspace_id"],
    )


def downgrade() -> None:
    """Remove sandbox provider state tables."""
    op.drop_index(
        "ix_sandbox_runtime_leases_workspace_id",
        table_name="sandbox_runtime_leases",
    )
    op.drop_index(
        "ix_sandbox_runtime_leases_stale",
        table_name="sandbox_runtime_leases",
        postgresql_where=sa.text("expires_at IS NOT NULL"),
    )
    op.drop_index(
        "ix_sandbox_runtime_leases_provider_state",
        table_name="sandbox_runtime_leases",
    )
    op.drop_index(
        "ix_sandbox_runtime_leases_active_runtime",
        table_name="sandbox_runtime_leases",
        postgresql_where=sa.text(
            "state IN ('allocating', 'starting', 'running', 'hibernating', 'deleting')"
        ),
    )
    op.drop_table("sandbox_runtime_leases")
    op.drop_index("ix_sandbox_providers_workspace_id", table_name="sandbox_providers")
    op.drop_index("ix_sandbox_providers_enabled_scope", table_name="sandbox_providers")
    op.drop_table("sandbox_providers")

    postgresql.ENUM(name="sandbox_runtime_lease_state").drop(op.get_bind())
    postgresql.ENUM(name="sandbox_provider_scope").drop(op.get_bind())
    postgresql.ENUM(name="sandbox_provider_kind").drop(op.get_bind())
