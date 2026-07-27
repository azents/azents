"""Tests for typed Runtime execution-policy resolution."""

import pytest
from pydantic import ValidationError

from azents.core.runtime_execution_policy import (
    RuntimeExecutionAvailabilityReason,
    RuntimeExecutionBooleanModule,
    RuntimeExecutionBooleanRestriction,
    RuntimeExecutionChangeDirection,
    RuntimeExecutionModuleId,
    RuntimeExecutionModuleSupport,
    RuntimeExecutionNetworkMode,
    RuntimeExecutionNetworkModule,
    RuntimeExecutionNetworkRestriction,
    RuntimeExecutionPolicyDocument,
    RuntimeExecutionPolicyLayer,
    RuntimeExecutionPolicyRestriction,
    RuntimeExecutionProviderCapabilities,
    RuntimeExecutionResourceModule,
    RuntimeExecutionResourceRestriction,
    RuntimeExecutionSourceVersions,
    RuntimeExecutionStorageMode,
    RuntimeExecutionStorageModule,
    RuntimeExecutionStorageRestriction,
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
    image_build: bool = True,
    container_run: bool = True,
    compose: bool = True,
    cpu_request_millicores: int | None = None,
    cpu_limit_millicores: int = 2_000,
    memory_request_bytes: int | None = None,
    memory_limit_bytes: int = 4_000,
    pids: int = 256,
    container_count: int = 10,
    ephemeral_storage_bytes: int = 8_000,
    persistent_storage_bytes: int | None = 20_000,
    storage_mode: RuntimeExecutionStorageMode = RuntimeExecutionStorageMode.PERSISTENT,
    storage_capacity: int = 10_000,
    network_mode: RuntimeExecutionNetworkMode = RuntimeExecutionNetworkMode.DIRECT,
    allowed: frozenset[str] = frozenset({"public", "registry"}),
    denied: frozenset[str] = frozenset({"metadata"}),
) -> RuntimeExecutionPolicyDocument:
    return RuntimeExecutionPolicyDocument(
        schema_version=1,
        image_build=RuntimeExecutionBooleanModule(
            module_id=RuntimeExecutionModuleId.IMAGE_BUILD,
            version=1,
            enabled=image_build,
        ),
        container_run=RuntimeExecutionBooleanModule(
            module_id=RuntimeExecutionModuleId.CONTAINER_RUN,
            version=1,
            enabled=container_run,
        ),
        compose=RuntimeExecutionBooleanModule(
            module_id=RuntimeExecutionModuleId.COMPOSE,
            version=1,
            enabled=compose,
        ),
        resources=RuntimeExecutionResourceModule(
            module_id=RuntimeExecutionModuleId.RESOURCES,
            version=1,
            cpu_request_millicores=cpu_request_millicores,
            cpu_limit_millicores=cpu_limit_millicores,
            memory_request_bytes=memory_request_bytes,
            memory_limit_bytes=memory_limit_bytes,
            pids=pids,
            container_count=container_count,
            ephemeral_storage_bytes=ephemeral_storage_bytes,
            persistent_storage_bytes=persistent_storage_bytes,
        ),
        engine_storage=RuntimeExecutionStorageModule(
            module_id=RuntimeExecutionModuleId.ENGINE_STORAGE,
            version=1,
            mode=storage_mode,
            capacity_bytes=(
                None
                if storage_mode is RuntimeExecutionStorageMode.NONE
                else storage_capacity
            ),
        ),
        network_egress=RuntimeExecutionNetworkModule(
            module_id=RuntimeExecutionModuleId.NETWORK_EGRESS,
            version=1,
            mode=network_mode,
            allowed_destinations=allowed,
            denied_destinations=denied,
        ),
    )


def _provider() -> RuntimeExecutionProviderCapabilities:
    return RuntimeExecutionProviderCapabilities(
        supported_modules=frozenset(
            RuntimeExecutionModuleSupport(
                module_id=module_id,
                version=1,
            )
            for module_id in RuntimeExecutionModuleId
        ),
        privileged_engine=True,
        storage_modes=frozenset(RuntimeExecutionStorageMode),
        network_modes=frozenset(RuntimeExecutionNetworkMode),
        resource_maxima=_policy().resources,
    )


def _versions() -> RuntimeExecutionSourceVersions:
    return RuntimeExecutionSourceVersions(
        profile=2,
        workspace=3,
        agent=4,
    )


def test_standard_policy_is_stable_with_direct_outbound_networking() -> None:
    """Reserved Standard is deterministic and permits outbound networking."""
    first = standard_runtime_execution_policy()
    second = standard_runtime_execution_policy()

    assert digest_runtime_execution_policy(first) == digest_runtime_execution_policy(
        second
    )
    assert first.image_build.enabled is False
    assert first.container_run.enabled is False
    assert first.compose.enabled is False
    assert first.engine_storage.mode is RuntimeExecutionStorageMode.NONE
    assert first.network_egress.mode is RuntimeExecutionNetworkMode.DIRECT
    assert first.network_egress.allowed_destinations == frozenset()
    assert first.network_egress.denied_destinations == frozenset()


def test_policy_rejects_unknown_fields_and_module_versions() -> None:
    """Application-owned schemas fail closed for unknown content."""
    payload = _policy().model_dump(mode="json")
    payload["unknown"] = True
    with pytest.raises(ValidationError):
        RuntimeExecutionPolicyDocument.model_validate(payload)

    payload = _policy().model_dump(mode="json")
    payload["image_build"]["version"] = 2
    with pytest.raises(ValidationError):
        RuntimeExecutionPolicyDocument.model_validate(payload)

    payload = _policy().model_dump(mode="json")
    payload["network_egress"]["mode"] = "proxy_required"
    with pytest.raises(ValidationError):
        RuntimeExecutionPolicyDocument.model_validate(payload)


def test_resolver_applies_monotone_operators_and_explains_sources() -> None:
    """Boolean, numeric, storage, allow, and deny values only narrow."""
    workspace = RuntimeExecutionPolicyRestriction(
        schema_version=1,
        image_build=None,
        container_run=None,
        compose=RuntimeExecutionBooleanRestriction(enabled=False),
        resources=RuntimeExecutionResourceRestriction(
            cpu_request_millicores=None,
            cpu_limit_millicores=1_000,
            memory_request_bytes=None,
            memory_limit_bytes=None,
            pids=128,
            container_count=None,
            ephemeral_storage_bytes=None,
            persistent_storage_bytes=None,
        ),
        engine_storage=RuntimeExecutionStorageRestriction(
            mode=RuntimeExecutionStorageMode.EPHEMERAL,
            capacity_bytes=6_000,
        ),
        network_egress=RuntimeExecutionNetworkRestriction(
            mode=RuntimeExecutionNetworkMode.RESTRICTED,
            allowed_destinations=frozenset({"registry"}),
            denied_destinations=frozenset({"blocked"}),
        ),
    )
    agent = RuntimeExecutionPolicyRestriction(
        schema_version=1,
        image_build=None,
        container_run=None,
        compose=None,
        resources=RuntimeExecutionResourceRestriction(
            cpu_request_millicores=None,
            cpu_limit_millicores=500,
            memory_request_bytes=None,
            memory_limit_bytes=None,
            pids=None,
            container_count=4,
            ephemeral_storage_bytes=None,
            persistent_storage_bytes=None,
        ),
        engine_storage=None,
        network_egress=RuntimeExecutionNetworkRestriction(
            mode=None,
            allowed_destinations=frozenset({"registry"}),
            denied_destinations=frozenset({"agent-deny"}),
        ),
    )

    result = resolve_runtime_execution_policy(
        profile_policy=_policy(),
        workspace_restriction=workspace,
        agent_restriction=agent,
        source_versions=_versions(),
        provider_capabilities=_provider(),
        profile_active=True,
        profile_allowed=True,
        applied_policy=None,
    )

    assert result.available is True
    assert result.effective_policy.compose.enabled is False
    assert result.effective_policy.resources.cpu_limit_millicores == 500
    assert result.effective_policy.resources.pids == 128
    assert result.effective_policy.resources.container_count == 4
    assert (
        result.effective_policy.engine_storage.mode
        is RuntimeExecutionStorageMode.EPHEMERAL
    )
    assert result.effective_policy.engine_storage.capacity_bytes == 6_000
    assert result.effective_policy.network_egress.allowed_destinations == frozenset(
        {"registry"}
    )
    assert result.effective_policy.network_egress.denied_destinations == frozenset(
        {"metadata", "blocked", "agent-deny"}
    )
    assert (
        result.governing_layers["resources.cpu_limit_millicores"]
        is RuntimeExecutionPolicyLayer.AGENT
    )


def test_lower_layer_expansion_is_rejected_with_governing_path() -> None:
    """A numeric or network expansion cannot be represented as authority."""
    with pytest.raises(ValueError, match="resources.cpu_limit_millicores"):
        validate_runtime_execution_restriction(
            _policy(cpu_limit_millicores=1_000),
            RuntimeExecutionPolicyRestriction(
                schema_version=1,
                image_build=None,
                container_run=None,
                compose=None,
                resources=RuntimeExecutionResourceRestriction(
                    cpu_request_millicores=None,
                    cpu_limit_millicores=2_000,
                    memory_request_bytes=None,
                    memory_limit_bytes=None,
                    pids=None,
                    container_count=None,
                    ephemeral_storage_bytes=None,
                    persistent_storage_bytes=None,
                ),
                engine_storage=None,
                network_egress=None,
            ),
            governing_layer=RuntimeExecutionPolicyLayer.PROFILE,
        )


def test_profile_tightening_safely_meets_stale_lower_restrictions() -> None:
    """Stored lower restrictions cannot broaden a newly narrowed Profile."""
    profile = standard_runtime_execution_policy()
    stale_workspace = empty_runtime_execution_restriction().model_copy(
        update={
            "network_egress": RuntimeExecutionNetworkRestriction(
                mode=RuntimeExecutionNetworkMode.DIRECT,
                allowed_destinations=None,
                denied_destinations=frozenset(),
            )
        }
    )

    result = resolve_runtime_execution_policy(
        profile_policy=profile.model_copy(
            update={
                "network_egress": profile.network_egress.model_copy(
                    update={"mode": RuntimeExecutionNetworkMode.NONE}
                )
            }
        ),
        workspace_restriction=stale_workspace,
        agent_restriction=empty_runtime_execution_restriction(),
        source_versions=_versions(),
        provider_capabilities=_provider(),
        profile_active=True,
        profile_allowed=True,
        applied_policy=profile,
    )

    assert result.available
    assert (
        result.effective_policy.network_egress.mode is RuntimeExecutionNetworkMode.NONE
    )


def test_dependency_failure_is_unavailable_without_profile_fallback() -> None:
    """Compose cannot remain enabled after container run is removed."""
    result = resolve_runtime_execution_policy(
        profile_policy=_policy(),
        workspace_restriction=RuntimeExecutionPolicyRestriction(
            schema_version=1,
            image_build=None,
            container_run=RuntimeExecutionBooleanRestriction(enabled=False),
            compose=None,
            resources=None,
            engine_storage=None,
            network_egress=None,
        ),
        agent_restriction=empty_runtime_execution_restriction(),
        source_versions=_versions(),
        provider_capabilities=_provider(),
        profile_active=True,
        profile_allowed=True,
        applied_policy=None,
    )

    assert result.available is False
    assert (
        result.availability_reason
        is RuntimeExecutionAvailabilityReason.DEPENDENCY_UNSATISFIED
    )
    assert result.change.direction is RuntimeExecutionChangeDirection.INCOMPATIBLE


def test_provider_support_is_typed_and_fails_closed() -> None:
    """An enabled module requires an exact application-owned Provider projection."""
    result = resolve_runtime_execution_policy(
        profile_policy=_policy(),
        workspace_restriction=empty_runtime_execution_restriction(),
        agent_restriction=empty_runtime_execution_restriction(),
        source_versions=_versions(),
        provider_capabilities=RuntimeExecutionProviderCapabilities(
            supported_modules=frozenset(),
            privileged_engine=False,
            storage_modes=frozenset(),
            network_modes=frozenset(),
            resource_maxima=None,
        ),
        profile_active=True,
        profile_allowed=True,
        applied_policy=None,
    )

    assert result.available is False
    assert (
        result.availability_reason
        is RuntimeExecutionAvailabilityReason.PROVIDER_MODULE_UNSUPPORTED
    )


def test_retired_or_disallowed_profile_remains_selected_but_unavailable() -> None:
    """Resolution reports the selected Profile failure instead of substituting one."""
    retired = resolve_runtime_execution_policy(
        profile_policy=standard_runtime_execution_policy(),
        workspace_restriction=empty_runtime_execution_restriction(),
        agent_restriction=empty_runtime_execution_restriction(),
        source_versions=_versions(),
        provider_capabilities=_provider(),
        profile_active=False,
        profile_allowed=True,
        applied_policy=None,
    )
    disallowed = retired.model_copy(
        update={
            "availability_reason": (
                RuntimeExecutionAvailabilityReason.PROFILE_NOT_ALLOWED
            )
        }
    )

    assert retired.available is False
    assert (
        retired.availability_reason
        is RuntimeExecutionAvailabilityReason.PROFILE_RETIRED
    )
    assert (
        disallowed.availability_reason
        is RuntimeExecutionAvailabilityReason.PROFILE_NOT_ALLOWED
    )


def test_change_classification_distinguishes_restriction_expansion_and_mixed() -> None:
    """Direction derives from canonical fields instead of UI heuristics."""
    baseline = _policy(compose=False, cpu_limit_millicores=1_000)
    restrictive = _policy(
        image_build=False,
        compose=False,
        cpu_limit_millicores=500,
    )
    expanding = _policy(compose=True, cpu_limit_millicores=2_000)
    mixed = _policy(image_build=False, compose=True, cpu_limit_millicores=2_000)

    assert (
        classify_runtime_execution_change(baseline, restrictive).direction
        is RuntimeExecutionChangeDirection.RESTRICTIVE
    )
    assert (
        classify_runtime_execution_change(baseline, expanding).direction
        is RuntimeExecutionChangeDirection.AUTHORITY_EXPANDING
    )
    assert (
        classify_runtime_execution_change(baseline, mixed).direction
        is RuntimeExecutionChangeDirection.MIXED
    )


def test_policy_meet_preserves_valid_storage_module() -> None:
    """Storage mode and capacity narrow as one valid authority module."""
    disabled = _policy(
        storage_mode=RuntimeExecutionStorageMode.NONE,
        network_mode=RuntimeExecutionNetworkMode.DIRECT,
    )
    ephemeral = _policy(
        storage_mode=RuntimeExecutionStorageMode.EPHEMERAL,
        storage_capacity=17_179_869_184,
        network_mode=RuntimeExecutionNetworkMode.DIRECT,
    )

    result = meet_runtime_execution_policies(disabled, ephemeral)

    assert result.engine_storage.mode is RuntimeExecutionStorageMode.NONE
    assert result.engine_storage.capacity_bytes is None


def test_policy_meet_intersects_restricted_network_authority() -> None:
    """Direct authority behaves as the universe while restrictions intersect."""
    direct = _policy(
        network_mode=RuntimeExecutionNetworkMode.DIRECT,
        denied=frozenset({"metadata"}),
    )
    restricted = _policy(
        network_mode=RuntimeExecutionNetworkMode.RESTRICTED,
        allowed=frozenset({"public", "registry"}),
        denied=frozenset({"private"}),
    )

    result = meet_runtime_execution_policies(direct, restricted)

    assert result.network_egress.mode is RuntimeExecutionNetworkMode.RESTRICTED
    assert result.network_egress.allowed_destinations == frozenset(
        {"public", "registry"}
    )
    assert result.network_egress.denied_destinations == frozenset(
        {"metadata", "private"}
    )


def test_policy_meet_intersects_two_network_allowlists() -> None:
    """Two restricted policies retain only destinations allowed by both."""
    left = _policy(
        network_mode=RuntimeExecutionNetworkMode.RESTRICTED,
        allowed=frozenset({"public", "registry"}),
        denied=frozenset({"metadata"}),
    )
    right = _policy(
        network_mode=RuntimeExecutionNetworkMode.RESTRICTED,
        allowed=frozenset({"registry", "packages"}),
        denied=frozenset({"private"}),
    )

    result = meet_runtime_execution_policies(left, right)

    assert result.network_egress.allowed_destinations == frozenset({"registry"})
    assert result.network_egress.denied_destinations == frozenset(
        {"metadata", "private"}
    )
