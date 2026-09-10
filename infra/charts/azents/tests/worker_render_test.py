"""Worker Helm render contract tests."""

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
    command = [
        helm,
        "template",
        "azents",
        str(CHART_DIR),
        "--show-only",
        "templates/server/worker-deployment.yaml.tpl",
    ]
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


def test_worker_defaults_to_one_replica() -> None:
    rendered = _helm_template()

    assert "name: worker" in rendered
    assert "replicas: 1" in rendered


def test_worker_replica_count_is_configurable() -> None:
    rendered = _helm_template("server.worker.replicas=3")

    assert "name: worker" in rendered
    assert "replicas: 3" in rendered
