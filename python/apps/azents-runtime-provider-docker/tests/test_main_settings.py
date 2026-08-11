"""Docker Runtime Provider process settings tests."""

import pytest
from azents_runtime_control.grpc_provider_client import GrpcProviderControlClient
from azents_runtime_control.provider import JsonValue

from azents_runtime_provider_docker.main import (
    ProviderSettings,
    _provider_registration,
    create_provider_control_client,
)
from azents_runtime_provider_docker.provider import RUNNER_LIMIT_ENV_NAMES

_REQUIRED_ENV = {
    "AZ_RUNTIME_CONTROL_ENDPOINT": "control:8020",
    "AZ_RUNTIME_CONTROL_ALLOW_INSECURE": "true",
    "AZ_RUNTIME_PROVIDER_ID": "provider-docker",
    "AZ_RUNTIME_PROVIDER_HOST_DATA_ROOT": "/tmp/azents",
    "AZ_RUNTIME_PROVIDER_WORKSPACE_PATH": "/runtime/home",
    "AZ_RUNTIME_PROVIDER_CREDENTIAL": "test-provider-credential",
}


def _expected_capability_contract() -> dict[str, JsonValue]:
    return {
        "schema_version": 1,
        "implementation_key": "docker",
        "implementation_version": "0.1.0",
        "protocol_version": "agent-runtime-provider-docker-v1",
        "core_lifecycle_operations": [
            "start",
            "stop",
            "restart",
            "reset",
            "observe",
            "terminal_delete",
        ],
        "optional_capabilities": [],
        "persistence": {
            "kind": "persistent",
            "reset_destroys_workspace": True,
            "terminal_delete_destroys_workspace": True,
        },
        "configuration_fields": [],
        "profile_contracts": [
            {
                "profile_kind": "docker_container",
                "contract_family": "docker.container-profile",
                "schema_versions": [1, 2],
                "capabilities": [
                    "docker.container-profile",
                    "runtime.resources",
                    "workspace.host-directory",
                ],
                "constraints": {
                    "maximums": {},
                    "allowed_values": {},
                },
            }
        ],
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


@pytest.mark.parametrize(
    "name",
    [
        "AZ_RUNTIME_PROVIDER_PROCESS_CONTAINMENT_BACKEND",
        "AZ_RUNTIME_PROVIDER_PROCESS_CONTAINMENT_SECURITY_PROFILE",
        "AZ_RUNTIME_PROVIDER_PROCESS_CONTAINMENT_QUALIFICATION_TIMEOUT_SECONDS",
    ],
)
def test_provider_rejects_removed_containment_environment(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv(name, "")

    with pytest.raises(RuntimeError, match=name):
        ProviderSettings()


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


def test_control_client_uses_explicit_issued_token_method(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    expected = object()
    observed: dict[str, object] = {}

    def from_endpoint(endpoint: str, **kwargs: object) -> object:
        observed["endpoint"] = endpoint
        observed.update(kwargs)
        return expected

    monkeypatch.setattr(GrpcProviderControlClient, "from_endpoint", from_endpoint)

    result = create_provider_control_client(ProviderSettings())

    assert result is expected
    assert observed["provider_auth_method"] == "azents_issued_token"


def test_registration_advertises_direct_v1_and_v2_contracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    settings = ProviderSettings()

    registration = _provider_registration(settings)

    assert registration.capability_contract == _expected_capability_contract()
    assert registration.metadata == {"tmp_path": "/tmp/agent"}
