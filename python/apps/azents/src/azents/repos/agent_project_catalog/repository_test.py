"""Agent Project catalog repository tests."""

import datetime

from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentProjectCatalogStatus, LLMProvider
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.repos.agent_project_catalog.data import AgentProjectCatalogStatusPatch
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.testing.model_selection import make_test_model_selection_dict

from . import AgentProjectCatalogRepository


async def _create_workspace(session: AsyncSession, handle: str) -> str:
    """Create Workspace for tests."""
    repo = WorkspaceRepository()
    result = await repo.create(
        session,
        WorkspaceCreate(name="Agent Project catalog test", handle=handle),
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
        name="Agent Project catalog test agent",
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


class TestAgentProjectCatalogRepository:
    """AgentProjectCatalogRepository behavior."""

    async def test_upsert_entry_is_idempotent(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Repeated upsert refreshes the same Agent/path row."""
        workspace_id = await _create_workspace(rdb_session, "catalog-upsert")
        agent_id = await _create_agent(rdb_session, workspace_id, "catalog-upsert")
        repo = AgentProjectCatalogRepository()

        first = await repo.upsert_entry(
            rdb_session,
            agent_id=agent_id,
            path="/workspace/agent/app",
        )
        second = await repo.upsert_entry(
            rdb_session,
            agent_id=agent_id,
            path="/workspace/agent/app",
        )
        entries = await repo.list_entries(rdb_session, agent_id=agent_id)

        assert first.id == second.id
        assert [entry.id for entry in entries] == [first.id]
        assert entries[0].status == AgentProjectCatalogStatus.UNCHECKED
        assert entries[0].checked_at is None

    async def test_list_entries_by_paths_filters_exact_paths(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Path lookup returns only exact Agent/path matches."""
        workspace_id = await _create_workspace(rdb_session, "catalog-list-paths")
        agent_id = await _create_agent(rdb_session, workspace_id, "catalog-list-paths")
        repo = AgentProjectCatalogRepository()
        await repo.upsert_entry(
            rdb_session,
            agent_id=agent_id,
            path="/workspace/agent/app-a",
        )
        await repo.upsert_entry(
            rdb_session,
            agent_id=agent_id,
            path="/workspace/agent/app-b",
        )

        entries = await repo.list_entries_by_paths(
            rdb_session,
            agent_id=agent_id,
            paths=["/workspace/agent/app-b"],
        )

        assert [entry.path for entry in entries] == ["/workspace/agent/app-b"]

    async def test_update_status_upserts_projection(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Status update records filesystem projection fields."""
        workspace_id = await _create_workspace(rdb_session, "catalog-status")
        agent_id = await _create_agent(rdb_session, workspace_id, "catalog-status")
        checked_at = datetime.datetime.now(datetime.UTC)
        repo = AgentProjectCatalogRepository()

        entry = await repo.update_status(
            rdb_session,
            agent_id=agent_id,
            path="/workspace/agent/app",
            patch=AgentProjectCatalogStatusPatch(
                status=AgentProjectCatalogStatus.AVAILABLE,
                status_detail=None,
                checked_at=checked_at,
            ),
        )

        assert entry.status == AgentProjectCatalogStatus.AVAILABLE
        assert entry.status_detail is None
        assert entry.checked_at == checked_at
        fetched = await repo.get_entry_by_path(
            rdb_session,
            agent_id=agent_id,
            path="/workspace/agent/app",
        )
        assert fetched is not None
        assert fetched.id == entry.id
