"""Concrete GitHub confirmation and external-I/O transaction regression."""

import dataclasses
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import NamedTuple
from unittest.mock import AsyncMock, MagicMock

import pytest

from azents.core.github_system_setting import PlatformGitHubAppEffective
from azents.core.system_setting import (
    SystemSettingAuditEventType,
    SystemSettingEffectiveGenerationChanged,
    SystemSettingImpactChanged,
    SystemSettingSection,
    SystemSettingValidationStatus,
)
from azents.core.system_setting_data import (
    StoredSystemSettingAuditEvent,
    SystemSettingActivated,
    SystemSettingAuditEventCreate,
    SystemSettingCandidatePending,
    SystemSettingMutation,
)
from azents.rdb.models.github_user_installation import RDBGithubUserInstallation
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.system_setting.repository import SystemSettingRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.services.system_setting.service import SystemSettingsService
from azents.testing.types import require_instance

from .client import (
    PlatformGitHubAppExternalValidation,
    PlatformGitHubAppValidationClient,
)
from .service import PlatformGitHubAppSystemSettingService
from .service_test import _mutation, _private_key, _service

SECTION = SystemSettingSection.PLATFORM_GITHUB_APP


def _valid() -> PlatformGitHubAppExternalValidation:
    return PlatformGitHubAppExternalValidation(
        status=SystemSettingValidationStatus.VALID,
        code=None,
        message=None,
        action_hint=None,
        metadata={"app_slug": "test-app"},
    )


def _client() -> PlatformGitHubAppValidationClient:
    client = MagicMock(spec=PlatformGitHubAppValidationClient)
    client.validate = AsyncMock(return_value=_valid())
    return require_instance(client, PlatformGitHubAppValidationClient)


async def _installation(
    manager: SessionManager[WriteSession],
    *,
    installation_id: int,
) -> None:
    async with manager() as session:
        user = await UserRepository().create(
            session,
            UserCreate(email=f"settings-{installation_id}@example.com"),
        )
        session.write_session.add(
            RDBGithubUserInstallation(
                user_id=user.id,
                installation_id=installation_id,
                account_login="test-organization",
                account_type="Organization",
                platform_app_id="123",
            )
        )


class _PendingIdentityChange(NamedTuple):
    """Service and captured candidate for an App identity transition."""

    service: PlatformGitHubAppSystemSettingService
    pending: SystemSettingCandidatePending


async def _pending_identity_change(
    manager: SessionManager[WriteSession],
) -> _PendingIdentityChange:
    service = _service(manager, _client())
    private_key = _private_key()
    first = await service.patch(_mutation(private_key))
    assert isinstance(first, SystemSettingActivated)
    await _installation(manager, installation_id=1234)
    pending = await service.patch(
        SystemSettingMutation(
            section=SECTION,
            expected_version=1,
            config_patch={"app_id": "456"},
            secret_actions={},
            actor_user_id=None,
        )
    )
    assert isinstance(pending, SystemSettingCandidatePending)
    assert pending.candidate.impact is not None
    assert pending.candidate.impact["confirmation_actions"] == ["activate"]
    assert pending.candidate.impact["confirmation_required"] is True
    assert "1234" not in repr(pending.candidate.impact)
    assert private_key not in repr(pending.candidate.impact)
    return _PendingIdentityChange(service=service, pending=pending)


async def test_confirmation_checks_aggregate_impact_drift_under_section_lock(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """New bound installations invalidate the captured aggregate, not just version."""
    service, pending = await _pending_identity_change(rdb_session_manager)
    await _installation(rdb_session_manager, installation_id=5678)
    with pytest.raises(SystemSettingImpactChanged) as error:
        await service.confirm_candidate(
            candidate_id=pending.candidate.id,
            expected_version=1,
            confirmation_action="activate",
            actor_user_id=None,
        )
    assert error.value.current_impact is not None
    assert error.value.current_impact["affected_installation_count"] == 2
    assert error.value.current_impact["confirmation_actions"] == ["activate"]
    state = await service.system_settings.get_state(SECTION)
    assert state.current is not None and state.current.version == 1
    assert state.candidate == pending.candidate
    audit = await service.list_audit_events(offset=0, limit=20)
    assert (
        len(
            [
                item
                for item in audit.items
                if item.event_type == SystemSettingAuditEventType.ACTIVATED
            ]
        )
        == 1
    )


async def test_confirmation_actions_and_json_list_equality_are_preserved(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """Only captured actions activate; reconnect counts stay redacted."""
    service, pending = await _pending_identity_change(rdb_session_manager)
    with pytest.raises(ValueError, match="Unsupported Platform GitHub App"):
        await service.confirm_candidate(
            candidate_id=pending.candidate.id,
            expected_version=1,
            confirmation_action="unsupported",
            actor_user_id=None,
        )
    assert await service.system_settings.get_candidate(SECTION) == pending.candidate
    activated = await service.confirm_candidate(
        candidate_id=pending.candidate.id,
        expected_version=1,
        confirmation_action="activate",
        actor_user_id=None,
    )
    assert activated.current.version == 2
    assert await service.system_settings.get_candidate(SECTION) is None
    detail = await service.get_detail()
    assert detail.binding_impact is not None
    assert detail.binding_impact.affected_installation_count == 1
    assert detail.binding_impact.reconnect_required
    audit = await service.list_audit_events(offset=0, limit=20)
    confirmations = [item for item in audit.items if item.impact_confirmed]
    assert len(confirmations) == 1
    assert confirmations[0].confirmation_action == "activate"
    assert "client-secret" not in repr(audit)


class _ActivationAuditFailure(SystemSettingRepository):
    async def append_audit_event(
        self,
        session: WriteSession,
        *,
        create: SystemSettingAuditEventCreate,
    ) -> StoredSystemSettingAuditEvent:
        result = await super().append_audit_event(session, create=create)
        if create.event_type == SystemSettingAuditEventType.ACTIVATED:
            raise ValueError("Injected confirmation audit failure.")
        return result


async def test_confirmation_partial_activation_rolls_back_candidate_and_current(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """Impact confirmation does not split activation, candidate deletion, and audit."""
    service, pending = await _pending_identity_change(rdb_session_manager)
    failing = dataclasses.replace(
        service,
        system_settings=SystemSettingsService(
            repository=dataclasses.replace(
                service.system_settings.repository,
                repository=_ActivationAuditFailure(),
            )
        ),
    )
    with pytest.raises(ValueError, match="confirmation audit failure"):
        await failing.confirm_candidate(
            candidate_id=pending.candidate.id,
            expected_version=1,
            confirmation_action="activate",
            actor_user_id=None,
        )
    state = await service.system_settings.get_state(SECTION)
    assert state.current is not None and state.current.version == 1
    assert state.candidate == pending.candidate
    assert not any(
        item.impact_confirmed
        for item in (await service.list_audit_events(offset=0, limit=20)).items
    )


async def test_github_validation_and_health_http_run_after_every_db_context_ends(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """Provider callbacks observe no retained or implicitly restarted transaction."""
    sessions: list[WriteSession] = []
    active: list[WriteSession] = []

    @asynccontextmanager
    async def tracked_manager() -> AsyncIterator[WriteSession]:
        async with rdb_session_manager() as session:
            sessions.append(session)
            active.append(session)
            try:
                yield session
            finally:
                active.remove(session)

    calls = 0

    async def validate(
        effective: PlatformGitHubAppEffective,
    ) -> PlatformGitHubAppExternalValidation:
        nonlocal calls
        assert effective.app_id == "123"
        assert not active
        assert all(not session.write_session.in_transaction() for session in sessions)
        calls += 1
        return _valid()

    client = MagicMock(spec=PlatformGitHubAppValidationClient)
    client.validate = AsyncMock(side_effect=validate)
    service = _service(
        tracked_manager, require_instance(client, PlatformGitHubAppValidationClient)
    )
    assert isinstance(
        await service.patch(_mutation(_private_key())), SystemSettingActivated
    )
    detail = await service.check_health(actor_user_id=None)
    assert detail.health is not None
    assert calls == 2
    assert not active
    assert all(not session.write_session.in_transaction() for session in sessions)


async def test_github_health_rejects_generation_changed_during_provider_check(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """A completed provider check cannot persist health for stale environment inputs."""
    service = _service(rdb_session_manager, _client())
    assert isinstance(
        await service.patch(_mutation(_private_key())), SystemSettingActivated
    )
    environment: dict[str, str] = {}
    payloads = dataclasses.replace(
        service.system_settings.repository.payloads,
        environment=dataclasses.replace(
            service.system_settings.repository.payloads.environment, values=environment
        ),
    )

    async def validate(
        _effective: PlatformGitHubAppEffective,
    ) -> PlatformGitHubAppExternalValidation:
        environment["AZ_GITHUB_PLATFORM_CLIENT_ID"] = "changed-client"
        return _valid()

    client = MagicMock(spec=PlatformGitHubAppValidationClient)
    client.validate = AsyncMock(side_effect=validate)
    service = dataclasses.replace(
        service,
        validation_client=require_instance(client, PlatformGitHubAppValidationClient),
        system_settings=SystemSettingsService(
            repository=dataclasses.replace(
                service.system_settings.repository, payloads=payloads
            )
        ),
    )
    with pytest.raises(SystemSettingEffectiveGenerationChanged):
        await service.check_health(actor_user_id=None)
    assert (await service.system_settings.get_state(SECTION)).health is None
    assert not any(
        item.event_type == SystemSettingAuditEventType.HEALTH_CHECKED
        for item in (await service.list_audit_events(offset=0, limit=20)).items
    )
