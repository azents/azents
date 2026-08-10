"""Job Runtime configuration tests."""

import pytest
from pydantic import ValidationError

from azents.core.config import Config, Settings
from azents.core.enums import JobRuntimeBackend


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "rdb_host": "localhost",
        "rdb_user": "azents",
        "rdb_db_name": "azents",
        "auth_jwt_secret_key": "test-secret",
        "credential_encryption_key": "test-key",
        **overrides,
    }
    return Settings.model_validate(values)


def test_job_runtime_defaults_to_local_across_settings_and_config() -> None:
    """Standalone and rendered deployments share the implemented Local default."""
    settings = _settings()

    assert settings.job_runtime_backend is JobRuntimeBackend.LOCAL
    assert Config.from_settings(settings).job_runtime_backend is JobRuntimeBackend.LOCAL


def test_temporal_is_reserved_as_one_closed_backend_value() -> None:
    """Temporal parses globally even though runtime startup rejects it."""
    settings = _settings(job_runtime_backend="temporal")

    assert settings.job_runtime_backend is JobRuntimeBackend.TEMPORAL
    assert (
        Config.from_settings(settings).job_runtime_backend is JobRuntimeBackend.TEMPORAL
    )


def test_per_handler_backend_value_is_rejected() -> None:
    """Configuration exposes no per-handler or mixed execution mode."""
    with pytest.raises(ValidationError):
        _settings(job_runtime_backend="mixed")
