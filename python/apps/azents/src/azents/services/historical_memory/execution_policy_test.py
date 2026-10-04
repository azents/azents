"""Effective execution policy resolution and durable settings roundtrip."""

import dataclasses
from unittest.mock import AsyncMock, create_autospec

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from azents.core.crypto import CredentialCipher
from azents.core.historical_memory_system_setting import (
    HistoricalMemoryExecutionConfig,
    HistoricalMemoryExecutionSecrets,
)
from azents.core.system_setting import (
    ResolvedSystemSetting,
    SystemSettingEnvironment,
    SystemSettingGenerationHasher,
    SystemSettingSection,
    SystemSettingVersionConflict,
)
from azents.core.system_setting_data import (
    SystemSettingActivated,
    SystemSettingMutation,
)
from azents.core.system_setting_payload import SystemSettingPayloadResolver
from azents.core.system_setting_registry import get_system_setting_registry
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.github_platform_system_setting.binding import (
    PlatformGitHubAppBindingRepository,
)
from azents.repos.github_platform_system_setting.operations import (
    PlatformGitHubAppImpactRepository,
)
from azents.repos.github_platform_system_setting.repository import (
    PlatformGitHubAppSystemSettingRepository,
)
from azents.repos.system_setting.operations import SystemSettingsRepository
from azents.repos.system_setting.repository import SystemSettingRepository
from azents.services.historical_memory.execution_policy import (
    HistoricalMemoryExecutionPolicyService,
)
from azents.services.system_setting.service import SystemSettingsService


def _resolved(config: HistoricalMemoryExecutionConfig) -> ResolvedSystemSetting:
    return ResolvedSystemSetting(
        section=SystemSettingSection.HISTORICAL_MEMORY_EXECUTION,
        schema_version=1,
        admin_version=0,
        config=config,
        secrets=HistoricalMemoryExecutionSecrets(),
        field_sources={},
        effective_generation="test-generation",
    )


def _service(session_manager: SessionManager[WriteSession]) -> SystemSettingsService:
    """Use the real registered resolver and local rollback-isolated repositories."""
    key = Fernet.generate_key().decode()
    cipher = CredentialCipher(key)
    github = PlatformGitHubAppSystemSettingRepository()
    return SystemSettingsService(
        repository=SystemSettingsRepository(
            session_manager=session_manager,
            read_session_manager=session_manager,
            repository=SystemSettingRepository(),
            payloads=SystemSettingPayloadResolver(
                registry=get_system_setting_registry(),
                cipher=cipher,
                environment=SystemSettingEnvironment(values={}),
                generation_hasher=SystemSettingGenerationHasher(key),
            ),
            github_impact=PlatformGitHubAppImpactRepository(
                session_manager=session_manager,
                impact_repository=github,
                bindings=PlatformGitHubAppBindingRepository(
                    repository=github, cipher=cipher
                ),
            ),
        )
    )


async def test_policy_resolves_current_settings_on_every_operation() -> None:
    """No process cache hides a subsequent system-admin policy change."""
    settings = create_autospec(SystemSettingsService, instance=True, spec_set=True)
    initial = HistoricalMemoryExecutionConfig()
    changed = HistoricalMemoryExecutionConfig(max_turns=3, timeout_seconds=90)
    settings.resolve = AsyncMock(side_effect=[_resolved(initial), _resolved(changed)])
    policy = HistoricalMemoryExecutionPolicyService(system_settings=settings)
    assert await policy.resolve() is initial
    assert await policy.resolve() is changed
    assert settings.resolve.await_count == 2
    settings.resolve.assert_awaited_with(
        SystemSettingSection.HISTORICAL_MEMORY_EXECUTION
    )


async def test_policy_rejects_wrong_typed_config() -> None:
    settings = create_autospec(SystemSettingsService, instance=True, spec_set=True)
    wrong = dataclasses.replace(
        _resolved(HistoricalMemoryExecutionConfig()),
        config=HistoricalMemoryExecutionSecrets(),
    )
    settings.resolve = AsyncMock(return_value=wrong)
    with pytest.raises(TypeError, match="execution settings model"):
        await HistoricalMemoryExecutionPolicyService(system_settings=settings).resolve()


async def test_policy_propagates_settings_failure() -> None:
    settings = create_autospec(SystemSettingsService, instance=True, spec_set=True)
    settings.resolve = AsyncMock(side_effect=RuntimeError("settings unavailable"))
    with pytest.raises(RuntimeError, match="settings unavailable"):
        await HistoricalMemoryExecutionPolicyService(system_settings=settings).resolve()


async def test_database_roundtrip_defaults_partial_update_null_and_stale_version(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """Real storage preserves omitted fields and explicit unlimited turns."""
    settings = _service(rdb_session_manager)
    policy = HistoricalMemoryExecutionPolicyService(system_settings=settings)
    assert await policy.resolve() == HistoricalMemoryExecutionConfig()
    initial = await settings.resolve(SystemSettingSection.HISTORICAL_MEMORY_EXECUTION)
    assert initial.admin_version == 0

    updated = await settings.mutate(
        SystemSettingMutation(
            section=SystemSettingSection.HISTORICAL_MEMORY_EXECUTION,
            expected_version=0,
            config_patch={"max_turns": 4, "timeout_seconds": 120},
            secret_actions={},
            actor_user_id=None,
        )
    )
    assert isinstance(updated, SystemSettingActivated)
    assert updated.current.version == 1
    assert await policy.resolve() == HistoricalMemoryExecutionConfig(
        max_turns=4, timeout_seconds=120
    )

    with pytest.raises(SystemSettingVersionConflict) as stale:
        await settings.mutate(
            SystemSettingMutation(
                section=SystemSettingSection.HISTORICAL_MEMORY_EXECUTION,
                expected_version=0,
                config_patch={"timeout_seconds": 1},
                secret_actions={},
                actor_user_id=None,
            )
        )
    assert stale.value.current_version == 1

    cleared = await settings.mutate(
        SystemSettingMutation(
            section=SystemSettingSection.HISTORICAL_MEMORY_EXECUTION,
            expected_version=1,
            config_patch={"max_turns": None},
            secret_actions={},
            actor_user_id=None,
        )
    )
    assert isinstance(cleared, SystemSettingActivated)
    assert cleared.current.version == 2
    assert cleared.current.config == {"max_turns": None, "timeout_seconds": 120}
    assert await policy.resolve() == HistoricalMemoryExecutionConfig(
        max_turns=None, timeout_seconds=120
    )

    with pytest.raises(ValidationError):
        await settings.mutate(
            SystemSettingMutation(
                section=SystemSettingSection.HISTORICAL_MEMORY_EXECUTION,
                expected_version=2,
                config_patch={"timeout_seconds": 0},
                secret_actions={},
                actor_user_id=None,
            )
        )
    retained = await _service(rdb_session_manager).resolve(
        SystemSettingSection.HISTORICAL_MEMORY_EXECUTION
    )
    assert retained.admin_version == 2
    assert retained.config == cleared.resolved.config
