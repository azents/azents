"""Agent deletion applies token cleanup guards before lifecycle mutation."""

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.github_user_oauth import GitHubUserErrorCode, GitHubUserOAuthError
from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.agent import AgentRepository
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.agent_decommission import AgentDecommissionRepository
from azents.repos.agent_decommission_finalizer import (
    AgentDecommissionFinalizerRepository,
)
from azents.repos.agent_operations import AgentOperationsRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.archived_session_retention import ArchivedSessionRetentionRepository
from azents.repos.runtime_profile.availability import (
    RuntimeProfileAvailabilityRepository,
)
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.repos.workspace_model_settings import WorkspaceModelSettingsRepository
from azents.repos.workspace_user import WorkspaceUserRepository


async def test_decommission_admission_guard_is_inside_completed_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = AsyncMock(spec=AsyncSession)
    session = ReadWriteSession(raw)
    active = False

    @asynccontextmanager
    async def manager() -> AsyncIterator[WriteSession]:
        nonlocal active
        active = True
        try:
            yield session
        finally:
            active = False

    async def reject(current: WriteSession, *, agent_id: str) -> None:
        assert active and current is session and agent_id == "agent-1"
        raise GitHubUserOAuthError(
            GitHubUserErrorCode.CLEANUP_REQUIRED, "Complete token cleanup first."
        )

    guard = AsyncMock(side_effect=reject)
    monkeypatch.setattr(
        "azents.repos.agent_operations.assert_agent_delete_allowed", guard
    )
    agents = AsyncMock(spec=AgentRepository)
    jobs = AsyncMock(spec=AgentDecommissionRepository)
    retention = AsyncMock(spec=ArchivedSessionRetentionRepository)
    retention.get_settings.return_value = SimpleNamespace(
        archived_session_retention_days=30
    )
    repository = AgentOperationsRepository(
        session_manager=manager,
        agent_repository=agents,
        admin_repository=AsyncMock(spec=AgentAdminRepository),
        workspace_model_settings_repository=AsyncMock(
            spec=WorkspaceModelSettingsRepository
        ),
        workspace_user_repository=AsyncMock(spec=WorkspaceUserRepository),
        agent_decommission_repository=jobs,
        archived_session_retention_repository=retention,
        agent_session_repository=AsyncMock(spec=AgentSessionRepository),
        runtime_profile_repository=AsyncMock(spec=RuntimeProfileRepository),
        runtime_profile_availability_repository=AsyncMock(
            spec=RuntimeProfileAvailabilityRepository
        ),
    )
    with pytest.raises(GitHubUserOAuthError):
        await repository.request_decommission(
            agent_id="agent-1", workspace_user_id="member-1"
        )
    assert not active
    guard.assert_awaited_once()
    agents.mark_decommissioning.assert_not_awaited()
    jobs.create_or_get.assert_not_awaited()


async def test_finalizer_checks_exact_toolkits_before_agent_lock_or_cascades(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = AsyncMock(spec=AsyncSession)
    raw.scalar.return_value = object()  # A successfully claimed exact finalizer job.
    session = ReadWriteSession(raw)
    guard = AsyncMock(
        side_effect=GitHubUserOAuthError(
            GitHubUserErrorCode.CLEANUP_REQUIRED, "Complete token cleanup first."
        )
    )
    monkeypatch.setattr(
        "azents.repos.agent_decommission_finalizer.assert_agent_delete_allowed", guard
    )
    with pytest.raises(GitHubUserOAuthError):
        await AgentDecommissionFinalizerRepository().finalize(
            session,
            job_id="job-1",
            agent_id="agent-1",
            lease_owner="worker-1",
            expected_attempt=1,
            now=datetime.datetime.now(datetime.UTC),
        )
    guard.assert_awaited_once_with(session, agent_id="agent-1")
    assert raw.scalar.await_count == 1  # Job claim only; no Agent-before-Toolkit lock.
    raw.delete.assert_not_awaited()
    raw.execute.assert_not_awaited()
