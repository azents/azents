"""Runtime execution-policy v1 domain tests."""

import pytest
from pydantic import ValidationError

from azents.core.runtime_execution_policy import (
    RuntimeExecutionAvailabilityReason,
    RuntimeExecutionChangeDirection,
    RuntimeExecutionDockerModule,
    RuntimeExecutionDockerRestriction,
    RuntimeExecutionModuleId,
    RuntimeExecutionModuleSupport,
    RuntimeExecutionPolicyDocument,
    RuntimeExecutionPolicyLayer,
    RuntimeExecutionPolicyRestriction,
    RuntimeExecutionProviderCapabilities,
    RuntimeExecutionResolution,
    RuntimeExecutionResourceModule,
    RuntimeExecutionResourceRestriction,
    RuntimeExecutionRestrictionExpansion,
    RuntimeExecutionSourceVersions,
    RuntimeExecutionStorageMode,
    canonical_runtime_execution_policy_json,
    classify_runtime_execution_change,
    digest_runtime_execution_policy,
    empty_runtime_execution_restriction,
    meet_runtime_execution_policies,
    resolve_runtime_execution_policy,
    standard_runtime_execution_policy,
    validate_runtime_execution_restriction,
)


def _policy(
    *,
    docker: bool = True,
    storage_mode: RuntimeExecutionStorageMode = RuntimeExecutionStorageMode.EPHEMERAL,
    storage_capacity_bytes: int = 8_589_934_592,
    cpu_request_millicores: int | None = 500,
    cpu_limit_millicores: int | None = 1_000,
    memory_request_bytes: int | None = 1_073_741_824,
    memory_limit_bytes: int | None = 2_147_483_648,
    ephemeral_storage_bytes: int | None = 10_737_418_240,
    persistent_storage_bytes: int | None = 21_474_836_480,
) -> RuntimeExecutionPolicyDocument:
    if not docker:
        storage_mode = RuntimeExecutionStorageMode.NONE
        storage_capacity_bytes = 0
    return RuntimeExecutionPolicyDocument(
        schema_version=1,
        docker=RuntimeExecutionDockerModule(
            module_id=RuntimeExecutionModuleId.DOCKER,
            version=1,
            enabled=docker,
            storage_mode=storage_mode,
            storage_capacity_bytes=(storage_capacity_bytes if docker else None),
        ),
        resources=RuntimeExecutionResourceModule(
            module_id=RuntimeExecutionModuleId.RESOURCES,
            version=1,
            cpu_request_millicores=cpu_request_millicores,
            cpu_limit_millicores=cpu_limit_millicores,
            memory_request_bytes=memory_request_bytes,
            memory_limit_bytes=memory_limit_bytes,
            ephemeral_storage_bytes=ephemeral_storage_bytes,
            persistent_storage_bytes=persistent_storage_bytes,
        ),
    )


def _capabilities() -> RuntimeExecutionProviderCapabilities:
    return RuntimeExecutionProviderCapabilities(
        supported_modules=frozenset(
            (
                RuntimeExecutionModuleSupport(
                    module_id=RuntimeExecutionModuleId.DOCKER, version=1
                ),
                RuntimeExecutionModuleSupport(
                    module_id=RuntimeExecutionModuleId.RESOURCES, version=1
                ),
            )
        ),
        storage_modes=frozenset(RuntimeExecutionStorageMode),
        resource_maxima=None,
    )


def _resolve(
    policy: RuntimeExecutionPolicyDocument,
    *,
    workspace: RuntimeExecutionPolicyRestriction | None = None,
    agent: RuntimeExecutionPolicyRestriction | None = None,
    capabilities: RuntimeExecutionProviderCapabilities | None = None,
) -> RuntimeExecutionResolution:
    return resolve_runtime_execution_policy(
        profile_policy=policy,
        workspace_restriction=workspace or empty_runtime_execution_restriction(),
        agent_restriction=agent or empty_runtime_execution_restriction(),
        source_versions=RuntimeExecutionSourceVersions(profile=1, workspace=1, agent=1),
        provider_capabilities=capabilities or _capabilities(),
        profile_active=True,
        profile_allowed=True,
        applied_policy=None,
    )


def test_standard_profile_has_no_docker_or_resource_authority() -> None:
    policy = standard_runtime_execution_policy()

    assert not policy.docker.enabled
    assert policy.docker.storage_mode is RuntimeExecutionStorageMode.NONE
    assert policy.docker.storage_capacity_bytes is None
    assert all(
        value is None
        for name, value in policy.resources
        if name not in {"module_id", "version"}
    )


def test_policy_uses_one_docker_and_one_runtime_resource_module() -> None:
    payload = _policy().model_dump(mode="json")

    assert set(payload) == {"schema_version", "docker", "resources"}
    assert payload["docker"]["module_id"] == "docker"
    assert payload["resources"]["module_id"] == "runtime.resources"
    assert "pids" not in payload["resources"]
    assert "container_count" not in payload["resources"]


def test_enabled_docker_requires_storage_mode_and_capacity() -> None:
    with pytest.raises(ValidationError, match="storage mode"):
        RuntimeExecutionDockerModule(
            module_id=RuntimeExecutionModuleId.DOCKER,
            version=1,
            enabled=True,
            storage_mode=RuntimeExecutionStorageMode.NONE,
            storage_capacity_bytes=None,
        )


def test_docker_restriction_disables_authority_without_storage_fields() -> None:
    with pytest.raises(ValidationError, match="enabled=false"):
        RuntimeExecutionDockerRestriction(
            enabled=None,
            storage_mode=RuntimeExecutionStorageMode.NONE,
            storage_capacity_bytes=None,
        )
    with pytest.raises(ValidationError, match="must not include storage"):
        RuntimeExecutionDockerRestriction(
            enabled=False,
            storage_mode=RuntimeExecutionStorageMode.EPHEMERAL,
            storage_capacity_bytes=1024**3,
        )


def test_resource_requests_cannot_exceed_limits() -> None:
    with pytest.raises(ValidationError, match="CPU request"):
        _policy(cpu_request_millicores=2_000, cpu_limit_millicores=1_000)
    with pytest.raises(ValidationError, match="Memory request"):
        _policy(memory_request_bytes=3_000, memory_limit_bytes=2_000)


def test_canonical_json_and_digest_are_deterministic() -> None:
    policy = _policy()

    assert canonical_runtime_execution_policy_json(policy).startswith('{"docker":')
    assert digest_runtime_execution_policy(policy) == digest_runtime_execution_policy(
        policy.model_copy(deep=True)
    )


def test_restrictions_reduce_docker_storage_and_resources() -> None:
    workspace = RuntimeExecutionPolicyRestriction(
        schema_version=1,
        docker=RuntimeExecutionDockerRestriction(
            enabled=None,
            storage_mode=RuntimeExecutionStorageMode.EPHEMERAL,
            storage_capacity_bytes=4_294_967_296,
        ),
        resources=RuntimeExecutionResourceRestriction(
            cpu_request_millicores=None,
            cpu_limit_millicores=750,
            memory_request_bytes=None,
            memory_limit_bytes=None,
            ephemeral_storage_bytes=None,
            persistent_storage_bytes=10_737_418_240,
        ),
    )
    agent = RuntimeExecutionPolicyRestriction(
        schema_version=1,
        docker=RuntimeExecutionDockerRestriction(
            enabled=False, storage_mode=None, storage_capacity_bytes=None
        ),
        resources=None,
    )

    result = _resolve(_policy(), workspace=workspace, agent=agent)

    assert not result.effective_policy.docker.enabled
    assert (
        result.effective_policy.docker.storage_mode is RuntimeExecutionStorageMode.NONE
    )
    assert result.effective_policy.resources.cpu_limit_millicores == 750
    assert result.effective_policy.resources.persistent_storage_bytes == 10_737_418_240
    assert (
        result.governing_layers["docker.enabled"] is RuntimeExecutionPolicyLayer.AGENT
    )
    assert result.reductions


def test_expanding_restriction_is_rejected() -> None:
    parent = _policy(cpu_limit_millicores=1_000)
    restriction = RuntimeExecutionPolicyRestriction(
        schema_version=1,
        docker=None,
        resources=RuntimeExecutionResourceRestriction(
            cpu_request_millicores=None,
            cpu_limit_millicores=2_000,
            memory_request_bytes=None,
            memory_limit_bytes=None,
            ephemeral_storage_bytes=None,
            persistent_storage_bytes=None,
        ),
    )

    with pytest.raises(RuntimeExecutionRestrictionExpansion) as error:
        validate_runtime_execution_restriction(
            parent, restriction, governing_layer=RuntimeExecutionPolicyLayer.WORKSPACE
        )
    assert error.value.path == "resources.cpu_limit_millicores"


def test_docker_without_ephemeral_allocation_is_unavailable() -> None:
    result = _resolve(_policy(ephemeral_storage_bytes=None))

    assert not result.available
    assert (
        result.availability_reason
        is RuntimeExecutionAvailabilityReason.DEPENDENCY_UNSATISFIED
    )


def test_provider_must_support_docker_module_and_storage() -> None:
    capabilities = RuntimeExecutionProviderCapabilities(
        supported_modules=frozenset(),
        storage_modes=frozenset({RuntimeExecutionStorageMode.NONE}),
        resource_maxima=None,
    )

    result = _resolve(_policy(), capabilities=capabilities)

    assert not result.available
    assert (
        result.availability_reason
        is RuntimeExecutionAvailabilityReason.PROVIDER_MODULE_UNSUPPORTED
    )


def test_policy_change_classification_covers_enable_disable_and_bounds() -> None:
    enabled = _policy()
    disabled = _policy(docker=False)

    assert (
        classify_runtime_execution_change(disabled, enabled).direction
        is RuntimeExecutionChangeDirection.AUTHORITY_EXPANDING
    )
    assert (
        classify_runtime_execution_change(enabled, disabled).direction
        is RuntimeExecutionChangeDirection.RESTRICTIVE
    )


def test_meet_keeps_only_shared_authority_and_smallest_bounds() -> None:
    result = meet_runtime_execution_policies(
        _policy(cpu_limit_millicores=1_000, storage_capacity_bytes=8_000),
        _policy(cpu_limit_millicores=500, storage_capacity_bytes=4_000),
    )

    assert result.docker.enabled
    assert result.docker.storage_capacity_bytes == 4_000
    assert result.resources.cpu_limit_millicores == 500

    no_docker = meet_runtime_execution_policies(result, _policy(docker=False))
    assert not no_docker.docker.enabled
    assert no_docker.docker.storage_capacity_bytes is None
