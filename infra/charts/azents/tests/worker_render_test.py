"""Worker Helm render contract tests."""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

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


def _worker_deployment(rendered: str) -> dict[str, object]:
    documents = tuple(yaml.safe_load_all(rendered))
    return next(
        document
        for document in documents
        if isinstance(document, dict)
        and document.get("kind") == "Deployment"
        and document.get("metadata", {}).get("name") == "worker"
    )


def test_worker_defaults_to_one_replica() -> None:
    worker = _worker_deployment(_helm_template())

    assert worker["spec"]["replicas"] == 1


def test_worker_replica_count_is_configurable() -> None:
    worker = _worker_deployment(_helm_template("server.worker.replicas=3"))

    assert worker["spec"]["replicas"] == 3
