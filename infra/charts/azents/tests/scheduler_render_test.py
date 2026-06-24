"""Scheduler Helm render contract tests."""

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


def test_scheduler_default_on_render_contract() -> None:
    """default server values render scheduler Deployment and PDB."""
    rendered = _helm_template()

    assert "name: scheduler" in rendered
    assert "./bin/scheduler.sh" in rendered
    assert "kind: PodDisruptionBudget" in rendered


def test_scheduler_can_be_disabled() -> None:
    """scheduler gate disables scheduler resources."""
    rendered = _helm_template("server.scheduler.enabled=false")

    assert "./bin/scheduler.sh" not in rendered
