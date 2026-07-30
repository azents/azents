import copy
import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "a8e8788ca12d"
down_revision: str | Sequence[str] | None = "24a6ab0f0b98"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MIGRATION_DESCRIPTION_PREFIX = "[legacy-runtime-profile-migration] "
_STANDARD_POLICY: dict[str, Any] = {
    "schema_version": 1,
    "docker": {
        "module_id": "docker",
        "version": 1,
        "enabled": False,
        "storage_mode": "none",
        "storage_capacity_bytes": None,
    },
    "resources": {
        "module_id": "runtime.resources",
        "version": 1,
        "cpu_request_millicores": None,
        "cpu_limit_millicores": None,
        "memory_request_bytes": None,
        "memory_limit_bytes": None,
        "ephemeral_storage_bytes": None,
        "persistent_storage_bytes": None,
    },
}
_EMPTY_WORKSPACE_POLICY = {"schema_version": 1, "network_restriction": None}


def upgrade() -> None:
    """Upgrade schema and convert deterministic legacy Agent selections."""
    op.add_column(
        "workspaces",
        sa.Column("default_runtime_profile_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "workspaces",
        sa.Column(
            "default_runtime_profile_version",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_workspaces_default_runtime_profile_version_positive",
        "workspaces",
        "default_runtime_profile_version >= 1",
    )
    op.create_index(
        "ix_workspaces_default_runtime_profile_id",
        "workspaces",
        ["default_runtime_profile_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_workspaces_default_runtime_profile_id",
        "workspaces",
        "workspace_runtime_profiles",
        ["default_runtime_profile_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.add_column(
        "agents", sa.Column("runtime_profile_id", sa.String(length=32), nullable=True)
    )
    op.add_column(
        "agents",
        sa.Column(
            "runtime_profile_selection_version",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_agents_runtime_profile_selection_version_positive",
        "agents",
        "runtime_profile_selection_version >= 1",
    )
    op.create_index(
        "ix_agents_runtime_profile_id",
        "agents",
        ["runtime_profile_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_agents_runtime_profile_id",
        "agents",
        "workspace_runtime_profiles",
        ["runtime_profile_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.alter_column(
        "runtime_configuration_revisions",
        "provider_capability_revision_id",
        existing_type=sa.String(length=32),
        nullable=True,
    )
    op.add_column(
        "runtime_configuration_revisions",
        sa.Column(
            "agent_selection_version",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
    )
    op.alter_column(
        "runtime_configuration_revisions",
        "agent_selection_version",
        server_default=None,
    )
    op.create_check_constraint(
        "ck_runtime_configuration_revisions_agent_selection_version",
        "runtime_configuration_revisions",
        "agent_selection_version >= 1",
    )
    op.create_check_constraint(
        "ck_runtime_configuration_revisions_ready_capability",
        "runtime_configuration_revisions",
        "resolution_status = 'blocked' OR provider_capability_revision_id IS NOT NULL",
    )

    op.add_column(
        "agent_runtimes",
        sa.Column("infrastructure_profile_id", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "agent_runtimes",
        sa.Column(
            "workspace_runtime_profile_id",
            sa.String(length=32),
            nullable=True,
        ),
    )
    op.add_column(
        "agent_runtimes",
        sa.Column(
            "desired_runtime_configuration_revision_id",
            sa.String(length=32),
            nullable=True,
        ),
    )
    op.add_column(
        "agent_runtimes",
        sa.Column(
            "applied_runtime_configuration_revision_id",
            sa.String(length=32),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_agent_runtimes_infrastructure_profile_id",
        "agent_runtimes",
        ["infrastructure_profile_id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_runtimes_workspace_runtime_profile_id",
        "agent_runtimes",
        ["workspace_runtime_profile_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_agent_runtimes_infrastructure_profile_id",
        "agent_runtimes",
        "runtime_infrastructure_profiles",
        ["infrastructure_profile_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_agent_runtimes_workspace_runtime_profile_id",
        "agent_runtimes",
        "workspace_runtime_profiles",
        ["workspace_runtime_profile_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_agent_runtimes_desired_runtime_configuration_revision_id",
        "agent_runtimes",
        "runtime_configuration_revisions",
        ["desired_runtime_configuration_revision_id"],
        ["id"],
        ondelete="RESTRICT",
        use_alter=True,
    )
    op.create_foreign_key(
        "fk_agent_runtimes_applied_runtime_configuration_revision_id",
        "agent_runtimes",
        "runtime_configuration_revisions",
        ["applied_runtime_configuration_revision_id"],
        ["id"],
        ondelete="RESTRICT",
        use_alter=True,
    )

    _convert_legacy_agent_selections(op.get_bind())

    op.drop_index("ix_agents_runtime_provider_id", table_name="agents")
    op.drop_column("agents", "runtime_provider_id")


def downgrade() -> None:
    """Restore the legacy logical Provider preference column."""
    op.add_column(
        "agents",
        sa.Column("runtime_provider_id", sa.String(length=120), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE agents AS agent
            SET runtime_provider_id = provider.provider_id
            FROM workspace_runtime_profiles AS profile
            JOIN runtime_providers AS provider ON provider.id = profile.provider_id
            WHERE agent.runtime_profile_id = profile.id
            """
        )
    )
    op.create_index(
        "ix_agents_runtime_provider_id",
        "agents",
        ["runtime_provider_id"],
        unique=False,
    )

    op.drop_constraint(
        "fk_agent_runtimes_applied_runtime_configuration_revision_id",
        "agent_runtimes",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_agent_runtimes_desired_runtime_configuration_revision_id",
        "agent_runtimes",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_agent_runtimes_workspace_runtime_profile_id",
        "agent_runtimes",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_agent_runtimes_infrastructure_profile_id",
        "agent_runtimes",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_agent_runtimes_workspace_runtime_profile_id",
        table_name="agent_runtimes",
    )
    op.drop_index(
        "ix_agent_runtimes_infrastructure_profile_id",
        table_name="agent_runtimes",
    )
    op.drop_column(
        "agent_runtimes",
        "applied_runtime_configuration_revision_id",
    )
    op.drop_column(
        "agent_runtimes",
        "desired_runtime_configuration_revision_id",
    )
    op.drop_column("agent_runtimes", "workspace_runtime_profile_id")
    op.drop_column("agent_runtimes", "infrastructure_profile_id")

    op.drop_constraint("fk_agents_runtime_profile_id", "agents", type_="foreignkey")
    op.drop_index("ix_agents_runtime_profile_id", table_name="agents")
    op.drop_constraint(
        "ck_agents_runtime_profile_selection_version_positive",
        "agents",
        type_="check",
    )
    op.drop_column("agents", "runtime_profile_selection_version")
    op.drop_column("agents", "runtime_profile_id")

    op.drop_constraint(
        "fk_workspaces_default_runtime_profile_id",
        "workspaces",
        type_="foreignkey",
    )
    op.drop_index("ix_workspaces_default_runtime_profile_id", table_name="workspaces")
    op.drop_constraint(
        "ck_workspaces_default_runtime_profile_version_positive",
        "workspaces",
        type_="check",
    )
    op.drop_column("workspaces", "default_runtime_profile_version")
    op.drop_column("workspaces", "default_runtime_profile_id")

    connection = op.get_bind()
    incompatible_revision_id = connection.execute(
        sa.text(
            """
            SELECT id
            FROM runtime_configuration_revisions
            WHERE provider_capability_revision_id IS NULL
              AND source_trace ->> 'migration' IS DISTINCT FROM
                  'legacy_runtime_profile_cutover'
            LIMIT 1
            """
        )
    ).scalar_one_or_none()
    if incompatible_revision_id is not None:
        raise RuntimeError(
            "Cannot downgrade while non-migration blocked Runtime configuration "
            f"revision {incompatible_revision_id} has no Provider capability."
        )
    connection.execute(
        sa.text(
            """
            DELETE FROM runtime_configuration_revisions
            WHERE source_trace ->> 'migration' = 'legacy_runtime_profile_cutover'
            """
        )
    )
    connection.execute(
        sa.text(
            """
            DELETE FROM workspace_runtime_profiles
            WHERE description LIKE :prefix
            """
        ),
        {"prefix": f"{_MIGRATION_DESCRIPTION_PREFIX}%"},
    )
    connection.execute(
        sa.text(
            """
            DELETE FROM runtime_infrastructure_profiles AS infrastructure
            WHERE infrastructure.description LIKE :prefix
              AND NOT EXISTS (
                SELECT 1
                FROM workspace_runtime_profiles AS profile
                WHERE profile.infrastructure_profile_id = infrastructure.id
              )
            """
        ),
        {"prefix": f"{_MIGRATION_DESCRIPTION_PREFIX}%"},
    )
    op.drop_constraint(
        "ck_runtime_configuration_revisions_ready_capability",
        "runtime_configuration_revisions",
        type_="check",
    )
    op.drop_constraint(
        "ck_runtime_configuration_revisions_agent_selection_version",
        "runtime_configuration_revisions",
        type_="check",
    )
    op.drop_column(
        "runtime_configuration_revisions",
        "agent_selection_version",
    )
    op.alter_column(
        "runtime_configuration_revisions",
        "provider_capability_revision_id",
        existing_type=sa.String(length=32),
        nullable=False,
    )


def _convert_legacy_agent_selections(connection: sa.Connection) -> None:
    platform_default = connection.execute(
        sa.text(
            """
            SELECT config
            FROM system_settings
            WHERE section = 'platform_runtime'
            """
        )
    ).scalar_one_or_none()
    platform_default_id = _as_object(platform_default).get("default_provider_id")

    rows = connection.execute(
        sa.text(
            """
            SELECT
                agent.id AS agent_id,
                agent.workspace_id,
                agent.runtime_provider_id AS agent_provider_id,
                runtime.id AS runtime_id,
                runtime.runtime_provider_id AS bound_provider_id,
                runtime.desired_generation AS runtime_desired_generation,
                runtime.applied_runtime_policy_snapshot_id
                    AS applied_runtime_policy_snapshot_id,
                setting.version AS agent_setting_version,
                setting.restriction AS agent_restriction,
                profile.version AS execution_profile_version,
                profile.policy AS execution_profile_policy,
                workspace_policy.version AS workspace_policy_version,
                workspace_policy.restriction AS workspace_restriction
            FROM agents AS agent
            LEFT JOIN agent_runtimes AS runtime ON runtime.agent_id = agent.id
            LEFT JOIN agent_runtime_execution_settings AS setting
                ON setting.agent_id = agent.id
            LEFT JOIN runtime_execution_profiles AS profile
                ON profile.id = setting.profile_id
            LEFT JOIN workspace_runtime_execution_policies AS workspace_policy
                ON workspace_policy.workspace_id = agent.workspace_id
            ORDER BY agent.id
            """
        )
    ).mappings()

    infrastructure_ids: dict[tuple[str, str], str] = {}
    workspace_profile_ids: dict[tuple[str, str], str] = {}
    for row in rows:
        logical_provider_id = (
            row["agent_provider_id"] or row["bound_provider_id"] or platform_default_id
        )
        if logical_provider_id is None:
            continue
        if not isinstance(logical_provider_id, str):
            raise RuntimeError(
                f"Cannot migrate Agent {row['agent_id']}: Runtime Provider "
                "selection is not a string."
            )
        provider = (
            connection.execute(
                sa.text(
                    """
                SELECT
                    provider.id,
                    provider.kind,
                    provider.current_contract_revision_id,
                    capability.digest AS capability_digest
                FROM runtime_providers AS provider
                LEFT JOIN runtime_provider_contract_revisions AS capability
                    ON capability.id = provider.current_contract_revision_id
                WHERE provider.provider_id = :provider_id
                """
                ),
                {"provider_id": logical_provider_id},
            )
            .mappings()
            .one_or_none()
        )
        if provider is None:
            raise RuntimeError(
                f"Cannot migrate Agent {row['agent_id']}: Runtime Provider "
                f"{logical_provider_id!r} does not exist."
            )

        effective_policy = _resolve_legacy_policy(
            profile_policy=row["execution_profile_policy"],
            workspace_restriction=row["workspace_restriction"],
            agent_restriction=row["agent_restriction"],
        )
        spec, contract_family, profile_kind, required_capabilities = (
            _build_infrastructure_spec(str(provider["kind"]), effective_policy)
        )
        spec_digest = _digest(spec)
        provider_id = str(provider["id"])
        infrastructure_key = (provider_id, spec_digest)
        infrastructure_id = infrastructure_ids.get(infrastructure_key)
        if infrastructure_id is None:
            infrastructure_id = _stable_id(
                "legacy-infrastructure", provider_id, spec_digest
            )
            description = _migration_description(
                legacy_policy=effective_policy,
                source={
                    "provider_logical_id": logical_provider_id,
                    "execution_profile_version": row["execution_profile_version"],
                    "workspace_policy_version": row["workspace_policy_version"],
                    "agent_setting_version": row["agent_setting_version"],
                },
            )
            connection.execute(
                sa.text(
                    """
                    INSERT INTO runtime_infrastructure_profiles (
                        id,
                        provider_id,
                        profile_kind,
                        display_name,
                        description,
                        lifecycle,
                        contract_family,
                        schema_version,
                        spec,
                        required_capabilities,
                        version,
                        digest,
                        created_by_user_id,
                        updated_by_user_id
                    ) VALUES (
                        :id,
                        :provider_id,
                        CAST(:profile_kind AS runtime_infrastructure_profile_kind),
                        :display_name,
                        :description,
                        CAST('active' AS runtime_profile_lifecycle),
                        :contract_family,
                        1,
                        CAST(:spec AS jsonb),
                        CAST(:required_capabilities AS jsonb),
                        1,
                        :digest,
                        NULL,
                        NULL
                    )
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {
                    "id": infrastructure_id,
                    "provider_id": provider_id,
                    "profile_kind": profile_kind,
                    "display_name": f"Migrated {profile_kind} {spec_digest[:8]}",
                    "description": description,
                    "contract_family": contract_family,
                    "spec": _canonical_json(spec),
                    "required_capabilities": _canonical_json(required_capabilities),
                    "digest": spec_digest,
                },
            )
            infrastructure_ids[infrastructure_key] = infrastructure_id

        workspace_id = str(row["workspace_id"])
        workspace_key = (workspace_id, infrastructure_id)
        workspace_profile_id = workspace_profile_ids.get(workspace_key)
        workspace_digest = _digest(
            {
                "provider_id": provider_id,
                "infrastructure_profile_id": infrastructure_id,
                "infrastructure_profile_digest": spec_digest,
                "policy": _EMPTY_WORKSPACE_POLICY,
            }
        )
        if workspace_profile_id is None:
            workspace_profile_id = _stable_id(
                "legacy-workspace-profile", workspace_id, infrastructure_id
            )
            connection.execute(
                sa.text(
                    """
                    INSERT INTO workspace_runtime_profiles (
                        id,
                        workspace_id,
                        provider_id,
                        infrastructure_profile_id,
                        display_name,
                        description,
                        lifecycle,
                        policy,
                        version,
                        digest,
                        created_by_workspace_user_id,
                        updated_by_workspace_user_id
                    ) VALUES (
                        :id,
                        :workspace_id,
                        :provider_id,
                        :infrastructure_profile_id,
                        :display_name,
                        :description,
                        CAST('active' AS runtime_profile_lifecycle),
                        CAST(:policy AS jsonb),
                        1,
                        :digest,
                        NULL,
                        NULL
                    )
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {
                    "id": workspace_profile_id,
                    "workspace_id": workspace_id,
                    "provider_id": provider_id,
                    "infrastructure_profile_id": infrastructure_id,
                    "display_name": f"Migrated Runtime {spec_digest[:8]}",
                    "description": (
                        f"{_MIGRATION_DESCRIPTION_PREFIX}Generated from the "
                        "legacy effective Runtime policy."
                    ),
                    "policy": _canonical_json(_EMPTY_WORKSPACE_POLICY),
                    "digest": workspace_digest,
                },
            )
            workspace_profile_ids[workspace_key] = workspace_profile_id

        selection_version = row["agent_setting_version"]
        connection.execute(
            sa.text(
                """
                UPDATE agents
                SET runtime_profile_id = :runtime_profile_id,
                    runtime_profile_selection_version = :selection_version
                WHERE id = :agent_id
                """
            ),
            {
                "runtime_profile_id": workspace_profile_id,
                "selection_version": (
                    max(1, int(selection_version))
                    if selection_version is not None
                    else 1
                ),
                "agent_id": row["agent_id"],
            },
        )
        runtime_id = row["runtime_id"]
        if runtime_id is not None:
            _attach_migrated_runtime_configuration(
                connection,
                runtime_id=str(runtime_id),
                provider_id=provider_id,
                provider_logical_id=logical_provider_id,
                provider_kind=str(provider["kind"]),
                capability_revision_id=(
                    str(provider["current_contract_revision_id"])
                    if provider["current_contract_revision_id"] is not None
                    else None
                ),
                capability_digest=(
                    str(provider["capability_digest"])
                    if provider["capability_digest"] is not None
                    else None
                ),
                infrastructure_id=infrastructure_id,
                infrastructure_version=1,
                infrastructure_digest=spec_digest,
                workspace_profile_id=workspace_profile_id,
                workspace_profile_version=1,
                workspace_profile_digest=workspace_digest,
                selection_version=(
                    max(1, int(selection_version))
                    if selection_version is not None
                    else 1
                ),
                legacy_execution_profile_version=(
                    int(row["execution_profile_version"])
                    if row["execution_profile_version"] is not None
                    else None
                ),
                legacy_workspace_policy_version=(
                    int(row["workspace_policy_version"])
                    if row["workspace_policy_version"] is not None
                    else None
                ),
                desired_generation=int(row["runtime_desired_generation"] or 0),
                spec=spec,
                required_capabilities=required_capabilities,
                legacy_applied_snapshot_id=(
                    str(row["applied_runtime_policy_snapshot_id"])
                    if row["applied_runtime_policy_snapshot_id"] is not None
                    else None
                ),
            )


def _attach_migrated_runtime_configuration(
    connection: sa.Connection,
    *,
    runtime_id: str,
    provider_id: str,
    provider_logical_id: str,
    provider_kind: str,
    capability_revision_id: str | None,
    capability_digest: str | None,
    infrastructure_id: str,
    infrastructure_version: int,
    infrastructure_digest: str,
    workspace_profile_id: str,
    workspace_profile_version: int,
    workspace_profile_digest: str,
    selection_version: int,
    legacy_execution_profile_version: int | None,
    legacy_workspace_policy_version: int | None,
    desired_generation: int,
    spec: Mapping[str, Any],
    required_capabilities: list[str],
    legacy_applied_snapshot_id: str | None,
) -> None:
    if provider_kind != "docker":
        status = "blocked"
        reason_code = "legacy_provider_configuration_required"
        resolved_configuration = None
    elif capability_revision_id is None:
        status = "blocked"
        reason_code = "provider_capability_unavailable"
        resolved_configuration = None
    else:
        status = "ready"
        reason_code = None
        resolved_configuration = {
            "schema_version": 1,
            "provider": {
                "id": provider_id,
                "logical_id": provider_logical_id,
                "kind": provider_kind,
                "capability_revision_id": capability_revision_id,
                "capability_digest": capability_digest,
            },
            "infrastructure_profile": {
                "id": infrastructure_id,
                "version": infrastructure_version,
                "digest": infrastructure_digest,
            },
            "workspace_runtime_profile": {
                "id": workspace_profile_id,
                "version": workspace_profile_version,
                "digest": workspace_profile_digest,
            },
            "effective_profile": spec,
        }
    source_trace = {
        "migration": "legacy_runtime_profile_cutover",
        "agent_selection_version": selection_version,
        "execution_profile_version": legacy_execution_profile_version,
        "workspace_policy_version": legacy_workspace_policy_version,
        "provider_capability_revision_id": capability_revision_id,
        "provider_capability_digest": capability_digest,
        "infrastructure_profile_version": infrastructure_version,
        "infrastructure_profile_digest": infrastructure_digest,
        "workspace_runtime_profile_version": workspace_profile_version,
        "workspace_runtime_profile_digest": workspace_profile_digest,
        "legacy_applied_runtime_policy_snapshot_id": legacy_applied_snapshot_id,
    }
    digest = _digest(
        {
            "status": status,
            "reason_code": reason_code,
            "missing_capabilities": [],
            "resolved_configuration": resolved_configuration,
            "source_trace": source_trace,
        }
    )
    revision_id = _stable_id(
        "legacy-runtime-configuration",
        runtime_id,
        digest,
        str(desired_generation),
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO runtime_configuration_revisions (
                id,
                runtime_id,
                provider_id,
                provider_capability_revision_id,
                infrastructure_profile_id,
                infrastructure_profile_version,
                workspace_runtime_profile_id,
                workspace_runtime_profile_version,
                agent_selection_version,
                resolution_status,
                reason_code,
                required_capabilities,
                missing_capabilities,
                resolved_configuration,
                source_trace,
                digest,
                target_desired_generation,
                provider_reported_digest,
                runner_reported_digest,
                provider_acknowledged_at,
                runtime_observed_at
            ) VALUES (
                :id,
                :runtime_id,
                :provider_id,
                :provider_capability_revision_id,
                :infrastructure_profile_id,
                :infrastructure_profile_version,
                :workspace_runtime_profile_id,
                :workspace_runtime_profile_version,
                :agent_selection_version,
                CAST(:resolution_status AS runtime_configuration_resolution_status),
                :reason_code,
                CAST(:required_capabilities AS jsonb),
                CAST('[]' AS jsonb),
                CAST(:resolved_configuration AS jsonb),
                CAST(:source_trace AS jsonb),
                :digest,
                :target_desired_generation,
                NULL,
                NULL,
                NULL,
                NULL
            )
            ON CONFLICT (
                runtime_id,
                digest,
                target_desired_generation
            ) DO NOTHING
            """
        ),
        {
            "id": revision_id,
            "runtime_id": runtime_id,
            "provider_id": provider_id,
            "provider_capability_revision_id": capability_revision_id,
            "infrastructure_profile_id": infrastructure_id,
            "infrastructure_profile_version": infrastructure_version,
            "workspace_runtime_profile_id": workspace_profile_id,
            "workspace_runtime_profile_version": workspace_profile_version,
            "agent_selection_version": selection_version,
            "resolution_status": status,
            "reason_code": reason_code,
            "required_capabilities": _canonical_json(required_capabilities),
            "resolved_configuration": (
                _canonical_json(resolved_configuration)
                if resolved_configuration is not None
                else None
            ),
            "source_trace": _canonical_json(source_trace),
            "digest": digest,
            "target_desired_generation": desired_generation,
        },
    )
    connection.execute(
        sa.text(
            """
            UPDATE agent_runtimes
            SET runtime_provider_id = :provider_logical_id,
                runtime_provider_resource_id = :provider_id,
                provider_binding_origin =
                    CAST('migration' AS runtime_provider_binding_origin),
                provider_binding_evidence = CAST(:binding_evidence AS jsonb),
                infrastructure_profile_id = :infrastructure_profile_id,
                workspace_runtime_profile_id = :workspace_runtime_profile_id,
                desired_runtime_configuration_revision_id = :revision_id
            WHERE id = :runtime_id
            """
        ),
        {
            "runtime_id": runtime_id,
            "provider_logical_id": provider_logical_id,
            "provider_id": provider_id,
            "binding_evidence": _canonical_json(
                {
                    "migration": "legacy_runtime_profile_cutover",
                    "workspace_runtime_profile_id": workspace_profile_id,
                    "infrastructure_profile_id": infrastructure_id,
                    "agent_selection_version": selection_version,
                }
            ),
            "infrastructure_profile_id": infrastructure_id,
            "workspace_runtime_profile_id": workspace_profile_id,
            "revision_id": revision_id,
        },
    )


def _resolve_legacy_policy(
    *,
    profile_policy: object,
    workspace_restriction: object,
    agent_restriction: object,
) -> dict[str, Any]:
    policy = copy.deepcopy(_as_object(profile_policy) or _STANDARD_POLICY)
    _apply_restriction(policy, _as_object(workspace_restriction))
    _apply_restriction(policy, _as_object(agent_restriction))
    return policy


def _apply_restriction(
    policy: dict[str, Any],
    restriction: Mapping[str, Any],
) -> None:
    for module_name in ("docker", "resources"):
        module_restriction = restriction.get(module_name)
        if not isinstance(module_restriction, Mapping):
            continue
        policy_module = policy.get(module_name)
        if not isinstance(policy_module, dict):
            continue
        for field, value in module_restriction.items():
            if value is not None:
                policy_module[field] = value
        if module_name == "docker" and policy_module.get("enabled") is False:
            policy_module["storage_mode"] = "none"
            policy_module["storage_capacity_bytes"] = None


def _build_infrastructure_spec(
    provider_kind: str,
    policy: Mapping[str, Any],
) -> tuple[dict[str, Any], str, str, list[str]]:
    resources = _as_object(policy.get("resources"))
    docker = _as_object(policy.get("docker"))
    if provider_kind == "docker":
        spec = {
            "profile_kind": "docker_container",
            "contract_family": "docker.container-profile",
            "schema_version": 1,
            "runner_resources": {
                "cpu_reservation_millicores": resources.get("cpu_request_millicores"),
                "cpu_limit_millicores": resources.get("cpu_limit_millicores"),
                "memory_reservation_bytes": resources.get("memory_request_bytes"),
                "memory_limit_bytes": resources.get("memory_limit_bytes"),
            },
            "network_name": None,
        }
        return (
            spec,
            "docker.container-profile",
            "docker_container",
            [
                "docker.container-profile",
                "runtime.resources",
                "workspace.host-directory",
            ],
        )

    docker_enabled = docker.get("enabled") is True
    storage_capacity = docker.get("storage_capacity_bytes")
    spec = {
        "profile_kind": "kubernetes_pod",
        "contract_family": "kubernetes.pod-profile",
        "schema_version": 1,
        "runner_resources": {
            "cpu_request_millicores": resources.get("cpu_request_millicores"),
            "cpu_limit_millicores": resources.get("cpu_limit_millicores"),
            "memory_request_bytes": resources.get("memory_request_bytes"),
            "memory_limit_bytes": resources.get("memory_limit_bytes"),
        },
        "workspace_volume": {
            "storage_class_name": "legacy-provider-default",
            "storage_request_bytes": resources.get("persistent_storage_bytes") or 1,
        },
        "network_policy": {"allowed_cidrs": [], "denied_cidrs": []},
        "service_account_name": None,
        "scheduling": {"node_selector": {}, "tolerations": []},
        "dind": (
            {
                "engine_resources": {
                    "cpu_request_millicores": None,
                    "cpu_limit_millicores": None,
                    "memory_request_bytes": None,
                    "memory_limit_bytes": None,
                },
                "docker_storage_bytes": storage_capacity or 1,
                "shared_temporary_storage_bytes": (
                    resources.get("ephemeral_storage_bytes") or 1
                ),
            }
            if docker_enabled
            else None
        ),
    }
    required_capabilities = [
        "kubernetes.pod-profile",
        "runtime.network-policy",
        "runtime.resources",
        "workspace.persistent-volume",
    ]
    if docker_enabled:
        required_capabilities.extend(["docker.dind", "docker.storage.ephemeral"])
    return (
        spec,
        "kubernetes.pod-profile",
        "kubernetes_pod",
        sorted(required_capabilities),
    )


def _migration_description(
    *,
    legacy_policy: Mapping[str, Any],
    source: Mapping[str, Any],
) -> str:
    provenance = {
        "legacy_effective_policy": legacy_policy,
        "source": source,
        "note": (
            "Kubernetes Provider-global values that were not represented in the "
            "legacy server policy use an explicit migration sentinel and remain "
            "fail-closed until replaced."
        ),
    }
    return f"{_MIGRATION_DESCRIPTION_PREFIX}{_canonical_json(provenance)}"


def _as_object(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        decoded = json.loads(value)
        return dict(decoded) if isinstance(decoded, Mapping) else {}
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _stable_id(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:32]
