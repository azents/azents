"""Runtime Profile composition tests."""

import pytest

from azents.core.runtime_profile import (
    DockerContainerProfileSpecV1,
    DockerContainerProfileSpecV2,
    DockerContainerResources,
    JsonValue,
    KubernetesContainerResources,
    KubernetesPodProfileSpecV1,
    KubernetesPodProfileSpecV2,
    KubernetesSchedulingModule,
    KubernetesWorkspaceVolume,
    RuntimeConfigurationApplicationImpact,
    RuntimeConfigurationResolutionStatus,
    RuntimeInfrastructureProfileKind,
    RuntimeNetworkPolicyModule,
    RuntimeProcessContainmentModuleV1,
    RuntimeProviderProfileContractSupport,
    WorkspaceRuntimeProfilePolicyV1,
    classify_runtime_configuration_application,
    compose_workspace_runtime_profile,
    digest_runtime_profile_document,
    evaluate_runtime_profile_compatibility,
    parse_runtime_infrastructure_profile_spec,
    required_runtime_profile_capabilities,
)


def _kubernetes_spec() -> KubernetesPodProfileSpecV1:
    return KubernetesPodProfileSpecV1(
        profile_kind=RuntimeInfrastructureProfileKind.KUBERNETES_POD,
        contract_family="kubernetes.pod-profile",
        schema_version=1,
        runner_resources=KubernetesContainerResources(
            cpu_request_millicores=None,
            cpu_limit_millicores=None,
            memory_request_bytes=None,
            memory_limit_bytes=None,
        ),
        workspace_volume=KubernetesWorkspaceVolume(
            storage_class_name="standard",
            storage_request_bytes=1,
        ),
        network_policy=RuntimeNetworkPolicyModule(
            allowed_cidrs=("10.0.0.0/8",),
            denied_cidrs=("10.1.0.0/16",),
        ),
        service_account_name=None,
        scheduling=KubernetesSchedulingModule(
            node_selector={},
            tolerations=(),
        ),
        dind=None,
    )


def _kubernetes_spec_v2(
    *,
    contained: bool,
) -> KubernetesPodProfileSpecV2:
    return KubernetesPodProfileSpecV2(
        profile_kind=RuntimeInfrastructureProfileKind.KUBERNETES_POD,
        contract_family="kubernetes.pod-profile",
        schema_version=2,
        runner_resources=KubernetesContainerResources(
            cpu_request_millicores=None,
            cpu_limit_millicores=None,
            memory_request_bytes=None,
            memory_limit_bytes=None,
        ),
        workspace_volume=KubernetesWorkspaceVolume(
            storage_class_name="standard",
            storage_request_bytes=1,
        ),
        network_policy=RuntimeNetworkPolicyModule(
            allowed_cidrs=("10.0.0.0/8",),
            denied_cidrs=("10.1.0.0/16",),
        ),
        service_account_name=None,
        scheduling=KubernetesSchedulingModule(
            node_selector={},
            tolerations=(),
        ),
        dind=None,
        process_containment=(
            RuntimeProcessContainmentModuleV1(schema_version=1) if contained else None
        ),
    )


def _docker_spec_v2(*, contained: bool) -> DockerContainerProfileSpecV2:
    return DockerContainerProfileSpecV2(
        profile_kind=RuntimeInfrastructureProfileKind.DOCKER_CONTAINER,
        contract_family="docker.container-profile",
        schema_version=2,
        runner_resources=DockerContainerResources(
            cpu_reservation_millicores=None,
            cpu_limit_millicores=None,
            memory_reservation_bytes=None,
            memory_limit_bytes=None,
        ),
        network_name=None,
        process_containment=(
            RuntimeProcessContainmentModuleV1(schema_version=1) if contained else None
        ),
    )


def _docker_spec() -> DockerContainerProfileSpecV1:
    return DockerContainerProfileSpecV1(
        profile_kind=RuntimeInfrastructureProfileKind.DOCKER_CONTAINER,
        contract_family="docker.container-profile",
        schema_version=1,
        runner_resources=DockerContainerResources(
            cpu_reservation_millicores=None,
            cpu_limit_millicores=None,
            memory_reservation_bytes=None,
            memory_limit_bytes=None,
        ),
        network_name=None,
    )


def test_kubernetes_profile_preserves_absent_requests_with_limits() -> None:
    """Profile parsing never copies limits into absent request fields."""
    payload = _kubernetes_spec().model_dump(mode="json")
    payload["runner_resources"] = {
        "cpu_request_millicores": None,
        "cpu_limit_millicores": 1000,
        "memory_request_bytes": None,
        "memory_limit_bytes": 2_147_483_648,
    }

    parsed = parse_runtime_infrastructure_profile_spec(payload)

    assert isinstance(parsed, KubernetesPodProfileSpecV1)
    assert parsed.runner_resources.cpu_request_millicores is None
    assert parsed.runner_resources.memory_request_bytes is None
    assert parsed.model_dump(mode="json")["runner_resources"] == {
        "cpu_request_millicores": None,
        "cpu_limit_millicores": 1000,
        "memory_request_bytes": None,
        "memory_limit_bytes": 2_147_483_648,
    }


@pytest.mark.parametrize(
    ("spec", "expected_type"),
    [
        (_kubernetes_spec(), KubernetesPodProfileSpecV1),
        (_kubernetes_spec_v2(contained=True), KubernetesPodProfileSpecV2),
        (_docker_spec(), DockerContainerProfileSpecV1),
        (_docker_spec_v2(contained=True), DockerContainerProfileSpecV2),
    ],
)
def test_profile_parser_dispatches_by_kind_and_schema_version(
    spec: (
        KubernetesPodProfileSpecV1
        | KubernetesPodProfileSpecV2
        | DockerContainerProfileSpecV1
        | DockerContainerProfileSpecV2
    ),
    expected_type: type[
        KubernetesPodProfileSpecV1
        | KubernetesPodProfileSpecV2
        | DockerContainerProfileSpecV1
        | DockerContainerProfileSpecV2
    ],
) -> None:
    """Profile parsing distinguishes v2 without changing existing kind values."""
    parsed = parse_runtime_infrastructure_profile_spec(spec.model_dump(mode="json"))

    assert isinstance(parsed, expected_type)
    assert parsed == spec


def test_kubernetes_v2_rejects_containment_with_nested_docker() -> None:
    """Contained Profiles cannot also grant nested Docker authority."""
    payload = _kubernetes_spec_v2(contained=True).model_dump(mode="json")
    payload["dind"] = {
        "engine_resources": {
            "cpu_request_millicores": None,
            "cpu_limit_millicores": None,
            "memory_request_bytes": None,
            "memory_limit_bytes": None,
        },
        "docker_storage_bytes": 1,
        "shared_temporary_storage_bytes": 1,
    }

    with pytest.raises(
        ValueError,
        match="Process containment cannot be combined with nested Docker",
    ):
        parse_runtime_infrastructure_profile_spec(payload)


def test_workspace_network_restriction_preserves_containment_module() -> None:
    """Workspace network composition cannot remove Provider containment."""
    effective = compose_workspace_runtime_profile(
        _kubernetes_spec_v2(contained=True),
        WorkspaceRuntimeProfilePolicyV1(
            schema_version=1,
            network_restriction=RuntimeNetworkPolicyModule(
                allowed_cidrs=("10.2.0.0/16",),
                denied_cidrs=(),
            ),
        ),
    )

    assert effective["process_containment"] == {"schema_version": 1}


@pytest.mark.parametrize(
    ("uncontained", "contained"),
    [
        (
            _kubernetes_spec_v2(contained=False),
            _kubernetes_spec_v2(contained=True),
        ),
        (
            _docker_spec_v2(contained=False),
            _docker_spec_v2(contained=True),
        ),
    ],
)
def test_containment_module_changes_canonical_profile_digest(
    uncontained: KubernetesPodProfileSpecV2 | DockerContainerProfileSpecV2,
    contained: KubernetesPodProfileSpecV2 | DockerContainerProfileSpecV2,
) -> None:
    """Containment participates in immutable effective-Profile identity."""
    assert digest_runtime_profile_document(uncontained) != (
        digest_runtime_profile_document(contained)
    )


@pytest.mark.parametrize(
    ("spec", "required"),
    [
        (_kubernetes_spec_v2(contained=False), False),
        (_kubernetes_spec_v2(contained=True), True),
        (_docker_spec_v2(contained=False), False),
        (_docker_spec_v2(contained=True), True),
    ],
)
def test_v2_profiles_require_containment_capability_only_when_enabled(
    spec: KubernetesPodProfileSpecV2 | DockerContainerProfileSpecV2,
    required: bool,
) -> None:
    """The portable capability follows exact typed containment presence."""
    capabilities = required_runtime_profile_capabilities(spec)

    assert ("runtime.process-containment" in capabilities) is required


def test_contained_profile_is_incompatible_without_provider_capability() -> None:
    """Schema v2 support alone does not claim process containment."""
    spec = _docker_spec_v2(contained=True)
    compatibility = evaluate_runtime_profile_compatibility(
        spec,
        [
            RuntimeProviderProfileContractSupport(
                profile_kind=RuntimeInfrastructureProfileKind.DOCKER_CONTAINER,
                contract_family="docker.container-profile",
                schema_versions=frozenset({1, 2}),
                capabilities=frozenset(
                    {
                        "docker.container-profile",
                        "runtime.resources",
                        "workspace.host-directory",
                    }
                ),
            )
        ],
    )

    assert compatibility.compatible is False
    assert compatibility.reason_code == "profile_capability_missing"
    assert compatibility.missing_capabilities == ("runtime.process-containment",)


def test_workspace_network_restriction_composes_within_platform_boundary() -> None:
    """Workspace CIDRs narrow allowed ranges and add denied ranges."""
    effective = compose_workspace_runtime_profile(
        _kubernetes_spec(),
        WorkspaceRuntimeProfilePolicyV1(
            schema_version=1,
            network_restriction=RuntimeNetworkPolicyModule(
                allowed_cidrs=("10.2.0.0/16",),
                denied_cidrs=("10.2.1.0/24",),
            ),
        ),
    )

    assert effective["network_policy"] == {
        "allowed_cidrs": ["10.2.0.0/16"],
        "denied_cidrs": ["10.1.0.0/16", "10.2.1.0/24"],
    }


def test_workspace_network_restriction_rejects_cidr_expansion() -> None:
    """Workspace allowed CIDRs cannot exceed the Pod Profile boundary."""
    with pytest.raises(ValueError, match="workspace_network_restriction_expands"):
        compose_workspace_runtime_profile(
            _kubernetes_spec(),
            WorkspaceRuntimeProfilePolicyV1(
                schema_version=1,
                network_restriction=RuntimeNetworkPolicyModule(
                    allowed_cidrs=("192.168.0.0/16",),
                    denied_cidrs=(),
                ),
            ),
        )


def test_docker_profile_rejects_workspace_network_restriction() -> None:
    """Docker Profiles reject unsupported Workspace network policy."""
    with pytest.raises(
        ValueError,
        match="workspace_network_restriction_unsupported",
    ):
        compose_workspace_runtime_profile(
            _docker_spec(),
            WorkspaceRuntimeProfilePolicyV1(
                schema_version=1,
                network_restriction=RuntimeNetworkPolicyModule(
                    allowed_cidrs=(),
                    denied_cidrs=("10.0.0.0/8",),
                ),
            ),
        )


def _resolved_configuration(
    effective_profile: dict[str, JsonValue],
    *,
    provider_kind: str = "kubernetes",
) -> dict[str, JsonValue]:
    return {
        "schema_version": 1,
        "provider": {
            "id": "provider-1",
            "logical_id": "provider-logical-1",
            "kind": provider_kind,
            "capability_revision_id": "capability-1",
            "capability_digest": "a" * 64,
        },
        "infrastructure_profile": {
            "id": "infrastructure-1",
            "version": 1,
            "digest": "b" * 64,
        },
        "workspace_runtime_profile": {
            "id": "workspace-profile-1",
            "version": 1,
            "digest": "c" * 64,
        },
        "effective_profile": effective_profile,
    }


def test_runtime_configuration_impact_allows_kubernetes_network_only_update() -> None:
    """Kubernetes NetworkPolicy-only changes can adopt without recreation."""
    applied_profile: dict[str, JsonValue] = _kubernetes_spec().model_dump(mode="json")
    desired_profile: dict[str, JsonValue] = {
        **applied_profile,
        "network_policy": {
            "allowed_cidrs": ["10.2.0.0/16"],
            "denied_cidrs": ["10.2.1.0/24"],
        },
    }
    applied = _resolved_configuration(applied_profile)
    desired = _resolved_configuration(desired_profile)
    desired["workspace_runtime_profile"] = {
        "id": "workspace-profile-1",
        "version": 2,
        "digest": "d" * 64,
    }

    assert (
        classify_runtime_configuration_application(
            desired_status=RuntimeConfigurationResolutionStatus.READY,
            desired_configuration=desired,
            applied_configuration=applied,
        )
        is RuntimeConfigurationApplicationImpact.IN_PLACE
    )


def test_runtime_configuration_impact_requires_recreation_for_pod_change() -> None:
    """PodSpec changes remain waiting for explicit recreation."""
    applied_profile: dict[str, JsonValue] = _kubernetes_spec().model_dump(mode="json")
    desired_profile: dict[str, JsonValue] = {
        **applied_profile,
        "service_account_name": "runtime-service-account",
    }

    assert (
        classify_runtime_configuration_application(
            desired_status=RuntimeConfigurationResolutionStatus.READY,
            desired_configuration=_resolved_configuration(desired_profile),
            applied_configuration=_resolved_configuration(applied_profile),
        )
        is RuntimeConfigurationApplicationImpact.RECREATE
    )


def test_runtime_configuration_impact_requires_recreation_for_docker_change() -> None:
    """Docker configuration changes require explicit recreation in v1."""
    applied_profile: dict[str, JsonValue] = {
        "profile_kind": "docker_container",
        "contract_family": "docker.container-profile",
        "schema_version": 1,
        "runner_resources": {},
        "network_name": "runtime-a",
    }
    desired_profile: dict[str, JsonValue] = {
        **applied_profile,
        "network_name": "runtime-b",
    }

    assert (
        classify_runtime_configuration_application(
            desired_status=RuntimeConfigurationResolutionStatus.READY,
            desired_configuration=_resolved_configuration(
                desired_profile,
                provider_kind="docker",
            ),
            applied_configuration=_resolved_configuration(
                applied_profile,
                provider_kind="docker",
            ),
        )
        is RuntimeConfigurationApplicationImpact.RECREATE
    )


@pytest.mark.parametrize(
    ("applied_containment", "desired_containment"),
    [
        (False, True),
        (True, False),
    ],
)
def test_containment_change_requires_runtime_recreation(
    applied_containment: bool,
    desired_containment: bool,
) -> None:
    """Adding or removing containment changes physical Runtime authority."""
    applied_profile = _docker_spec_v2(contained=applied_containment).model_dump(
        mode="json"
    )
    desired_profile = _docker_spec_v2(contained=desired_containment).model_dump(
        mode="json"
    )

    assert (
        classify_runtime_configuration_application(
            desired_status=RuntimeConfigurationResolutionStatus.READY,
            desired_configuration=_resolved_configuration(
                desired_profile,
                provider_kind="docker",
            ),
            applied_configuration=_resolved_configuration(
                applied_profile,
                provider_kind="docker",
            ),
        )
        is RuntimeConfigurationApplicationImpact.RECREATE
    )


@pytest.mark.parametrize("upgrade", [True, False])
def test_profile_version_change_requires_runtime_recreation(upgrade: bool) -> None:
    """Profile schema-version changes recreate the physical Runtime."""
    version_1 = _kubernetes_spec().model_dump(mode="json")
    version_2 = _kubernetes_spec_v2(contained=False).model_dump(mode="json")
    applied_profile = version_1 if upgrade else version_2
    desired_profile = version_2 if upgrade else version_1

    assert (
        classify_runtime_configuration_application(
            desired_status=RuntimeConfigurationResolutionStatus.READY,
            desired_configuration=_resolved_configuration(desired_profile),
            applied_configuration=_resolved_configuration(applied_profile),
        )
        is RuntimeConfigurationApplicationImpact.RECREATE
    )


def test_runtime_configuration_impact_preserves_blocked_applied_runtime() -> None:
    """Blocked desired configuration never replaces the applied incarnation."""
    assert (
        classify_runtime_configuration_application(
            desired_status=RuntimeConfigurationResolutionStatus.BLOCKED,
            desired_configuration=None,
            applied_configuration=_resolved_configuration(
                _kubernetes_spec().model_dump(mode="json")
            ),
        )
        is RuntimeConfigurationApplicationImpact.BLOCKED
    )
