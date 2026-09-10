"""Workspace configuration tests."""

import pytest
from pydantic import ValidationError

from azents.core.config import Config, Settings


def _settings(
    *,
    workspace_runner_file_operation_timeout_seconds: float | None,
) -> Settings:
    return Settings(
        rdb_host="localhost",
        rdb_user="azents",
        rdb_db_name="azents",
        auth_jwt_secret_key="test-secret",
        credential_encryption_key="test-key",
        testenv_workspace_runner_file_operation_timeout_seconds=(
            workspace_runner_file_operation_timeout_seconds
        ),
    )


def test_workspace_runner_file_operation_timeout_defaults_to_production_value() -> None:
    settings = _settings(workspace_runner_file_operation_timeout_seconds=None)

    assert settings.testenv_workspace_runner_file_operation_timeout_seconds is None
    assert (
        Config.from_settings(
            settings
        ).testenv_workspace_runner_file_operation_timeout_seconds
        is None
    )


def test_workspace_runner_file_operation_timeout_accepts_testenv_override() -> None:
    settings = _settings(workspace_runner_file_operation_timeout_seconds=10.0)

    assert (
        Config.from_settings(
            settings
        ).testenv_workspace_runner_file_operation_timeout_seconds
        == 10.0
    )


@pytest.mark.parametrize("timeout_seconds", [0.0, -1.0, float("inf")])
def test_workspace_runner_file_operation_timeout_must_be_positive_finite(
    timeout_seconds: float,
) -> None:
    with pytest.raises(ValidationError):
        _settings(workspace_runner_file_operation_timeout_seconds=timeout_seconds)
