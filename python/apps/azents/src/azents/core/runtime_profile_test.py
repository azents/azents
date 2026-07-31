"""Runtime Profile composition tests."""

import pytest

from azents.core.runtime_profile import (
    DockerContainerProfileSpecV1,
    DockerContainerResources,
    KubernetesContainerResources,
    KubernetesPodProfileSpecV1,
    KubernetesSchedulingModule,
    KubernetesWorkspaceVolume,
    RuntimeInfrastructureProfileKind,
    RuntimeNetworkPolicyModule,
    WorkspaceRuntimeProfilePolicyV1,
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
