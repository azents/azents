"""Kubernetes Runtime Provider Helm render contract tests."""

import shutil
import subprocess
from pathlib import Path

import pytest

CHART_DIR = Path(__file__).resolve().parents[1]


def _helm_template(*values: str) -> str:
    """Run helm template, or skip when the helm binary is unavailable."""
    helm = shutil.which("helm")
    if helm is None:
        pytest.skip("helm binary is not available")
    command = [helm, "template", "azents", str(CHART_DIR)]
    base_values = (
        "server.image.repository=repo/server",
        "server.image.tag=sha",
        "web.image.repository=repo/web",
        "web.image.tag=sha",
        "adminWeb.image.repository=repo/admin-web",
        "adminWeb.image.tag=sha",
        "secrets.existingSecrets.redis=azents-redis",
        "runtimeProviderKubernetes.credential.existingSecret=azents-provider-credential",
    )
    for value in (*base_values, *values):
        command.extend(["--set", value])
    completed = subprocess.run(
        command,
        cwd=CHART_DIR,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def test_runtime_provider_kubernetes_default_off_render_contract() -> None:
    """Default values render an authoritative empty Provider source."""
    rendered = _helm_template()

    assert "azents-runtime-provider-kubernetes" not in rendered
    assert "azents-runtime-provider-bootstrap" in rendered
    assert 'key: "helm/default/azents"' in rendered
    assert "providers:\n      []" in rendered
    assert "AZ_RUNTIME_DEFAULT_PROVIDER_ID" not in rendered
    assert "AZ_RUNTIME_PROVIDER_BOOTSTRAP_SOURCE_KEY" in rendered
    assert "AZ_RUNTIME_PROVIDER_BOOTSTRAP_SOURCE_PATH" in rendered
    assert "mountPath: /var/run/azents/runtime-provider-bootstrap" in rendered


def test_runtime_provider_kubernetes_enabled_render_contract() -> None:
    """Enabled values render provider/runner images and PVC policy env."""
    rendered = _helm_template(
        "runtimeProviderKubernetes.enabled=true",
        "runtimeProviderKubernetes.image.repository=repo/provider",
        "runtimeProviderKubernetes.image.tag=sha",
        "runtimeProviderKubernetes.runnerImage.repository=repo/runner",
        "runtimeProviderKubernetes.runnerImage.tag=sha",
    )

    assert "azents-runtime-provider-kubernetes" in rendered
    assert "azents-runtime-provider-bootstrap" in rendered
    assert "declarationKey: runtime-provider-kubernetes" in rendered
    assert "providerId: system-kubernetes" in rendered
    assert "availabilityMode: platform_wide" in rendered
    assert "AZ_RUNTIME_DEFAULT_PROVIDER_ID" not in rendered
    assert "mountPath: /var/run/azents/runtime-provider-bootstrap" in rendered
    assert "repo/provider:sha" in rendered
    assert "repo/runner:sha" in rendered
    assert "AZ_RUNTIME_CONTROL_ENDPOINT" in rendered
    assert "AZ_RUNTIME_CONTROL_AUTH_TOKEN" not in rendered
    assert "AZ_RUNTIME_PROVIDER_CREDENTIAL" in rendered
    assert "azents-provider-credential" in rendered
    assert "provider-credential" in rendered
    assert "AZ_RUNTIME_PROVIDER_LEASE_NAMESPACE" in rendered
    assert "AZ_RUNTIME_PROVIDER_WORKLOAD_NAMESPACE" in rendered
    assert "AZ_RUNTIME_PROVIDER_STORAGE_CLASS" in rendered
    assert "AZ_RUNTIME_PROVIDER_WORKSPACE_PATH" in rendered
    assert "AZ_RUNTIME_PROVIDER_POD_NODE_SELECTOR" in rendered
    assert "AZ_RUNTIME_PROVIDER_POD_TOLERATIONS" in rendered
    assert "AZ_RUNTIME_PROVIDER_POD_IMAGE_PULL_SECRETS" in rendered
    assert "AZ_RUNTIME_RUNNER_RESOURCES" in rendered
    assert (
        'value: "{\\"requests\\":{\\"cpu\\":\\"1\\",\\"memory\\":\\"2Gi\\"}}"'
        in rendered
    )
    for name, value in (
        ("AZ_RUNTIME_RUNNER_MAX_CONCURRENT_OPERATIONS_PER_SESSION", "10"),
        ("AZ_RUNTIME_RUNNER_MAX_CONCURRENT_SYSTEM_OPERATIONS", "10"),
        ("AZ_RUNTIME_RUNNER_MAX_CONCURRENT_OPERATIONS", "50"),
        ("AZ_RUNTIME_RUNNER_MAX_PENDING_OPERATIONS_PER_OWNER", "100"),
        ("AZ_RUNTIME_RUNNER_MAX_PENDING_OPERATIONS", "1000"),
        ("AZ_RUNTIME_RUNNER_MAX_CONCURRENT_CONTROL_OPERATIONS", "4"),
    ):
        assert f'- name: {name}\n              value: "{value}"' in rendered
    assert "AZ_RUNTIME_RUNNER_CPU_REQUEST" not in rendered
    assert "AZ_RUNTIME_RUNNER_MEMORY_REQUEST" not in rendered
    assert "AZ_RUNTIME_RUNNER_CPU_LIMIT" not in rendered
    assert "AZ_RUNTIME_RUNNER_MEMORY_LIMIT" not in rendered
    assert "AZ_RUNTIME_SERVICE_ACCOUNT_NAME" not in rendered
    assert "azents-runtime-workload-isolation" in rendered
    assert "azents/managed-by: azents-runtime-provider-kubernetes" in rendered
    assert "192.168.0.0/16" in rendered
    assert 'namespace: "default"' in rendered
    assert 'namespace: "azents-runtime"' in rendered


def test_runtime_provider_kubernetes_auth_enabled_render_contract() -> None:
    """auth enabled values render the Runtime Control auth token Secret ref."""
    rendered = _helm_template(
        "runtimeProviderKubernetes.enabled=true",
        "runtimeProviderKubernetes.image.repository=repo/provider",
        "runtimeProviderKubernetes.image.tag=sha",
        "runtimeProviderKubernetes.runnerImage.repository=repo/runner",
        "runtimeProviderKubernetes.runnerImage.tag=sha",
        "server.runtimeControl.auth.enabled=true",
        "server.runtimeControl.auth.existingSecret=azents-runtime-control-auth",
    )

    assert "AZ_RUNTIME_CONTROL_AUTH_TOKEN" in rendered
    assert "azents-runtime-control-auth" in rendered
    assert "runtime-control-token" in rendered


def test_runtime_provider_kubernetes_network_policy_allows_runtime_control() -> None:
    """Runtime workload NetworkPolicy allows Runner streams to runtime-control."""
    rendered = _helm_template(
        "runtimeProviderKubernetes.enabled=true",
        "runtimeProviderKubernetes.image.repository=repo/provider",
        "runtimeProviderKubernetes.image.tag=sha",
        "runtimeProviderKubernetes.runnerImage.repository=repo/runner",
        "runtimeProviderKubernetes.runnerImage.tag=sha",
    )

    runtime_control_index = rendered.index(
        "app.kubernetes.io/component: runtime-control"
    )
    public_rule_index = rendered.index("cidr: 0.0.0.0/0")
    denied_index = rendered.index("192.168.0.0/16")

    assert 'kubernetes.io/metadata.name: "default"' in rendered
    assert 'app.kubernetes.io/instance: "azents"' in rendered
    assert 'app.kubernetes.io/name: "azents"' in rendered
    assert "port: 8030" in rendered
    assert runtime_control_index < public_rule_index < denied_index


def test_runtime_provider_kubernetes_network_policy_allows_explicit_cidrs() -> None:
    """Explicit allowed CIDRs remain allowed even under broader denied CIDRs."""
    rendered = _helm_template(
        "runtimeProviderKubernetes.enabled=true",
        "runtimeProviderKubernetes.image.repository=repo/provider",
        "runtimeProviderKubernetes.image.tag=sha",
        "runtimeProviderKubernetes.runnerImage.repository=repo/runner",
        "runtimeProviderKubernetes.runnerImage.tag=sha",
        "runtimeProviderKubernetes.networkPolicy.allowedCidrs[0]=192.168.68.144/32",
    )

    allowed_index = rendered.index('cidr: "192.168.68.144/32"')
    public_rule_index = rendered.index("cidr: 0.0.0.0/0")
    denied_index = rendered.index("192.168.0.0/16")

    assert allowed_index < public_rule_index < denied_index


def test_runtime_provider_kubernetes_network_policy_renders_extra_egress() -> None:
    """Runtime workload NetworkPolicy renders raw extra egress rules."""
    rendered = _helm_template(
        "runtimeProviderKubernetes.enabled=true",
        "runtimeProviderKubernetes.image.repository=repo/provider",
        "runtimeProviderKubernetes.image.tag=sha",
        "runtimeProviderKubernetes.runnerImage.repository=repo/runner",
        "runtimeProviderKubernetes.runnerImage.tag=sha",
        "runtimeProviderKubernetes.networkPolicy.extraEgress[0].to[0].namespaceSelector.matchLabels.kubernetes\\.io/metadata\\.name=kube-system",
        "runtimeProviderKubernetes.networkPolicy.extraEgress[0].to[0].podSelector.matchLabels.app\\.kubernetes\\.io/name=traefik",
        "runtimeProviderKubernetes.networkPolicy.extraEgress[0].ports[0].protocol=TCP",
        "runtimeProviderKubernetes.networkPolicy.extraEgress[0].ports[0].port=443",
    )

    assert "namespaceSelector:" in rendered
    assert "kubernetes.io/metadata.name: kube-system" in rendered
    assert "app.kubernetes.io/name: traefik" in rendered
    assert "port: 443" in rendered


def test_runtime_provider_kubernetes_inherits_global_image_pull_secrets() -> None:
    """Runtime Pods inherit global imagePullSecrets unless explicitly overridden."""
    rendered = _helm_template(
        "global.imagePullSecrets[0].name=ecr-pull-secret",
        "runtimeProviderKubernetes.enabled=true",
        "runtimeProviderKubernetes.image.repository=repo/provider",
        "runtimeProviderKubernetes.image.tag=sha",
        "runtimeProviderKubernetes.runnerImage.repository=repo/runner",
        "runtimeProviderKubernetes.runnerImage.tag=sha",
    )

    assert "AZ_RUNTIME_PROVIDER_POD_IMAGE_PULL_SECRETS" in rendered
    assert 'value: "[{\\"name\\":\\"ecr-pull-secret\\"}]"' in rendered


def test_runtime_provider_kubernetes_overrides_runtime_pod_image_pull_secrets() -> None:
    """Runtime Pod imagePullSecrets can be configured independently."""
    rendered = _helm_template(
        "global.imagePullSecrets[0].name=ecr-pull-secret",
        "runtimeProviderKubernetes.enabled=true",
        "runtimeProviderKubernetes.image.repository=repo/provider",
        "runtimeProviderKubernetes.image.tag=sha",
        "runtimeProviderKubernetes.runnerImage.repository=repo/runner",
        "runtimeProviderKubernetes.runnerImage.tag=sha",
        "runtimeProviderKubernetes.runtimePod.imagePullSecrets[0].name=runner-pull-secret",
    )

    assert 'value: "[{\\"name\\":\\"runner-pull-secret\\"}]"' in rendered


def test_runtime_provider_kubernetes_runner_resources_render_contract() -> None:
    """Runner resources render as the Kubernetes ResourceRequirements JSON."""
    rendered = _helm_template(
        "runtimeProviderKubernetes.enabled=true",
        "runtimeProviderKubernetes.image.repository=repo/provider",
        "runtimeProviderKubernetes.image.tag=sha",
        "runtimeProviderKubernetes.runnerImage.repository=repo/runner",
        "runtimeProviderKubernetes.runnerImage.tag=sha",
        "runtimeProviderKubernetes.runnerResources.requests.cpu=1000m",
        "runtimeProviderKubernetes.runnerResources.requests.ephemeral-storage=1Gi",
        "runtimeProviderKubernetes.runnerResources.limits.memory=4Gi",
        "runtimeProviderKubernetes.runnerResources.limits.hugepages-2Mi=1Gi",
        "runtimeProviderKubernetes.runnerResources.claims[0].name=claim-1",
        "runtimeProviderKubernetes.runnerResources.claims[0].request=gpu",
    )

    assert "AZ_RUNTIME_RUNNER_RESOURCES" in rendered
    assert (
        'value: "{\\"claims\\":[{\\"name\\":\\"claim-1\\",\\"request\\":\\"gpu\\"}],'
        '\\"limits\\":{\\"hugepages-2Mi\\":\\"1Gi\\",\\"memory\\":\\"4Gi\\"},'
        '\\"requests\\":{\\"cpu\\":\\"1000m\\",\\"ephemeral-storage\\":\\"1Gi\\",\\"memory\\":\\"2Gi\\"}}"'
        in rendered
    )


def test_runtime_provider_kubernetes_runner_limits_render_contract() -> None:
    """Runner scheduling limit overrides reach the Provider environment."""
    rendered = _helm_template(
        "runtimeProviderKubernetes.enabled=true",
        "runtimeProviderKubernetes.image.repository=repo/provider",
        "runtimeProviderKubernetes.image.tag=sha",
        "runtimeProviderKubernetes.runnerImage.repository=repo/runner",
        "runtimeProviderKubernetes.runnerImage.tag=sha",
        "runtimeProviderKubernetes.runnerLimits.maxConcurrentOperationsPerSession=2",
        "runtimeProviderKubernetes.runnerLimits.maxConcurrentSystemOperations=3",
        "runtimeProviderKubernetes.runnerLimits.maxConcurrentOperations=7",
        "runtimeProviderKubernetes.runnerLimits.maxPendingOperationsPerOwner=11",
        "runtimeProviderKubernetes.runnerLimits.maxPendingOperations=31",
        "runtimeProviderKubernetes.runnerLimits.maxConcurrentControlOperations=2",
    )

    for name, value in (
        ("AZ_RUNTIME_RUNNER_MAX_CONCURRENT_OPERATIONS_PER_SESSION", "2"),
        ("AZ_RUNTIME_RUNNER_MAX_CONCURRENT_SYSTEM_OPERATIONS", "3"),
        ("AZ_RUNTIME_RUNNER_MAX_CONCURRENT_OPERATIONS", "7"),
        ("AZ_RUNTIME_RUNNER_MAX_PENDING_OPERATIONS_PER_OWNER", "11"),
        ("AZ_RUNTIME_RUNNER_MAX_PENDING_OPERATIONS", "31"),
        ("AZ_RUNTIME_RUNNER_MAX_CONCURRENT_CONTROL_OPERATIONS", "2"),
    ):
        assert f'- name: {name}\n              value: "{value}"' in rendered


def test_runtime_provider_kubernetes_digest_pinning_render_contract() -> None:
    """Runtime Provider and Runner images render tag plus digest when configured."""
    rendered = _helm_template(
        "runtimeProviderKubernetes.enabled=true",
        "runtimeProviderKubernetes.image.repository=repo/provider",
        "runtimeProviderKubernetes.image.tag=sha",
        "runtimeProviderKubernetes.image.digest=sha256:providerdigest",
        "runtimeProviderKubernetes.runnerImage.repository=repo/runner",
        "runtimeProviderKubernetes.runnerImage.tag=sha",
        "runtimeProviderKubernetes.runnerImage.digest=sha256:runnerdigest",
    )

    assert "repo/provider:sha@sha256:providerdigest" in rendered
    assert "repo/runner:sha@sha256:runnerdigest" in rendered


def test_runtime_provider_kubernetes_credential_bootstrap_render_contract() -> None:
    """Credential bootstrap uses one narrow short-lived Secret writer Job."""
    rendered = _helm_template(
        "runtimeProviderKubernetes.enabled=true",
        "secrets.existingSecrets.auth=azents-auth",
        "runtimeProviderKubernetes.credential.bootstrap.enabled=true",
        "runtimeProviderKubernetes.credential.bootstrap.secretName=azents-provider-credential-bootstrap",
        "runtimeProviderKubernetes.image.repository=repo/provider",
        "runtimeProviderKubernetes.image.tag=sha",
        "runtimeProviderKubernetes.runnerImage.repository=repo/runner",
        "runtimeProviderKubernetes.runnerImage.tag=sha",
    )

    assert "kind: Job" in rendered
    assert "runtime-provider-bootstrap-" in rendered
    assert 'resources: ["secrets"]' in rendered
    assert 'resourceNames: ["azents-provider-credential-bootstrap"]' in rendered
    assert "azents-provider-credential" in rendered
    assert 'verbs: ["get", "patch", "update"]' in rendered
    assert 'verbs: ["create"' not in rendered
    assert "src/cli/runtime_provider_bootstrap.py" in rendered
    assert "AZ_CREDENTIAL_ENCRYPTION_KEY" in rendered
    assert "kind: Secret" in rendered
    assert 'azents.io/runtime-provider-id: "system-kubernetes"' in rendered


def test_release_namespace_render_contract() -> None:
    """Helm release namespace places app components together."""
    rendered = _helm_template(
        "runtimeProviderKubernetes.enabled=true",
        "runtimeProviderKubernetes.image.repository=repo/provider",
        "runtimeProviderKubernetes.image.tag=sha",
        "runtimeProviderKubernetes.runnerImage.repository=repo/runner",
        "runtimeProviderKubernetes.runnerImage.tag=sha",
    )

    assert "namespace: azents-server" not in rendered
    assert "namespace: azents-web" not in rendered
    assert "namespace: azents-admin-web" not in rendered
    assert 'namespace: "default"' in rendered
    assert 'namespace: "azents-runtime"' in rendered
