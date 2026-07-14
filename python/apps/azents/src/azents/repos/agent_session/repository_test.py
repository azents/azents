"""AgentSessionRepository tests."""

import asyncio
import datetime
from collections.abc import Sequence
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
import sqlalchemy as sa
from azcommon.result import Success
from pytest import MonkeyPatch
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

import azents.repos.agent_session as agent_session_repo
from azents.core.enums import (
    AgentSessionKind,
    AgentSessionPrimaryKind,
    AgentSessionRunState,
    AgentSessionStartReason,
    AgentSessionStatus,
    AgentSessionTitleSource,
    LLMProvider,
    SessionAgentKind,
)
from azents.core.inference_profile import SessionInferenceState
from azents.core.llm_catalog import ModelReasoningEffort
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_execution.data import AgentRunCreate
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_model_selection_dict,
)

from . import AgentSessionRepository
from .data import AgentSession, AgentSessionCreate, SessionAgent


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

    async def test_heartbeat_running_rejects_stale_owner_generation(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """A stolen lease generation cannot refresh the durable heartbeat."""
        workspace_id = await _create_workspace(rdb_session, "heartbeat-fence-ws")
        agent_id = await _create_agent(rdb_session, workspace_id, "heartbeat-fence")
        repo = AgentSessionRepository()
        created = await repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
            ),
        )
        await repo.mark_running(rdb_session, created.id)
        first_generation = await repo.claim_owner_generation(rdb_session, created.id)
        fixed_heartbeat = datetime.datetime(2000, 1, 1, tzinfo=datetime.UTC)
        await rdb_session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == created.id)
            .values(run_heartbeat_at=fixed_heartbeat)
        )
        second_generation = await repo.claim_owner_generation(rdb_session, created.id)

        stale_updated = await repo.heartbeat_running(
            rdb_session,
            created.id,
            expected_owner_generation=first_generation,
        )
        stale_heartbeat = await rdb_session.scalar(
            sa.select(RDBAgentSession.run_heartbeat_at).where(
                RDBAgentSession.id == created.id
            )
        )

        assert first_generation == 1
        assert second_generation == 2
        assert stale_updated is False
        assert stale_heartbeat == fixed_heartbeat

        current_updated = await repo.heartbeat_running(
            rdb_session,
            created.id,
            expected_owner_generation=second_generation,
        )
        current = await repo.get_by_id(rdb_session, created.id)

        assert current_updated is True
        assert current is not None
        assert current.run_state is AgentSessionRunState.RUNNING
        assert current.owner_generation == second_generation
        assert current.run_heartbeat_at > fixed_heartbeat

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

    async def test_request_stop_preserves_first_intent_and_stamps_active_run(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Repeated stops reuse one identity and correlate the active Run."""
        workspace_id = await _create_workspace(rdb_session, "request-stop-ws")
        agent_id = await _create_agent(rdb_session, workspace_id, "request-stop")
        session_repo = AgentSessionRepository()
        agent_session = await session_repo.create(
            rdb_session,
            AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
            ),
        )
        run_repo = AgentRunRepository()
        agent_run = await run_repo.create(
            rdb_session,
            AgentRunCreate(
                session_id=agent_session.id,
                parent_agent_run_id=None,
            ),
        )
        first_user = await UserRepository().create(
            rdb_session,
            UserCreate(email="request-stop-first@example.com"),
        )
        second_user = await UserRepository().create(
            rdb_session,
            UserCreate(email="request-stop-second@example.com"),
        )

        first = await session_repo.request_stop(
            rdb_session,
            session_id=agent_session.id,
            stop_request_id="stop-1",
            user_id=first_user.id,
        )
        second = await session_repo.request_stop(
            rdb_session,
            session_id=agent_session.id,
            stop_request_id="stop-2",
            user_id=second_user.id,
        )
        stopped_run = await run_repo.get_by_id(rdb_session, agent_run.id)

        assert first is not None
        assert first.stop_requested_at is not None
        assert first.stop_request_id == "stop-1"
        assert first.stop_requested_by == first_user.id
        assert second is not None
        assert second.stop_requested_at == first.stop_requested_at
        assert second.stop_request_id == "stop-1"
        assert second.stop_requested_by == first_user.id
        assert stopped_run is not None
        assert stopped_run.stop_requested_at == first.stop_requested_at

        await session_repo.update_title(
            rdb_session,
            session_id=agent_session.id,
            title="Renamed after stop",
            title_source=AgentSessionTitleSource.MANUAL,
        )
        run_after_title = await run_repo.get_by_id(rdb_session, agent_run.id)
        assert run_after_title is not None
        assert run_after_title.stop_requested_at == first.stop_requested_at

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

    async def test_list_subtree_treats_concurrently_deleted_link_as_missing_session(
        self,
        monkeypatch: MonkeyPatch,
    ) -> None:
        """A delete that wins the root fence cannot turn a stop lookup into 500."""
        order: list[str] = []
        repo = AgentSessionRepository()
        linked_reads = 0

        async def get_linked(
            session: AsyncSession,
            agent_session_id: str,
        ) -> SessionAgent | None:
            nonlocal linked_reads
            del session
            assert agent_session_id == "root-session"
            order.append("read_link")
            linked_reads += 1
            if linked_reads > 1:
                return None
            return cast(
                SessionAgent,
                SimpleNamespace(
                    id="root-agent",
                    root_session_agent_id="root-agent",
                ),
            )

        async def lock_deleted_root(
            session: AsyncSession,
            session_agent_id: str,
        ) -> None:
            del session
            assert session_agent_id == "root-agent"
            order.append("lock_root")

        async def get_deleted_session(
            session: AsyncSession,
            agent_session_id: str,
        ) -> None:
            del session
            assert agent_session_id == "root-session"
            order.append("read_agent_session")

        monkeypatch.setattr(repo, "get_session_agent_by_session_id", get_linked)
        monkeypatch.setattr(repo, "lock_session_agent_by_id", lock_deleted_root)
        monkeypatch.setattr(repo, "get_by_id", get_deleted_session)

        session_ids = await repo.list_session_agent_subtree_session_ids(
            cast(AsyncSession, object()),
            agent_session_id="root-session",
        )

        assert session_ids == ["root-session"]
        assert order == [
            "read_link",
            "lock_root",
            "read_link",
            "read_agent_session",
        ]

    async def test_list_subtree_rejects_link_change_after_root_fence(
        self,
        monkeypatch: MonkeyPatch,
    ) -> None:
        """Never enumerate a different tree from the pre-fence SessionAgent link."""
        order: list[str] = []
        repo = AgentSessionRepository()
        linked_reads = 0

        async def get_linked(
            session: AsyncSession,
            agent_session_id: str,
        ) -> SessionAgent:
            nonlocal linked_reads
            del session
            assert agent_session_id == "root-session"
            order.append("read_link")
            linked_reads += 1
            if linked_reads == 1:
                return cast(
                    SessionAgent,
                    SimpleNamespace(
                        id="old-agent",
                        root_session_agent_id="old-root",
                    ),
                )
            return cast(
                SessionAgent,
                SimpleNamespace(
                    id="new-agent",
                    root_session_agent_id="new-root",
                ),
            )

        async def lock_old_root(
            session: AsyncSession,
            session_agent_id: str,
        ) -> SessionAgent:
            del session
            assert session_agent_id == "old-root"
            order.append("lock_root")
            return cast(SessionAgent, SimpleNamespace(id="old-root"))

        monkeypatch.setattr(repo, "get_session_agent_by_session_id", get_linked)
        monkeypatch.setattr(repo, "lock_session_agent_by_id", lock_old_root)

        with pytest.raises(RuntimeError, match="link changed"):
            await repo.list_session_agent_subtree_session_ids(
                cast(AsyncSession, object()),
                agent_session_id="root-session",
            )

        assert order == ["read_link", "lock_root", "read_link"]

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

        await repo.delete_by_id(rdb_session, root_session.id)

        assert await repo.get_by_id(rdb_session, root_session.id) is None
        assert await repo.get_by_id(rdb_session, child.agent_session_id) is None
        assert await repo.get_by_id(rdb_session, nested.agent_session_id) is None
        assert await repo.get_session_agent_by_id(rdb_session, root_agent.id) is None
        assert await repo.get_session_agent_by_id(rdb_session, child.id) is None
        assert await repo.get_session_agent_by_id(rdb_session, nested.id) is None

    async def test_delete_linked_session_locks_root_before_agent_sessions(
        self,
        monkeypatch: MonkeyPatch,
    ) -> None:
        """Serialize tree deletion in the same root-to-Session lock order."""
        order: list[str] = []
        repo = AgentSessionRepository()

        async def get_linked(
            session: AsyncSession,
            agent_session_id: str,
        ) -> SessionAgent:
            del session, agent_session_id
            order.append("read_link")
            return cast(
                SessionAgent,
                SimpleNamespace(
                    id="root-agent",
                    context_id="root-context",
                    root_session_agent_id="root-agent",
                ),
            )

        async def lock_root(
            session: AsyncSession,
            session_agent_id: str,
        ) -> SessionAgent:
            del session
            assert session_agent_id == "root-agent"
            order.append("lock_root")
            return cast(SessionAgent, SimpleNamespace(id="root-agent"))

        async def list_descendants(
            session: AsyncSession,
            *,
            session_agent_id: str,
            include_self: bool,
        ) -> list[SessionAgent]:
            del session
            assert session_agent_id == "root-agent"
            assert include_self is True
            order.append("read_subtree")
            return [
                cast(
                    SessionAgent,
                    SimpleNamespace(agent_session_id="root-session"),
                )
            ]

        async def lock_sessions(
            session: AsyncSession,
            *,
            agent_session_ids: Sequence[str],
        ) -> dict[str, AgentSession]:
            del session
            assert agent_session_ids == ["root-session"]
            order.append("lock_agent_sessions")
            return {
                "root-session": cast(
                    AgentSession,
                    SimpleNamespace(id="root-session"),
                )
            }

        class RecordingSession:
            async def execute(self, statement: object) -> object:
                assert isinstance(statement, sa.Delete)
                table_name = cast(sa.Table, statement.table).name
                order.append(f"delete_{table_name}")
                return object()

            async def flush(self) -> None:
                order.append("flush")

        monkeypatch.setattr(repo, "get_session_agent_by_session_id", get_linked)
        monkeypatch.setattr(repo, "lock_session_agent_by_id", lock_root)
        monkeypatch.setattr(repo, "list_descendant_session_agents", list_descendants)
        monkeypatch.setattr(repo, "lock_by_ids", lock_sessions)

        await repo.delete_by_id(
            cast(AsyncSession, RecordingSession()),
            "root-session",
        )

        assert order == [
            "read_link",
            "lock_root",
            "read_link",
            "read_subtree",
            "lock_agent_sessions",
            "delete_session_agent_context_git_worktrees",
            "delete_agent_sessions",
            "flush",
        ]

    async def test_delete_linked_session_fails_if_link_disappears_after_fence(
        self,
        monkeypatch: MonkeyPatch,
    ) -> None:
        """Never fall back to an unfenced AgentSession delete after a linked read."""
        order: list[str] = []
        repo = AgentSessionRepository()
        linked_reads = 0

        async def get_linked(
            session: AsyncSession,
            agent_session_id: str,
        ) -> SessionAgent | None:
            nonlocal linked_reads
            del session, agent_session_id
            order.append("read_link")
            linked_reads += 1
            if linked_reads > 1:
                return None
            return cast(
                SessionAgent,
                SimpleNamespace(
                    id="root-agent",
                    root_session_agent_id="root-agent",
                ),
            )

        async def lock_root(
            session: AsyncSession,
            session_agent_id: str,
        ) -> SessionAgent:
            del session, session_agent_id
            order.append("lock_root")
            return cast(SessionAgent, SimpleNamespace(id="root-agent"))

        async def get_remaining_session(
            session: AsyncSession,
            agent_session_id: str,
        ) -> AgentSession:
            del session, agent_session_id
            order.append("read_agent_session")
            return cast(AgentSession, SimpleNamespace(id="root-session"))

        class RecordingSession:
            async def execute(self, statement: object) -> object:
                del statement
                order.append("delete_agent_session")
                return object()

            async def flush(self) -> None:
                order.append("flush")

        monkeypatch.setattr(repo, "get_session_agent_by_session_id", get_linked)
        monkeypatch.setattr(repo, "lock_session_agent_by_id", lock_root)
        monkeypatch.setattr(repo, "get_by_id", get_remaining_session)

        with pytest.raises(RuntimeError, match="link disappeared"):
            await repo.delete_by_id(
                cast(AsyncSession, RecordingSession()),
                "root-session",
            )

        assert order == [
            "read_link",
            "lock_root",
            "read_link",
            "read_agent_session",
        ]

    async def test_delete_unlinked_session_preserves_direct_delete(
        self,
        monkeypatch: MonkeyPatch,
    ) -> None:
        """Unlinked legacy Sessions remain directly deletable without a tree lock."""
        order: list[str] = []
        repo = AgentSessionRepository()

        async def get_unlinked(
            session: AsyncSession,
            agent_session_id: str,
        ) -> None:
            del session, agent_session_id
            order.append("read_link")

        async def lock_sessions(
            session: AsyncSession,
            *,
            agent_session_ids: Sequence[str],
        ) -> dict[str, AgentSession]:
            del session
            order.append("lock_agent_session")
            return {
                session_id: cast(AgentSession, object())
                for session_id in agent_session_ids
            }

        class RecordingSession:
            async def execute(self, statement: object) -> object:
                del statement
                order.append("delete_agent_session")
                return object()

            async def flush(self) -> None:
                order.append("flush")

        monkeypatch.setattr(repo, "get_session_agent_by_session_id", get_unlinked)
        monkeypatch.setattr(repo, "lock_by_ids", lock_sessions)

        await repo.delete_by_id(
            cast(AsyncSession, RecordingSession()),
            "legacy-session",
        )

        assert order == [
            "read_link",
            "lock_agent_session",
            "delete_agent_session",
            "flush",
        ]
