"""AgentSessionRepository tests."""

import asyncio
import datetime
from uuid import uuid4

from azcommon.result import Success
from pytest import MonkeyPatch
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

import azents.repos.agent_session as agent_session_repo
from azents.core.enums import (
    AgentSessionPrimaryKind,
    AgentSessionStartReason,
    AgentSessionStatus,
    AgentSessionTitleSource,
    LLMProvider,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.testing.model_selection import make_test_model_selection_dict

from . import AgentSessionRepository
from .data import AgentSessionCreate


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
        repo = AgentSessionRepository()

        first = await repo.ensure_team_primary_for_agent(
            rdb_session, workspace_id=workspace_id, agent_id=agent_id
        )
        second = await repo.ensure_team_primary_for_agent(
            rdb_session, workspace_id=workspace_id, agent_id=agent_id
        )

        assert first.id == second.id
        assert first.status == AgentSessionStatus.ACTIVE
        assert first.primary_kind == AgentSessionPrimaryKind.TEAM_PRIMARY
        assert first.title is None
        assert first.handle.count("-") == 2

    async def test_create_retries_duplicate_session_handle(
        self, rdb_session: AsyncSession, monkeypatch: MonkeyPatch
    ) -> None:
        """AgentSession handle generation retries unique constraint conflicts."""
        workspace_id = await _create_workspace(rdb_session, "agent-session-handle-ws")
        agent_id = await _create_agent(
            rdb_session, workspace_id, "agent-session-handle"
        )
        handles = iter(
            [
                "abandon-ability-able",
                "abandon-ability-able",
                "about-above-absent",
            ]
        )
        monkeypatch.setattr(
            agent_session_repo,
            "generate_session_handle",
            lambda: next(handles),
        )
        repo = AgentSessionRepository()

        first = await repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
                primary_kind=None,
                start_reason=AgentSessionStartReason.INITIAL,
            ),
        )
        second = await repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
                primary_kind=None,
                start_reason=AgentSessionStartReason.INITIAL,
            ),
        )

        assert first.handle == "abandon-ability-able"
        assert second.handle == "about-above-absent"

    async def test_update_title_round_trips_custom_title(
        self, rdb_session: AsyncSession
    ) -> None:
        """AgentSession title can be updated and cleared."""
        workspace_id = await _create_workspace(rdb_session, "agent-session-title-ws")
        agent_id = await _create_agent(rdb_session, workspace_id, "agent-session-title")
        repo = AgentSessionRepository()
        agent_session = await repo.ensure_team_primary_for_agent(
            rdb_session, workspace_id=workspace_id, agent_id=agent_id
        )

        titled = await repo.update_title(
            rdb_session,
            session_id=agent_session.id,
            title="Design review",
            title_source=AgentSessionTitleSource.MANUAL,
        )
        cleared = await repo.update_title(
            rdb_session,
            session_id=agent_session.id,
            title=None,
            title_source=None,
        )

        assert titled is not None
        assert titled.title == "Design review"
        assert cleared is not None
        assert cleared.title is None

    async def test_ensure_active_recreates_after_archive(
        self, rdb_session: AsyncSession
    ) -> None:
        """Create new active session when active session is archived."""
        workspace_id = await _create_workspace(rdb_session, "agent-session-archive-ws")
        agent_id = await _create_agent(
            rdb_session, workspace_id, "agent-session-archive-model"
        )
        repo = AgentSessionRepository()
        first = await repo.ensure_team_primary_for_agent(
            rdb_session, workspace_id=workspace_id, agent_id=agent_id
        )
        await repo.archive(
            rdb_session,
            first.id,
            ended_at=datetime.datetime.now(datetime.timezone.utc),
        )

        second = await repo.ensure_team_primary_for_agent(
            rdb_session, workspace_id=workspace_id, agent_id=agent_id
        )

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
            await setup_session.commit()

        repo = AgentSessionRepository()
        async with AsyncSession(rdb_engine, expire_on_commit=False) as first_session:
            first = await repo.ensure_team_primary_for_agent(
                first_session, workspace_id=workspace_id, agent_id=agent_id
            )

            async with AsyncSession(
                rdb_engine, expire_on_commit=False
            ) as second_session:
                second_task = asyncio.create_task(
                    repo.ensure_team_primary_for_agent(
                        second_session, workspace_id=workspace_id, agent_id=agent_id
                    )
                )
                await asyncio.sleep(0.1)
                await first_session.commit()
                second = await asyncio.wait_for(second_task, timeout=5)
                await second_session.commit()

        assert second.id == first.id
        assert second.status == AgentSessionStatus.ACTIVE

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
        repo = AgentSessionRepository()
        agent_session = await repo.ensure_team_primary_for_agent(
            rdb_session, workspace_id=workspace_id, agent_id=agent_id
        )
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
