"""Runtime Control server settings tests."""

import pytest

from azents.runtime.control_server import (
    RuntimeControlSettings,
    runtime_control_auth_token,
)


def _settings(
    *,
    auth_enabled: bool,
    auth_token: str | None,
) -> RuntimeControlSettings:
    return RuntimeControlSettings(
        runtime_control_auth_enabled=auth_enabled,
        runtime_control_auth_token=auth_token,
        runtime_runner_image="runner:test",
        runtime_runner_control_endpoint="runtime-control:8030",
    )


def test_runtime_control_auth_disabled_ignores_missing_token() -> None:
    """Local/test deployments can disable Runtime Control auth explicitly."""
    settings = _settings(auth_enabled=False, auth_token=None)

    assert runtime_control_auth_token(settings) is None


def test_runtime_control_auth_enabled_requires_token() -> None:
    """Enabled Runtime Control auth fails startup validation without a token."""
    settings = _settings(auth_enabled=True, auth_token=None)

    with pytest.raises(RuntimeError, match="AZ_RUNTIME_CONTROL_AUTH_TOKEN"):
        runtime_control_auth_token(settings)


def test_runtime_control_auth_enabled_normalizes_token() -> None:
    """Runtime Control auth uses the unified AUTH_TOKEN setting name."""
    settings = _settings(auth_enabled=True, auth_token="  control-token  ")

    assert runtime_control_auth_token(settings) == "control-token"
