"""AgentSessionRepository tests."""

import asyncio
import datetime
from uuid import uuid4

from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.enums import (
    AgentSessionEndReason,
    AgentSessionStartReason,
    AgentSessionStatus,
    LLMProvider,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.testing.model_selection import make_test_model_selection_dict

from . import AgentSessionRepository


async def _create_workspace(session: AsyncSession, handle: str) -> str:
    """Create Workspace for tests."""
    repo = WorkspaceRepository()
    result = await repo.create(
        session, WorkspaceCreate(name="AgentSession test", handle=handle)
    )
    assert isinstance(result, Success)
    workspace_id = await repo.resolve_id(session, handle)
    assert workspace_id is not None
    return workspace_id


async def _create_agent(session: AsyncSession, workspace_id: str, slug: str) -> str:
    """Create Agent for tests."""

    integration = RDBLLMProviderIntegration(
        workspace_id=workspace_id,
        provider=LLMProvider.ANTHROPIC,
        name=f"{slug}-integration",
        encrypted_credentials="encrypted-test-value",
        config=None,
    )
    session.add(integration)
    await session.flush()

    agent = RDBAgent(
        workspace_id=workspace_id,
        name="AgentSession test agent",
        model_selection=make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier=f"{slug}-id",
        ),
        lightweight_model_selection=make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier=f"{slug}-id",
        ),
    )
    session.add(agent)
    await session.flush()
    return agent.id


class TestAgentSessionRepository:
    """AgentSessionRepository tests."""

    async def test_ensure_active_creates_one_active_session(
        self, rdb_session: AsyncSession
    ) -> None:
        """Ensure only one active AgentSession per AgentRuntime."""
        workspace_id = await _create_workspace(rdb_session, "agent-session-ws")
        agent_id = await _create_agent(rdb_session, workspace_id, "agent-session-model")
        runtime = await AgentRuntimeRepository().ensure_for_agent(rdb_session, agent_id)
        repo = AgentSessionRepository()

        first = await repo.ensure_active(rdb_session, runtime.id)
        second = await repo.ensure_active(rdb_session, runtime.id)

        assert first.id == second.id
        assert first.status == AgentSessionStatus.ACTIVE

    async def test_ensure_active_recreates_after_archive(
        self, rdb_session: AsyncSession
    ) -> None:
        """Create new active session when active session is archived."""
        workspace_id = await _create_workspace(rdb_session, "agent-session-archive-ws")
        agent_id = await _create_agent(
            rdb_session, workspace_id, "agent-session-archive-model"
        )
        runtime = await AgentRuntimeRepository().ensure_for_agent(rdb_session, agent_id)
        repo = AgentSessionRepository()
        first = await repo.ensure_active(rdb_session, runtime.id)
        await repo.archive(
            rdb_session,
            first.id,
            ended_at=datetime.datetime.now(datetime.timezone.utc),
        )

        second = await repo.ensure_active(rdb_session, runtime.id)

        assert second.id != first.id
        assert second.status == AgentSessionStatus.ACTIVE

    async def test_ensure_active_reuses_row_inserted_by_concurrent_transaction(
        self, rdb_engine: AsyncEngine, latest_db_schema: None
    ) -> None:
        """Concurrent ensure_active reuses existing active row."""
        del latest_db_schema
        suffix = uuid4().hex[:8]
        async with AsyncSession(rdb_engine, expire_on_commit=False) as setup_session:
            workspace_id = await _create_workspace(
                setup_session, f"agent-session-race-{suffix}"
            )
            agent_id = await _create_agent(
                setup_session,
                workspace_id,
                f"agent-session-race-model-{suffix}",
            )
            runtime = await AgentRuntimeRepository().ensure_for_agent(
                setup_session, agent_id
            )
            await setup_session.commit()

        repo = AgentSessionRepository()
        async with AsyncSession(rdb_engine, expire_on_commit=False) as first_session:
            first = await repo.ensure_active(first_session, runtime.id)

            async with AsyncSession(
                rdb_engine, expire_on_commit=False
            ) as second_session:
                second_task = asyncio.create_task(
                    repo.ensure_active(second_session, runtime.id)
                )
                await asyncio.sleep(0.1)
                await first_session.commit()
                second = await asyncio.wait_for(second_task, timeout=5)
                await second_session.commit()

        assert second.id == first.id
        assert second.status == AgentSessionStatus.ACTIVE

    async def test_rotate_active_archives_current_and_creates_new(
        self, rdb_session: AsyncSession
    ) -> None:
        """rotation ends existing active with preservation and makes new active."""
        workspace_id = await _create_workspace(rdb_session, "agent-session-rotate-ws")
        agent_id = await _create_agent(
            rdb_session, workspace_id, "agent-session-rotate-model"
        )
        runtime = await AgentRuntimeRepository().ensure_for_agent(rdb_session, agent_id)
        repo = AgentSessionRepository()
        first = await repo.ensure_active(rdb_session, runtime.id)
        now = datetime.datetime.now(datetime.timezone.utc)

        second = await repo.rotate_active(
            rdb_session,
            runtime.id,
            start_reason=AgentSessionStartReason.MANUAL_RESET,
            end_reason=AgentSessionEndReason.MANUAL_RESET,
            now=now,
        )

        archived = await repo.get_by_id(rdb_session, first.id)
        assert archived is not None
        assert archived.status == AgentSessionStatus.ARCHIVED
        assert archived.end_reason == AgentSessionEndReason.MANUAL_RESET
        assert archived.ended_at == now
        assert second.id != first.id
        assert second.status == AgentSessionStatus.ACTIVE
        assert second.start_reason == AgentSessionStartReason.MANUAL_RESET

    async def test_claim_lifecycle_start_sets_marker_once(
        self, rdb_session: AsyncSession
    ) -> None:
        """lifecycle start marker is set only on initial claim."""
        workspace_id = await _create_workspace(
            rdb_session, "agent-session-lifecycle-ws"
        )
        agent_id = await _create_agent(
            rdb_session, workspace_id, "agent-session-lifecycle-model"
        )
        runtime = await AgentRuntimeRepository().ensure_for_agent(rdb_session, agent_id)
        repo = AgentSessionRepository()
        agent_session = await repo.ensure_active(rdb_session, runtime.id)
        first_claimed_at = datetime.datetime.now(datetime.timezone.utc)
        second_claimed_at = first_claimed_at + datetime.timedelta(seconds=1)

        first_claimed = await repo.claim_lifecycle_start(
            rdb_session,
            agent_session.id,
            now=first_claimed_at,
        )
        second_claimed = await repo.claim_lifecycle_start(
            rdb_session,
            agent_session.id,
            now=second_claimed_at,
        )

        assert first_claimed is True
        assert second_claimed is False
        assert (
            await repo.get_lifecycle_started_at(rdb_session, agent_session.id)
            == first_claimed_at
        )
        refreshed = await repo.get_by_id(rdb_session, agent_session.id)
        assert refreshed is not None
        assert refreshed.lifecycle_started_at == first_claimed_at

    async def test_claim_lifecycle_start_allows_rotated_session(
        self, rdb_session: AsyncSession
    ) -> None:
        """New session created by rotation has separate lifecycle marker."""
        workspace_id = await _create_workspace(
            rdb_session, "agent-session-lifecycle-rotate-ws"
        )
        agent_id = await _create_agent(
            rdb_session, workspace_id, "agent-session-lifecycle-rotate-model"
        )
        runtime = await AgentRuntimeRepository().ensure_for_agent(rdb_session, agent_id)
        repo = AgentSessionRepository()
        first = await repo.ensure_active(rdb_session, runtime.id)
        first_claimed_at = datetime.datetime.now(datetime.timezone.utc)
        rotated_at = first_claimed_at + datetime.timedelta(seconds=1)
        second_claimed_at = first_claimed_at + datetime.timedelta(seconds=2)

        assert (
            await repo.claim_lifecycle_start(
                rdb_session,
                first.id,
                now=first_claimed_at,
            )
            is True
        )
        second = await repo.rotate_active(
            rdb_session,
            runtime.id,
            start_reason=AgentSessionStartReason.MANUAL_RESET,
            end_reason=AgentSessionEndReason.MANUAL_RESET,
            now=rotated_at,
        )

        second_claimed = await repo.claim_lifecycle_start(
            rdb_session,
            second.id,
            now=second_claimed_at,
        )

        assert second.id != first.id
        assert second_claimed is True
        assert (
            await repo.get_lifecycle_started_at(rdb_session, first.id)
            == first_claimed_at
        )
        assert (
            await repo.get_lifecycle_started_at(rdb_session, second.id)
            == second_claimed_at
        )
