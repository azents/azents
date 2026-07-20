"""Provider-neutral System Settings contract tests."""

import datetime
from typing import Any

import pytest
from cryptography.fernet import Fernet
from pydantic import BaseModel

from azents.core.system_setting import (
    SystemSettingActivationMode,
    SystemSettingDefinition,
    SystemSettingEnvironment,
    SystemSettingEnvironmentBinding,
    SystemSettingFieldTarget,
    SystemSettingGenerationHasher,
    SystemSettingMissingSchemaMigration,
    SystemSettingNewerSchemaVersion,
    SystemSettingRegistry,
    SystemSettingSection,
)


class _Config(BaseModel):
    endpoint: str | None = None


class _Secrets(BaseModel):
    token: str | None = None


class _OverlappingSecrets(BaseModel):
    endpoint: str | None = None


def _validate(_config: BaseModel, _secrets: BaseModel) -> None:
    """Accept the typed payload for contract tests."""


def _definition(
    *,
    schema_version: int = 1,
    secret_model: type[BaseModel] = _Secrets,
    environment_bindings: tuple[SystemSettingEnvironmentBinding, ...] = (),
    payload_migrations: dict[
        int,
        Any,
    ]
    | None = None,
) -> SystemSettingDefinition:
    return SystemSettingDefinition(
        section=SystemSettingSection.PLATFORM_GITHUB_APP,
        schema_version=schema_version,
        config_model=_Config,
        secret_model=secret_model,
        activation_mode=SystemSettingActivationMode.DIRECT,
        environment_bindings=environment_bindings,
        candidate_ttl=datetime.timedelta(hours=24),
        local_validator=_validate,
        payload_migrations=payload_migrations or {},
    )


def test_payload_migrations_run_sequentially_without_persisting_on_read() -> None:
    """Older payloads migrate in memory through every registered schema step."""

    def migrate_v1(
        config: dict[str, Any],
        secrets: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return ({"endpoint": config["legacy_endpoint"]}, secrets)

    def migrate_v2(
        config: dict[str, Any],
        secrets: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return (config, {"token": secrets["legacy_token"]})

    definition = _definition(
        schema_version=3,
        payload_migrations={1: migrate_v1, 2: migrate_v2},
    )
    original_config = {"legacy_endpoint": "https://example.com"}
    original_secrets = {"legacy_token": "secret"}

    config, secrets = definition.migrate_payload(
        schema_version=1,
        config=original_config,
        secrets=original_secrets,
    )

    assert config == {"endpoint": "https://example.com"}
    assert secrets == {"token": "secret"}
    assert original_config == {"legacy_endpoint": "https://example.com"}
    assert original_secrets == {"legacy_token": "secret"}


def test_payload_migration_fails_closed_for_unknown_schema_versions() -> None:
    """Missing and newer schema versions are never silently interpreted."""
    definition = _definition(schema_version=2)

    with pytest.raises(SystemSettingMissingSchemaMigration):
        definition.migrate_payload(schema_version=1, config={}, secrets={})
    with pytest.raises(SystemSettingNewerSchemaVersion):
        definition.migrate_payload(schema_version=3, config={}, secrets={})


def test_registry_rejects_unknown_or_overlapping_environment_fields() -> None:
    """Compiled bindings must target unambiguous typed fields."""
    with pytest.raises(ValueError, match="unknown field"):
        SystemSettingRegistry(
            definitions=(
                _definition(
                    environment_bindings=(
                        SystemSettingEnvironmentBinding(
                            field_name="missing",
                            environment_variable="AZ_TEST_MISSING",
                            target=SystemSettingFieldTarget.CONFIG,
                        ),
                    )
                ),
            )
        )
    with pytest.raises(ValueError, match="must be distinct"):
        SystemSettingRegistry(
            definitions=(_definition(secret_model=_OverlappingSecrets),)
        )


def test_environment_presence_preserves_authoritative_empty_values() -> None:
    """Present empty values remain distinct from absent environment bindings."""
    environment = SystemSettingEnvironment(values={"AZ_TEST_TOKEN": ""})

    assert environment.contains("AZ_TEST_TOKEN")
    assert environment.get_present("AZ_TEST_TOKEN") == ""
    assert not environment.contains("AZ_TEST_ABSENT")


def test_generation_is_stable_for_equivalent_effective_payloads() -> None:
    """Generation depends only on the complete effective typed payload."""
    hasher = SystemSettingGenerationHasher(Fernet.generate_key().decode())
    config = _Config(endpoint="https://example.com")
    secrets = _Secrets(token="secret")

    first = hasher.generate(
        section=SystemSettingSection.PLATFORM_GITHUB_APP,
        schema_version=1,
        config=config,
        secrets=secrets,
    )
    second = hasher.generate(
        section=SystemSettingSection.PLATFORM_GITHUB_APP,
        schema_version=1,
        config=_Config(endpoint="https://example.com"),
        secrets=_Secrets(token="secret"),
    )
    changed = hasher.generate(
        section=SystemSettingSection.PLATFORM_GITHUB_APP,
        schema_version=1,
        config=config,
        secrets=_Secrets(token="rotated"),
    )

    assert first == second
    assert first != changed
    assert len(first) == 64
