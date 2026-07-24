"""Action execution repository tests."""

import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ActionExecutionEventKind,
    ActionExecutionStatus,
    EventKind,
    LLMProvider,
)
from azents.engine.events.action_messages import (
    ActionMessagePayload,
    CreateGitWorktreeAction,
)
from azents.engine.events.types import validate_event_payload
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.repos.action_execution import ActionExecutionRepository
from azents.repos.action_execution.data import (
    ActionExecutionCreate,
    ActionExecutionEventCreate,
)
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSessionCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.testing.model_selection import make_test_model_selection_dict


async def _create_agent_session(
    session: AsyncSession,
    handle: str,
) -> str:
    """Create an AgentSession for action execution tests."""
    await WorkspaceRepository().create(
        session,
        WorkspaceCreate(name="Action execution test", handle=handle),
    )
    workspace_id = await WorkspaceRepository().resolve_id(session, handle)
    assert workspace_id is not None
    integration = RDBLLMProviderIntegration(
        workspace_id=workspace_id,
        provider=LLMProvider.ANTHROPIC,
        name=f"{handle}-integration",
        encrypted_credentials="encrypted-test-value",
        config=None,
    )
    session.add(integration)
    await session.flush()
    agent = RDBAgent(
        workspace_id=workspace_id,
        name="Action execution test agent",
        model_selection=make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier=f"{handle}-model-id",
        ),
        lightweight_model_selection=make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier=f"{handle}-model-id",
        ),
    )
    session.add(agent)
    await session.flush()
    runtime = RDBAgentRuntime(workspace_id=workspace_id, agent_id=agent.id)
    session.add(runtime)
    await session.flush()
    agent_session = await AgentSessionRepository().create(
        session,
        AgentSessionCreate(
            workspace_id=workspace_id,
            agent_id=agent.id,
            title=None,
        ),
    )
    return agent_session.id


def test_validate_event_payload_accepts_create_git_worktree_action() -> None:
    """Action messages accept create_git_worktree TurnAction payloads."""
    payload = ActionMessagePayload(
        sender_user_id=None,
        action=CreateGitWorktreeAction(
            source_project_path="/workspace/agent/repo",
            starting_ref="main",
        ),
        message="",
    )

    validated = validate_event_payload(
        EventKind.ACTION_MESSAGE,
        payload.model_dump(mode="json"),
    )

    assert isinstance(validated, ActionMessagePayload)
    assert isinstance(validated.action, CreateGitWorktreeAction)
    assert validated.action.source_project_path == "/workspace/agent/repo"
    assert validated.action.starting_ref == "main"


class TestActionExecutionRepository:
    """ActionExecutionRepository tests."""

    async def test_create_project_and_append_events(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Execution state and progress events are keyed by action_message event."""
        session_id = await _create_agent_session(rdb_session, "action-exec-create")
        input_buffer_id = "01900000000070008000000000000001"
        action = CreateGitWorktreeAction(
            source_project_path="/workspace/agent/repo",
            starting_ref="main",
        ).model_dump(mode="json")
        repo = ActionExecutionRepository()

        execution = await repo.create(
            rdb_session,
            ActionExecutionCreate(
                sender_user_id=None,
                id=None,
                session_id=session_id,
                input_buffer_id=input_buffer_id,
                action_type="create_git_worktree",
                action=action,
                status=ActionExecutionStatus.PENDING,
                owner_generation=1,
            ),
        )
        same_execution = await repo.create(
            rdb_session,
            ActionExecutionCreate(
                sender_user_id=None,
                id=None,
                session_id=session_id,
                input_buffer_id=input_buffer_id,
                action_type="create_git_worktree",
                action=action,
                status=ActionExecutionStatus.PENDING,
                owner_generation=1,
            ),
        )
        started = await repo.append_event(
            rdb_session,
            ActionExecutionEventCreate(
                action_execution_id=execution.id,
                session_id=session_id,
                kind=ActionExecutionEventKind.COMMAND_STARTED,
                step_key="create_git_worktree",
                command_argv=["git", "worktree", "add"],
                content="Starting Git worktree creation.",
                exit_code=None,
            ),
        )
        completed = await repo.append_event(
            rdb_session,
            ActionExecutionEventCreate(
                action_execution_id=execution.id,
                session_id=session_id,
                kind=ActionExecutionEventKind.COMPLETED,
                step_key="create_git_worktree",
                command_argv=None,
                content="Git worktree action completed.",
                exit_code=0,
            ),
        )
        marked = await repo.mark_running(
            rdb_session,
            action_execution_id=execution.id,
            started_at=datetime.datetime.now(datetime.UTC),
        )

        assert same_execution.id == execution.id
        assert execution.input_buffer_id == input_buffer_id
        assert marked.status is ActionExecutionStatus.RUNNING
        assert started.sequence == 1
        assert completed.sequence == 2
        projection = await repo.get_projection_by_input_buffer_id(
            rdb_session,
            input_buffer_id=input_buffer_id,
        )
        assert projection is not None
        assert projection.execution.id == execution.id
        assert [event.id for event in projection.events] == [started.id, completed.id]
