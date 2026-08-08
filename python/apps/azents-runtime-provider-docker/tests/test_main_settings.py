"""Docker Runtime Provider process settings tests."""

import pytest
from azents_runtime_control.grpc_provider_client import GrpcProviderControlClient
from azents_runtime_control.provider import JsonValue

from azents_runtime_provider_docker.main import (
    ProviderSettings,
    _provider_registration,
    _validate_containment_security_options,
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
_CONTAINMENT_ENV_NAMES = (
    "AZ_RUNTIME_PROVIDER_PROCESS_CONTAINMENT_BACKEND",
    "AZ_RUNTIME_PROVIDER_PROCESS_CONTAINMENT_SECURITY_PROFILE",
    "AZ_RUNTIME_PROVIDER_PROCESS_CONTAINMENT_QUALIFICATION_TIMEOUT_SECONDS",
)


def _expected_capability_contract(
    *,
    containment_enabled: bool,
) -> dict[str, JsonValue]:
    capabilities = [
        "docker.container-profile",
        "runtime.resources",
        "workspace.host-directory",
    ]
    schema_versions = [1]
    if containment_enabled:
        capabilities.append("runtime.process-containment")
        schema_versions.append(2)
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
                "schema_versions": schema_versions,
                "capabilities": capabilities,
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
    for name in _CONTAINMENT_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


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


def test_registration_keeps_v1_contract_when_containment_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)

    registration = _provider_registration(ProviderSettings())

    assert registration.capability_contract == _expected_capability_contract(
        containment_enabled=False
    )
    assert "process_containment_backend" not in registration.metadata


def test_registration_advertises_v2_only_for_configured_containment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv(
        "AZ_RUNTIME_PROVIDER_PROCESS_CONTAINMENT_BACKEND",
        "bwrap",
    )
    monkeypatch.setenv(
        "AZ_RUNTIME_PROVIDER_PROCESS_CONTAINMENT_SECURITY_PROFILE",
        "azents-runtime-bwrap",
    )
    monkeypatch.setenv(
        "AZ_RUNTIME_PROVIDER_PROCESS_CONTAINMENT_QUALIFICATION_TIMEOUT_SECONDS",
        "15",
    )

    settings = ProviderSettings()
    registration = _provider_registration(settings)

    assert settings.process_containment is not None
    assert registration.capability_contract == _expected_capability_contract(
        containment_enabled=True
    )
    assert registration.metadata["process_containment_backend"] == "bwrap"


def test_incomplete_containment_settings_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv(
        "AZ_RUNTIME_PROVIDER_PROCESS_CONTAINMENT_SECURITY_PROFILE",
        "azents-runtime-bwrap",
    )

    with pytest.raises(RuntimeError, match="require a configured backend"):
        ProviderSettings()


@pytest.mark.parametrize(
    "security_profile",
    (
        "unconfined",
        "azents-runtime-bwrap-typo",
        " azents-runtime-bwrap",
    ),
)
def test_unsupported_containment_security_profiles_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
    security_profile: str,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv(
        "AZ_RUNTIME_PROVIDER_PROCESS_CONTAINMENT_BACKEND",
        "bwrap",
    )
    monkeypatch.setenv(
        "AZ_RUNTIME_PROVIDER_PROCESS_CONTAINMENT_SECURITY_PROFILE",
        security_profile,
    )
    monkeypatch.setenv(
        "AZ_RUNTIME_PROVIDER_PROCESS_CONTAINMENT_QUALIFICATION_TIMEOUT_SECONDS",
        "15",
    )

    with pytest.raises(RuntimeError, match="security profile is unsupported"):
        ProviderSettings()


@pytest.mark.parametrize(
    "security_options",
    (
        [],
        ["name=seccomp,profile=builtin", "name=cgroupns"],
    ),
)
def test_containment_requires_docker_apparmor_support(
    security_options: list[str],
) -> None:
    with pytest.raises(RuntimeError, match="requires Docker AppArmor support"):
        _validate_containment_security_options(security_options)


@pytest.mark.parametrize(
    "security_options",
    (
        ["name=apparmor"],
        ["name=apparmor,profile=default"],
    ),
)
def test_containment_accepts_docker_apparmor_support(
    security_options: list[str],
) -> None:
    _validate_containment_security_options(security_options)
