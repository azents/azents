"""Agent automatic Project policy repository tests."""

import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from azcommon.result import Failure, Success
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import LLMProvider, WorkspaceUserRole
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_automatic_project_setting import (
    RDBAgentAutomaticProjectSetting,
)
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import WorkspaceUserCreate
from azents.testing.model_selection import make_test_model_selection_dict

from . import AgentAutomaticProjectRepository
from .data import AgentAutomaticProjectPolicyRevisionConflict


async def _create_workspace(session: AsyncSession, handle: str) -> str:
    """Create Workspace for policy repository tests."""
    repo = WorkspaceRepository()
    result = await repo.create(
        session,
        WorkspaceCreate(name="Automatic Project policy test", handle=handle),
    )
    assert isinstance(result, Success)
    workspace_id = await repo.resolve_id(session, handle)
    assert workspace_id is not None
    return workspace_id


async def _create_agent(session: AsyncSession, workspace_id: str, slug: str) -> str:
    """Create Agent and its initial empty policy setting."""
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
        name="Automatic Project policy test agent",
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
    session.add(RDBAgentAutomaticProjectSetting(agent_id=agent.id))
    await session.flush()
    return agent.id


async def _create_workspace_user(
    session: AsyncSession,
    *,
    workspace_id: str,
    email: str,
) -> str:
    """Create WorkspaceUser for persisted policy update attribution."""
    user = await UserRepository().create(session, UserCreate(email=email))
    result = await WorkspaceUserRepository().create(
        session,
        WorkspaceUserCreate(
            workspace_id=workspace_id,
            user_id=user.id,
            name="Policy manager",
            role=WorkspaceUserRole.MANAGER,
        ),
    )
    assert isinstance(result, Success)
    return result.value.id


class TestAgentAutomaticProjectRepository:
    """AgentAutomaticProjectRepository behavior."""

    async def test_get_policy_reads_setting_and_items_in_one_statement(self) -> None:
        """Read one coherent policy snapshot without a second item query."""
        session = AsyncMock(spec=AsyncSession)
        now = datetime.datetime.now(datetime.UTC)
        setting = RDBAgentAutomaticProjectSetting(agent_id="agent-policy-read")
        setting.created_at = now
        setting.updated_at = now
        result = MagicMock()
        result.all.return_value = [
            (setting, "/workspace/agent/first"),
            (setting, "/workspace/agent/second"),
        ]
        session.execute.return_value = result

        policy = await AgentAutomaticProjectRepository().get_policy(
            session,
            agent_id=setting.agent_id,
        )

        assert policy is not None
        assert policy.project_paths == (
            "/workspace/agent/first",
            "/workspace/agent/second",
        )
        assert session.execute.await_count == 1

    async def test_get_policy_returns_initial_empty_revision_one(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Every persisted policy can represent an empty Project list."""
        workspace_id = await _create_workspace(rdb_session, "automatic-policy-empty")
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            "automatic-policy-empty",
        )

        policy = await AgentAutomaticProjectRepository().get_policy(
            rdb_session,
            agent_id=agent_id,
        )

        assert policy is not None
        assert policy.revision == 1
        assert policy.project_paths == ()
        assert policy.updated_by_workspace_user_id is None

    async def test_replace_policy_preserves_submitted_path_order(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Successful whole-list replacement increments revision and keeps order."""
        workspace_id = await _create_workspace(rdb_session, "automatic-policy-order")
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            "automatic-policy-order",
        )
        workspace_user_id = await _create_workspace_user(
            rdb_session,
            workspace_id=workspace_id,
            email="automatic-policy-order@example.com",
        )
        repo = AgentAutomaticProjectRepository()

        result = await repo.replace_policy(
            rdb_session,
            agent_id=agent_id,
            expected_revision=1,
            paths=[
                "/workspace/agent/payment-api",
                "/workspace/agent/order-service",
            ],
            updated_by_workspace_user_id=workspace_user_id,
        )

        assert isinstance(result, Success)
        assert result.value.revision == 2
        assert result.value.project_paths == (
            "/workspace/agent/payment-api",
            "/workspace/agent/order-service",
        )
        assert result.value.updated_by_workspace_user_id == workspace_user_id
        fetched = await repo.get_policy(rdb_session, agent_id=agent_id)
        assert fetched is not None
        assert fetched == result.value

    async def test_replace_policy_stale_revision_keeps_existing_items(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """A failed revision predicate never deletes the current item set."""
        workspace_id = await _create_workspace(rdb_session, "automatic-policy-stale")
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            "automatic-policy-stale",
        )
        workspace_user_id = await _create_workspace_user(
            rdb_session,
            workspace_id=workspace_id,
            email="automatic-policy-stale@example.com",
        )
        repo = AgentAutomaticProjectRepository()
        first = await repo.replace_policy(
            rdb_session,
            agent_id=agent_id,
            expected_revision=1,
            paths=["/workspace/agent/kept"],
            updated_by_workspace_user_id=workspace_user_id,
        )
        assert isinstance(first, Success)

        stale = await repo.replace_policy(
            rdb_session,
            agent_id=agent_id,
            expected_revision=1,
            paths=["/workspace/agent/rejected"],
            updated_by_workspace_user_id=workspace_user_id,
        )

        assert isinstance(stale, Failure)
        assert isinstance(stale.error, AgentAutomaticProjectPolicyRevisionConflict)
        assert stale.error.expected_revision == 1
        current = await repo.get_policy(rdb_session, agent_id=agent_id)
        assert current is not None
        assert current.revision == 2
        assert current.project_paths == ("/workspace/agent/kept",)

    async def test_replace_policy_empty_list_clears_existing_items(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """An empty whole-list replacement clears persisted policy paths."""
        workspace_id = await _create_workspace(rdb_session, "automatic-policy-clear")
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            "automatic-policy-clear",
        )
        workspace_user_id = await _create_workspace_user(
            rdb_session,
            workspace_id=workspace_id,
            email="automatic-policy-clear@example.com",
        )
        repo = AgentAutomaticProjectRepository()
        initial_replace = await repo.replace_policy(
            rdb_session,
            agent_id=agent_id,
            expected_revision=1,
            paths=["/workspace/agent/to-clear"],
            updated_by_workspace_user_id=workspace_user_id,
        )
        assert isinstance(initial_replace, Success)

        cleared = await repo.replace_policy(
            rdb_session,
            agent_id=agent_id,
            expected_revision=2,
            paths=[],
            updated_by_workspace_user_id=workspace_user_id,
        )

        assert isinstance(cleared, Success)
        assert cleared.value.revision == 3
        assert cleared.value.project_paths == ()
        fetched = await repo.get_policy(rdb_session, agent_id=agent_id)
        assert fetched is not None
        assert fetched.project_paths == ()

    async def test_replace_policy_rejects_duplicate_paths(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """The database constraint rejects duplicate persisted Project paths."""
        workspace_id = await _create_workspace(
            rdb_session,
            "automatic-policy-duplicate",
        )
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            "automatic-policy-duplicate",
        )
        workspace_user_id = await _create_workspace_user(
            rdb_session,
            workspace_id=workspace_id,
            email="automatic-policy-duplicate@example.com",
        )

        with pytest.raises(
            IntegrityError,
            match="uq_agent_automatic_project_items_agent_path",
        ):
            async with rdb_session.begin_nested():
                await AgentAutomaticProjectRepository().replace_policy(
                    rdb_session,
                    agent_id=agent_id,
                    expected_revision=1,
                    paths=[
                        "/workspace/agent/duplicate",
                        "/workspace/agent/duplicate",
                    ],
                    updated_by_workspace_user_id=workspace_user_id,
                )

        policy = await AgentAutomaticProjectRepository().get_policy(
            rdb_session,
            agent_id=agent_id,
        )
        assert policy is not None
        assert policy.revision == 1
        assert policy.project_paths == ()
