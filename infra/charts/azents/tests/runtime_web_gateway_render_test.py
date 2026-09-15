"""Runtime Web Gateway Helm render contract tests."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

CHART_DIR = Path(__file__).resolve().parents[1]
_RUNNER_DIGEST = f"sha256:{'a' * 64}"


def _helm_template(*values: str) -> str:
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
        f"runtimeProviderKubernetes.engineImage.digest=sha256:{'c' * 64}",
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


def _enabled_values() -> tuple[str, ...]:
    return (
        "server.runtimeControl.enabled=true",
        "server.runtimeControl.runnerImage.repository=repo/runner",
        "server.runtimeControl.runnerImage.tag=sha",
        f"server.runtimeControl.runnerImage.digest={_RUNNER_DIGEST}",
        "server.runtimeControl.webTransport.enabled=true",
        "server.runtimeControl.webTransport.gatewayPeerIdentities=runtime-web-gateway",
        "server.runtimeControl.webTransport.controlPeerIdentities=runtime-control",
        "server.runtimeWebGateway.enabled=true",
        "server.runtimeWebGateway.mainWebOrigin=https://app.example.com",
        "server.runtimeWebGateway.brokerOrigin=https://auth.services.example.com",
        "server.runtimeWebGateway.serviceSuffix=services.example.com",
        "server.runtimeWebGateway.cookieDomain=example.com",
        "server.runtimeWebGateway.controlTls.existingSecret=runtime-web-gateway-tls",
        "server.runtimeWebGateway.ingress.enabled=true",
        "server.runtimeWebGateway.ingress.hosts[0].host=*.services.example.net",
        "secrets.existingSecrets.auth=azents-auth",
    )


def _rendered_resource(rendered: str, *, kind: str, name: str) -> str:
    marker = f"kind: {kind}\nmetadata:\n  name: {name}\n"
    for document in rendered.split("---"):
        if marker in document:
            return document
    raise AssertionError(f"{kind} {name} was not rendered")


def test_runtime_web_gateway_is_disabled_by_default() -> None:
    rendered = _helm_template()
    worker = _rendered_resource(rendered, kind="Deployment", name="worker")

    assert "name: runtime-web-gateway" not in rendered
    assert "runtime-control-headless" not in rendered
    assert (
        'name: AZ_RUNTIME_WEB_GATEWAY_ENABLED\n              value: "false"' in worker
    )
    assert "AZ_RUNTIME_WEB_GATEWAY_SERVICE_SUFFIX" not in worker


def test_enabled_gateway_renders_isolated_process_and_trusted_control_path() -> None:
    rendered = _helm_template(*_enabled_values())

    assert 'command: ["./bin/runtime-web-gateway.sh"]' in rendered
    assert "name: runtime-web-gateway" in rendered
    assert "AZ_RUNTIME_WEB_GATEWAY_MAIN_WEB_ORIGIN" in rendered
    assert "AZ_RUNTIME_WEB_GATEWAY_CONTROL_TLS_CERTIFICATE_FILE" in rendered
    assert "runtime-web-gateway-tls" in rendered
    assert "kind: HorizontalPodAutoscaler" in rendered
    assert "kind: PodDisruptionBudget" in rendered
    assert "runtime-control-headless" in rendered
    assert "name: trusted-web" in rendered
    runtime_control = _rendered_resource(
        rendered,
        kind="Deployment",
        name="runtime-control",
    )
    assert (
        "name: AZ_RUNTIME_CONTROL_RUNNER_WEB_CONNECT_ADDRESS\n"
        '              value: "runtime-control.$(AZ_RUNTIME_CONTROL_POD_NAMESPACE).svc.cluster.local:8030"'
    ) in runtime_control
    assert (
        "runtime-control-headless.$(AZ_RUNTIME_CONTROL_POD_NAMESPACE).svc:8030"
        not in runtime_control
    )
    assert "AZ_RUNTIME_CONTROL_TRUSTED_ADVERTISE_ADDRESS" in rendered
    assert "AZ_RUNTIME_CONTROL_TRUSTED_GATEWAY_PEER_IDENTITIES" in rendered
    assert "AZ_RUNTIME_CONTROL_TRUSTED_CONTROL_PEER_IDENTITIES" in rendered
    assert "name: AZ_RUNTIME_WEB_GATEWAY_IDENTITY_LIFETIME_SECONDS" in rendered
    assert 'RUNTIME_WEB_GATEWAY_ENABLED: "true"' in rendered
    assert 'RUNTIME_WEB_GATEWAY_AUTH_MODE: "shared_cookie"' in rendered
    assert 'RUNTIME_WEB_GATEWAY_MAIN_WEB_ORIGIN: "https://app.example.com"' in rendered
    assert (
        'RUNTIME_WEB_GATEWAY_BROKER_ORIGIN: "https://auth.services.example.com"'
        in rendered
    )
    assert 'RUNTIME_WEB_GATEWAY_COOKIE_DOMAIN: "example.com"' in rendered
    assert (
        'RUNTIME_WEB_GATEWAY_IDENTITY_COOKIE_NAME: "__Http-Azents-Runtime-Web"'
        in rendered
    )
    deployment = _rendered_resource(
        rendered,
        kind="Deployment",
        name="runtime-web-gateway",
    )
    hpa = _rendered_resource(
        rendered,
        kind="HorizontalPodAutoscaler",
        name="runtime-web-gateway",
    )
    assert "terminationGracePeriodSeconds: 150" in deployment
    assert "containerPort: 8041" in deployment
    assert "path: /__azents/drain" in deployment
    assert "path: /__azents/live" in deployment
    assert "port: operations" in deployment
    assert "AZ_RUNTIME_WEB_GATEWAY_CONTROL_SESSION_POOL_SIZE" in deployment
    assert "AZ_RUNTIME_WEB_GATEWAY_MAXIMUM_ACTIVE_EXCHANGES" in deployment
    assert "AZ_RUNTIME_WEB_GATEWAY_MAXIMUM_CONTROL_BUFFER_BYTES" in deployment
    assert "AZ_RUNTIME_WEB_GATEWAY_MAXIMUM_PENDING_TASKS" in deployment
    assert "path: /__azents/ready" in deployment
    assert "requests:" in deployment
    assert "cpu: 250m" in deployment
    assert "memory: 512Mi" in deployment
    assert "name: cpu" in hpa
    assert "name: memory" in hpa
    assert "stabilizationWindowSeconds: 300" in hpa


def test_gateway_hpa_can_render_optional_pressure_metric() -> None:
    rendered = _helm_template(
        *_enabled_values(),
        "server.runtimeWebGateway.autoscaling.pressure.enabled=true",
    )
    hpa = _rendered_resource(
        rendered,
        kind="HorizontalPodAutoscaler",
        name="runtime-web-gateway",
    )

    assert "type: Pods" in hpa
    assert 'name: "runtime_web_gateway_pressure"' in hpa
    assert 'averageValue: "700m"' in hpa


@pytest.mark.parametrize(
    "invalid_request",
    (
        "server.runtimeWebGateway.resources.requests.cpu=0",
        "server.runtimeWebGateway.resources.requests.memory=0Mi",
    ),
)
def test_gateway_hpa_rejects_zero_resource_requests(
    invalid_request: str,
) -> None:
    with pytest.raises(subprocess.CalledProcessError):
        _helm_template(*_enabled_values(), invalid_request)


def test_gateway_pressure_metric_contract_is_not_operator_overridable() -> None:
    with pytest.raises(subprocess.CalledProcessError):
        _helm_template(
            *_enabled_values(),
            "server.runtimeWebGateway.autoscaling.pressure.metricName=other",
        )


def test_gateway_ingress_declares_streaming_and_large_request_contract() -> None:
    rendered = _helm_template(*_enabled_values())
    ingress = _rendered_resource(
        rendered,
        kind="Ingress",
        name="runtime-web-gateway",
    )

    assert 'nginx.ingress.kubernetes.io/proxy-buffering: "off"' in ingress
    assert 'nginx.ingress.kubernetes.io/proxy-request-buffering: "off"' in ingress
    assert "nginx.ingress.kubernetes.io/proxy-body-size: 1g" in ingress
    assert 'nginx.ingress.kubernetes.io/proxy-http-version: "1.1"' in ingress
    assert 'nginx.ingress.kubernetes.io/proxy-next-upstream: "off"' in ingress
    assert 'nginx.ingress.kubernetes.io/proxy-read-timeout: "28800"' in ingress
    assert 'nginx.ingress.kubernetes.io/proxy-send-timeout: "28800"' in ingress
    assert 'nginx.ingress.kubernetes.io/ssl-redirect: "true"' in ingress


def test_enabled_gateway_configures_worker_endpoint_urls() -> None:
    rendered = _helm_template(*_enabled_values())
    worker = _rendered_resource(rendered, kind="Deployment", name="worker")

    assert 'name: AZ_RUNTIME_WEB_GATEWAY_ENABLED\n              value: "true"' in worker
    assert (
        "name: AZ_RUNTIME_WEB_GATEWAY_SERVICE_SUFFIX\n"
        '              value: "services.example.com"'
    ) in worker


def test_enabled_gateway_allows_operator_managed_external_routing() -> None:
    values = tuple(
        value
        for value in _enabled_values()
        if not value.startswith("server.runtimeWebGateway.ingress.")
    )

    rendered = _helm_template(*values)

    assert "kind: Deployment" in rendered
    assert "name: runtime-web-gateway" in rendered
    assert "kind: Ingress" not in rendered


def test_runtime_web_configuration_change_rolls_main_web() -> None:
    shared_cookie = _helm_template(*_enabled_values())
    separate_domain = _helm_template(
        *_enabled_values(),
        "server.runtimeWebGateway.authMode=separate_domain",
    )

    checksum_pattern = re.compile(r"checksum/web-config: ([a-f0-9]{64})")
    shared_checksum = checksum_pattern.search(shared_cookie)
    separate_checksum = checksum_pattern.search(separate_domain)

    assert shared_checksum is not None
    assert separate_checksum is not None
    assert shared_checksum.group(1) != separate_checksum.group(1)


def test_gateway_requires_the_trusted_control_transport() -> None:
    values = tuple(
        value
        for value in _enabled_values()
        if value != "server.runtimeControl.webTransport.enabled=true"
    )

    with pytest.raises(subprocess.CalledProcessError) as raised:
        _helm_template(*values)

    assert "runtimecontrol.webtransport.enabled is required" in (
        raised.value.stderr.lower()
    )


def test_gateway_requires_explicit_tls_and_public_security_configuration() -> None:
    values = tuple(
        value
        for value in _enabled_values()
        if not value.startswith("server.runtimeWebGateway.controlTls.existingSecret=")
    )

    with pytest.raises(subprocess.CalledProcessError) as raised:
        _helm_template(*values)

    assert "runtimewebgateway.controltls.existingsecret is required" in (
        raised.value.stderr.lower()
    )
