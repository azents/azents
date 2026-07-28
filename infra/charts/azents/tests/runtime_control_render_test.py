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


def _helm_template(*values: str) -> str:
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


def test_runtime_control_renders_dedicated_workspace_s3_credential_aliases() -> None:
    """Only Runtime Control receives the aliases consumed by its transfer S3 client."""
    rendered = _helm_template(
        "server.runtimeControl.enabled=true",
        "server.runtimeControl.runnerImage.repository=repo/runner",
        "server.runtimeControl.runnerImage.tag=sha",
        f"server.runtimeControl.runnerImage.digest={_RUNNER_DIGEST}",
        "objectStorage.external.endpoint=https://s3.internal",
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
