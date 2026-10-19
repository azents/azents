"""Concurrent partial Agent cadence updates validate the current fenced pair."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.agent_errors import InvalidRoutineCadence
from azents.core.crypto import CredentialCipher
from azents.core.enums import WorkspaceUserRole
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.models.session_agent import RDBSessionAgent
from azents.rdb.models.session_agent_context import RDBSessionAgentContext
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import AgentUpdate
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.agent_decommission import AgentDecommissionRepository
from azents.repos.agent_operations import AgentOperationsRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.archived_session_retention import ArchivedSessionRetentionRepository
from azents.repos.routine.persistence_test import _subject
from azents.repos.runtime_profile.availability import (
    RuntimeProfileAvailabilityRepository,
)
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.repos.workspace_model_settings import WorkspaceModelSettingsRepository
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.worker.session.idle_continuation_lock_test import (
    _wait_for_database_blocker,
)


@pytest.mark.parametrize("minimum_first", [True, False])
async def test_concurrent_partial_cadence_updates_revalidate_fenced_pair(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    minimum_first: bool,
) -> None:
    """Delay raises the refreshed tick; tick-only inversion remains invalid."""
    del latest_db_schema
    async with AsyncSession(rdb_engine, expire_on_commit=False) as raw:
        scope = await _subject(ReadWriteSession(raw))
        await raw.execute(
            sa.update(RDBAgent)
            .where(RDBAgent.id == scope.agent_id)
            .values(
                routine_check_interval_minutes=180,
            )
        )
        await raw.commit()
    waiter_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()

    @asynccontextmanager
    async def manager() -> AsyncIterator[WriteSession]:
        async with AsyncSession(rdb_engine, expire_on_commit=False) as raw:
            pid = await raw.scalar(sa.text("SELECT pg_backend_pid()"))
            assert isinstance(pid, int)
            waiter_pid.set_result(pid)
            yield ReadWriteSession(raw)
            await raw.commit()

    users = AsyncMock(spec=WorkspaceUserRepository)
    users.get.return_value = SimpleNamespace(
        workspace_id=scope.workspace_id,
        role=WorkspaceUserRole.OWNER,
    )
    operations = AgentOperationsRepository(
        session_manager=manager,
        credential_cipher=CredentialCipher(Fernet.generate_key().decode()),
        agent_repository=AgentRepository(),
        admin_repository=AsyncMock(spec=AgentAdminRepository),
        workspace_model_settings_repository=AsyncMock(
            spec=WorkspaceModelSettingsRepository
        ),
        workspace_user_repository=users,
        agent_decommission_repository=AsyncMock(spec=AgentDecommissionRepository),
        archived_session_retention_repository=AsyncMock(
            spec=ArchivedSessionRetentionRepository
        ),
        agent_session_repository=AsyncMock(spec=AgentSessionRepository),
        runtime_profile_repository=AsyncMock(spec=RuntimeProfileRepository),
        runtime_profile_availability_repository=AsyncMock(
            spec=RuntimeProfileAvailabilityRepository
        ),
    )
    try:
        async with AsyncSession(rdb_engine) as holder:
            await AgentRepository().lock_by_id(ReadWriteSession(holder), scope.agent_id)
            first: AgentUpdate = (
                {"routine_min_action_delay_minutes": 120}
                if minimum_first
                else {"routine_check_interval_minutes": 60}
            )
            second: AgentUpdate = (
                {"routine_check_interval_minutes": 60}
                if minimum_first
                else {"routine_min_action_delay_minutes": 120}
            )
            await AgentRepository().update_by_id(
                ReadWriteSession(holder), scope.agent_id, first
            )
            pid = await holder.scalar(sa.text("SELECT pg_backend_pid()"))
            assert isinstance(pid, int)
            async with asyncio.timeout(15), asyncio.TaskGroup() as tasks:
                pending = tasks.create_task(
                    operations.update_by_id(
                        agent_id=scope.agent_id,
                        workspace_id=scope.workspace_id,
                        workspace_user_id="authorized-fixture",
                        update=second,
                        runtime_profile_change=None,
                        model_configuration_changed=False,
                        valid_model_target_labels=["default", "lightweight"],
                        model_target_label="default",
                        reasoning_effort=None,
                    )
                )
                await _wait_for_database_blocker(
                    rdb_engine,
                    blocked_pid=await waiter_pid,
                    blocker_pid=pid,
                )
                await holder.commit()
            result = pending.result()
            if minimum_first:
                assert result.failure and isinstance(
                    result.error, InvalidRoutineCadence
                )
            else:
                assert result.success
                assert result.value.routine_check_interval_minutes == 120
                assert result.value.routine_min_action_delay_minutes == 120
        async with AsyncSession(rdb_engine) as raw:
            row = (
                await raw.execute(
                    sa.select(
                        RDBAgent.routine_min_action_delay_minutes,
                        RDBAgent.routine_check_interval_minutes,
                    ).where(RDBAgent.id == scope.agent_id)
                )
            ).one()
            assert row == ((120, 180) if minimum_first else (120, 120))
    finally:
        async with rdb_engine.begin() as cleanup:
            await cleanup.execute(
                sa.update(RDBSessionAgentContext)
                .where(RDBSessionAgentContext.workspace_id == scope.workspace_id)
                .values(root_session_agent_id=None)
            )
            await cleanup.execute(
                sa.delete(RDBSessionAgent).where(
                    RDBSessionAgent.context_id.in_(
                        sa.select(RDBSessionAgentContext.id).where(
                            RDBSessionAgentContext.workspace_id == scope.workspace_id
                        )
                    )
                )
            )
            await cleanup.execute(
                sa.delete(RDBSessionAgentContext).where(
                    RDBSessionAgentContext.workspace_id == scope.workspace_id
                )
            )
            await cleanup.execute(
                sa.delete(RDBAgentSession).where(
                    RDBAgentSession.workspace_id == scope.workspace_id
                )
            )
            await cleanup.execute(
                sa.delete(RDBAgentRuntime).where(
                    RDBAgentRuntime.agent_id == scope.agent_id
                )
            )
            await cleanup.execute(
                sa.delete(RDBAgent).where(RDBAgent.id == scope.agent_id)
            )
            await cleanup.execute(
                sa.delete(RDBLLMProviderIntegration).where(
                    RDBLLMProviderIntegration.workspace_id == scope.workspace_id
                )
            )
            await cleanup.execute(
                sa.delete(RDBWorkspace).where(RDBWorkspace.id == scope.workspace_id)
            )
