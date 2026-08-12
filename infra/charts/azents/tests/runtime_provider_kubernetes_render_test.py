"""Kubernetes Runtime Provider Helm render contract tests."""

import shutil
import subprocess
from pathlib import Path

import pytest

CHART_DIR = Path(__file__).resolve().parents[1]
_RUNNER_DIGEST = f"sha256:{'a' * 64}"
_ENGINE_DIGEST = f"sha256:{'c' * 64}"
_PROVIDER_DIGEST = f"sha256:{'d' * 64}"
_PROXY_DIGEST = f"sha256:{'e' * 64}"
_ADDON_DIGEST = "f" * 64


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
        "runtimeProviderKubernetes.engineImage.repository=repo/engine",
        "runtimeProviderKubernetes.engineImage.tag=sha",
        f"runtimeProviderKubernetes.engineImage.digest={_ENGINE_DIGEST}",
        f"runtimeProviderKubernetes.runnerImage.digest={_RUNNER_DIGEST}",
        "secrets.existingSecrets.redis=azents-redis",
        "server.runtimeControl.tls.existingSecret=azents-runtime-control-tls",
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
    assert "method: kubernetes_service_account" in rendered
    assert (
        "subject: system:serviceaccount:default:azents-runtime-provider-kubernetes"
        in rendered
    )
    assert "namespace: default" in rendered
    assert "serviceAccountName: azents-runtime-provider-kubernetes" in rendered
    assert "audience: azents-runtime-control" in rendered
    assert "AZ_RUNTIME_DEFAULT_PROVIDER_ID" not in rendered
    assert "mountPath: /var/run/azents/runtime-provider-bootstrap" in rendered
    assert "repo/provider:sha" in rendered
    assert f"repo/runner:sha@{_RUNNER_DIGEST}" in rendered
    assert f"repo/engine:sha@{_ENGINE_DIGEST}" in rendered
    assert "AZ_RUNTIME_CONTROL_ENDPOINT" in rendered
    assert "AZ_RUNTIME_CONTROL_AUTH_TOKEN" not in rendered
    assert "AZ_RUNTIME_CONTROL_ALLOW_INSECURE" in rendered
    assert "AZ_RUNTIME_CONTROL_TLS_CA_FILE" in rendered
    assert "azents-runtime-control-tls" in rendered
    assert "AZ_RUNTIME_PROVIDER_READINESS_FILE" in rendered
    assert "readinessProbe:" in rendered
    assert "AZ_RUNTIME_PROVIDER_CREDENTIAL_FILE" not in rendered
    assert "AZ_RUNTIME_PROVIDER_SERVICE_ACCOUNT_TOKEN_FILE" in rendered
    assert (
        "mountPath: /var/run/secrets/azents/runtime-provider-service-account-token"
        in rendered
    )
    assert "audience: azents-runtime-control" in rendered
    assert "path: token" in rendered
    assert "runtime-provider-credential" not in rendered
    assert "AZ_RUNTIME_PROVIDER_LEASE_NAMESPACE" in rendered
    assert "AZ_RUNTIME_PROVIDER_WORKLOAD_NAMESPACE" in rendered
    assert "AZ_RUNTIME_PROVIDER_DEFAULT_DENY_LABELS" in rendered
    assert '\\"app.kubernetes.io/managed-by\\":\\"Helm\\"' in rendered
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
    assert "azents-runtime-legacy-workload-egress" in rendered
    assert "azents-runtime-execution-policy-default-deny" in rendered
    assert "azents/managed-by: azents-runtime-provider-kubernetes" in rendered
    assert 'azents/execution-policy-managed: "true"' in rendered
    assert "AZ_RUNTIME_PROVIDER_ENGINE_IMAGE" in rendered
    assert "repo/engine:sha" in rendered
    assert "AZ_RUNTIME_PROVIDER_RUNTIME_CONTROL_NAMESPACE" in rendered
    assert "AZ_RUNTIME_PROVIDER_RUNTIME_CONTROL_LABELS" in rendered
    assert "AZ_RUNTIME_PROVIDER_RUNTIME_CONTROL_PORT" in rendered
    assert (
        "- name: AZ_RUNTIME_PROVIDER_ATTEST_PROXY_REQUIRED\n"
        '              value: "false"'
    ) in rendered
    assert (
        '- name: AZ_RUNTIME_PROVIDER_ATTEST_NO_NETWORK\n              value: "false"'
    ) in rendered
    assert (
        '- name: AZ_RUNTIME_PROVIDER_PROXY_IMAGE\n              value: ""'
    ) in rendered
    assert "AZ_RUNTIME_PROVIDER_PROXY_ADDON_DIGEST" in rendered
    assert "AZ_RUNTIME_PROVIDER_DIAGNOSTIC_REFRESH_INTERVAL_SECONDS" in rendered
    assert "AZ_RUNTIME_PROVIDER_MANDATORY_SERVICES" in rendered
    assert '\\"role\\":\\"runtime_control\\"' in rendered
    assert '\\"role\\":\\"runtime_transfer\\"' in rendered
    assert rendered.count('\\"name\\":\\"runtime-control\\"') >= 2
    assert '\\"runtime-control.default.svc.cluster.local\\"' in rendered
    assert 'resources: ["runtimeclasses"]' not in rendered
    assert "192.168.0.0/16" in rendered
    assert 'namespace: "default"' in rendered
    assert 'namespace: "azents-runtime"' in rendered


def test_runtime_provider_bootstrap_matches_custom_service_account_identity() -> None:
    """Bootstrap authentication follows the rendered Provider identity."""
    rendered = _helm_template(
        "server.namespace.name=azents-control",
        "runtimeProviderKubernetes.enabled=true",
        "runtimeProviderKubernetes.image.repository=repo/provider",
        "runtimeProviderKubernetes.image.tag=sha",
        "runtimeProviderKubernetes.runnerImage.repository=repo/runner",
        "runtimeProviderKubernetes.runnerImage.tag=sha",
        "runtimeProviderKubernetes.serviceAccount.name=platform-runtime-provider",
    )

    assert (
        "subject: system:serviceaccount:azents-control:platform-runtime-provider"
        in rendered
    )
    assert "namespace: azents-control" in rendered
    assert "serviceAccountName: platform-runtime-provider" in rendered
    assert 'serviceAccountName: "azents-runtime-provider-kubernetes"' not in rendered


def test_runtime_provider_kubernetes_rejects_removed_credential_values() -> None:
    """Removed Provider credential values fail chart schema validation."""
    with pytest.raises(subprocess.CalledProcessError) as raised:
        _helm_template(
            "runtimeProviderKubernetes.enabled=true",
            "runtimeProviderKubernetes.image.repository=repo/provider",
            "runtimeProviderKubernetes.image.tag=sha",
            "runtimeProviderKubernetes.runnerImage.repository=repo/runner",
            "runtimeProviderKubernetes.runnerImage.tag=sha",
            "runtimeProviderKubernetes.credential.existingSecret=legacy-credential",
        )

    error = raised.value.stderr.lower()
    assert "schema" in error
    assert "credential" in error
    assert "not allowed" in error


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


def test_runtime_provider_kubernetes_policy_managed_pods_fail_closed() -> None:
    """Policy-managed Pods have a deny baseline and no broad legacy egress."""
    rendered = _helm_template(
        "runtimeProviderKubernetes.enabled=true",
        "runtimeProviderKubernetes.image.repository=repo/provider",
        "runtimeProviderKubernetes.image.tag=sha",
        "runtimeProviderKubernetes.runnerImage.repository=repo/runner",
        "runtimeProviderKubernetes.runnerImage.tag=sha",
    )

    legacy_policy = rendered[
        rendered.index("name: azents-runtime-legacy-workload-egress") : rendered.index(
            "name: azents-runtime-execution-policy-default-deny"
        )
    ]
    default_deny = rendered[
        rendered.index("name: azents-runtime-execution-policy-default-deny") :
    ]

    assert "key: azents/execution-policy-managed" in legacy_policy
    assert "operator: DoesNotExist" in legacy_policy
    assert 'azents/execution-policy-managed: "true"' not in legacy_policy
    assert 'azents/execution-policy-managed: "true"' in default_deny
    assert "ingress: []" in default_deny
    assert "egress: []" in default_deny
    assert "cidr: 0.0.0.0/0" not in default_deny


def test_runtime_provider_kubernetes_default_deny_cannot_be_disabled() -> None:
    """Disabling legacy broad egress retains the policy-managed deny baseline."""
    rendered = _helm_template(
        "runtimeProviderKubernetes.enabled=true",
        "runtimeProviderKubernetes.image.repository=repo/provider",
        "runtimeProviderKubernetes.image.tag=sha",
        "runtimeProviderKubernetes.runnerImage.repository=repo/runner",
        "runtimeProviderKubernetes.runnerImage.tag=sha",
        "runtimeProviderKubernetes.networkPolicy.enabled=false",
    )

    assert "azents-runtime-legacy-workload-egress" not in rendered
    assert "azents-runtime-execution-policy-default-deny" in rendered


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
        "runtimeProviderKubernetes.networkPolicy.extraEgress[0].ports[0].port=websecure",
    )

    assert "namespaceSelector:" in rendered
    assert "kubernetes.io/metadata.name: kube-system" in rendered
    assert "app.kubernetes.io/name: traefik" in rendered
    assert "port: websecure" in rendered
    assert "AZ_RUNTIME_PROVIDER_NETWORK_HARD_CAP_ALLOWED_CIDRS" in rendered
    assert "AZ_RUNTIME_PROVIDER_NETWORK_HARD_CAP_DENIED_CIDRS" in rendered
    assert "AZ_RUNTIME_PROVIDER_NETWORK_HARD_CAP_EXTRA_EGRESS" in rendered
    assert '\\"port\\":\\"websecure\\"' in rendered


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
        f"runtimeProviderKubernetes.image.digest={_PROVIDER_DIGEST}",
        "runtimeProviderKubernetes.runnerImage.repository=repo/runner",
        "runtimeProviderKubernetes.runnerImage.tag=sha",
        f"runtimeProviderKubernetes.runnerImage.digest={_RUNNER_DIGEST}",
    )

    assert f"repo/provider:sha@{_PROVIDER_DIGEST}" in rendered
    assert f"repo/runner:sha@{_RUNNER_DIGEST}" in rendered


@pytest.mark.parametrize(
    "digest_value",
    [
        "runtimeProviderKubernetes.runnerImage.digest=",
        "runtimeProviderKubernetes.engineImage.digest=",
    ],
)
def test_runtime_execution_images_require_immutable_digests(
    digest_value: str,
) -> None:
    with pytest.raises(subprocess.CalledProcessError) as raised:
        _helm_template(
            "runtimeProviderKubernetes.enabled=true",
            "runtimeProviderKubernetes.image.repository=repo/provider",
            "runtimeProviderKubernetes.image.tag=sha",
            "runtimeProviderKubernetes.runnerImage.repository=repo/runner",
            "runtimeProviderKubernetes.runnerImage.tag=sha",
            digest_value,
        )

    assert "digest" in raised.value.stderr.lower()


def test_proxy_required_attestation_requires_immutable_artifacts() -> None:
    """Proxy-required cannot render without immutable image and addon identities."""
    with pytest.raises(subprocess.CalledProcessError) as raised:
        _helm_template(
            "runtimeProviderKubernetes.enabled=true",
            "runtimeProviderKubernetes.image.repository=repo/provider",
            "runtimeProviderKubernetes.image.tag=sha",
            "runtimeProviderKubernetes.runnerImage.repository=repo/runner",
            "runtimeProviderKubernetes.runnerImage.tag=sha",
            "runtimeProviderKubernetes.strictNetwork.attestations.proxyRequired=true",
        )

    assert "strictnetwork.proxy" in raised.value.stderr.lower()


@pytest.mark.parametrize(
    ("proxy_required", "no_network"),
    [
        (True, False),
        (False, True),
        (True, True),
    ],
)
def test_strict_attestations_render_independently(
    proxy_required: bool,
    no_network: bool,
) -> None:
    """Independent attestations and optional proxy artifacts reach Provider env."""
    values = [
        "runtimeProviderKubernetes.enabled=true",
        "runtimeProviderKubernetes.image.repository=repo/provider",
        "runtimeProviderKubernetes.image.tag=sha",
        "runtimeProviderKubernetes.runnerImage.repository=repo/runner",
        "runtimeProviderKubernetes.runnerImage.tag=sha",
        (
            "runtimeProviderKubernetes.strictNetwork.attestations.proxyRequired="
            f"{str(proxy_required).lower()}"
        ),
        (
            "runtimeProviderKubernetes.strictNetwork.attestations.noNetwork="
            f"{str(no_network).lower()}"
        ),
    ]
    if proxy_required:
        values.extend(
            (
                "runtimeProviderKubernetes.strictNetwork.proxy.image.repository=repo/proxy",
                "runtimeProviderKubernetes.strictNetwork.proxy.image.tag=sha",
                (
                    "runtimeProviderKubernetes.strictNetwork.proxy.image.digest="
                    f"{_PROXY_DIGEST}"
                ),
                (
                    "runtimeProviderKubernetes.strictNetwork.proxy.addonDigest="
                    f"{_ADDON_DIGEST}"
                ),
            )
        )

    rendered = _helm_template(*values)

    assert (
        "- name: AZ_RUNTIME_PROVIDER_ATTEST_PROXY_REQUIRED\n"
        f'              value: "{str(proxy_required).lower()}"'
    ) in rendered
    assert (
        "- name: AZ_RUNTIME_PROVIDER_ATTEST_NO_NETWORK\n"
        f'              value: "{str(no_network).lower()}"'
    ) in rendered
    if proxy_required:
        assert f"repo/proxy:sha@{_PROXY_DIGEST}" in rendered
        assert f'value: "{_ADDON_DIGEST}"' in rendered
    else:
        assert "repo/proxy" not in rendered


def test_runtime_provider_kubernetes_has_narrow_complete_resource_authority() -> None:
    """Provider RBAC owns strict resources without broad credential authority."""
    rendered = _helm_template(
        "runtimeProviderKubernetes.enabled=true",
        "runtimeProviderKubernetes.image.repository=repo/provider",
        "runtimeProviderKubernetes.image.tag=sha",
        "runtimeProviderKubernetes.runnerImage.repository=repo/runner",
        "runtimeProviderKubernetes.runnerImage.tag=sha",
    )

    assert "kind: Job" not in rendered
    assert "runtime-provider-credential-bootstrap" not in rendered
    provider_rbac = "\n".join(
        document
        for document in rendered.split("---\n")
        if "templates/runtime-provider-kubernetes/rbac.yaml.tpl" in document
    )
    assert provider_rbac
    assert 'resources: ["pods"]' in provider_rbac
    assert 'resources: ["persistentvolumeclaims"]' in provider_rbac
    assert 'resources: ["services", "configmaps"]' in provider_rbac
    assert (
        'resources: ["secrets"]\n    verbs: ["get", "create", "update", "delete"]'
    ) in provider_rbac
    assert 'resources: ["networkpolicies"]' in provider_rbac
    assert 'resources: ["leases"]' in provider_rbac
    assert 'resources: ["namespaces"]' in provider_rbac
    assert 'resources: ["selfsubjectaccessreviews"]' in provider_rbac
    assert "resourceNames:" in provider_rbac
    assert '- "azents-runtime"' in provider_rbac
    assert '- "runtime-control"' in provider_rbac
    assert provider_rbac.count('resources: ["services"]') == 1
    assert "tokenreviews" not in provider_rbac
    assert 'resources: ["subjectaccessreviews"]' not in provider_rbac
    assert "impersonate" not in provider_rbac


def test_runtime_provider_kubernetes_renders_no_network_controller() -> None:
    """Strict packaging adds no DNS, proxy, or second reconciliation Deployment."""
    rendered = _helm_template(
        "runtimeProviderKubernetes.enabled=true",
        "runtimeProviderKubernetes.image.repository=repo/provider",
        "runtimeProviderKubernetes.image.tag=sha",
        "runtimeProviderKubernetes.runnerImage.repository=repo/runner",
        "runtimeProviderKubernetes.runnerImage.tag=sha",
    )

    provider_deployments = [
        document
        for document in rendered.split("---\n")
        if "kind: Deployment" in document and "runtime-provider-kubernetes" in document
    ]
    assert len(provider_deployments) == 1
    assert "dns-controller" not in rendered
    assert "proxy-controller" not in rendered
    assert "kind: CustomResourceDefinition" not in rendered


def test_workload_identity_does_not_render_storage_or_privilege() -> None:
    """Authentication rollout does not own storage or grant host privilege."""
    rendered = _helm_template(
        "runtimeProviderKubernetes.enabled=true",
        "runtimeProviderKubernetes.image.repository=repo/provider",
        "runtimeProviderKubernetes.image.tag=sha",
        "runtimeProviderKubernetes.runnerImage.repository=repo/runner",
        "runtimeProviderKubernetes.runnerImage.tag=sha",
    )

    assert "kind: PersistentVolumeClaim" not in rendered
    assert "kind: PersistentVolume" not in rendered
    assert "/var/run/docker.sock" not in rendered
    assert "privileged: true" not in rendered


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
