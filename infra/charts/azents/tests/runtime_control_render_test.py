"""Runtime Control Helm render contract tests."""

import shutil
import subprocess
from pathlib import Path

import pytest

CHART_DIR = Path(__file__).resolve().parents[1]
_RUNNER_DIGEST = f"sha256:{'a' * 64}"
_ENGINE_DIGEST = f"sha256:{'c' * 64}"
_SERVER_DIGEST = f"sha256:{'d' * 64}"
_WEB_DIGEST = f"sha256:{'e' * 64}"
_ADMIN_WEB_DIGEST = f"sha256:{'f' * 64}"


def _helm_template(*values: str, json_values: tuple[str, ...] = ()) -> str:
    """Run helm template or skip when helm is unavailable."""
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
        "secrets.existingSecrets.redis=azents-redis",
        "server.runtimeControl.tls.existingSecret=azents-runtime-control-tls",
    )
    if "server.runtimeControl.enabled=true" in values:
        object_storage_defaults = {
            "endpoint": "objectStorage.external.endpoint=https://s3.internal",
            "bucket": "objectStorage.external.bucket=workspace-bucket",
        }
        configured_keys = {
            value.removeprefix("objectStorage.external.").split("=", 1)[0]
            for value in values
            if value.startswith("objectStorage.external.")
        }
        configured_keys.update(
            value.removeprefix("objectStorage.external.").split("=", 1)[0]
            for value in json_values
            if value.startswith("objectStorage.external.")
        )
        base_values += tuple(
            value
            for key, value in object_storage_defaults.items()
            if key not in configured_keys
        )
    for value in (*base_values, *values):
        command.extend(["--set", value])
    for value in json_values:
        command.extend(["--set-json", value])
    completed = subprocess.run(
        command,
        cwd=CHART_DIR,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def test_runtime_control_default_off_render_contract() -> None:
    """default values do not render runtime-control."""
    rendered = _helm_template()

    assert "runtime-control" not in rendered


def test_server_component_digest_pinning_render_contract() -> None:
    """Server, web, and admin web images render tag plus digest when configured."""
    rendered = _helm_template(
        f"server.image.digest={_SERVER_DIGEST}",
        f"web.image.digest={_WEB_DIGEST}",
        f"adminWeb.image.digest={_ADMIN_WEB_DIGEST}",
    )

    assert f"repo/server:sha@{_SERVER_DIGEST}" in rendered
    assert f"repo/web:sha@{_WEB_DIGEST}" in rendered
    assert f"repo/admin-web:sha@{_ADMIN_WEB_DIGEST}" in rendered


def test_runtime_control_enabled_render_contract() -> None:
    """enabled values render runtime-control and Runner image env."""
    rendered = _helm_template(
        "server.runtimeControl.enabled=true",
        "server.image.repository=repo/server",
        "server.image.tag=sha",
        "server.runtimeControl.runnerImage.repository=repo/runner",
        "server.runtimeControl.runnerImage.tag=sha",
        f"server.runtimeControl.runnerImage.digest={_RUNNER_DIGEST}",
        "secrets.existingSecrets.auth=azents-auth",
    )

    assert 'command: ["./bin/runtime-control.sh"]' in rendered
    assert "initialDelaySeconds: 5" in rendered
    assert "AZ_RUNTIME_CONTROL_AUTH_TOKEN" not in rendered
    assert "AZ_RUNTIME_CONTROL_ALLOW_INSECURE" in rendered
    assert "AZ_RUNTIME_CONTROL_KUBERNETES_TOKEN_REVIEW_ENABLED" in rendered
    assert "AZ_RUNTIME_CONTROL_TLS_CERTIFICATE_FILE" in rendered
    assert "azents-runtime-control-tls" in rendered
    assert "AZ_RUNTIME_RUNNER_IMAGE" in rendered
    assert "AZ_RUNTIME_CONTROL_TRANSFER_BACKEND" in rendered
    assert 'value: "redis"' in rendered
    assert (
        "name: AZ_RUNTIME_CONTROL_TRANSFER_REDIS_NAMESPACE\n"
        '              value: "azents:runtime:transfer:v2"'
    ) in rendered
    assert "AZ_RUNTIME_CONTROL_TRANSFER_OBJECT_PREFIX" in rendered
    assert "AZ_RUNTIME_TRANSFER_COORDINATOR_ENDPOINT" in rendered
    assert "AZ_RUNTIME_TRANSFER_COORDINATOR_TLS_CA_FILE" in rendered
    assert "AZ_RUNTIME_TRANSFER_COORDINATOR_ALLOW_INSECURE" in rendered
    assert "AZ_CREDENTIAL_ENCRYPTION_KEY" in rendered
    assert "azents-auth" in rendered
    assert f"repo/runner:sha@{_RUNNER_DIGEST}" in rendered
    assert "kind: ClusterRole" in rendered
    assert 'resources: ["tokenreviews"]' in rendered
    assert 'verbs: ["create"]' in rendered
    assert "azents-runtime-control-tokenreview" in rendered
    tokenreview_binding = rendered[rendered.index("kind: ClusterRoleBinding") :]
    tokenreview_binding = tokenreview_binding[: tokenreview_binding.index("---\n", 4)]
    assert 'name: "azents-server"' in tokenreview_binding
    assert 'namespace: "default"' in tokenreview_binding
    assert "azents-runtime-provider-kubernetes" not in tokenreview_binding
    assert rendered.count("mountPath: /var/run/secrets/azents/runtime-control-tls") == 3


def test_runtime_control_web_transport_renders_capacity_and_internal_lifecycle() -> (
    None
):
    """Runtime Web capacity and operations stay explicit and internal-only."""
    rendered = _helm_template(
        "server.runtimeControl.enabled=true",
        "server.runtimeControl.runnerImage.repository=repo/runner",
        "server.runtimeControl.runnerImage.tag=sha",
        f"server.runtimeControl.runnerImage.digest={_RUNNER_DIGEST}",
        "server.runtimeControl.webTransport.enabled=true",
        "server.runtimeControl.webTransport.gatewayPeerIdentities=runtime-web-gateway",
        "server.runtimeControl.webTransport.controlPeerIdentities=runtime-control",
    )
    deployment_start = rendered.index(
        "kind: Deployment\nmetadata:\n  name: runtime-control"
    )
    deployment = rendered[
        deployment_start : rendered.index("\n---\n", deployment_start)
    ]
    service_start = rendered.index("kind: Service\nmetadata:\n  name: runtime-control")
    service = rendered[service_start : rendered.index("\n---\n", service_start)]

    assert "terminationGracePeriodSeconds: 150" in deployment
    assert "name: operations" in deployment
    assert "containerPort: 8033" in deployment
    assert (
        'name: AZ_RUNTIME_CONTROL_WEB_METRICS_PORT\n              value: "8033"'
    ) in deployment
    expected_capacity = {
        "AZ_RUNTIME_CONTROL_WEB_CAPACITY_BACKEND": "memory",
        "AZ_RUNTIME_CONTROL_WEB_CAPACITY_MAXIMUM_ACTIVE_STREAMS": "64",
        "AZ_RUNTIME_CONTROL_WEB_CAPACITY_MAXIMUM_SSE_STREAMS": "8",
        "AZ_RUNTIME_CONTROL_WEB_CAPACITY_MAXIMUM_WEBSOCKET_STREAMS": "8",
        "AZ_RUNTIME_CONTROL_WEB_CAPACITY_MAXIMUM_PENDING_OPENS": "64",
        "AZ_RUNTIME_CONTROL_WEB_CAPACITY_MAXIMUM_BUFFER_BYTES": "67108864",
        "AZ_RUNTIME_CONTROL_WEB_CAPACITY_INBOUND_BYTES_PER_SECOND": "1073741824",
        "AZ_RUNTIME_CONTROL_WEB_CAPACITY_OUTBOUND_BYTES_PER_SECOND": "1073741824",
        "AZ_RUNTIME_CONTROL_WEB_CAPACITY_BURST_BYTES": "67108864",
        "AZ_RUNTIME_CONTROL_WEB_CAPACITY_REDIS_NAMESPACE": (
            "azents:runtime:web:capacity"
        ),
        "AZ_RUNTIME_CONTROL_WEB_CAPACITY_REDIS_TTL_SECONDS": "30",
        "AZ_RUNTIME_CONTROL_WEB_MAXIMUM_RELAY_SESSIONS": "32",
        "AZ_RUNTIME_CONTROL_WEB_HARD_MAXIMUM_SESSIONS": "128",
        "AZ_RUNTIME_CONTROL_WEB_HARD_MAXIMUM_ACTIVE_STREAMS": "1024",
        "AZ_RUNTIME_CONTROL_WEB_HARD_MAXIMUM_APPLICATION_BUFFER_BYTES": "536870912",
        "AZ_RUNTIME_CONTROL_WEB_HARD_MAXIMUM_CONTROL_BUFFER_BYTES": "67108864",
        "AZ_RUNTIME_CONTROL_WEB_HARD_MAXIMUM_QUEUED_ENVELOPES": "4096",
        "AZ_RUNTIME_CONTROL_WEB_HARD_MAXIMUM_PENDING_TASKS": "2048",
        "AZ_RUNTIME_CONTROL_WEB_HARD_MAXIMUM_EVENT_LOOP_LAG_MILLISECONDS": "250",
        "AZ_RUNTIME_CONTROL_WEB_HARD_MAXIMUM_RESIDENT_MEMORY_BYTES": "1073741824",
    }
    for name, value in expected_capacity.items():
        assert f'name: {name}\n              value: "{value}"' in deployment
    assert "path: /__azents/runtime-web/ready" not in deployment
    assert (
        "readinessProbe:\n            tcpSocket:\n              port: grpc"
        in deployment
    )
    assert deployment.count("path: /__azents/runtime-web/live") == 2
    assert "/__azents/runtime-web/drain" in deployment
    assert 'method="POST"' in deployment
    assert "timeout=140" in deployment
    assert "port: operations" in deployment
    assert "name: operations" not in service
    assert "8033" not in service


@pytest.mark.parametrize(
    "invalid_value",
    (
        "server.runtimeControl.metricsPort=0",
        "server.runtimeControl.webCapacity.maximumActiveStreams=0",
        "server.runtimeControl.webCapacity.maximumSseStreams=0",
        "server.runtimeControl.webCapacity.maximumWebsocketStreams=0",
        "server.runtimeControl.webCapacity.maximumPendingOpens=0",
        "server.runtimeControl.webCapacity.maximumBufferBytes=0",
        "server.runtimeControl.webCapacity.inboundBytesPerSecond=0",
        "server.runtimeControl.webCapacity.outboundBytesPerSecond=0",
        "server.runtimeControl.webCapacity.burstBytes=0",
        "server.runtimeControl.webCapacity.backend=other",
        "server.runtimeControl.webCapacity.redisNamespace=",
        "server.runtimeControl.webCapacity.redisTtlSeconds=0",
        "server.runtimeControl.webCapacity.redisTtlSeconds=301",
        "server.runtimeControl.webCapacity.maximumRelaySessions=0",
        "server.runtimeControl.webCapacity.maximumRelaySessions=257",
        "server.runtimeControl.terminationGracePeriodSeconds=149",
    ),
)
def test_runtime_control_web_capacity_schema_rejects_invalid_values(
    invalid_value: str,
) -> None:
    with pytest.raises(subprocess.CalledProcessError):
        _helm_template(
            "server.runtimeControl.enabled=true",
            "server.runtimeControl.webTransport.enabled=true",
            "server.runtimeControl.webTransport.gatewayPeerIdentities=runtime-web-gateway",
            "server.runtimeControl.webTransport.controlPeerIdentities=runtime-control",
            "server.runtimeControl.runnerImage.repository=repo/runner",
            "server.runtimeControl.runnerImage.tag=sha",
            f"server.runtimeControl.runnerImage.digest={_RUNNER_DIGEST}",
            invalid_value,
        )


@pytest.mark.parametrize(
    "invalid_value",
    (
        "server.runtimeControl.webCapacity.maximumActiveStreams=7",
        "server.runtimeControl.webCapacity.maximumWebsocketStreams=65",
        "server.runtimeControl.metricsPort=8030",
        "server.runtimeControl.metricsPort=8032",
    ),
)
def test_runtime_control_web_template_rejects_cross_field_conflicts(
    invalid_value: str,
) -> None:
    with pytest.raises(subprocess.CalledProcessError):
        _helm_template(
            "server.runtimeControl.enabled=true",
            "server.runtimeControl.webTransport.enabled=true",
            "server.runtimeControl.webTransport.gatewayPeerIdentities=runtime-web-gateway",
            "server.runtimeControl.webTransport.controlPeerIdentities=runtime-control",
            "server.runtimeControl.runnerImage.repository=repo/runner",
            "server.runtimeControl.runnerImage.tag=sha",
            f"server.runtimeControl.runnerImage.digest={_RUNNER_DIGEST}",
            invalid_value,
        )


def test_runtime_control_web_capacity_can_select_redis_explicitly() -> None:
    rendered = _helm_template(
        "server.runtimeControl.enabled=true",
        "server.runtimeControl.webTransport.enabled=true",
        "server.runtimeControl.webTransport.gatewayPeerIdentities=runtime-web-gateway",
        "server.runtimeControl.webTransport.controlPeerIdentities=runtime-control",
        "server.runtimeControl.webCapacity.backend=redis",
        "server.runtimeControl.webCapacity.redisNamespace=custom:web:capacity",
        "server.runtimeControl.runnerImage.repository=repo/runner",
        "server.runtimeControl.runnerImage.tag=sha",
        f"server.runtimeControl.runnerImage.digest={_RUNNER_DIGEST}",
    )

    assert (
        'name: AZ_RUNTIME_CONTROL_WEB_CAPACITY_BACKEND\n              value: "redis"'
    ) in rendered
    assert (
        "name: AZ_RUNTIME_CONTROL_WEB_CAPACITY_REDIS_NAMESPACE\n"
        '              value: "custom:web:capacity"'
    ) in rendered


def test_runtime_control_renders_values_object_numbers_as_decimal_integers() -> None:
    """ArgoCD valuesObject numbers remain valid integer environment values."""
    rendered = _helm_template(
        "server.runtimeControl.enabled=true",
        "server.runtimeControl.runnerImage.repository=repo/runner",
        "server.runtimeControl.runnerImage.tag=sha",
        f"server.runtimeControl.runnerImage.digest={_RUNNER_DIGEST}",
        json_values=(
            "server.runtimeControl.transfer.perRuntimeBytes=8388608",
            "server.runtimeControl.transfer.deploymentBytes=33554432",
            "server.runtimeControl.transfer.multipartPartBytes=5242880",
        ),
    )

    assert (
        "name: AZ_RUNTIME_CONTROL_TRANSFER_PER_RUNTIME_BYTES\n"
        '              value: "8388608"'
    ) in rendered
    assert (
        "name: AZ_RUNTIME_CONTROL_TRANSFER_DEPLOYMENT_BYTES\n"
        '              value: "33554432"'
    ) in rendered
    assert (
        "name: AZ_RUNTIME_CONTROL_TRANSFER_MULTIPART_PART_BYTES\n"
        '              value: "5242880"'
    ) in rendered


def test_runtime_control_renders_dedicated_workspace_s3_credential_aliases() -> None:
    """Only Runtime Control receives the aliases consumed by its transfer S3 client."""
    rendered = _helm_template(
        "server.runtimeControl.enabled=true",
        "server.runtimeControl.runnerImage.repository=repo/runner",
        "server.runtimeControl.runnerImage.tag=sha",
        f"server.runtimeControl.runnerImage.digest={_RUNNER_DIGEST}",
        "objectStorage.external.endpoint=https://s3.internal",
        "objectStorage.external.publicEndpoint=https://s3.example.com",
        "objectStorage.external.bucket=workspace-bucket",
        "secrets.existingSecrets.objectStorage=workspace-s3-credentials",
    )
    start = rendered.index("kind: Deployment\nmetadata:\n  name: runtime-control")
    runtime_control = rendered[start : rendered.index("\n---\n", start)]

    assert "AZ_RUNTIME_CONTROL_WORKSPACE_S3_ENDPOINT_URL" in rendered
    assert "AZ_RUNTIME_CONTROL_WORKSPACE_S3_BUCKET" in rendered
    assert rendered.count("AZ_RUNTIME_CONTROL_WORKSPACE_S3_ENDPOINT_URL") == 1
    assert rendered.count("AZ_RUNTIME_CONTROL_WORKSPACE_S3_BUCKET") == 1
    assert "name: AZ_RUNTIME_CONTROL_WORKSPACE_S3_ACCESS_KEY_ID" in runtime_control
    assert "name: AZ_RUNTIME_CONTROL_WORKSPACE_S3_SECRET_ACCESS_KEY" in runtime_control
    assert 'name: "workspace-s3-credentials"' in runtime_control
    assert rendered.count("AZ_RUNTIME_CONTROL_WORKSPACE_S3_ACCESS_KEY_ID") == 1
    assert rendered.count("AZ_RUNTIME_CONTROL_WORKSPACE_S3_SECRET_ACCESS_KEY") == 1
    assert (
        "name: AZ_RUNTIME_CONTROL_WORKSPACE_S3_PUBLIC_ENDPOINT_URL\n"
        '              value: "https://s3.example.com"'
    ) in runtime_control


def test_server_renders_distinct_public_s3_endpoint() -> None:
    """The browser endpoint is independent from trusted internal S3 traffic."""
    rendered = _helm_template(
        "objectStorage.external.endpoint=http://s3.internal",
        "objectStorage.external.publicEndpoint=https://s3.example.com",
        "objectStorage.external.bucket=workspace-bucket",
    )

    assert 'AZ_WORKSPACE_S3_ENDPOINT_URL: "http://s3.internal"' in rendered
    assert 'AZ_WORKSPACE_S3_PUBLIC_ENDPOINT_URL: "https://s3.example.com"' in rendered
    assert rendered.count("AZ_WORKSPACE_S3_PUBLIC_ENDPOINT_URL") == 1


def test_runtime_control_renders_distinct_public_s3_endpoint() -> None:
    """Runtime Control receives the public endpoint used by presigned URLs."""
    rendered = _helm_template(
        "server.runtimeControl.enabled=true",
        "server.runtimeControl.runnerImage.repository=repo/runner",
        "server.runtimeControl.runnerImage.tag=sha",
        f"server.runtimeControl.runnerImage.digest={_RUNNER_DIGEST}",
        "objectStorage.external.endpoint=http://s3.internal",
        "objectStorage.external.publicEndpoint=https://s3.example.com",
        "objectStorage.external.bucket=workspace-bucket",
    )
    start = rendered.index("kind: Deployment\nmetadata:\n  name: runtime-control")
    runtime_control = rendered[start : rendered.index("\n---\n", start)]

    assert (
        "name: AZ_RUNTIME_CONTROL_WORKSPACE_S3_PUBLIC_ENDPOINT_URL\n"
        '              value: "https://s3.example.com"'
    ) in runtime_control
    assert rendered.count("AZ_RUNTIME_CONTROL_WORKSPACE_S3_PUBLIC_ENDPOINT_URL") == 1


def test_runtime_control_enables_token_review_for_kubernetes_provider() -> None:
    """Kubernetes Provider enables TokenReview on Runtime Control."""
    rendered = _helm_template(
        "server.runtimeControl.enabled=true",
        "server.runtimeControl.runnerImage.repository=repo/runner",
        "server.runtimeControl.runnerImage.tag=sha",
        f"server.runtimeControl.runnerImage.digest={_RUNNER_DIGEST}",
        "runtimeProviderKubernetes.enabled=true",
        "runtimeProviderKubernetes.image.repository=repo/provider",
        "runtimeProviderKubernetes.image.tag=sha",
        "runtimeProviderKubernetes.runnerImage.repository=repo/runner",
        "runtimeProviderKubernetes.runnerImage.tag=sha",
        f"runtimeProviderKubernetes.runnerImage.digest={_RUNNER_DIGEST}",
    )

    runtime_control = rendered[rendered.index("name: runtime-control") :]
    assert (
        "name: AZ_RUNTIME_CONTROL_KUBERNETES_TOKEN_REVIEW_ENABLED\n"
        '              value: "true"'
    ) in runtime_control


def test_runtime_control_allows_single_replica_configuration() -> None:
    """Runtime Control scaling is deployment-defined."""
    rendered = _helm_template(
        "server.runtimeControl.enabled=true",
        "server.runtimeControl.replicas=1",
        "server.runtimeControl.autoscaling.enabled=false",
        "server.runtimeControl.runnerImage.repository=repo/runner",
        "server.runtimeControl.runnerImage.tag=sha",
        f"server.runtimeControl.runnerImage.digest={_RUNNER_DIGEST}",
    )

    assert "replicas: 1" in rendered
    assert "maxUnavailable: 1" in rendered


def test_runtime_control_supports_cutover_scale_zero_without_hpa_or_pdb() -> None:
    """One release can stop every legacy allocator before schema activation."""
    rendered = _helm_template(
        "server.runtimeControl.enabled=true",
        "server.runtimeControl.replicas=0",
        "server.runtimeControl.autoscaling.enabled=false",
        "server.runtimeControl.pdb.enabled=false",
        "server.runtimeControl.runnerImage.repository=repo/runner",
        "server.runtimeControl.runnerImage.tag=sha",
        f"server.runtimeControl.runnerImage.digest={_RUNNER_DIGEST}",
    )

    runtime_control = rendered[
        rendered.index("kind: Deployment\nmetadata:\n  name: runtime-control") :
    ]
    assert "replicas: 0" in runtime_control
    assert "kind: HorizontalPodAutoscaler" not in rendered
    assert "kind: PodDisruptionBudget" not in runtime_control


def test_runtime_control_runner_requires_immutable_digest() -> None:
    with pytest.raises(subprocess.CalledProcessError) as raised:
        _helm_template(
            "server.runtimeControl.enabled=true",
            "server.runtimeControl.runnerImage.repository=repo/runner",
            "server.runtimeControl.runnerImage.tag=sha",
        )

    assert "server.runtimecontrol.runnerimage.digest is required" in (
        raised.value.stderr.lower()
    )


def test_runtime_control_rejects_memory_transfer_state_with_hpa() -> None:
    """Memory transfer state cannot route requests across Control replicas."""
    with pytest.raises(subprocess.CalledProcessError) as raised:
        _helm_template(
            "server.runtimeControl.enabled=true",
            "server.runtimeControl.transfer.stateBackend=memory",
            "server.runtimeControl.runnerImage.repository=repo/runner",
            "server.runtimeControl.runnerImage.tag=sha",
            f"server.runtimeControl.runnerImage.digest={_RUNNER_DIGEST}",
        )

    assert "memory Runtime Transfer state requires exactly one" in raised.value.stderr


def test_runtime_control_allows_memory_transfer_state_for_single_replica() -> None:
    """Runtime Transfer remains usable without Redis-backed transfer state."""
    rendered = _helm_template(
        "server.runtimeControl.enabled=true",
        "server.runtimeControl.replicas=1",
        "server.runtimeControl.autoscaling.enabled=false",
        "server.runtimeControl.transfer.stateBackend=memory",
        "server.runtimeControl.runnerImage.repository=repo/runner",
        "server.runtimeControl.runnerImage.tag=sha",
        f"server.runtimeControl.runnerImage.digest={_RUNNER_DIGEST}",
    )

    assert "name: AZ_RUNTIME_CONTROL_TRANSFER_BACKEND" in rendered
    assert 'value: "memory"' in rendered


def test_runtime_control_rejects_removed_lifecycle_acknowledgement_values() -> None:
    """Removed deployment acknowledgement cannot silently regain lifespan authority."""
    with pytest.raises(subprocess.CalledProcessError) as raised:
        _helm_template(
            "server.runtimeControl.enabled=true",
            "server.runtimeControl.transfer.lifecycleAcknowledgement.owner=platform",
            "server.runtimeControl.runnerImage.repository=repo/runner",
            "server.runtimeControl.runnerImage.tag=sha",
            f"server.runtimeControl.runnerImage.digest={_RUNNER_DIGEST}",
        )

    error = raised.value.stderr.lower()
    assert "schema" in error
    assert "lifecycleacknowledgement" in error


def test_runtime_control_rejects_transfer_list_page_above_s3_limit() -> None:
    """Runtime Transfer page bounds remain compatible with S3 list APIs."""
    with pytest.raises(subprocess.CalledProcessError) as raised:
        _helm_template(
            "server.runtimeControl.enabled=true",
            "server.runtimeControl.transfer.listPageSize=1001",
            "server.runtimeControl.runnerImage.repository=repo/runner",
            "server.runtimeControl.runnerImage.tag=sha",
            f"server.runtimeControl.runnerImage.digest={_RUNNER_DIGEST}",
        )

    error = raised.value.stderr.lower()
    assert "schema" in error
    assert "listpagesize" in error


def test_runtime_control_rejects_removed_shared_auth_values() -> None:
    """Removed shared-token values fail chart schema validation."""
    with pytest.raises(subprocess.CalledProcessError) as raised:
        _helm_template(
            "server.runtimeControl.enabled=true",
            "server.runtimeControl.auth.enabled=true",
            "server.runtimeControl.auth.existingSecret=azents-runtime-control-auth",
            "server.runtimeControl.runnerImage.repository=repo/runner",
            "server.runtimeControl.runnerImage.tag=sha",
            f"server.runtimeControl.runnerImage.digest={_RUNNER_DIGEST}",
        )

    error = raised.value.stderr.lower()
    assert "schema" in error
    assert "auth" in error
    assert "not allowed" in error


def test_runtime_control_requires_workspace_s3_bucket() -> None:
    """Runtime Control cannot render without a Workspace Upload bucket."""
    with pytest.raises(subprocess.CalledProcessError) as raised:
        _helm_template(
            "server.runtimeControl.enabled=true",
            "objectStorage.external.bucket=",
            "server.runtimeControl.runnerImage.repository=repo/runner",
            "server.runtimeControl.runnerImage.tag=sha",
            f"server.runtimeControl.runnerImage.digest={_RUNNER_DIGEST}",
        )

    error = raised.value.stderr.lower()
    assert "objectstorage/external/bucket" in error
    assert "minlength" in error
