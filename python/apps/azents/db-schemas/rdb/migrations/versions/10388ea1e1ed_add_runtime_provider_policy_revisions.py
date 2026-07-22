"""add runtime provider policy revisions

Revision ID: 10388ea1e1ed
Revises: 8d1ff4cc92a1
Create Date: 2026-07-22 15:28:17.541442

"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from azents.rdb.types.datetime import TimeZoneDateTime

# revision identifiers, used by Alembic.
revision: str = "10388ea1e1ed"
down_revision: str | Sequence[str] | None = "8d1ff4cc92a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RUNTIME_PROVIDER_CONTRACT_STATUS = postgresql.ENUM(
    "candidate",
    "accepted",
    "rejected",
    "superseded",
    name="runtime_provider_contract_status",
    create_type=False,
)
_RUNTIME_PROVIDER_CONFIG_REVISION_STATE = postgresql.ENUM(
    "candidate",
    "provider_accepted",
    "active",
    "superseded",
    "rejected",
    "divergent",
    name="runtime_provider_config_revision_state",
    create_type=False,
)
_RUNTIME_PROVIDER_CONFIG_VALIDATION_STATUS = postgresql.ENUM(
    "pending",
    "valid",
    "invalid",
    name="runtime_provider_config_validation_status",
    create_type=False,
)
_RUNTIME_PROVIDER_BINDING_ORIGIN = postgresql.ENUM(
    "agent_preference",
    "platform_default",
    "migration",
    name="runtime_provider_binding_origin",
    create_type=False,
)
_RUNTIME_POLICY_SNAPSHOT_APPLICATION_STATE = postgresql.ENUM(
    "pending",
    "applied",
    "divergent",
    "legacy_unverified",
    name="runtime_policy_snapshot_application_state",
    create_type=False,
)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    for enum_type in (
        _RUNTIME_PROVIDER_CONTRACT_STATUS,
        _RUNTIME_PROVIDER_CONFIG_REVISION_STATE,
        _RUNTIME_PROVIDER_CONFIG_VALIDATION_STATUS,
        _RUNTIME_PROVIDER_BINDING_ORIGIN,
        _RUNTIME_POLICY_SNAPSHOT_APPLICATION_STATE,
    ):
        enum_type.create(bind, checkfirst=True)

    op.add_column(
        "agent_runtimes",
        sa.Column("runtime_provider_resource_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "agent_runtimes",
        sa.Column(
            "provider_binding_origin",
            _RUNTIME_PROVIDER_BINDING_ORIGIN,
            nullable=True,
        ),
    )
    op.add_column(
        "agent_runtimes",
        sa.Column(
            "provider_binding_evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_agent_runtimes_runtime_provider_resource_id",
        "agent_runtimes",
        "runtime_providers",
        ["runtime_provider_resource_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_agent_runtimes_runtime_provider_resource_id",
        "agent_runtimes",
        ["runtime_provider_resource_id"],
        unique=False,
    )

    op.create_table(
        "runtime_provider_contract_revisions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("provider_id", sa.String(length=32), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("implementation_version", sa.String(length=120), nullable=False),
        sa.Column("protocol_version", sa.String(length=120), nullable=False),
        sa.Column("contract", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "compatibility",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("status", _RUNTIME_PROVIDER_CONTRACT_STATUS, nullable=False),
        sa.Column("validation_code", sa.String(length=120), nullable=True),
        sa.Column("validation_message", sa.Text(), nullable=True),
        sa.Column("accepted_by_user_id", sa.String(length=32), nullable=True),
        sa.Column("accepted_at", TimeZoneDateTime(), nullable=True),
        sa.Column("rejected_by_user_id", sa.String(length=32), nullable=True),
        sa.Column("rejected_at", TimeZoneDateTime(), nullable=True),
        sa.Column(
            "created_at",
            TimeZoneDateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["accepted_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["runtime_providers.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["rejected_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider_id",
            "digest",
            name="uq_runtime_provider_contract_revisions_provider_digest",
        ),
    )
    op.create_index(
        "ix_runtime_provider_contract_revisions_provider_created",
        "runtime_provider_contract_revisions",
        ["provider_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_runtime_provider_contract_revisions_provider_status",
        "runtime_provider_contract_revisions",
        ["provider_id", "status"],
        unique=False,
    )

    op.create_table(
        "runtime_provider_config_revisions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("provider_id", sa.String(length=32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("base_revision_id", sa.String(length=32), nullable=True),
        sa.Column("contract_revision_id", sa.String(length=32), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "state",
            _RUNTIME_PROVIDER_CONFIG_REVISION_STATE,
            nullable=False,
        ),
        sa.Column(
            "validation_status",
            _RUNTIME_PROVIDER_CONFIG_VALIDATION_STATUS,
            nullable=False,
        ),
        sa.Column("encrypted_secrets", sa.Text(), nullable=True),
        sa.Column(
            "secret_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("validation_request_id", sa.String(length=32), nullable=True),
        sa.Column("validation_code", sa.String(length=120), nullable=True),
        sa.Column("validation_message", sa.Text(), nullable=True),
        sa.Column(
            "validation_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("impact", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=32), nullable=True),
        sa.Column("activated_by_user_id", sa.String(length=32), nullable=True),
        sa.Column("activated_at", TimeZoneDateTime(), nullable=True),
        sa.Column(
            "created_at",
            TimeZoneDateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            TimeZoneDateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["activated_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["contract_revision_id"],
            ["runtime_provider_contract_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["runtime_providers.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider_id",
            "revision",
            name="uq_runtime_provider_config_revisions_provider_revision",
        ),
    )
    op.create_foreign_key(
        "fk_runtime_provider_config_revisions_base_revision_id",
        "runtime_provider_config_revisions",
        "runtime_provider_config_revisions",
        ["base_revision_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_runtime_provider_config_revisions_provider_state",
        "runtime_provider_config_revisions",
        ["provider_id", "state"],
        unique=False,
    )
    op.create_index(
        "ix_runtime_provider_config_revisions_validation_request",
        "runtime_provider_config_revisions",
        ["validation_request_id"],
        unique=False,
    )

    op.create_table(
        "agent_runtime_provider_overrides",
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column("provider_id", sa.String(length=32), nullable=False),
        sa.Column("contract_revision_id", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "validation_status",
            _RUNTIME_PROVIDER_CONFIG_VALIDATION_STATUS,
            nullable=False,
        ),
        sa.Column("encrypted_secrets", sa.Text(), nullable=True),
        sa.Column(
            "secret_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("updated_by_user_id", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            TimeZoneDateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            TimeZoneDateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["contract_revision_id"],
            ["runtime_provider_contract_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["runtime_providers.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("agent_id", "provider_id"),
    )
    op.create_index(
        "ix_agent_runtime_provider_overrides_provider_id",
        "agent_runtime_provider_overrides",
        ["provider_id"],
        unique=False,
    )

    op.create_table(
        "runtime_policy_snapshots",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("runtime_id", sa.String(length=32), nullable=False),
        sa.Column("provider_id", sa.String(length=32), nullable=False),
        sa.Column("contract_revision_id", sa.String(length=32), nullable=False),
        sa.Column(
            "resolved_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "source_trace",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("target_desired_generation", sa.Integer(), nullable=False),
        sa.Column(
            "application_state",
            _RUNTIME_POLICY_SNAPSHOT_APPLICATION_STATE,
            nullable=False,
        ),
        sa.Column("config_revision_id", sa.String(length=32), nullable=True),
        sa.Column("override_provider_id", sa.String(length=32), nullable=True),
        sa.Column("override_version", sa.Integer(), nullable=True),
        sa.Column("encrypted_secrets", sa.Text(), nullable=True),
        sa.Column(
            "secret_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("provider_acknowledged_at", TimeZoneDateTime(), nullable=True),
        sa.Column("runtime_observed_at", TimeZoneDateTime(), nullable=True),
        sa.Column(
            "created_at",
            TimeZoneDateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["config_revision_id"],
            ["runtime_provider_config_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["contract_revision_id"],
            ["runtime_provider_contract_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["runtime_providers.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["runtime_id"],
            ["agent_runtimes.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "runtime_id",
            "digest",
            name="uq_runtime_policy_snapshots_runtime_digest",
        ),
    )
    op.create_index(
        "ix_runtime_policy_snapshots_runtime_created",
        "runtime_policy_snapshots",
        ["runtime_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_runtime_policy_snapshots_provider_created",
        "runtime_policy_snapshots",
        ["provider_id", "created_at"],
        unique=False,
    )

    op.add_column(
        "runtime_providers",
        sa.Column("accepted_contract_revision_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "runtime_providers",
        sa.Column("active_config_revision_id", sa.String(length=32), nullable=True),
    )
    op.create_foreign_key(
        "fk_runtime_providers_accepted_contract_revision_id",
        "runtime_providers",
        "runtime_provider_contract_revisions",
        ["accepted_contract_revision_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_runtime_providers_active_config_revision_id",
        "runtime_providers",
        "runtime_provider_config_revisions",
        ["active_config_revision_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.add_column(
        "agent_runtimes",
        sa.Column("runtime_policy_snapshot_id", sa.String(length=32), nullable=True),
    )
    op.create_foreign_key(
        "fk_agent_runtimes_runtime_policy_snapshot_id",
        "agent_runtimes",
        "runtime_policy_snapshots",
        ["runtime_policy_snapshot_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "fk_agent_runtimes_runtime_policy_snapshot_id",
        "agent_runtimes",
        type_="foreignkey",
    )
    op.drop_column("agent_runtimes", "runtime_policy_snapshot_id")
    op.drop_constraint(
        "fk_runtime_providers_active_config_revision_id",
        "runtime_providers",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_runtime_providers_accepted_contract_revision_id",
        "runtime_providers",
        type_="foreignkey",
    )
    op.drop_column("runtime_providers", "active_config_revision_id")
    op.drop_column("runtime_providers", "accepted_contract_revision_id")
    op.drop_table("runtime_policy_snapshots")
    op.drop_table("agent_runtime_provider_overrides")
    op.drop_constraint(
        "fk_runtime_provider_config_revisions_base_revision_id",
        "runtime_provider_config_revisions",
        type_="foreignkey",
    )
    op.drop_table("runtime_provider_config_revisions")
    op.drop_table("runtime_provider_contract_revisions")
    op.drop_index(
        "ix_agent_runtimes_runtime_provider_resource_id",
        table_name="agent_runtimes",
    )
    op.drop_constraint(
        "fk_agent_runtimes_runtime_provider_resource_id",
        "agent_runtimes",
        type_="foreignkey",
    )
    op.drop_column("agent_runtimes", "provider_binding_evidence")
    op.drop_column("agent_runtimes", "provider_binding_origin")
    op.drop_column("agent_runtimes", "runtime_provider_resource_id")

    bind = op.get_bind()
    for enum_type in (
        _RUNTIME_POLICY_SNAPSHOT_APPLICATION_STATE,
        _RUNTIME_PROVIDER_BINDING_ORIGIN,
        _RUNTIME_PROVIDER_CONFIG_VALIDATION_STATUS,
        _RUNTIME_PROVIDER_CONFIG_REVISION_STATE,
        _RUNTIME_PROVIDER_CONTRACT_STATUS,
    ):
        enum_type.drop(bind, checkfirst=True)
