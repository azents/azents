"""Independent opt-in Proxy chart with least-privilege resolver-only inputs."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

CHART = Path(__file__).resolve().parents[1]


def render(*values: str, enabled: bool = True) -> subprocess.CompletedProcess[str]:
    helm = shutil.which("helm")
    if helm is None:
        pytest.skip("helm binary is not available")
    command = [helm, "template", "azents", str(CHART)]
    defaults = [
        "server.enabled=false",
        "web.enabled=false",
        "adminWeb.enabled=false",
        "llmProxy.image.repository=repo/llm-proxy",
        "llmProxy.image.tag=test-sha",
        "llmProxy.authority.url=https://authority.internal/internal/llm",
        "llmProxy.authority.authentication=shared_key",
        "llmProxy.authority.resolver.existingSecret=proxy-resolver",
    ]
    if enabled:
        defaults.append("llmProxy.enabled=true")
    for value in (*defaults, *values):
        command.extend(["--set", value])
    return subprocess.run(
        command, cwd=CHART, capture_output=True, text=True, check=False
    )


def test_proxy_is_default_off_and_independent_of_server() -> None:
    result = render(enabled=False)
    assert result.returncode == 0, result.stderr
    assert "llm-proxy" not in result.stdout
    enabled = render()
    assert enabled.returncode == 0, enabled.stderr
    assert "kind: Deployment" in enabled.stdout
    assert "kind: Service" in enabled.stdout


@pytest.mark.parametrize("replicas", [1, 3])
def test_proxy_has_no_server_environment_or_issuer_authority(replicas: int) -> None:
    result = render(
        f"llmProxy.replicas={replicas}",
        "llmProxy.authority.ca.existingSecret=private-ca",
    )
    assert result.returncode == 0, result.stderr
    documents = list(yaml.safe_load_all(result.stdout))
    deployment = next(
        item for item in documents if item and item["kind"] == "Deployment"
    )
    spec = deployment["spec"]
    assert spec["replicas"] == replicas
    pod = spec["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    container = pod["containers"][0]
    assert container["image"] == "repo/llm-proxy:test-sha"
    assert "envFrom" not in container
    env = {item["name"]: item for item in container["env"]}
    assert set(env) == {
        "AZ_LLM_PROXY_PORT",
        "AZ_LLM_PROXY_AUTHORITY_URL",
        "AZ_LLM_PROXY_AUTHORITY_TIMEOUT_SECONDS",
        "AZ_LLM_PROXY_RESOLVER_KEY",
        "AZ_LLM_PROXY_AUTHORITY_CA_FILE",
    }
    assert env["AZ_LLM_PROXY_RESOLVER_KEY"]["valueFrom"]["secretKeyRef"] == {
        "name": "proxy-resolver",
        "key": "resolver-key",
    }
    assert container["volumeMounts"][0]["readOnly"] is True
    assert pod["volumes"][0]["secret"]["secretName"] == "private-ca"
    assert "issuer" not in json.dumps(pod).lower()
    assert container["readinessProbe"]["httpGet"]["path"] == "/health/liveliness"


def test_proxy_ingress_exposes_only_exact_inference_routes_over_tls() -> None:
    result = render(
        "llmProxy.ingress.enabled=true",
        "llmProxy.ingress.hosts[0]=llm.example.com",
        "llmProxy.ingress.tls[0].hosts[0]=llm.example.com",
        "llmProxy.ingress.tls[0].secretName=public-proxy-tls",
    )
    assert result.returncode == 0, result.stderr
    ingress = next(
        item
        for item in yaml.safe_load_all(result.stdout)
        if item and item["kind"] == "Ingress"
    )
    assert ingress["spec"]["tls"][0]["secretName"] == "public-proxy-tls"
    paths = ingress["spec"]["rules"][0]["http"]["paths"]
    assert {item["path"] for item in paths} == {"/v1/models", "/v1/responses"}
    assert all(item["pathType"] == "Exact" for item in paths)
    assert (
        ingress["metadata"]["annotations"][
            "nginx.ingress.kubernetes.io/proxy-next-upstream"
        ]
        == "off"
    )


@pytest.mark.parametrize(
    "value",
    [
        "llmProxy.replicas=0",
        "llmProxy.authority.url=http://authority/internal/llm",
        "llmProxy.authority.resolver.existingSecret=",
        "llmProxy.ingress.enabled=true",
        "llmProxy.issuerKey=forbidden",
        "llmProxy.envFrom=forbidden",
    ],
)
def test_proxy_invalid_or_privilege_expanding_configuration_fails(value: str) -> None:
    result = render(value)
    assert result.returncode != 0


def test_authority_resolver_secret_is_only_in_the_api_server() -> None:
    result = render(
        "server.enabled=true",
        "server.image.repository=repo/server",
        "server.image.tag=test-sha",
        "server.llmAuthority.resolver.existingSecret=server-resolver",
    )
    assert result.returncode == 0, result.stderr
    recipients: list[str] = []
    for item in yaml.safe_load_all(result.stdout):
        if not item or item["kind"] != "Deployment":
            continue
        for container in item["spec"]["template"]["spec"]["containers"]:
            for env in container.get("env", []):
                if env["name"] == "AZ_LLM_RESOLVER_SERVICE_KEY":
                    recipients.append(container["name"])
                    assert env["valueFrom"]["secretKeyRef"] == {
                        "name": "server-resolver",
                        "key": "resolver-key",
                    }
    assert recipients == ["apiserver"]


@pytest.mark.parametrize("managed", [True, False])
def test_kubernetes_identity_preserves_configured_server_identity(
    managed: bool,
) -> None:
    result = render(
        "server.enabled=true",
        "server.image.repository=repo/server",
        "server.image.tag=test-sha",
        "llmProxy.authority.authentication=kubernetes_service_account",
        "llmProxy.authority.resolver.existingSecret=",
        "server.serviceAccount.name=consumer-cloud-identity",
        f"server.serviceAccount.create={str(managed).lower()}",
    )
    assert result.returncode == 0, result.stderr
    documents = [doc for doc in yaml.safe_load_all(result.stdout) if doc]
    deployments = {
        doc["metadata"]["name"]: doc["spec"]["template"]["spec"]
        for doc in documents
        if doc["kind"] == "Deployment"
    }
    proxy = deployments["azents-llm-proxy"]
    assert proxy["serviceAccountName"] == "azents-llm-proxy"
    assert proxy["automountServiceAccountToken"] is False
    identity = next(v for v in proxy["volumes"] if v["name"] == "resolver-identity")
    assert identity["projected"]["sources"] == [
        {
            "serviceAccountToken": {
                "audience": "azents-llm-resolver",
                "expirationSeconds": 3600,
                "path": "token",
            }
        }
    ]
    api = deployments["apiserver"]
    assert api["serviceAccountName"] == "consumer-cloud-identity"
    env = {e["name"]: e for e in api["containers"][0]["env"]}
    assert env["AZ_LLM_RESOLVER_KUBERNETES_SERVICE_ACCOUNT"]["value"] == (
        "system:serviceaccount:default:azents-llm-proxy"
    )
    assert "AZ_LLM_RESOLVER_SERVICE_KEY" not in env
    role = next(
        d
        for d in documents
        if d["kind"] == "ClusterRole" and "resolver-review" in d["metadata"]["name"]
    )
    assert role["rules"] == [
        {
            "apiGroups": ["authentication.k8s.io"],
            "resources": ["tokenreviews"],
            "verbs": ["create"],
        }
    ]
    binding = next(
        d
        for d in documents
        if d["kind"] == "ClusterRoleBinding"
        and d["roleRef"]["name"] == role["metadata"]["name"]
    )
    assert binding["subjects"] == [
        {
            "kind": "ServiceAccount",
            "name": "consumer-cloud-identity",
            "namespace": "default",
        }
    ]
