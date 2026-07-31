"""Runtime Profile composition tests."""

import pytest

from azents.core.runtime_profile import (
    DockerContainerProfileSpecV1,
    DockerContainerResources,
    JsonValue,
    KubernetesContainerResources,
    KubernetesPodProfileSpecV1,
    KubernetesSchedulingModule,
    KubernetesWorkspaceVolume,
    RuntimeConfigurationApplicationImpact,
    RuntimeConfigurationResolutionStatus,
    RuntimeInfrastructureProfileKind,
    RuntimeNetworkPolicyModule,
    WorkspaceRuntimeProfilePolicyV1,
    classify_runtime_configuration_application,
    compose_workspace_runtime_profile,
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
    spec = DockerContainerProfileSpecV1(
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

    with pytest.raises(
        ValueError,
        match="workspace_network_restriction_unsupported",
    ):
        compose_workspace_runtime_profile(
            spec,
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
