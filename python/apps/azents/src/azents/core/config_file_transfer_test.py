"""General file defaults and gated lightweight testenv limits."""

import pytest
from pydantic import ValidationError

from azents.core.config import Config, Settings
from azents.core.file_transfer import GENERAL_FILE_MAXIMUM_BYTES


def _settings(*, enabled: bool, maximum_bytes: int | None) -> Settings:
    """Build application settings without provider or Runtime dependencies."""
    return Settings(
        rdb_host="localhost",
        rdb_user="azents",
        rdb_db_name="azents",
        auth_jwt_secret_key="test-secret",
        credential_encryption_key="test-key",
        testenv_api_enabled=enabled,
        testenv_general_file_maximum_bytes=maximum_bytes,
    )


@pytest.mark.parametrize("enabled", [False, True])
def test_general_file_limit_defaults_to_128_mib(enabled: bool) -> None:
    """Enabling testenv alone never changes the production-default policy."""
    config = Config.from_settings(_settings(enabled=enabled, maximum_bytes=None))
    assert config.general_file_maximum_bytes == GENERAL_FILE_MAXIMUM_BYTES
    assert GENERAL_FILE_MAXIMUM_BYTES == 128 * 1024 * 1024


@pytest.mark.parametrize(
    "maximum_bytes", [1, 16, 1024 * 1024, GENERAL_FILE_MAXIMUM_BYTES]
)
def test_general_file_limit_accepts_gated_lower_value(maximum_bytes: int) -> None:
    """Testenv supplies one validated effective value to every injected consumer."""
    config = Config.from_settings(_settings(enabled=True, maximum_bytes=maximum_bytes))
    assert config.general_file_maximum_bytes == maximum_bytes


def test_general_file_limit_override_requires_testenv_gate() -> None:
    """Production settings reject an accidental test-only policy override."""
    with pytest.raises(ValidationError, match="requires the testenv API gate"):
        _settings(enabled=False, maximum_bytes=16)


@pytest.mark.parametrize("maximum_bytes", [0, -1, GENERAL_FILE_MAXIMUM_BYTES + 1, True])
def test_testenv_general_file_limit_cannot_be_nonpositive_or_expanded(
    maximum_bytes: int,
) -> None:
    """The testenv knob can only lower the existing product ceiling."""
    with pytest.raises(ValidationError):
        _settings(enabled=True, maximum_bytes=maximum_bytes)


@pytest.mark.parametrize(
    "maximum_bytes", [0, -1, GENERAL_FILE_MAXIMUM_BYTES + 1, True, 1.5]
)
def test_injected_general_file_limit_is_bounded_positive_integer(
    maximum_bytes: int | float,
) -> None:
    """Typed Config construction rejects invalid effective consumer policies."""
    config = Config.from_settings(_settings(enabled=False, maximum_bytes=None))
    with pytest.raises(ValidationError):
        Config.model_validate(
            {**config.model_dump(), "general_file_maximum_bytes": maximum_bytes}
        )


def test_testenv_general_file_limit_is_read_from_prefixed_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Settings parse the small override through the existing AZ_ environment path."""
    monkeypatch.setenv("AZ_TESTENV_API_ENABLED", "true")
    monkeypatch.setenv("AZ_TESTENV_GENERAL_FILE_MAXIMUM_BYTES", "1048576")
    settings = Settings(
        rdb_host="localhost",
        rdb_user="azents",
        rdb_db_name="azents",
        auth_jwt_secret_key="test-secret",
        credential_encryption_key="test-key",
    )
    assert Config.from_settings(settings).general_file_maximum_bytes == 1024 * 1024
