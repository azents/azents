"""Admin surface Helm render contract tests."""

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


def test_admin_surface_default_configuration_contract() -> None:
    """Default render uses Azents sessions and explicit internal URL names."""
    rendered = _helm_template()

    assert "PUBLIC_BASE_URL" in rendered
    assert "INTERNAL_PUBLIC_API_URL" in rendered
    assert "INTERNAL_ADMIN_API_URL" in rendered
    assert "ADMIN_WEB_URL" in rendered
    assert "ADMIN_API_AUTH_METHOD" not in rendered
    assert "AUTH_ENABLED" not in rendered
    assert "GITHUB_CLIENT_ID" not in rendered
    assert "GITHUB_CLIENT_SECRET" not in rendered


def test_admin_surface_routing_topology_contract() -> None:
    """Separate hosts and gateway paths are passed through without assumptions."""
    rendered = _helm_template(
        "adminWeb.publicUrl=https://gateway.example.test/platform/admin",
        "adminWeb.publicWebUrl=https://app.example.test",
        "adminWeb.publicApi.internalUrl=http://public-api.internal:8100",
        "adminWeb.adminApi.internalUrl=http://admin-api.internal:8101",
        "web.adminWebUrl=https://admin.example.test/console",
        "adminWeb.ingress.enabled=true",
        "adminWeb.ingress.hosts[0].host=admin.example.test",
        "adminWeb.ingress.hosts[0].path=/console",
        "adminWeb.ingress.hosts[0].pathType=Prefix",
    )

    assert "https://gateway.example.test/platform/admin" in rendered
    assert "https://app.example.test" in rendered
    assert "http://public-api.internal:8100" in rendered
    assert "http://admin-api.internal:8101" in rendered
    assert "https://admin.example.test/console" in rendered
    assert 'host: "admin.example.test"' in rendered
    assert 'path: "/console"' in rendered


def test_admin_surface_configured_bootstrap_secret_contract() -> None:
    """Configured bootstrap token is injected only through a Secret reference."""
    rendered = _helm_template(
        "server.systemBootstrap.existingSecret=azents-bootstrap",
        "server.systemBootstrap.tokenKey=initial-setup-token",
    )

    assert "AZ_SYSTEM_BOOTSTRAP_SETUP_TOKEN" in rendered
    assert 'name: "azents-bootstrap"' in rendered
    assert 'key: "initial-setup-token"' in rendered


def test_platform_github_app_secret_is_scoped_to_required_workloads() -> None:
    """Platform GitHub App fields use a dedicated Secret outside scheduler."""
    rendered = _helm_template(
        "server.platformGitHubApp.existingSecret=azents-github-app",
        "server.platformGitHubApp.appIdKey=app-id",
        "server.platformGitHubApp.privateKeyKey=private-key",
        "server.platformGitHubApp.clientIdKey=client-id",
        "server.platformGitHubApp.clientSecretKey=client-secret",
    )

    assert rendered.count("AZ_GITHUB_PLATFORM_APP_ID") == 3
    assert rendered.count("AZ_GITHUB_PLATFORM_PRIVATE_KEY") == 3
    assert rendered.count("AZ_GITHUB_PLATFORM_CLIENT_ID") == 3
    assert rendered.count("AZ_GITHUB_PLATFORM_CLIENT_SECRET") == 3
    assert rendered.count('name: "azents-github-app"') >= 12
    scheduler_document = next(
        document
        for document in rendered.split("---")
        if "./bin/scheduler.sh" in document
    )
    assert "AZ_GITHUB_PLATFORM_" not in scheduler_document


def test_platform_github_app_supports_mixed_field_ownership() -> None:
    """Empty field keys leave those fields under Admin-managed ownership."""
    rendered = _helm_template(
        "server.platformGitHubApp.existingSecret=azents-github-app",
        "server.platformGitHubApp.appIdKey=app-id",
        "server.platformGitHubApp.privateKeyKey=",
        "server.platformGitHubApp.clientIdKey=client-id",
        "server.platformGitHubApp.clientSecretKey=",
    )

    assert rendered.count("AZ_GITHUB_PLATFORM_APP_ID") == 3
    assert rendered.count("AZ_GITHUB_PLATFORM_CLIENT_ID") == 3
    assert "AZ_GITHUB_PLATFORM_PRIVATE_KEY" not in rendered
    assert "AZ_GITHUB_PLATFORM_CLIENT_SECRET" not in rendered


def test_admin_surface_can_be_disabled() -> None:
    """Disabling Admin Web omits its workload while keeping Main Web deployable."""
    rendered = _helm_template("adminWeb.enabled=false")

    assert "name: admin-web" not in rendered
    assert "name: web" in rendered
