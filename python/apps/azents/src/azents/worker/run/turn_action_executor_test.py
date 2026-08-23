"""Worker operation TurnAction executor registry tests."""

import datetime
from typing import Any, Literal, assert_never, cast
from unittest.mock import AsyncMock

import pytest

from azents.core.enums import ActionExecutionStatus
from azents.engine.events.action_messages import (
    AgentCreateGitWorktreeAction,
    AgentRemoveGitWorktreeAction,
    CleanupOrphanGitWorktreesAction,
    CreateGitWorktreeAction,
    CreateSessionWorkingFolderAction,
    GoalAction,
    OperationAction,
)
from azents.engine.events.types import Event
from azents.repos.action_execution.data import (
    ActionExecution,
    ActionExecutionProjection,
)
from azents.services.session_git_worktree import (
    GitWorktreeActionExecutionResult,
    SessionGitWorktreeService,
)
from azents.services.turn_action import TurnActionCapabilityRegistry

from .turn_action_executor import (
    OperationActionExecutionContext,
    OperationActionExecutorRegistry,
)

_RESULT = GitWorktreeActionExecutionResult(
    completed=True,
    context_invalidated=False,
    complete_run=False,
)
OperationMethodName = Literal[
    "run_git_worktree_action",
    "run_cleanup_orphan_git_worktrees_action",
    "run_create_session_working_folder_action",
    "run_agent_create_git_worktree_action",
    "run_agent_remove_git_worktree_action",
]


class _Service:
    """Operation service test double with one mock per registration."""

    def __init__(self) -> None:
        self.run_git_worktree_action = AsyncMock(return_value=_RESULT)
        self.run_cleanup_orphan_git_worktrees_action = AsyncMock(return_value=_RESULT)
        self.run_create_session_working_folder_action = AsyncMock(return_value=_RESULT)
        self.run_agent_create_git_worktree_action = AsyncMock(return_value=_RESULT)
        self.run_agent_remove_git_worktree_action = AsyncMock(return_value=_RESULT)


def _agent_create_action() -> AgentCreateGitWorktreeAction:
    return AgentCreateGitWorktreeAction(
        bridge_identity="bridge-create",
        originating_run_id="run-origin",
        client_tool_call_id="call-create",
        session_agent_context_id="context-1",
        originating_agent_session_id="session-1",
        source_project_id="project-1",
        source_project_path="/workspace/agent/source",
        starting_ref=None,
        branch_name=None,
    )


def _agent_remove_action() -> AgentRemoveGitWorktreeAction:
    return AgentRemoveGitWorktreeAction(
        bridge_identity="bridge-remove",
        originating_run_id="run-origin",
        client_tool_call_id="call-remove",
        session_agent_context_id="context-1",
        originating_agent_session_id="session-1",
        worktree_project_id="project-2",
        worktree_allocation_id="allocation-1",
        worktree_path="/workspace/agent/worktree",
        force=False,
    )


def _execution(action: OperationAction) -> ActionExecution:
    now = datetime.datetime.now(datetime.UTC)
    return ActionExecution(
        id="execution-1",
        session_id="session-1",
        mailbox_item_id="mailbox-1",
        sender_user_id=None,
        action_type=action.type,
        action=action.model_dump(mode="json"),
        status=ActionExecutionStatus.PENDING,
        owner_generation=3,
        failure_summary=None,
        cancellation_summary=None,
        started_at=None,
        completed_at=None,
        failed_at=None,
        cancelled_at=None,
        created_at=now,
        updated_at=now,
    )


def _service() -> _Service:
    return _Service()


def _registry(
    service: _Service | None = None,
) -> OperationActionExecutorRegistry:
    return OperationActionExecutorRegistry(
        capabilities=TurnActionCapabilityRegistry(
            agent_session_repository=cast(Any, object()),
            goal_store=cast(Any, object()),
            skill_store=cast(Any, object()),
            vfs_projection_service=None,
        ),
        session_git_worktree_service=cast(
            SessionGitWorktreeService,
            service or _service(),
        ),
    )


async def _projection_updated(projection: ActionExecutionProjection) -> None:
    del projection


async def _history_event_appended(event: Event) -> None:
    del event


def _context(
    execution: ActionExecution,
    *,
    active_run_id: str | None = "run-1",
) -> OperationActionExecutionContext:
    return OperationActionExecutionContext(
        agent_id="agent-1",
        session_id="session-1",
        active_run_id=active_run_id,
        execution=execution,
        owner_generation=3,
        on_projection_updated=_projection_updated,
        on_history_event_appended=_history_event_appended,
    )


@pytest.mark.parametrize(
    ("action", "method_name", "bridge"),
    [
        (
            CreateGitWorktreeAction(
                source_project_path="/workspace/agent/source",
                starting_ref="main",
            ),
            "run_git_worktree_action",
            False,
        ),
        (
            CleanupOrphanGitWorktreesAction(),
            "run_cleanup_orphan_git_worktrees_action",
            False,
        ),
        (
            CreateSessionWorkingFolderAction(),
            "run_create_session_working_folder_action",
            False,
        ),
        (
            _agent_create_action(),
            "run_agent_create_git_worktree_action",
            True,
        ),
        (
            _agent_remove_action(),
            "run_agent_remove_git_worktree_action",
            True,
        ),
    ],
)
@pytest.mark.asyncio
async def test_execute_dispatches_every_operation_registration(
    action: OperationAction,
    method_name: OperationMethodName,
    bridge: bool,
) -> None:
    """Every operation discriminator selects exactly one domain executor."""
    service = _service()
    registry = _registry(service)
    execution = _execution(action)

    result = await registry.execute(
        action=action,
        context=_context(execution),
    )

    assert result == _RESULT
    match method_name:
        case "run_git_worktree_action":
            method = service.run_git_worktree_action
        case "run_cleanup_orphan_git_worktrees_action":
            method = service.run_cleanup_orphan_git_worktrees_action
        case "run_create_session_working_folder_action":
            method = service.run_create_session_working_folder_action
        case "run_agent_create_git_worktree_action":
            method = service.run_agent_create_git_worktree_action
        case "run_agent_remove_git_worktree_action":
            method = service.run_agent_remove_git_worktree_action
        case _:
            assert_never(method_name)
    method.assert_awaited_once()
    await_args = method.await_args
    assert await_args is not None
    kwargs = await_args.kwargs
    assert kwargs["agent_id"] == "agent-1"
    assert kwargs["session_id"] == "session-1"
    assert kwargs["execution"] == execution
    assert kwargs["action"] == action
    assert kwargs["owner_generation"] == 3
    if bridge:
        assert kwargs["predecessor_run_id"] == "run-1"
    else:
        assert "predecessor_run_id" not in kwargs
    assert (
        sum(cast(AsyncMock, value).await_count for value in vars(service).values()) == 1
    )


@pytest.mark.parametrize("action", [_agent_create_action(), _agent_remove_action()])
@pytest.mark.asyncio
async def test_agent_bridge_requires_active_processing_run(
    action: OperationAction,
) -> None:
    """Agent-managed bridge actions fail before side effects without a Run."""
    service = _service()
    registry = _registry(service)

    with pytest.raises(RuntimeError, match="requires an active processing Run"):
        await registry.execute(
            action=action,
            context=_context(_execution(action), active_run_id=None),
        )

    assert all(
        cast(AsyncMock, value).await_count == 0 for value in vars(service).values()
    )


def test_decode_rejects_non_operation_action() -> None:
    """Persisted executions cannot acquire a model-producing handler."""
    registry = _registry()

    with pytest.raises(ValueError, match="requires an operation action"):
        registry.decode(GoalAction().model_dump(mode="json"))
