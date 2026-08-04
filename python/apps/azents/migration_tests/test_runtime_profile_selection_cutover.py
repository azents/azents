"""Migration tests for Workspace-owned Runtime Profile selection cutover."""

import copy
import json
from collections.abc import Mapping

import pytest
import sqlalchemy as sa
from pytest_alembic.runner import MigrationContext
from sqlalchemy.engine import Engine

from azents.testing.types import is_string_object_dict

_PARENT_REVISION = "24a6ab0f0b98"
_REVISION = "a8e8788ca12d"
_WORKSPACE_ID = "workspace-runtime-cutover"
_AGENT_ID = "agent-runtime-cutover"
_RUNTIME_ID = "runtime-cutover"
_PROVIDER_ID = "provider-runtime-cutover"
_PROVIDER_LOGICAL_ID = "system-docker-runtime-cutover"
_CONTRACT_ID = "contract-runtime-cutover"
_PROFILE_ID = "legacy-profile-runtime-cutover"
_DOCKER_CONTRACT: dict[str, object] = {
    "schema_version": 1,
    "implementation_key": "docker",
    "implementation_version": "1.0.0",
    "protocol_version": "agent-runtime-provider-docker-v1",
    "core_lifecycle_operations": [
        "start",
        "stop",
        "restart",
        "reset",
        "observe",
        "terminal_delete",
    ],
    "optional_capabilities": [],
    "persistence": {
        "kind": "persistent",
        "reset_destroys_workspace": True,
        "terminal_delete_destroys_workspace": True,
    },
    "configuration_fields": [],
    "profile_contracts": [
        {
            "profile_kind": "docker_container",
            "contract_family": "docker.container-profile",
            "schema_versions": [1],
            "capabilities": [
                "docker.container-profile",
                "runtime.resources",
                "workspace.host-directory",
            ],
            "constraints": {
                "maximums": {},
                "allowed_values": {},
            },
        }
    ],
}

_PROFILE_POLICY = """
{
  "schema_version": 1,
  "docker": {
    "module_id": "docker",
    "version": 1,
    "enabled": true,
    "storage_mode": "ephemeral",
    "storage_capacity_bytes": 8192
  },
  "resources": {
    "module_id": "runtime.resources",
    "version": 1,
    "cpu_request_millicores": 500,
    "cpu_limit_millicores": 1000,
    "memory_request_bytes": 512,
    "memory_limit_bytes": 1024,
    "ephemeral_storage_bytes": 2048,
    "persistent_storage_bytes": 4096
  }
}
"""
_WORKSPACE_RESTRICTION = """
{
  "schema_version": 1,
  "resources": {
    "cpu_limit_millicores": 900,
    "memory_limit_bytes": 900
  }
}
"""
_AGENT_RESTRICTION = """
{
  "schema_version": 1,
  "docker": {
    "storage_capacity_bytes": 4096
  },
  "resources": {
    "cpu_limit_millicores": 750
  }
}
"""


def _seed_legacy_selection(
    connection: sa.Connection,
    *,
    provider_enabled: bool = True,
    provider_lifecycle_state: str = "active",
    provider_contract: Mapping[str, object] = _DOCKER_CONTRACT,
) -> None:
    """Insert one complete pre-cutover Agent selection and effective policy."""
    connection.execute(
        sa.text(
            """
            INSERT INTO workspaces (id, name, handle)
            VALUES (:id, 'Runtime cutover', 'runtime-cutover')
            """
        ),
        {"id": _WORKSPACE_ID},
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO runtime_providers (
                id, provider_id, scope, kind, display_name, registration_method,
                enabled, lifecycle_state, availability_mode, admin_version,
                capabilities
            )
            VALUES (
                :id, :provider_id, 'system', 'docker', 'Docker cutover',
                'admin', :enabled,
                CAST(:lifecycle_state AS runtime_provider_lifecycle_state),
                'platform_wide', 0, '{}'::jsonb
            )
            """
        ),
        {
            "id": _PROVIDER_ID,
            "provider_id": _PROVIDER_LOGICAL_ID,
            "enabled": provider_enabled,
            "lifecycle_state": provider_lifecycle_state,
        },
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO runtime_provider_contract_revisions (
                id, provider_id, digest, implementation_version,
                protocol_version, contract, compatibility
            )
            VALUES (
                :id, :provider_id, :digest, '1.0.0',
                'agent-runtime-provider-docker-v1',
                CAST(:contract AS jsonb),
                '{"compatible": true}'::jsonb
            )
            """
        ),
        {
            "id": _CONTRACT_ID,
            "provider_id": _PROVIDER_ID,
            "digest": "1" * 64,
            "contract": json.dumps(provider_contract),
        },
    )
    connection.execute(
        sa.text(
            """
            UPDATE runtime_providers
            SET current_contract_revision_id = :contract_id
            WHERE id = :provider_id
            """
        ),
        {"contract_id": _CONTRACT_ID, "provider_id": _PROVIDER_ID},
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO agents (
                id, workspace_id, name, model_selection,
                lightweight_model_selection, selectable_model_options,
                main_model_label, lightweight_model_label, runtime_provider_id
            )
            VALUES (
                :id, :workspace_id, 'Runtime cutover Agent',
                '{}'::jsonb, '{}'::jsonb,
                '[
                    {"label": "main", "model_selection": {}},
                    {"label": "lightweight", "model_selection": {}}
                ]'::jsonb,
                'main', 'lightweight', :provider_id
            )
            """
        ),
        {
            "id": _AGENT_ID,
            "workspace_id": _WORKSPACE_ID,
            "provider_id": _PROVIDER_LOGICAL_ID,
        },
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO agent_runtimes (
                id, workspace_id, agent_id, runtime_provider_id,
                runtime_provider_resource_id, provider_binding_origin,
                desired_generation
            )
            VALUES (
                :id, :workspace_id, :agent_id, :provider_logical_id,
                :provider_id, 'agent_explicit', 3
            )
            """
        ),
        {
            "id": _RUNTIME_ID,
            "workspace_id": _WORKSPACE_ID,
            "agent_id": _AGENT_ID,
            "provider_logical_id": _PROVIDER_LOGICAL_ID,
            "provider_id": _PROVIDER_ID,
        },
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO runtime_execution_profiles (
                id, display_name, description, lifecycle, version, policy,
                digest, reserved, system_key
            )
            VALUES (
                :id, 'Legacy selected', 'Legacy selected Profile', 'active', 4,
                CAST(:policy AS jsonb), :digest, false, NULL
            )
            """
        ),
        {
            "id": _PROFILE_ID,
            "policy": _PROFILE_POLICY,
            "digest": "2" * 64,
        },
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO workspace_runtime_execution_policies (
                workspace_id, version, restriction, digest
            )
            VALUES (
                :workspace_id, 5, CAST(:restriction AS jsonb), :digest
            )
            """
        ),
        {
            "workspace_id": _WORKSPACE_ID,
            "restriction": _WORKSPACE_RESTRICTION,
            "digest": "3" * 64,
        },
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO agent_runtime_execution_settings (
                agent_id, profile_id, version, restriction, digest
            )
            VALUES (
                :agent_id, :profile_id, 7,
                CAST(:restriction AS jsonb), :digest
            )
            """
        ),
        {
            "agent_id": _AGENT_ID,
            "profile_id": _PROFILE_ID,
            "restriction": _AGENT_RESTRICTION,
            "digest": "4" * 64,
        },
    )


def test_runtime_profile_cutover_preserves_effective_selection(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Convert the legacy effective policy into one exact immutable path."""
    alembic_runner.migrate_up_to(_PARENT_REVISION)
    with alembic_engine.begin() as connection:
        _seed_legacy_selection(connection)

    alembic_runner.migrate_up_to(_REVISION)

    with alembic_engine.connect() as connection:
        agent = (
            connection.execute(
                sa.text(
                    """
                    SELECT runtime_profile_id, runtime_profile_selection_version
                    FROM agents
                    WHERE id = :agent_id
                    """
                ),
                {"agent_id": _AGENT_ID},
            )
            .mappings()
            .one()
        )
        assert agent["runtime_profile_id"] is not None
        assert agent["runtime_profile_selection_version"] == 7

        profile = (
            connection.execute(
                sa.text(
                    """
                    SELECT provider_id, infrastructure_profile_id, policy
                    FROM workspace_runtime_profiles
                    WHERE id = :profile_id
                    """
                ),
                {"profile_id": agent["runtime_profile_id"]},
            )
            .mappings()
            .one()
        )
        assert profile["provider_id"] == _PROVIDER_ID
        assert profile["policy"] == {
            "schema_version": 1,
            "network_restriction": None,
        }

        infrastructure = (
            connection.execute(
                sa.text(
                    """
                    SELECT profile_kind, spec, required_capabilities
                    FROM runtime_infrastructure_profiles
                    WHERE id = :profile_id
                    """
                ),
                {"profile_id": profile["infrastructure_profile_id"]},
            )
            .mappings()
            .one()
        )
        assert infrastructure["profile_kind"] == "docker_container"
        assert infrastructure["spec"]["runner_resources"] == {
            "cpu_reservation_millicores": 500,
            "cpu_limit_millicores": 750,
            "memory_reservation_bytes": 512,
            "memory_limit_bytes": 900,
        }
        assert set(infrastructure["required_capabilities"]) == {
            "docker.container-profile",
            "runtime.resources",
            "workspace.host-directory",
        }

        runtime = (
            connection.execute(
                sa.text(
                    """
                    SELECT infrastructure_profile_id, workspace_runtime_profile_id,
                           desired_runtime_configuration_revision_id,
                           runtime_provider_id, runtime_provider_resource_id
                    FROM agent_runtimes
                    WHERE id = :runtime_id
                    """
                ),
                {"runtime_id": _RUNTIME_ID},
            )
            .mappings()
            .one()
        )
        assert (
            runtime["infrastructure_profile_id"] == profile["infrastructure_profile_id"]
        )
        assert runtime["workspace_runtime_profile_id"] == agent["runtime_profile_id"]
        assert runtime["runtime_provider_id"] == _PROVIDER_LOGICAL_ID
        assert runtime["runtime_provider_resource_id"] == _PROVIDER_ID

        revision = (
            connection.execute(
                sa.text(
                    """
                    SELECT resolution_status, agent_selection_version,
                           target_desired_generation, resolved_configuration,
                           source_trace
                    FROM runtime_configuration_revisions
                    WHERE id = :revision_id
                    """
                ),
                {"revision_id": runtime["desired_runtime_configuration_revision_id"]},
            )
            .mappings()
            .one()
        )
        assert revision["resolution_status"] == "ready"
        assert revision["agent_selection_version"] == 7
        assert revision["target_desired_generation"] == 3
        assert (
            revision["resolved_configuration"]["effective_profile"]
            == (infrastructure["spec"])
        )
        source_trace = revision["source_trace"]
        assert isinstance(source_trace, Mapping)
        assert source_trace["migration"] == "legacy_runtime_profile_cutover"
        assert source_trace["execution_profile_version"] == 4
        assert source_trace["workspace_policy_version"] == 5

    assert "runtime_provider_id" not in {
        column["name"] for column in sa.inspect(alembic_engine).get_columns("agents")
    }

    alembic_runner.migrate_down_to(_PARENT_REVISION)
    with alembic_engine.connect() as connection:
        restored_provider = connection.execute(
            sa.text("SELECT runtime_provider_id FROM agents WHERE id = :agent_id"),
            {"agent_id": _AGENT_ID},
        ).scalar_one()
        assert restored_provider == _PROVIDER_LOGICAL_ID


def test_runtime_profile_cutover_blocks_malformed_provider_capability(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Malformed current advertisement cannot become a ready configuration."""
    alembic_runner.migrate_up_to(_PARENT_REVISION)
    with alembic_engine.begin() as connection:
        _seed_legacy_selection(
            connection,
            provider_contract={"schema_version": 1},
        )

    alembic_runner.migrate_up_to(_REVISION)

    _assert_migrated_revision_blocked(
        alembic_engine,
        reason_code="provider_capability_invalid",
    )


def test_runtime_profile_cutover_blocks_unsupported_provider_configuration_fields(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Unsupported contract sections cannot bypass migration validation."""
    contract = copy.deepcopy(_DOCKER_CONTRACT)
    contract["configuration_fields"] = [{}]
    alembic_runner.migrate_up_to(_PARENT_REVISION)
    with alembic_engine.begin() as connection:
        _seed_legacy_selection(connection, provider_contract=contract)

    alembic_runner.migrate_up_to(_REVISION)

    _assert_migrated_revision_blocked(
        alembic_engine,
        reason_code="provider_capability_invalid",
    )


def test_runtime_profile_cutover_blocks_missing_provider_capability(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """A current advertisement must provide every generated Profile capability."""
    contract = copy.deepcopy(_DOCKER_CONTRACT)
    profile_contracts = contract["profile_contracts"]
    assert isinstance(profile_contracts, list)
    profile_contract = profile_contracts[0]
    assert is_string_object_dict(profile_contract)
    profile_contract["capabilities"] = [
        "docker.container-profile",
        "runtime.resources",
    ]
    alembic_runner.migrate_up_to(_PARENT_REVISION)
    with alembic_engine.begin() as connection:
        _seed_legacy_selection(connection, provider_contract=contract)

    alembic_runner.migrate_up_to(_REVISION)

    _assert_migrated_revision_blocked(
        alembic_engine,
        reason_code="profile_capability_missing",
        missing_capabilities=["workspace.host-directory"],
    )


@pytest.mark.parametrize(
    ("provider_enabled", "provider_lifecycle_state", "reason_code"),
    [
        (False, "active", "provider_disabled"),
        (True, "decommissioning", "provider_not_active"),
    ],
)
def test_runtime_profile_cutover_blocks_unavailable_provider(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
    *,
    provider_enabled: bool,
    provider_lifecycle_state: str,
    reason_code: str,
) -> None:
    """Administrative Provider availability remains fail closed during cutover."""
    alembic_runner.migrate_up_to(_PARENT_REVISION)
    with alembic_engine.begin() as connection:
        _seed_legacy_selection(
            connection,
            provider_enabled=provider_enabled,
            provider_lifecycle_state=provider_lifecycle_state,
        )

    alembic_runner.migrate_up_to(_REVISION)

    _assert_migrated_revision_blocked(
        alembic_engine,
        reason_code=reason_code,
    )


def test_runtime_profile_cutover_rejects_missing_selected_provider(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Fail closed rather than discard an explicit missing Provider selection."""
    alembic_runner.migrate_up_to(_PARENT_REVISION)
    with alembic_engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO workspaces (id, name, handle)
                VALUES (:id, 'Missing Provider cutover', 'missing-provider-cutover')
                """
            ),
            {"id": _WORKSPACE_ID},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO agents (
                    id, workspace_id, name, model_selection,
                    lightweight_model_selection, selectable_model_options,
                    main_model_label, lightweight_model_label, runtime_provider_id
                )
                VALUES (
                    :id, :workspace_id, 'Missing Provider Agent',
                    '{}'::jsonb, '{}'::jsonb,
                    '[
                        {"label": "main", "model_selection": {}},
                        {"label": "lightweight", "model_selection": {}}
                    ]'::jsonb,
                    'main', 'lightweight', 'missing-provider'
                )
                """
            ),
            {"id": _AGENT_ID, "workspace_id": _WORKSPACE_ID},
        )

    with pytest.raises(RuntimeError, match="missing-provider.*does not exist"):
        alembic_runner.migrate_up_to(_REVISION)


def test_runtime_profile_cutover_downgrade_rejects_unrepresentable_revision(
    alembic_runner: MigrationContext,
    alembic_engine: Engine,
) -> None:
    """Rollback fails closed instead of deleting unrelated blocked revisions."""
    alembic_runner.migrate_up_to(_PARENT_REVISION)
    with alembic_engine.begin() as connection:
        _seed_legacy_selection(connection)
    alembic_runner.migrate_up_to(_REVISION)

    with alembic_engine.begin() as connection:
        runtime = (
            connection.execute(
                sa.text(
                    """
                    SELECT infrastructure_profile_id, workspace_runtime_profile_id
                    FROM agent_runtimes
                    WHERE id = :runtime_id
                    """
                ),
                {"runtime_id": _RUNTIME_ID},
            )
            .mappings()
            .one()
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
                    target_desired_generation
                ) VALUES (
                    'unrelated-blocked-revision',
                    :runtime_id,
                    :provider_id,
                    NULL,
                    :infrastructure_profile_id,
                    1,
                    :workspace_runtime_profile_id,
                    1,
                    8,
                    'blocked',
                    'provider_capability_unavailable',
                    '[]'::jsonb,
                    '[]'::jsonb,
                    NULL,
                    '{"origin": "post-migration"}'::jsonb,
                    :digest,
                    4
                )
                """
            ),
            {
                "runtime_id": _RUNTIME_ID,
                "provider_id": _PROVIDER_ID,
                "infrastructure_profile_id": runtime["infrastructure_profile_id"],
                "workspace_runtime_profile_id": (
                    runtime["workspace_runtime_profile_id"]
                ),
                "digest": "5" * 64,
            },
        )

    with pytest.raises(RuntimeError, match="Cannot downgrade"):
        alembic_runner.migrate_down_to(_PARENT_REVISION)


def _assert_migrated_revision_blocked(
    engine: Engine,
    *,
    reason_code: str,
    missing_capabilities: list[str] | None = None,
) -> None:
    with engine.connect() as connection:
        revision = (
            connection.execute(
                sa.text(
                    """
                    SELECT revision.resolution_status,
                           revision.reason_code,
                           revision.missing_capabilities,
                           revision.resolved_configuration
                    FROM agent_runtimes AS runtime
                    JOIN runtime_configuration_revisions AS revision
                      ON revision.id =
                         runtime.desired_runtime_configuration_revision_id
                    WHERE runtime.id = :runtime_id
                    """
                ),
                {"runtime_id": _RUNTIME_ID},
            )
            .mappings()
            .one()
        )
    assert revision["resolution_status"] == "blocked"
    assert revision["reason_code"] == reason_code
    assert revision["missing_capabilities"] == (missing_capabilities or [])
    assert revision["resolved_configuration"] is None
