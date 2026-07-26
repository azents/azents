"""Immutable gateway configuration tests."""

import pytest
from conftest import gateway_env

from azents_container_policy_gateway.config import gateway_config_from_env


def test_gateway_config_validates_complete_policy_before_binding() -> None:
    config = gateway_config_from_env(gateway_env(container_run=True, compose=True))

    assert config.runtime_id == "runtime-1"
    assert config.desired_generation == 3
    assert config.policy.container_run is True
    assert config.policy.compose is True


def test_gateway_config_rejects_policy_digest_mismatch() -> None:
    env = gateway_env(container_run=True)
    env["AZ_RUNTIME_EXECUTION_POLICY_DIGEST"] = "0" * 64

    with pytest.raises(ValueError, match="digest does not match"):
        gateway_config_from_env(env)


def test_gateway_config_rejects_shared_public_and_private_socket() -> None:
    env = gateway_env(container_run=True)
    env["AZ_RUNTIME_GATEWAY_ENGINE_SOCKET"] = env["AZ_RUNTIME_GATEWAY_LISTEN_SOCKET"]

    with pytest.raises(ValueError, match="must be different"):
        gateway_config_from_env(env)


@pytest.mark.parametrize(
    "name",
    [
        "AZ_RUNTIME_ID",
        "AZ_RUNTIME_EXECUTION_POLICY_DESIRED_GENERATION",
        "AZ_RUNTIME_EXECUTION_POLICY_SNAPSHOT_ID",
        "AZ_RUNTIME_EXECUTION_POLICY_DIGEST",
        "AZ_RUNTIME_EXECUTION_POLICY_MODULE_VERSIONS",
        "AZ_RUNTIME_EXECUTION_POLICY_SOURCE_VERSIONS",
        "AZ_RUNTIME_EXECUTION_POLICY_DOCUMENT",
        "AZ_RUNTIME_GATEWAY_LISTEN_SOCKET",
        "AZ_RUNTIME_GATEWAY_ENGINE_SOCKET",
    ],
)
def test_gateway_config_rejects_missing_contract_fields(name: str) -> None:
    env = gateway_env(container_run=True)
    env.pop(name)

    with pytest.raises(ValueError):
        gateway_config_from_env(env)
