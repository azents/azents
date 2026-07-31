"""Remove legacy Runtime policy authority."""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "aafb89c5904b"
down_revision: str | Sequence[str] | None = "a8e8788ca12d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RUNTIME_POLICY_SNAPSHOT_APPLICATION_STATE = postgresql.ENUM(
    "pending",
    "applied",
    "divergent",
    "legacy_unverified",
    name="runtime_policy_snapshot_application_state",
    create_type=False,
)
_RUNTIME_EXECUTION_CHANGE_DIRECTION = postgresql.ENUM(
    "metadata_only",
    "restrictive",
    "authority_expanding",
    "mixed",
    "incompatible",
    "application",
    name="runtime_execution_change_direction",
    create_type=False,
)
_RUNTIME_EXECUTION_MANAGEMENT_LAYER = postgresql.ENUM(
    "profile",
    "workspace",
    "agent",
    "runtime",
    name="runtime_execution_management_layer",
    create_type=False,
)
_RUNTIME_EXECUTION_AUDIT_EVENT_TYPE = postgresql.ENUM(
    "profile_created",
    "profile_replaced",
    "profile_retired",
    "workspace_policy_replaced",
    "agent_settings_replaced",
    "target_snapshot_attached",
    "applied_snapshot_promoted",
    name="runtime_execution_audit_event_type",
    create_type=False,
)
_RUNTIME_EXECUTION_PROFILE_LIFECYCLE = postgresql.ENUM(
    "active",
    "retired",
    name="runtime_execution_profile_lifecycle",
    create_type=False,
)
_REMOVED_ENUMS = (
    _RUNTIME_POLICY_SNAPSHOT_APPLICATION_STATE,
    _RUNTIME_EXECUTION_CHANGE_DIRECTION,
    _RUNTIME_EXECUTION_MANAGEMENT_LAYER,
    _RUNTIME_EXECUTION_AUDIT_EVENT_TYPE,
    _RUNTIME_EXECUTION_PROFILE_LIFECYCLE,
)


def upgrade() -> None:
    """Remove replaced execution-policy persistence and Runtime fields."""
    op.add_column(
        "runtime_recreation_operation_items",
        sa.Column("dispatched_generation", sa.Integer(), nullable=True),
    )

    op.drop_constraint(
        "fk_agent_runtimes_applied_runtime_policy_snapshot_id",
        "agent_runtimes",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_agent_runtimes_runtime_policy_snapshot_id",
        "agent_runtimes",
        type_="foreignkey",
    )
    op.drop_column("agent_runtimes", "applied_runtime_policy_snapshot_id")
    op.drop_column("agent_runtimes", "runtime_policy_snapshot_id")
    op.drop_column("agent_runtimes", "provider_config")

    op.drop_table("runtime_policy_snapshots")
    op.drop_table("agent_runtime_provider_overrides")
    op.drop_table("runtime_execution_policy_audit_events")
    op.drop_table("agent_runtime_execution_settings")
    op.drop_table("workspace_runtime_execution_profile_allowances")
    op.drop_table("workspace_runtime_execution_policies")
    op.drop_table("runtime_execution_profiles")

    bind = op.get_bind()
    for enum_type in _REMOVED_ENUMS:
        enum_type.drop(bind, checkfirst=False)


def downgrade() -> None:
    """Restore the legacy schema without reconstructing discarded row data."""
    op.drop_column(
        "runtime_recreation_operation_items",
        "dispatched_generation",
    )

    bind = op.get_bind()
    for enum_type in reversed(_REMOVED_ENUMS):
        enum_type.create(bind, checkfirst=False)

    op.create_table(
        "runtime_execution_profiles",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "lifecycle",
            _RUNTIME_EXECUTION_PROFILE_LIFECYCLE,
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("policy", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("reserved", sa.Boolean(), nullable=False),
        sa.Column("system_key", sa.String(length=120), nullable=True),
        sa.Column("updated_by_user_id", sa.String(length=32), nullable=True),
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
            "version >= 1",
            name="ck_runtime_execution_profiles_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "system_key",
            name="uq_runtime_execution_profiles_system_key",
        ),
    )
    op.create_index(
        "ix_runtime_execution_profiles_lifecycle",
        "runtime_execution_profiles",
        ["lifecycle"],
        unique=False,
    )
    op.create_index(
        "ix_runtime_execution_profiles_updated_by_user_id",
        "runtime_execution_profiles",
        ["updated_by_user_id"],
        unique=False,
    )

    op.create_table(
        "workspace_runtime_execution_policies",
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "restriction",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column(
            "updated_by_workspace_user_id",
            sa.String(length=32),
            nullable=True,
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
        sa.CheckConstraint(
            "version >= 1",
            name="ck_workspace_runtime_execution_policies_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_workspace_user_id"],
            ["workspace_users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("workspace_id"),
    )
    op.create_index(
        "ix_workspace_runtime_exec_policies_updated_by_workspace_user",
        "workspace_runtime_execution_policies",
        ["updated_by_workspace_user_id"],
        unique=False,
    )

    op.create_table(
        "workspace_runtime_execution_profile_allowances",
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("profile_id", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["runtime_execution_profiles.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspace_runtime_execution_policies.workspace_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("workspace_id", "profile_id"),
    )
    op.create_index(
        "ix_workspace_runtime_execution_profile_allowances_profile_id",
        "workspace_runtime_execution_profile_allowances",
        ["profile_id"],
        unique=False,
    )

    op.create_table(
        "agent_runtime_execution_settings",
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column("profile_id", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "restriction",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column(
            "updated_by_workspace_user_id",
            sa.String(length=32),
            nullable=True,
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
        sa.CheckConstraint(
            "version >= 1",
            name="ck_agent_runtime_execution_settings_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["runtime_execution_profiles.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_workspace_user_id"],
            ["workspace_users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("agent_id"),
    )
    op.create_index(
        "ix_agent_runtime_execution_settings_profile_id",
        "agent_runtime_execution_settings",
        ["profile_id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_runtime_exec_settings_updated_by_workspace_user",
        "agent_runtime_execution_settings",
        ["updated_by_workspace_user_id"],
        unique=False,
    )

    op.create_table(
        "runtime_execution_policy_audit_events",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column(
            "event_type",
            _RUNTIME_EXECUTION_AUDIT_EVENT_TYPE,
            nullable=False,
        ),
        sa.Column(
            "management_layer",
            _RUNTIME_EXECUTION_MANAGEMENT_LAYER,
            nullable=False,
        ),
        sa.Column("target_id", sa.String(length=120), nullable=False),
        sa.Column("correlation_id", sa.String(length=120), nullable=False),
        sa.Column(
            "classification",
            _RUNTIME_EXECUTION_CHANGE_DIRECTION,
            nullable=False,
        ),
        sa.Column(
            "changed_paths",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "impact_counts",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("reason_code", sa.String(length=120), nullable=False),
        sa.Column("outcome_code", sa.String(length=120), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("workspace_id", sa.String(length=32), nullable=True),
        sa.Column("agent_id", sa.String(length=32), nullable=True),
        sa.Column("runtime_id", sa.String(length=32), nullable=True),
        sa.Column("actor_user_id", sa.String(length=32), nullable=True),
        sa.Column("actor_workspace_user_id", sa.String(length=32), nullable=True),
        sa.Column("system_authority", sa.Boolean(), nullable=False),
        sa.Column("before_digest", sa.String(length=64), nullable=True),
        sa.Column("after_digest", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["actor_workspace_user_id"],
            ["workspace_users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["runtime_id"],
            ["agent_runtimes.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for index_name, columns in (
        (
            "ix_runtime_execution_policy_audit_events_target_created",
            ["target_id", "created_at"],
        ),
        (
            "ix_runtime_execution_policy_audit_events_workspace_created",
            ["workspace_id", "created_at"],
        ),
        (
            "ix_runtime_execution_policy_audit_events_agent_created",
            ["agent_id", "created_at"],
        ),
        (
            "ix_runtime_execution_policy_audit_events_runtime_created",
            ["runtime_id", "created_at"],
        ),
    ):
        op.create_index(
            index_name,
            "runtime_execution_policy_audit_events",
            columns,
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
            postgresql.ENUM(
                "pending",
                "valid",
                "invalid",
                name="runtime_provider_config_validation_status",
                create_type=False,
            ),
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
        sa.Column("execution_profile_id", sa.String(length=32), nullable=True),
        sa.Column("execution_profile_version", sa.Integer(), nullable=True),
        sa.Column("execution_workspace_version", sa.Integer(), nullable=True),
        sa.Column("execution_agent_version", sa.Integer(), nullable=True),
        sa.Column("resolved_execution_policy_json", sa.Text(), nullable=True),
        sa.Column(
            "execution_source_trace",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "execution_provider_compatibility",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("execution_target_digest", sa.String(length=64), nullable=True),
        sa.Column("execution_reported_digest", sa.String(length=64), nullable=True),
        sa.Column("encrypted_secrets", sa.Text(), nullable=True),
        sa.Column(
            "secret_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "provider_acknowledged_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "runtime_observed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
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
            ["execution_profile_id"],
            ["runtime_execution_profiles.id"],
            name="fk_runtime_policy_snapshots_execution_profile_id",
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
            "target_desired_generation",
            name="uq_runtime_policy_snapshots_runtime_digest_generation",
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
        "agent_runtimes",
        sa.Column("runtime_policy_snapshot_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "agent_runtimes",
        sa.Column(
            "applied_runtime_policy_snapshot_id",
            sa.String(length=32),
            nullable=True,
        ),
    )
    op.add_column(
        "agent_runtimes",
        sa.Column(
            "provider_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_agent_runtimes_runtime_policy_snapshot_id",
        "agent_runtimes",
        "runtime_policy_snapshots",
        ["runtime_policy_snapshot_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_agent_runtimes_applied_runtime_policy_snapshot_id",
        "agent_runtimes",
        "runtime_policy_snapshots",
        ["applied_runtime_policy_snapshot_id"],
        ["id"],
        ondelete="RESTRICT",
    )
