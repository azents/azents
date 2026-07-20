"""Runtime Control Helm render contract tests."""

import shutil
import subprocess
from pathlib import Path

import pytest

CHART_DIR = Path(__file__).resolve().parents[1]


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
        "secrets.existingSecrets.redis=azents-redis",
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
        "server.image.digest=sha256:serverdigest",
        "web.image.digest=sha256:webdigest",
        "adminWeb.image.digest=sha256:admindigest",
    )

    assert "repo/server:sha@sha256:serverdigest" in rendered
    assert "repo/web:sha@sha256:webdigest" in rendered
    assert "repo/admin-web:sha@sha256:admindigest" in rendered


def test_runtime_control_enabled_render_contract() -> None:
    """enabled values render runtime-control and Runner image env."""
    rendered = _helm_template(
        "server.runtimeControl.enabled=true",
        "server.image.repository=repo/server",
        "server.image.tag=sha",
        "server.runtimeControl.runnerImage.repository=repo/runner",
        "server.runtimeControl.runnerImage.tag=sha",
        "server.runtimeControl.runnerImage.digest=sha256:runnerdigest",
    )

    assert "src/cli/runtime_control_server.py" in rendered
    assert "initialDelaySeconds: 5" in rendered
    assert "AZ_RUNTIME_CONTROL_AUTH_ENABLED" in rendered
    assert "AZ_RUNTIME_CONTROL_AUTH_TOKEN" not in rendered
    assert "AZ_RUNTIME_RUNNER_IMAGE" in rendered
    assert "repo/runner:sha@sha256:runnerdigest" in rendered


def test_runtime_control_allows_single_replica_configuration() -> None:
    """Runtime Control scaling is deployment-defined."""
    rendered = _helm_template(
        "server.runtimeControl.enabled=true",
        "server.runtimeControl.replicas=1",
        "server.runtimeControl.autoscaling.enabled=false",
        "server.runtimeControl.runnerImage.repository=repo/runner",
        "server.runtimeControl.runnerImage.tag=sha",
    )

    assert "replicas: 1" in rendered
    assert "maxUnavailable: 1" in rendered


def test_runtime_control_auth_enabled_render_contract() -> None:
    """auth enabled values render the Runtime Control auth token Secret ref."""
    rendered = _helm_template(
        "server.runtimeControl.enabled=true",
        "server.runtimeControl.auth.enabled=true",
        "server.runtimeControl.auth.existingSecret=azents-runtime-control-auth",
        "server.runtimeControl.runnerImage.repository=repo/runner",
        "server.runtimeControl.runnerImage.tag=sha",
    )

    assert "AZ_RUNTIME_CONTROL_AUTH_ENABLED" in rendered
    assert "AZ_RUNTIME_CONTROL_AUTH_TOKEN" in rendered
    assert "azents-runtime-control-auth" in rendered
    assert "runtime-control-token" in rendered
