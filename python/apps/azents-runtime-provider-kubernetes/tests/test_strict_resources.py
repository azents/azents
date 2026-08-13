"""Strict Runtime proxy resource assembly tests."""

from datetime import UTC, datetime

from azents_runtime_control.runtime_configuration import (
    RuntimeNetworkMode,
    RuntimeProxyDomainMode,
    RuntimeProxyDomainPolicy,
    RuntimeProxyRequiredNetworkAccess,
)

from azents_runtime_provider_kubernetes.interception_ca import (
    CA_COMBINED_SECRET_KEY,
    CA_PUBLIC_SECRET_KEY,
    generate_runtime_ca,
)
from azents_runtime_provider_kubernetes.kubernetes_api import (
    EmptyDirVolume,
    LocalObjectReference,
    SecretVolume,
)
from azents_runtime_provider_kubernetes.owned_resources import (
    ANNOTATION_ARTIFACT_DIGEST,
    ANNOTATION_CA_FINGERPRINT,
    ANNOTATION_POLICY_DIGEST,
    OwnedResourceIdentity,
)
from azents_runtime_provider_kubernetes.strict_resources import (
    RUNNER_PROXY_INPUT_ENV,
    RUNTIME_TRUST_MOUNT_PATH,
    RUNTIME_TRUST_VOLUME,
    ProxyResourceInputs,
    build_proxy_resources,
    runtime_ca_volume,
    runtime_proxy_environment,
    runtime_trust_volume,
)


def test_proxy_resources_preserve_stable_service_and_exact_evidence() -> None:
    resources = build_proxy_resources(
        _inputs(),
        existing_cluster_ip="10.96.0.20",
    )

    assert resources.service.spec.cluster_ip == "10.96.0.20"
    assert resources.service_hostname == (
        "azents-runtime-runtime-1-proxy.azents-runtime.svc"
    )
    assert resources.policy_config_map.metadata.name.endswith(
        f"-{resources.policy_digest[:12]}"
    )
    assert resources.policy_config_map.immutable is True
    assert (
        resources.policy_config_map.metadata.annotations[ANNOTATION_POLICY_DIGEST]
        == resources.policy_digest
    )
    assert (
        resources.pod.metadata.annotations[ANNOTATION_CA_FINGERPRINT]
        == (resources.ca_secret.metadata.annotations[ANNOTATION_CA_FINGERPRINT])
    )
    assert resources.pod.metadata.annotations[ANNOTATION_ARTIFACT_DIGEST] == (
        resources.artifact_digest
    )
    container = resources.pod.spec.containers[0]
    environment = {item.name: item.value for item in container.env}
    assert environment["AZ_RUNTIME_PROXY_POLICY_DIGEST"] == resources.policy_digest
    assert environment["AZ_RUNTIME_PROXY_ARTIFACT_DIGEST"] == (
        resources.artifact_digest
    )
    assert container.readiness_probe is not None
    assert tuple(container.readiness_probe.exec_action.command) == (
        "/workspace/python/apps/azents-runtime-proxy/.venv/bin/python",
        "-m",
        "azents_runtime_proxy.main",
        "ready",
    )


def test_proxy_and_runtime_ca_volumes_keep_private_material_separate() -> None:
    resources = build_proxy_resources(_inputs(), existing_cluster_ip=None)
    proxy_volume = resources.pod.spec.volumes[1]
    assert isinstance(proxy_volume, SecretVolume)
    assert {item.key for item in proxy_volume.items} == {
        CA_COMBINED_SECRET_KEY,
        CA_PUBLIC_SECRET_KEY,
    }

    runtime_volume = runtime_ca_volume(resources.ca_secret.metadata.name)

    assert {item.key for item in runtime_volume.items} == {CA_PUBLIC_SECRET_KEY}
    assert CA_COMBINED_SECRET_KEY not in {item.key for item in runtime_volume.items}


def test_runtime_proxy_environment_uses_provider_only_runner_input() -> None:
    hostname = "azents-runtime-runtime-1-proxy.azents-runtime.svc"

    assert runtime_proxy_environment(hostname, 8080) == {
        RUNNER_PROXY_INPUT_ENV: f"http://{hostname}:8080"
    }


def test_runtime_trust_volume_is_bounded_memory_backed_workspace() -> None:
    volume = runtime_trust_volume()

    assert isinstance(volume, EmptyDirVolume)
    assert volume.name == RUNTIME_TRUST_VOLUME
    assert volume.medium == "Memory"
    assert volume.size_limit == "16Mi"
    assert RUNTIME_TRUST_MOUNT_PATH == "/var/run/azents-runtime"


def _inputs() -> ProxyResourceInputs:
    return ProxyResourceInputs(
        namespace="azents-runtime",
        identity=OwnedResourceIdentity(
            provider_id="provider-k8s",
            runtime_id="runtime-1",
            workspace_id="workspace-1",
            agent_id="agent-1",
        ),
        desired_generation=3,
        configuration_sequence=7,
        configuration_digest="d" * 64,
        network_access=RuntimeProxyRequiredNetworkAccess(
            mode=RuntimeNetworkMode.PROXY_REQUIRED,
            allowed_cidrs=("203.0.113.0/24",),
            denied_cidrs=("203.0.113.128/25",),
            domain_policy=RuntimeProxyDomainPolicy(
                mode=RuntimeProxyDomainMode.ALLOWLIST,
                allowed_domains=("*.example.com",),
                denied_domains=("blocked.example.com",),
            ),
        ),
        ca=generate_runtime_ca("runtime-1", now=datetime.now(UTC)),
        proxy_image=f"repo/proxy@sha256:{'a' * 64}",
        addon_digest="b" * 64,
        proxy_port=8080,
        readiness_port=8081,
        image_pull_secrets=(LocalObjectReference(name="pull-secret"),),
        node_selector={"runtime": "isolated"},
        tolerations=(),
    )
