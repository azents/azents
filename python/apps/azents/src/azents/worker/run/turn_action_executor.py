"""Closed Worker operation TurnAction execution registry."""

import dataclasses
from collections.abc import Awaitable, Callable
from typing import Annotated, assert_never

from fastapi import Depends

from azents.engine.events.action_messages import (
    AgentCreateGitWorktreeAction,
    AgentRemoveGitWorktreeAction,
    CleanupOrphanGitWorktreesAction,
    CreateGitWorktreeAction,
    CreateSessionWorkingFolderAction,
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

ProjectionUpdated = Callable[[ActionExecutionProjection], Awaitable[None]]
HistoryEventAppended = Callable[[Event], Awaitable[None]]


@dataclasses.dataclass(frozen=True)
class OperationActionExecutionContext:
    """Shared Worker context for one admitted operation action."""

    agent_id: str
    session_id: str
    active_run_id: str | None
    execution: ActionExecution
    owner_generation: int
    on_projection_updated: ProjectionUpdated
    on_history_event_appended: HistoryEventAppended


@dataclasses.dataclass(frozen=True)
class OperationActionExecutorRegistry:
    """Explicit closed registry for operation action execution."""

    capabilities: Annotated[TurnActionCapabilityRegistry, Depends()]
    session_git_worktree_service: Annotated[SessionGitWorktreeService, Depends()]

    def decode(self, value: object) -> OperationAction:
        """Decode and validate one persisted operation action."""
        action = self.capabilities.decode(value)
        policy = self.capabilities.policy_for(action)
        if not policy.operation:
            raise ValueError("Action execution requires an operation action")
        match action:
            case (
                CreateGitWorktreeAction()
                | CleanupOrphanGitWorktreesAction()
                | CreateSessionWorkingFolderAction()
                | AgentCreateGitWorktreeAction()
                | AgentRemoveGitWorktreeAction()
            ):
                return action
            case _:
                assert_never(action)  # ty: ignore[type-assertion-failure] — policy narrowing is not visible to the type checker.

    async def execute(
        self,
        *,
        action: OperationAction,
        context: OperationActionExecutionContext,
    ) -> GitWorktreeActionExecutionResult:
        """Execute one typed operation through its registered domain owner."""
        service = self.session_git_worktree_service
        match action:
            case CreateGitWorktreeAction():
                return await service.run_git_worktree_action(
                    agent_id=context.agent_id,
                    session_id=context.session_id,
                    execution=context.execution,
                    action=action,
                    owner_generation=context.owner_generation,
                    on_projection_updated=context.on_projection_updated,
                    on_history_event_appended=context.on_history_event_appended,
                )
            case CleanupOrphanGitWorktreesAction():
                return await service.run_cleanup_orphan_git_worktrees_action(
                    agent_id=context.agent_id,
                    session_id=context.session_id,
                    execution=context.execution,
                    action=action,
                    owner_generation=context.owner_generation,
                    on_projection_updated=context.on_projection_updated,
                    on_history_event_appended=context.on_history_event_appended,
                )
            case CreateSessionWorkingFolderAction():
                return await service.run_create_session_working_folder_action(
                    agent_id=context.agent_id,
                    session_id=context.session_id,
                    execution=context.execution,
                    action=action,
                    owner_generation=context.owner_generation,
                    on_projection_updated=context.on_projection_updated,
                    on_history_event_appended=context.on_history_event_appended,
                )
            case AgentCreateGitWorktreeAction():
                if context.active_run_id is None:
                    raise RuntimeError(
                        "Agent worktree bridge requires an active processing Run"
                    )
                return await service.run_agent_create_git_worktree_action(
                    agent_id=context.agent_id,
                    session_id=context.session_id,
                    execution=context.execution,
                    action=action,
                    owner_generation=context.owner_generation,
                    predecessor_run_id=context.active_run_id,
                    on_projection_updated=context.on_projection_updated,
                    on_history_event_appended=context.on_history_event_appended,
                )
            case AgentRemoveGitWorktreeAction():
                if context.active_run_id is None:
                    raise RuntimeError(
                        "Agent worktree bridge requires an active processing Run"
                    )
                return await service.run_agent_remove_git_worktree_action(
                    agent_id=context.agent_id,
                    session_id=context.session_id,
                    execution=context.execution,
                    action=action,
                    owner_generation=context.owner_generation,
                    predecessor_run_id=context.active_run_id,
                    on_projection_updated=context.on_projection_updated,
                    on_history_event_appended=context.on_history_event_appended,
                )
            case _:
                assert_never(action)
