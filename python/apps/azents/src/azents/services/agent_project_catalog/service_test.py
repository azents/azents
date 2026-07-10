"""Agent Project catalog service tests."""

import datetime

from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentProjectCatalogStatus, LLMProvider, RuntimeRunnerState
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.session import SessionManager
from azents.repos.agent_project_catalog import AgentProjectCatalogRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.runtime.control_protocol.runner_operations import (
    RuntimeFileStatResult,
    RuntimeRunnerOperationClient,
)
from azents.testing.model_selection import make_test_model_selection_dict

from . import AgentProjectCatalogService


class _FakeRunnerOperations(RuntimeRunnerOperationClient):
    """Runner operation fake for Project status refresh."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.paths: list[str] = []

    async def stat_file(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None = None,
        path: str,
        deadline_at: datetime.datetime,
    ) -> RuntimeFileStatResult:
        """Return configured stat result."""
        del runtime_id, runner_generation, deadline_at
        self.paths.append(path)
        if self.kind == "missing":
            return RuntimeFileStatResult(
                path=path,
                kind="missing",
                size_bytes=None,
                symlink=False,
                real_path=None,
                resolved_kind=None,
                modified_at=None,
                final_cursor="0",
            )
        return RuntimeFileStatResult(
            path=path,
            kind="directory",
            size_bytes=None,
            symlink=False,
            real_path=None,
            resolved_kind="directory",
            modified_at=None,
            final_cursor="0",
        )


async def _create_workspace(session: AsyncSession, handle: str) -> str:
    """Create Workspace for tests."""
    repo = WorkspaceRepository()
    result = await repo.create(
        session,
        WorkspaceCreate(name="Agent Project catalog service test", handle=handle),
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
        name="Agent Project catalog service test agent",
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


def _service(
    rdb_session_manager: SessionManager[AsyncSession],
    *,
    runner_operations: RuntimeRunnerOperationClient | None = None,
) -> AgentProjectCatalogService:
    """Create service for tests."""
    return AgentProjectCatalogService(
        catalog_repository=AgentProjectCatalogRepository(),
        agent_runtime_repository=AgentRuntimeRepository(),
        session_manager=rdb_session_manager,
        runner_operations=runner_operations,
    )


class TestAgentProjectCatalogService:
    """AgentProjectCatalogService behavior."""

    async def test_upsert_project_candidate_does_not_require_session(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Catalog candidates can exist before an AgentSession is created."""
        async with rdb_session_manager() as session:
            workspace_id = await _create_workspace(session, "catalog-service-candidate")
            agent_id = await _create_agent(
                session,
                workspace_id,
                "catalog-service-candidate",
            )

        result = await _service(rdb_session_manager).upsert_project_candidate(
            agent_id=agent_id,
            path="/workspace/agent/app/../app",
        )

        assert isinstance(result, Success)
        assert result.value.path == "/workspace/agent/app"
        async with rdb_session_manager() as session:
            entries = await AgentProjectCatalogRepository().list_entries(
                session,
                agent_id=agent_id,
            )
        assert [entry.path for entry in entries] == ["/workspace/agent/app"]

    async def test_upsert_project_candidate_rejects_invalid_path(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Project candidates must still satisfy Agent Workspace path rules."""
        result = await _service(rdb_session_manager).upsert_project_candidate(
            agent_id="agent-1",
            path="/tmp/app",
        )

        assert isinstance(result, Failure)

    async def test_refresh_project_status_without_ready_runtime_is_unavailable(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Absent runtime stores UNAVAILABLE without runner calls."""
        async with rdb_session_manager() as session:
            workspace_id = await _create_workspace(
                session,
                "catalog-service-unavailable",
            )
            agent_id = await _create_agent(
                session,
                workspace_id,
                "catalog-service-unavailable",
            )

        result = await _service(rdb_session_manager).refresh_project_status(
            agent_id=agent_id,
            path="/workspace/agent/app",
        )

        assert isinstance(result, Success)
        assert result.value.status == AgentProjectCatalogStatus.UNAVAILABLE
        assert result.value.checked_at is not None

    async def test_refresh_project_status_maps_directory_to_available(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Runner directory stat stores AVAILABLE."""
        async with rdb_session_manager() as session:
            workspace_id = await _create_workspace(session, "catalog-service-available")
            agent_id = await _create_agent(
                session,
                workspace_id,
                "catalog-service-available",
            )
            runtime = await AgentRuntimeRepository().ensure_for_agent(session, agent_id)
            rdb_runtime = await session.get(RDBAgentRuntime, runtime.id)
            assert rdb_runtime is not None
            rdb_runtime.runner_state = RuntimeRunnerState.READY
        runner_operations = _FakeRunnerOperations(kind="directory")

        result = await _service(
            rdb_session_manager,
            runner_operations=runner_operations,
        ).refresh_project_status(
            agent_id=agent_id,
            path="/workspace/agent/app",
        )

        assert isinstance(result, Success)
        assert result.value.status == AgentProjectCatalogStatus.AVAILABLE
        assert result.value.status_detail is None
        assert runner_operations.paths == ["/workspace/agent/app"]

    async def test_refresh_project_status_maps_missing_to_missing(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Runner missing stat stores MISSING."""
        async with rdb_session_manager() as session:
            workspace_id = await _create_workspace(session, "catalog-service-missing")
            agent_id = await _create_agent(
                session,
                workspace_id,
                "catalog-service-missing",
            )
            runtime = await AgentRuntimeRepository().ensure_for_agent(session, agent_id)
            rdb_runtime = await session.get(RDBAgentRuntime, runtime.id)
            assert rdb_runtime is not None
            rdb_runtime.runner_state = RuntimeRunnerState.READY
        runner_operations = _FakeRunnerOperations(kind="missing")

        result = await _service(
            rdb_session_manager,
            runner_operations=runner_operations,
        ).refresh_project_status(
            agent_id=agent_id,
            path="/workspace/agent/app",
        )

        assert isinstance(result, Success)
        assert result.value.status == AgentProjectCatalogStatus.MISSING
        assert result.value.status_detail == "Path does not exist."
