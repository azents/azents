"""Root AgentSession creation service tests."""

import asyncio
from uuid import uuid4

import pytest
import sqlalchemy as sa
from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.enums import LLMProvider
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_automatic_project_item import (
    RDBAgentAutomaticProjectItem,
)
from azents.rdb.models.agent_automatic_project_setting import (
    RDBAgentAutomaticProjectSetting,
)
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.repos.agent_automatic_project import AgentAutomaticProjectRepository
from azents.repos.agent_project_catalog import AgentProjectCatalogRepository
from azents.repos.agent_project_default import AgentProjectDefaultRepository
from azents.repos.agent_project_preset import AgentProjectPresetRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSessionCreate
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.testing.model_selection import make_test_model_selection_dict

from . import RootAgentSessionCreationService
from .data import AgentDefaultRootWorkspaceIntent, ExplicitRootWorkspaceIntent


async def _create_workspace(session: AsyncSession, handle: str) -> str:
    """Create one Workspace for a root Session creation test."""
    repository = WorkspaceRepository()
    result = await repository.create(
        session,
        WorkspaceCreate(name="Root Session creation test", handle=handle),
    )
    assert isinstance(result, Success)
    workspace_id = await repository.resolve_id(session, handle)
    assert workspace_id is not None
    return workspace_id


async def _create_agent(
    session: AsyncSession,
    *,
    workspace_id: str,
    slug: str,
    policy_paths: list[str],
    revision: int,
) -> str:
    """Create an Agent and its persisted automatic Project policy."""
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
        name="Root Session creation test agent",
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
    session.add(RDBAgentAutomaticProjectSetting(agent_id=agent.id, revision=revision))
    session.add_all(
        [
            RDBAgentAutomaticProjectItem(
                agent_id=agent.id,
                path=path,
                position=position,
            )
            for position, path in enumerate(policy_paths)
        ]
    )
    await session.flush()
    return agent.id


def _service() -> RootAgentSessionCreationService:
    """Build the shared root Session creation boundary."""
    return RootAgentSessionCreationService(
        agent_session_repository=AgentSessionRepository(),
        automatic_project_repository=AgentAutomaticProjectRepository(),
        session_workspace_project_repository=SessionWorkspaceProjectRepository(),
    )


class TestRootAgentSessionCreationService:
    """Root Session Project initialization behavior."""

    async def test_explicit_paths_are_normalized_and_never_merge_policy(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Explicit paths win over defaults, including an intentional empty intent."""
        workspace_id = await _create_workspace(rdb_session, "root-explicit")
        agent_id = await _create_agent(
            rdb_session,
            workspace_id=workspace_id,
            slug="root-explicit",
            policy_paths=["/workspace/agent/policy-only"],
            revision=4,
        )
        service = _service()

        explicit = await service.create_root_session(
            rdb_session,
            create=AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
                primary_kind=None,
            ),
            workspace_intent=ExplicitRootWorkspaceIntent(
                existing_project_paths=[
                    " /workspace/agent/explicit/../explicit ",
                    "/workspace/agent/explicit",
                ],
            ),
        )
        empty = await service.create_root_session(
            rdb_session,
            create=AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
                primary_kind=None,
            ),
            workspace_intent=ExplicitRootWorkspaceIntent(existing_project_paths=[]),
        )

        explicit_projects = await SessionWorkspaceProjectRepository().list_projects(
            rdb_session,
            session_id=explicit.agent_session.id,
        )
        empty_projects = await SessionWorkspaceProjectRepository().list_projects(
            rdb_session,
            session_id=empty.agent_session.id,
        )
        assert explicit.created is True
        assert explicit.initial_project_paths == ("/workspace/agent/explicit",)
        assert explicit.policy_revision is None
        assert [project.path for project in explicit_projects] == [
            "/workspace/agent/explicit"
        ]
        assert empty.initial_project_paths == ()
        assert empty_projects == []
        assert (
            await AgentProjectDefaultRepository().list_defaults(
                rdb_session,
                agent_id=agent_id,
            )
            == []
        )
        assert (
            await AgentProjectPresetRepository().list_presets(
                rdb_session,
                agent_id=agent_id,
            )
            == []
        )
        assert (
            await AgentProjectCatalogRepository().list_entries(
                rdb_session,
                agent_id=agent_id,
            )
            == []
        )

    async def test_team_primary_snapshots_policy_only_for_creation_winner(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """New primary receives policy Projects while reuse remains unchanged."""
        workspace_id = await _create_workspace(rdb_session, "root-primary")
        agent_id = await _create_agent(
            rdb_session,
            workspace_id=workspace_id,
            slug="root-primary",
            policy_paths=[
                "/workspace/agent/policy-a",
                "/workspace/agent/policy-b",
            ],
            revision=7,
        )
        service = _service()

        created = await service.ensure_team_primary(
            rdb_session,
            workspace_id=workspace_id,
            agent_id=agent_id,
        )
        reused = await service.ensure_team_primary(
            rdb_session,
            workspace_id=workspace_id,
            agent_id=agent_id,
        )
        projects = await SessionWorkspaceProjectRepository().list_projects(
            rdb_session,
            session_id=created.agent_session.id,
        )

        assert created.created is True
        assert created.initial_project_paths == (
            "/workspace/agent/policy-a",
            "/workspace/agent/policy-b",
        )
        assert created.policy_revision == 7
        assert reused.created is False
        assert reused.agent_session.id == created.agent_session.id
        assert reused.initial_project_paths == (
            "/workspace/agent/policy-a",
            "/workspace/agent/policy-b",
        )
        assert reused.policy_revision is None
        assert [project.path for project in projects] == [
            "/workspace/agent/policy-a",
            "/workspace/agent/policy-b",
        ]
        assert (
            await AgentProjectDefaultRepository().list_defaults(
                rdb_session,
                agent_id=agent_id,
            )
            == []
        )
        assert (
            await AgentProjectPresetRepository().list_presets(
                rdb_session,
                agent_id=agent_id,
            )
            == []
        )
        assert (
            await AgentProjectCatalogRepository().list_entries(
                rdb_session,
                agent_id=agent_id,
            )
            == []
        )

    async def test_team_primary_preserves_empty_policy(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """An empty automatic policy preserves the empty-Project behavior."""
        workspace_id = await _create_workspace(rdb_session, "root-primary-empty")
        agent_id = await _create_agent(
            rdb_session,
            workspace_id=workspace_id,
            slug="root-primary-empty",
            policy_paths=[],
            revision=3,
        )

        result = await _service().ensure_team_primary(
            rdb_session,
            workspace_id=workspace_id,
            agent_id=agent_id,
        )

        assert result.created is True
        assert result.initial_project_paths == ()
        assert result.policy_revision == 3
        assert (
            await SessionWorkspaceProjectRepository().list_projects(
                rdb_session,
                session_id=result.agent_session.id,
            )
            == []
        )

    async def test_team_primary_race_applies_policy_only_for_winner(
        self,
        rdb_engine: AsyncEngine,
        latest_db_schema: None,
    ) -> None:
        """A race loser reuses the winner's durable Project snapshot."""
        del latest_db_schema
        suffix = uuid4().hex[:8]
        async with AsyncSession(rdb_engine, expire_on_commit=False) as setup_session:
            workspace_id = await _create_workspace(
                setup_session,
                f"root-primary-race-{suffix}",
            )
            agent_id = await _create_agent(
                setup_session,
                workspace_id=workspace_id,
                slug=f"root-primary-race-{suffix}",
                policy_paths=[
                    "/workspace/agent/policy-a",
                    "/workspace/agent/policy-b",
                ],
                revision=5,
            )
            await setup_session.commit()

        service = _service()
        async with AsyncSession(rdb_engine, expire_on_commit=False) as first_session:
            first = await service.ensure_team_primary(
                first_session,
                workspace_id=workspace_id,
                agent_id=agent_id,
            )
            async with AsyncSession(
                rdb_engine,
                expire_on_commit=False,
            ) as second_session:
                second_task = asyncio.create_task(
                    service.ensure_team_primary(
                        second_session,
                        workspace_id=workspace_id,
                        agent_id=agent_id,
                    )
                )
                await asyncio.sleep(0.1)
                await first_session.commit()
                second = await asyncio.wait_for(second_task, timeout=5)
                await second_session.commit()

        assert first.created is True
        assert first.policy_revision == 5
        assert second.created is False
        assert second.policy_revision is None
        assert second.agent_session.id == first.agent_session.id
        assert second.initial_project_paths == (
            "/workspace/agent/policy-a",
            "/workspace/agent/policy-b",
        )

    async def test_missing_policy_rolls_back_new_team_primary(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """A missing invariant policy row cannot silently become an empty policy."""
        workspace_id = await _create_workspace(rdb_session, "root-policy-missing")
        agent_id = await _create_agent(
            rdb_session,
            workspace_id=workspace_id,
            slug="root-policy-missing",
            policy_paths=[],
            revision=1,
        )
        await rdb_session.execute(
            sa.delete(RDBAgentAutomaticProjectSetting).where(
                RDBAgentAutomaticProjectSetting.agent_id == agent_id
            )
        )

        with pytest.raises(
            RuntimeError,
            match="Agent automatic Project policy is missing",
        ):
            async with rdb_session.begin_nested():
                await _service().ensure_team_primary(
                    rdb_session,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                )

        assert (
            await AgentSessionRepository().list_active_by_agent_id(
                rdb_session,
                agent_id,
            )
            == []
        )

    async def test_root_creation_rolls_back_session_context_and_projects(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Caller rollback removes the complete root Session initialization unit."""
        workspace_id = await _create_workspace(rdb_session, "root-rollback")
        agent_id = await _create_agent(
            rdb_session,
            workspace_id=workspace_id,
            slug="root-rollback",
            policy_paths=[],
            revision=1,
        )
        service = _service()

        with pytest.raises(RuntimeError, match="rollback"):
            async with rdb_session.begin_nested():
                await service.create_root_session(
                    rdb_session,
                    create=AgentSessionCreate(
                        workspace_id=workspace_id,
                        agent_id=agent_id,
                        title=None,
                        primary_kind=None,
                    ),
                    workspace_intent=AgentDefaultRootWorkspaceIntent(),
                )
                raise RuntimeError("rollback")

        assert (
            await AgentSessionRepository().list_active_by_agent_id(
                rdb_session,
                agent_id,
            )
            == []
        )
