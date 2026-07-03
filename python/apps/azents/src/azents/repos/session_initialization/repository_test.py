"""SessionInitializationRepository tests."""

import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    LLMProvider,
    SessionInitializationEventKind,
    SessionInitializationStatus,
    SessionInitializationStepType,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.testing.model_selection import make_test_model_selection_dict

from . import SessionInitializationRepository
from .data import (
    SessionInitializationCreate,
    SessionInitializationEventCreate,
    SessionInitializationStepCreate,
)


async def _create_workspace(session: AsyncSession, handle: str) -> str:
    """Create Workspace for tests."""
    repo = WorkspaceRepository()
    await repo.create(
        session, WorkspaceCreate(name="Initialization test", handle=handle)
    )
    workspace_id = await repo.resolve_id(session, handle)
    assert workspace_id is not None
    return workspace_id


async def _create_session(session: AsyncSession, workspace_id: str, slug: str) -> str:
    """Create AgentSession for tests."""
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
        name="Initialization test agent",
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

    agent_session = await AgentSessionRepository().ensure_team_primary_for_agent(
        session,
        workspace_id=workspace_id,
        agent_id=agent.id,
    )
    return agent_session.id


class TestSessionInitializationRepository:
    """SessionInitializationRepository tests."""

    async def test_create_and_get_initialization(
        self, rdb_session: AsyncSession
    ) -> None:
        """Create and fetch initialization by AgentSession."""
        workspace_id = await _create_workspace(rdb_session, "init-row-ws")
        session_id = await _create_session(rdb_session, workspace_id, "init-row")
        repo = SessionInitializationRepository()

        created = await repo.create_initialization(
            rdb_session,
            SessionInitializationCreate(
                session_id=session_id,
                status=SessionInitializationStatus.READY,
                failure_summary=None,
                started_at=None,
                completed_at=None,
                failed_at=None,
                canceled_at=None,
                cleaned_at=None,
            ),
        )
        loaded = await repo.get_by_session_id(rdb_session, session_id=session_id)

        assert loaded is not None
        assert loaded.id == created.id
        assert loaded.status == SessionInitializationStatus.READY
        assert loaded.retry_count == 0

    async def test_create_ready_noop_if_absent_is_idempotent(
        self, rdb_session: AsyncSession
    ) -> None:
        """Ready no-op initialization creation is idempotent."""
        workspace_id = await _create_workspace(rdb_session, "init-ready-ws")
        session_id = await _create_session(rdb_session, workspace_id, "init-ready")
        repo = SessionInitializationRepository()

        first = await repo.create_ready_noop_if_absent(
            rdb_session,
            session_id=session_id,
            completed_at=datetime.datetime(2026, 7, 3, tzinfo=datetime.UTC),
        )
        second = await repo.create_ready_noop_if_absent(
            rdb_session,
            session_id=session_id,
            completed_at=datetime.datetime(2026, 7, 4, tzinfo=datetime.UTC),
        )
        steps = await repo.list_steps(rdb_session, initialization_id=first.id)

        assert second.id == first.id
        assert first.status == SessionInitializationStatus.READY
        assert [step.step_key for step in steps] == ["noop_ready"]
        assert steps[0].blocking is False
        assert steps[0].retryable is False

    async def test_steps_are_listed_by_sequence(
        self, rdb_session: AsyncSession
    ) -> None:
        """Initialization steps are returned in deterministic sequence order."""
        workspace_id = await _create_workspace(rdb_session, "init-steps-ws")
        session_id = await _create_session(rdb_session, workspace_id, "init-steps")
        repo = SessionInitializationRepository()
        initialization = await repo.create_initialization(
            rdb_session,
            SessionInitializationCreate(
                session_id=session_id,
                status=SessionInitializationStatus.PENDING,
                failure_summary=None,
                started_at=None,
                completed_at=None,
                failed_at=None,
                canceled_at=None,
                cleaned_at=None,
            ),
        )

        await repo.create_step(
            rdb_session,
            SessionInitializationStepCreate(
                initialization_id=initialization.id,
                session_id=session_id,
                sequence=2,
                step_key="register_workspace_project",
                step_type=SessionInitializationStepType.REGISTER_WORKSPACE_PROJECT,
                blocking=True,
                retryable=True,
                depends_on_step_keys=["create_git_worktree"],
                resource_descriptors=[],
            ),
        )
        await repo.create_step(
            rdb_session,
            SessionInitializationStepCreate(
                initialization_id=initialization.id,
                session_id=session_id,
                sequence=1,
                step_key="create_git_worktree",
                step_type=SessionInitializationStepType.CREATE_GIT_WORKTREE,
                blocking=True,
                retryable=True,
                depends_on_step_keys=[],
                resource_descriptors=[{"type": "git_worktree"}],
            ),
        )

        steps = await repo.list_steps(
            rdb_session,
            initialization_id=initialization.id,
        )

        assert [step.step_key for step in steps] == [
            "create_git_worktree",
            "register_workspace_project",
        ]
        assert steps[0].resource_descriptors == [{"type": "git_worktree"}]
        assert steps[1].depends_on_step_keys == ["create_git_worktree"]

    async def test_append_event_assigns_monotonic_sequence(
        self, rdb_session: AsyncSession
    ) -> None:
        """Appended initialization events receive increasing sequence numbers."""
        workspace_id = await _create_workspace(rdb_session, "init-events-ws")
        session_id = await _create_session(rdb_session, workspace_id, "init-events")
        repo = SessionInitializationRepository()
        initialization = await repo.create_initialization(
            rdb_session,
            SessionInitializationCreate(
                session_id=session_id,
                status=SessionInitializationStatus.RUNNING,
                failure_summary=None,
                started_at=None,
                completed_at=None,
                failed_at=None,
                canceled_at=None,
                cleaned_at=None,
            ),
        )
        step = await repo.create_step(
            rdb_session,
            SessionInitializationStepCreate(
                initialization_id=initialization.id,
                session_id=session_id,
                sequence=1,
                step_key="create_git_worktree",
                step_type=SessionInitializationStepType.CREATE_GIT_WORKTREE,
                blocking=True,
                retryable=True,
                depends_on_step_keys=[],
                resource_descriptors=[],
            ),
        )

        first = await repo.append_event(
            rdb_session,
            SessionInitializationEventCreate(
                initialization_id=initialization.id,
                step_id=step.id,
                session_id=session_id,
                kind=SessionInitializationEventKind.COMMAND_STARTED,
                command_argv=["git", "worktree", "add"],
                content=None,
                exit_code=None,
            ),
        )
        second = await repo.append_event(
            rdb_session,
            SessionInitializationEventCreate(
                initialization_id=initialization.id,
                step_id=step.id,
                session_id=session_id,
                kind=SessionInitializationEventKind.STDOUT,
                command_argv=None,
                content="Preparing worktree",
                exit_code=None,
            ),
        )

        events = await repo.list_events(
            rdb_session,
            initialization_id=initialization.id,
        )

        assert first.sequence == 1
        assert second.sequence == 2
        assert [event.sequence for event in events] == [1, 2]
        assert events[0].command_argv == ["git", "worktree", "add"]
        assert events[1].content == "Preparing worktree"
