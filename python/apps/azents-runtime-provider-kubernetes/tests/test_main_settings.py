"""Runtime Provider settings tests."""

import asyncio
from pathlib import Path

import pytest

from azents_runtime_provider_kubernetes.kubernetes_api import (
    ContainerResourceClaim,
    ContainerResources,
    LocalObjectReference,
)
from azents_runtime_provider_kubernetes.main import (
    ProviderSettings,
    read_provider_credential,
    wait_for_provider_credential_change,
)
from azents_runtime_provider_kubernetes.provider import RUNNER_LIMIT_ENV_NAMES


@pytest.fixture
def provider_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    for name in RUNNER_LIMIT_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AZ_RUNTIME_CONTROL_ENDPOINT", "runtime-control:8030")
    monkeypatch.setenv("AZ_RUNTIME_CONTROL_ALLOW_INSECURE", "true")
    monkeypatch.setenv(
        "AZ_RUNTIME_PROVIDER_READINESS_FILE",
        "/tmp/runtime-provider-ready",
    )
    monkeypatch.setenv("AZ_RUNTIME_PROVIDER_ID", "system-kubernetes")
    monkeypatch.setenv("AZ_RUNTIME_PROVIDER_LEASE_NAMESPACE", "azents")
    monkeypatch.setenv("AZ_RUNTIME_PROVIDER_WORKLOAD_NAMESPACE", "azents-runtime")
    monkeypatch.setenv(
        "AZ_RUNTIME_PROVIDER_LEASE_NAME",
        "azents-runtime-provider-kubernetes",
    )
    monkeypatch.setenv("AZ_RUNTIME_PROVIDER_WORKSPACE_PATH", "/workspace/agent")
    monkeypatch.setenv("AZ_RUNTIME_PROVIDER_STORAGE_CLASS", "gp3")
    monkeypatch.setenv("AZ_RUNTIME_PROVIDER_PVC_SIZE", "20Gi")
    monkeypatch.setenv("AZ_RUNTIME_PROVIDER_POD_ANNOTATIONS", "{}")
    monkeypatch.setenv("AZ_RUNTIME_PROVIDER_POD_NODE_SELECTOR", "{}")
    monkeypatch.setenv("AZ_RUNTIME_PROVIDER_POD_TOLERATIONS", "[]")
    credential_file = tmp_path / "provider-credential"
    credential_file.write_text("test-provider-credential\n")
    monkeypatch.setenv(
        "AZ_RUNTIME_PROVIDER_CREDENTIAL_FILE",
        str(credential_file),
    )
    monkeypatch.setenv("AZ_RUNTIME_PROVIDER_LEASE_DURATION_SECONDS", "30")
    return credential_file


def test_provider_settings_defaults_runner_resources_to_none(
    provider_env: Path,
) -> None:
    settings = ProviderSettings()

    assert settings.runner_resources is None
    assert settings.runner_env == {}
    assert settings.image_pull_secrets == ()
    assert settings.provider_credential_file == provider_env
    assert (
        read_provider_credential(settings.provider_credential_file)
        == "test-provider-credential"
    )


@pytest.mark.asyncio
async def test_provider_detects_projected_credential_rotation(
    provider_env: Path,
) -> None:
    settings = ProviderSettings()
    provider_env.write_text("rotated-provider-credential\n")

    await asyncio.wait_for(
        wait_for_provider_credential_change(
            settings.provider_credential_file,
            current="test-provider-credential",
            stop=asyncio.Event(),
        ),
        timeout=1,
    )


def test_provider_rejects_empty_credential_file(provider_env: Path) -> None:
    provider_env.write_text("\n")

    with pytest.raises(RuntimeError, match="credential file is empty"):
        read_provider_credential(provider_env)


def test_provider_settings_collects_runner_limit_environment(
    monkeypatch: pytest.MonkeyPatch,
    provider_env: Path,
) -> None:
    expected = {
        name: "" if index == 0 else str(index)
        for index, name in enumerate(RUNNER_LIMIT_ENV_NAMES)
    }
    for name, value in expected.items():
        monkeypatch.setenv(name, value)

    settings = ProviderSettings()

    assert settings.runner_env == expected


def test_provider_settings_accepts_runner_resources_null(
    monkeypatch: pytest.MonkeyPatch,
    provider_env: Path,
) -> None:
    monkeypatch.setenv("AZ_RUNTIME_RUNNER_RESOURCES", "null")

    settings = ProviderSettings()

    assert settings.runner_resources is None


def test_provider_settings_accepts_generic_runner_resources(
    monkeypatch: pytest.MonkeyPatch,
    provider_env: Path,
) -> None:
    monkeypatch.setenv(
        "AZ_RUNTIME_RUNNER_RESOURCES",
        (
            '{"requests":{"cpu":"500m","ephemeral-storage":"1Gi"},'
            '"limits":{"memory":"2Gi","nvidia.com/gpu":1},'
            '"claims":[{"name":"gpu-claim","request":"gpu"}]}'
        ),
    )

    settings = ProviderSettings()

    assert settings.runner_resources == ContainerResources(
        requests={"cpu": "500m", "ephemeral-storage": "1Gi"},
        limits={"memory": "2Gi", "nvidia.com/gpu": 1},
        claims=(ContainerResourceClaim(name="gpu-claim", request="gpu"),),
    )


def test_provider_settings_accepts_pod_image_pull_secrets(
    monkeypatch: pytest.MonkeyPatch,
    provider_env: Path,
) -> None:
    monkeypatch.setenv(
        "AZ_RUNTIME_PROVIDER_POD_IMAGE_PULL_SECRETS",
        '[{"name":"ecr-pull-secret"}]',
    )

    settings = ProviderSettings()

    assert settings.image_pull_secrets == (
        LocalObjectReference(name="ecr-pull-secret"),
    )
