"""Add Runtime execution policy domain."""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f18c05d9d547"
down_revision: str | Sequence[str] | None = "10d8111b556c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROFILE_LIFECYCLE = postgresql.ENUM(
    "active",
    "retired",
    name="runtime_execution_profile_lifecycle",
    create_type=False,
)
_AUDIT_EVENT_TYPE = postgresql.ENUM(
    "platform_policy_replaced",
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
_MANAGEMENT_LAYER = postgresql.ENUM(
    "platform",
    "profile",
    "workspace",
    "agent",
    "runtime",
    name="runtime_execution_management_layer",
    create_type=False,
)
_CHANGE_DIRECTION = postgresql.ENUM(
    "metadata_only",
    "restrictive",
    "authority_expanding",
    "mixed",
    "incompatible",
    "application",
    name="runtime_execution_change_direction",
    create_type=False,
)

_STANDARD_POLICY = {
    "schema_version": 1,
    "image_build": {
        "module_id": "container.image_build",
        "version": 1,
        "enabled": False,
    },
    "container_run": {
        "module_id": "container.run",
        "version": 1,
        "enabled": False,
    },
    "compose": {
        "module_id": "container.compose",
        "version": 1,
        "enabled": False,
    },
    "resources": {
        "module_id": "container.resources",
        "version": 1,
        "cpu_millicores": None,
        "memory_bytes": None,
        "pids": None,
        "container_count": None,
        "ephemeral_storage_bytes": None,
    },
    "engine_storage": {
        "module_id": "engine.storage",
        "version": 1,
        "mode": "none",
        "capacity_bytes": None,
    },
    "network_egress": {
        "module_id": "network.egress",
        "version": 1,
        "mode": "none",
        "allowed_destinations": [],
        "denied_destinations": [],
    },
}
_STANDARD_DIGEST = "277fff74ee7d60ad1f0f26ac30635d6fb6a0844dcf6d89787afa090fbd092c3f"
_EMPTY_RESTRICTION = {
    "schema_version": 1,
    "image_build": None,
    "container_run": None,
    "compose": None,
    "resources": None,
    "engine_storage": None,
    "network_egress": None,
}
_EMPTY_RESTRICTION_DIGEST = (
    "f708ccb0cfe044d9eba4e5ccfcb8d4c5f7f4cd2f110bffde9871654a53ff51ca"
)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    _PROFILE_LIFECYCLE.create(bind, checkfirst=False)
    _AUDIT_EVENT_TYPE.create(bind, checkfirst=False)
    _MANAGEMENT_LAYER.create(bind, checkfirst=False)
    _CHANGE_DIRECTION.create(bind, checkfirst=False)

    op.create_table(
        "runtime_execution_platform_policies",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("policy", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
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
            "id = 'platform'",
            name="ck_runtime_execution_platform_policies_singleton_id",
        ),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_runtime_execution_platform_policies_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_runtime_execution_platform_policies_updated_by_user_id",
        "runtime_execution_platform_policies",
        ["updated_by_user_id"],
        unique=False,
    )

    op.create_table(
        "runtime_execution_profiles",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("lifecycle", _PROFILE_LIFECYCLE, nullable=False),
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
        sa.Column("event_type", _AUDIT_EVENT_TYPE, nullable=False),
        sa.Column("management_layer", _MANAGEMENT_LAYER, nullable=False),
        sa.Column("target_id", sa.String(length=120), nullable=False),
        sa.Column("correlation_id", sa.String(length=120), nullable=False),
        sa.Column("classification", _CHANGE_DIRECTION, nullable=False),
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
    op.create_index(
        "ix_runtime_execution_policy_audit_events_target_created",
        "runtime_execution_policy_audit_events",
        ["target_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_runtime_execution_policy_audit_events_workspace_created",
        "runtime_execution_policy_audit_events",
        ["workspace_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_runtime_execution_policy_audit_events_agent_created",
        "runtime_execution_policy_audit_events",
        ["agent_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_runtime_execution_policy_audit_events_runtime_created",
        "runtime_execution_policy_audit_events",
        ["runtime_id", "created_at"],
        unique=False,
    )

    op.add_column(
        "runtime_policy_snapshots",
        sa.Column("execution_profile_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "runtime_policy_snapshots",
        sa.Column("execution_platform_version", sa.Integer(), nullable=True),
    )
    op.add_column(
        "runtime_policy_snapshots",
        sa.Column("execution_profile_version", sa.Integer(), nullable=True),
    )
    op.add_column(
        "runtime_policy_snapshots",
        sa.Column("execution_workspace_version", sa.Integer(), nullable=True),
    )
    op.add_column(
        "runtime_policy_snapshots",
        sa.Column("execution_agent_version", sa.Integer(), nullable=True),
    )
    op.add_column(
        "runtime_policy_snapshots",
        sa.Column(
            "resolved_execution_policy",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "runtime_policy_snapshots",
        sa.Column(
            "execution_source_trace",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "runtime_policy_snapshots",
        sa.Column(
            "execution_provider_compatibility",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "runtime_policy_snapshots",
        sa.Column("execution_target_digest", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "runtime_policy_snapshots",
        sa.Column("execution_reported_digest", sa.String(length=64), nullable=True),
    )
    op.create_foreign_key(
        "fk_runtime_policy_snapshots_execution_profile_id",
        "runtime_policy_snapshots",
        "runtime_execution_profiles",
        ["execution_profile_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "uq_runtime_policy_snapshots_runtime_digest",
        "runtime_policy_snapshots",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_runtime_policy_snapshots_runtime_digest_generation",
        "runtime_policy_snapshots",
        ["runtime_id", "digest", "target_desired_generation"],
    )

    op.add_column(
        "agent_runtimes",
        sa.Column(
            "applied_runtime_policy_snapshot_id",
            sa.String(length=32),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_agent_runtimes_applied_runtime_policy_snapshot_id",
        "agent_runtimes",
        "runtime_policy_snapshots",
        ["applied_runtime_policy_snapshot_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    standard_policy_json = json.dumps(
        _STANDARD_POLICY,
        sort_keys=True,
        separators=(",", ":"),
    )
    op.execute(
        sa.text(
            """
            INSERT INTO runtime_execution_platform_policies (
                id,
                version,
                policy,
                digest,
                updated_by_user_id
            )
            VALUES (
                'platform',
                1,
                CAST(:policy AS jsonb),
                :digest,
                NULL
            )
            """
        ).bindparams(
            sa.bindparam(
                "policy",
                value=standard_policy_json,
                type_=sa.String(),
                literal_execute=True,
            ),
            sa.bindparam(
                "digest",
                value=_STANDARD_DIGEST,
                type_=sa.String(),
                literal_execute=True,
            ),
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO runtime_execution_profiles (
                id,
                display_name,
                description,
                lifecycle,
                version,
                policy,
                digest,
                reserved,
                system_key,
                updated_by_user_id
            )
            VALUES (
                'system-standard',
                'Standard',
                'Baseline Runtime environment without optional container authority.',
                'active',
                1,
                CAST(:policy AS jsonb),
                :digest,
                TRUE,
                'system-standard',
                NULL
            )
            """
        ).bindparams(
            sa.bindparam(
                "policy",
                value=standard_policy_json,
                type_=sa.String(),
                literal_execute=True,
            ),
            sa.bindparam(
                "digest",
                value=_STANDARD_DIGEST,
                type_=sa.String(),
                literal_execute=True,
            ),
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO workspace_runtime_execution_policies (
                workspace_id,
                version,
                restriction,
                digest,
                updated_by_workspace_user_id,
                created_at,
                updated_at
            )
            SELECT
                id,
                1,
                CAST(:restriction AS jsonb),
                :digest,
                NULL,
                created_at,
                updated_at
            FROM workspaces
            """
        ).bindparams(
            restriction=json.dumps(
                _EMPTY_RESTRICTION,
                sort_keys=True,
                separators=(",", ":"),
            ),
            digest=_EMPTY_RESTRICTION_DIGEST,
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO workspace_runtime_execution_profile_allowances (
                workspace_id,
                profile_id,
                created_at
            )
            SELECT id, 'system-standard', created_at
            FROM workspaces
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO agent_runtime_execution_settings (
                agent_id,
                profile_id,
                version,
                restriction,
                digest,
                updated_by_workspace_user_id,
                created_at,
                updated_at
            )
            SELECT
                id,
                'system-standard',
                1,
                CAST(:restriction AS jsonb),
                :digest,
                NULL,
                created_at,
                updated_at
            FROM agents
            """
        ).bindparams(
            restriction=json.dumps(
                _EMPTY_RESTRICTION,
                sort_keys=True,
                separators=(",", ":"),
            ),
            digest=_EMPTY_RESTRICTION_DIGEST,
        )
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "fk_agent_runtimes_applied_runtime_policy_snapshot_id",
        "agent_runtimes",
        type_="foreignkey",
    )
    op.drop_column("agent_runtimes", "applied_runtime_policy_snapshot_id")

    op.drop_constraint(
        "uq_runtime_policy_snapshots_runtime_digest_generation",
        "runtime_policy_snapshots",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_runtime_policy_snapshots_runtime_digest",
        "runtime_policy_snapshots",
        ["runtime_id", "digest"],
    )
    op.drop_constraint(
        "fk_runtime_policy_snapshots_execution_profile_id",
        "runtime_policy_snapshots",
        type_="foreignkey",
    )
    op.drop_column("runtime_policy_snapshots", "execution_reported_digest")
    op.drop_column("runtime_policy_snapshots", "execution_target_digest")
    op.drop_column("runtime_policy_snapshots", "execution_provider_compatibility")
    op.drop_column("runtime_policy_snapshots", "execution_source_trace")
    op.drop_column("runtime_policy_snapshots", "resolved_execution_policy")
    op.drop_column("runtime_policy_snapshots", "execution_agent_version")
    op.drop_column("runtime_policy_snapshots", "execution_workspace_version")
    op.drop_column("runtime_policy_snapshots", "execution_profile_version")
    op.drop_column("runtime_policy_snapshots", "execution_platform_version")
    op.drop_column("runtime_policy_snapshots", "execution_profile_id")

    op.drop_index(
        "ix_runtime_execution_policy_audit_events_runtime_created",
        table_name="runtime_execution_policy_audit_events",
    )
    op.drop_index(
        "ix_runtime_execution_policy_audit_events_agent_created",
        table_name="runtime_execution_policy_audit_events",
    )
    op.drop_index(
        "ix_runtime_execution_policy_audit_events_workspace_created",
        table_name="runtime_execution_policy_audit_events",
    )
    op.drop_index(
        "ix_runtime_execution_policy_audit_events_target_created",
        table_name="runtime_execution_policy_audit_events",
    )
    op.drop_table("runtime_execution_policy_audit_events")
    op.drop_index(
        "ix_agent_runtime_exec_settings_updated_by_workspace_user",
        table_name="agent_runtime_execution_settings",
    )
    op.drop_index(
        "ix_agent_runtime_execution_settings_profile_id",
        table_name="agent_runtime_execution_settings",
    )
    op.drop_table("agent_runtime_execution_settings")
    op.drop_index(
        "ix_workspace_runtime_execution_profile_allowances_profile_id",
        table_name="workspace_runtime_execution_profile_allowances",
    )
    op.drop_table("workspace_runtime_execution_profile_allowances")
    op.drop_index(
        "ix_workspace_runtime_exec_policies_updated_by_workspace_user",
        table_name="workspace_runtime_execution_policies",
    )
    op.drop_table("workspace_runtime_execution_policies")
    op.drop_index(
        "ix_runtime_execution_profiles_updated_by_user_id",
        table_name="runtime_execution_profiles",
    )
    op.drop_index(
        "ix_runtime_execution_profiles_lifecycle",
        table_name="runtime_execution_profiles",
    )
    op.drop_table("runtime_execution_profiles")
    op.drop_index(
        "ix_runtime_execution_platform_policies_updated_by_user_id",
        table_name="runtime_execution_platform_policies",
    )
    op.drop_table("runtime_execution_platform_policies")

    bind = op.get_bind()
    _CHANGE_DIRECTION.drop(bind, checkfirst=False)
    _MANAGEMENT_LAYER.drop(bind, checkfirst=False)
    _AUDIT_EVENT_TYPE.drop(bind, checkfirst=False)
    _PROFILE_LIFECYCLE.drop(bind, checkfirst=False)
