"""AgentSessionRepository tests."""

import asyncio
import datetime
from uuid import uuid4

import pytest
from azcommon.result import Success
from pytest import MonkeyPatch
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

import azents.repos.agent_session as agent_session_repo
from azents.core.enums import (
    AgentSessionKind,
    AgentSessionPrimaryKind,
    AgentSessionStartReason,
    AgentSessionStatus,
    AgentSessionTitleSource,
    LLMProvider,
    SessionAgentKind,
)
from azents.core.inference_profile import SessionInferenceState
from azents.core.llm_catalog import ModelReasoningEffort
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.repos.session_lifecycle_finalizer import (
    SessionLifecycleFinalizerRepository,
)
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_model_selection_dict,
    make_test_model_settings,
)

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

    async def test_claim_owner_generation_is_monotonic(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Increment the durable ownership evidence once per claim."""
        workspace_id = await _create_workspace(rdb_session, "owner-generation-ws")
        agent_id = await _create_agent(rdb_session, workspace_id, "owner-generation")
        repo = AgentSessionRepository()
        created = await repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
            ),
        )

        assert created.owner_generation == 0
        assert await repo.claim_owner_generation(rdb_session, created.id) == 1
        assert await repo.claim_owner_generation(rdb_session, created.id) == 2
        refreshed = await repo.get_by_id(rdb_session, created.id)
        assert refreshed is not None
        assert refreshed.owner_generation == 2

    async def test_fence_archived_owner_generations_invalidates_stale_workers(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Increment durable ownership only for the locked archived subtree."""
        workspace_id = await _create_workspace(rdb_session, "purge-fence-ws")
        agent_id = await _create_agent(rdb_session, workspace_id, "purge-fence")
        repo = AgentSessionRepository()
        created = await repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
            ),
        )
        archived_at = datetime.datetime.now(datetime.UTC)
        await repo.archive_tree(
            rdb_session,
            root_session_id=created.id,
            session_ids=[created.id],
            archived_at=archived_at,
            purge_after=archived_at,
            policy_revision=1,
            retention_days=0,
        )

        fenced_count = await repo.fence_archived_owner_generations(
            rdb_session,
            session_ids=[created.id],
        )

        assert fenced_count == 1
        refreshed = await repo.get_by_id(rdb_session, created.id)
        assert refreshed is not None
        assert refreshed.status is AgentSessionStatus.ARCHIVED
        assert refreshed.owner_generation == 1

    async def test_last_inference_profile_round_trip(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Persist explicit Default and explicit effort session profiles."""
        workspace_id = await _create_workspace(rdb_session, "session-profile-ws")
        agent_id = await _create_agent(rdb_session, workspace_id, "session-profile")
        repo = AgentSessionRepository()
        created = await repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
            ),
        )

        assert created.inference_state is None

        resolved_at = datetime.datetime.now(datetime.UTC)
        default_state = SessionInferenceState(
            model_target_label="Quality",
            model_selection=make_test_model_selection(),
            model_settings=make_test_model_settings(),
            reasoning_effort=None,
            effective_context_window_tokens=100_000,
            effective_auto_compaction_threshold_tokens=80_000,
            resolved_at=resolved_at,
        )
        default_profile = await repo.set_inference_state(
            rdb_session,
            session_id=created.id,
            inference_state=default_state,
        )
        assert default_profile.inference_state == default_state

        explicit_state = default_state.model_copy(
            update={"reasoning_effort": ModelReasoningEffort.HIGH}
        )
        explicit_profile = await repo.set_inference_state(
            rdb_session,
            session_id=created.id,
            inference_state=explicit_state,
        )
        assert explicit_profile.inference_state == explicit_state

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

    async def test_session_agent_child_tree_creation_and_lookup(
        self, rdb_session: AsyncSession
    ) -> None:
        """Child and nested SessionAgents share one root tree context."""
        workspace_id = await _create_workspace(rdb_session, "session-agent-tree-ws")
        agent_id = await _create_agent(rdb_session, workspace_id, "session-agent-tree")
        repo = AgentSessionRepository()
        root_session = await repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
                primary_kind=None,
                start_reason=AgentSessionStartReason.INITIAL,
            ),
        )
        root_agent = await repo.get_session_agent_by_session_id(
            rdb_session,
            root_session.id,
        )
        assert root_agent is not None
        assert root_agent.kind == SessionAgentKind.ROOT
        assert root_agent.path == "/root"

        child = await repo.create_child_session_agent(
            rdb_session,
            parent_session_agent_id=root_agent.id,
            name="reviewer_1",
            agent_type="default",
            title="Reviewer",
            last_task_message="Review this change",
        )
        nested = await repo.create_child_session_agent(
            rdb_session,
            parent_session_agent_id=child.id,
            name="fixer-2",
            agent_type="default",
            title=None,
            last_task_message="Fix the review findings",
        )

        assert child.kind == SessionAgentKind.SUBAGENT
        assert child.context_id == root_agent.context_id
        assert child.root_session_agent_id == root_agent.id
        assert child.parent_session_agent_id == root_agent.id
        assert child.path == "/root/reviewer_1"
        assert child.last_task_message == "Review this change"
        assert nested.context_id == root_agent.context_id
        assert nested.root_session_agent_id == root_agent.id
        assert nested.parent_session_agent_id == child.id
        assert nested.path == "/root/reviewer_1/fixer-2"
        assert child.last_message_at is None

        updated_child = await repo.mark_session_agent_message_activity(
            rdb_session,
            session_agent_id=child.id,
        )
        assert updated_child is not None
        assert updated_child.last_message_at is not None

        tree = await repo.list_session_agent_tree(
            rdb_session,
            root_session_agent_id=root_agent.id,
        )
        assert [agent.path for agent in tree] == [
            "/root",
            "/root/reviewer_1",
            "/root/reviewer_1/fixer-2",
        ]
        descendants = await repo.list_descendant_session_agents(
            rdb_session,
            session_agent_id=child.id,
            include_self=False,
        )
        assert [agent.id for agent in descendants] == [nested.id]

        resolved_relative = await repo.resolve_session_agent_path(
            rdb_session,
            current_session_agent_id=root_agent.id,
            path="reviewer_1/fixer-2",
        )
        resolved_absolute = await repo.resolve_session_agent_path(
            rdb_session,
            current_session_agent_id=nested.id,
            path="/root/reviewer_1",
        )
        assert resolved_relative is not None
        assert resolved_relative.id == nested.id
        assert resolved_absolute is not None
        assert resolved_absolute.id == child.id

        observed = await repo.update_session_agent_observation_cursor(
            rdb_session,
            session_agent_id=child.id,
            parent_observed_run_index=3,
            parent_observed_event_id="0123456789abcdef0123456789abcdef",
        )
        assert observed is not None
        assert observed.parent_observed_run_index == 3
        assert observed.parent_observed_event_id == "0123456789abcdef0123456789abcdef"

    async def test_session_agent_child_names_are_strict(
        self, rdb_session: AsyncSession
    ) -> None:
        """Child SessionAgent names are strict canonical path segments."""
        workspace_id = await _create_workspace(rdb_session, "session-agent-name-ws")
        agent_id = await _create_agent(rdb_session, workspace_id, "session-agent-name")
        repo = AgentSessionRepository()
        root_session = await repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
                primary_kind=None,
                start_reason=AgentSessionStartReason.INITIAL,
            ),
        )
        root_agent = await repo.get_session_agent_by_session_id(
            rdb_session,
            root_session.id,
        )
        assert root_agent is not None

        for name in ["", "has space", "../x", "x/y", "-bad", "한글", "a" * 65]:
            with pytest.raises(ValueError):
                await repo.create_child_session_agent(
                    rdb_session,
                    parent_session_agent_id=root_agent.id,
                    name=name,
                    agent_type="default",
                    title=None,
                    last_task_message=None,
                )

    async def test_session_agent_duplicate_sibling_is_rejected(
        self, rdb_session: AsyncSession
    ) -> None:
        """Sibling SessionAgents cannot reuse a parent-local name."""
        workspace_id = await _create_workspace(rdb_session, "session-agent-dupe-ws")
        agent_id = await _create_agent(rdb_session, workspace_id, "session-agent-dupe")
        repo = AgentSessionRepository()
        root_session = await repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
                primary_kind=None,
                start_reason=AgentSessionStartReason.INITIAL,
            ),
        )
        root_agent = await repo.get_session_agent_by_session_id(
            rdb_session,
            root_session.id,
        )
        assert root_agent is not None
        await repo.create_child_session_agent(
            rdb_session,
            parent_session_agent_id=root_agent.id,
            name="worker",
            agent_type="default",
            title=None,
            last_task_message=None,
        )

        with pytest.raises(ValueError):
            await repo.create_child_session_agent(
                rdb_session,
                parent_session_agent_id=root_agent.id,
                name="worker",
                agent_type="default",
                title=None,
                last_task_message=None,
            )

    async def test_session_agent_path_lookup_is_root_tree_scoped(
        self, rdb_session: AsyncSession
    ) -> None:
        """Path lookup does not cross root SessionAgent trees."""
        workspace_id = await _create_workspace(rdb_session, "session-agent-scope-ws")
        agent_id = await _create_agent(rdb_session, workspace_id, "session-agent-scope")
        repo = AgentSessionRepository()
        first_session = await repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
                primary_kind=None,
                start_reason=AgentSessionStartReason.INITIAL,
            ),
        )
        second_session = await repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
                primary_kind=None,
                start_reason=AgentSessionStartReason.INITIAL,
            ),
        )
        first_root = await repo.get_session_agent_by_session_id(
            rdb_session,
            first_session.id,
        )
        second_root = await repo.get_session_agent_by_session_id(
            rdb_session,
            second_session.id,
        )
        assert first_root is not None
        assert second_root is not None
        child = await repo.create_child_session_agent(
            rdb_session,
            parent_session_agent_id=first_root.id,
            name="worker",
            agent_type="default",
            title=None,
            last_task_message=None,
        )

        resolved_from_second_tree = await repo.resolve_session_agent_path(
            rdb_session,
            current_session_agent_id=second_root.id,
            path=child.path,
        )

        assert resolved_from_second_tree is None

    async def test_child_agent_sessions_are_hidden_from_ordinary_lists(
        self, rdb_session: AsyncSession
    ) -> None:
        """Child AgentSessions are hidden by session_kind from ordinary lists."""
        workspace_id = await _create_workspace(rdb_session, "session-agent-hidden-ws")
        agent_id = await _create_agent(
            rdb_session, workspace_id, "session-agent-hidden"
        )
        repo = AgentSessionRepository()
        root_session = await repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
                primary_kind=None,
                start_reason=AgentSessionStartReason.INITIAL,
            ),
        )
        root_agent = await repo.get_session_agent_by_session_id(
            rdb_session,
            root_session.id,
        )
        assert root_agent is not None
        child = await repo.create_child_session_agent(
            rdb_session,
            parent_session_agent_id=root_agent.id,
            name="worker",
            agent_type="default",
            title=None,
            last_task_message=None,
        )

        workspace_sessions = await repo.list_by_workspace(rdb_session, workspace_id)
        active_sessions = await repo.list_active_by_agent_id(rdb_session, agent_id)
        child_session = await repo.get_by_id(rdb_session, child.agent_session_id)

        assert [session.id for session in workspace_sessions] == [root_session.id]
        assert [session.id for session in active_sessions] == [root_session.id]
        assert child_session is not None
        assert child_session.session_kind == AgentSessionKind.SUBAGENT

    async def test_delete_session_agent_subtree_deletes_child_sessions(
        self, rdb_session: AsyncSession
    ) -> None:
        """Deleting a linked AgentSession deletes the SessionAgent subtree sessions."""
        workspace_id = await _create_workspace(rdb_session, "session-agent-delete-ws")
        agent_id = await _create_agent(
            rdb_session, workspace_id, "session-agent-delete"
        )
        repo = AgentSessionRepository()
        root_session = await repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
                primary_kind=None,
                start_reason=AgentSessionStartReason.INITIAL,
            ),
        )
        root_agent = await repo.get_session_agent_by_session_id(
            rdb_session,
            root_session.id,
        )
        assert root_agent is not None
        child = await repo.create_child_session_agent(
            rdb_session,
            parent_session_agent_id=root_agent.id,
            name="worker",
            agent_type="default",
            title=None,
            last_task_message=None,
        )
        nested = await repo.create_child_session_agent(
            rdb_session,
            parent_session_agent_id=child.id,
            name="nested",
            agent_type="default",
            title=None,
            last_task_message=None,
        )

        await SessionLifecycleFinalizerRepository().finalize_purged_root_tree(
            rdb_session,
            root_session_id=root_session.id,
            session_ids=[
                root_session.id,
                child.agent_session_id,
                nested.agent_session_id,
            ],
        )

        assert await repo.get_by_id(rdb_session, root_session.id) is None
        assert await repo.get_by_id(rdb_session, child.agent_session_id) is None
        assert await repo.get_by_id(rdb_session, nested.agent_session_id) is None
        assert await repo.get_session_agent_by_id(rdb_session, root_agent.id) is None
        assert await repo.get_session_agent_by_id(rdb_session, child.id) is None
        assert await repo.get_session_agent_by_id(rdb_session, nested.id) is None
