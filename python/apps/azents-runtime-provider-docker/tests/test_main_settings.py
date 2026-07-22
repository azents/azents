"""Docker Runtime Provider process settings tests."""

import pytest

from azents_runtime_provider_docker.main import ProviderSettings
from azents_runtime_provider_docker.provider import RUNNER_LIMIT_ENV_NAMES

_REQUIRED_ENV = {
    "AZ_RUNTIME_CONTROL_ENDPOINT": "control:8020",
    "AZ_RUNTIME_PROVIDER_ID": "provider-docker",
    "AZ_RUNTIME_PROVIDER_DOCKER_NETWORK": "azents-runtime",
    "AZ_RUNTIME_PROVIDER_HOST_DATA_ROOT": "/tmp/azents",
    "AZ_RUNTIME_PROVIDER_AUTH_CREDENTIAL_ID": "provider-credential",
    "AZ_RUNTIME_PROVIDER_CREDENTIAL": "test-provider-credential",
}


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in _REQUIRED_ENV.items():
        monkeypatch.setenv(name, value)


def test_runner_limit_environment_is_empty_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    for name in RUNNER_LIMIT_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)

    assert ProviderSettings().runner_env == {}


def test_runner_limit_environment_preserves_configured_raw_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    expected = {
        name: "" if index == 0 else str(index)
        for index, name in enumerate(RUNNER_LIMIT_ENV_NAMES)
    }
    for name, value in expected.items():
        monkeypatch.setenv(name, value)

    assert ProviderSettings().runner_env == expected
