"""Closed Worker operation TurnAction execution registry."""

import dataclasses
from collections.abc import Awaitable, Callable
from typing import Annotated, assert_never

from fastapi import Depends

from azents.core.action_execution_data import (
    ActionExecution,
    ActionExecutionProjection,
    OperationActionExecutionResult,
)
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.engine.events.action_messages import (
    AgentCreateGitWorktreeAction,
    AgentRemoveGitWorktreeAction,
    CleanupOrphanGitWorktreesAction,
    CreateGitWorktreeAction,
    CreateSessionWorkingFolderAction,
    OperationAction,
    RoutineJudgmentAction,
)
from azents.engine.events.types import Event
from azents.engine.routine_judgment_context import (
    RoutineJudgmentActionContext,
    RoutineJudgmentContext,
)
from azents.services.routine.judgment import RoutineJudgmentService
from azents.services.session_git_worktree import (
    SessionGitWorktreeService,
)
from azents.services.turn_action import TurnActionCapabilityRegistry

ProjectionUpdated = Callable[[ActionExecutionProjection], Awaitable[None]]
HistoryEventAppended = Callable[[Event], Awaitable[None]]
ActionRemoved = Callable[[str], Awaitable[None]]


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
    on_action_removed: ActionRemoved
    routine_judgment: RoutineJudgmentActionContext | None


@dataclasses.dataclass(frozen=True)
class OperationActionExecutorRegistry:
    """Explicit closed registry for operation action execution."""

    capabilities: Annotated[TurnActionCapabilityRegistry, Depends()]
    session_git_worktree_service: Annotated[SessionGitWorktreeService, Depends()]
    routine_judgment_service: Annotated[RoutineJudgmentService, Depends()]

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
                | RoutineJudgmentAction()
            ):
                return action
            case _:
                assert_never(action)  # ty: ignore[type-assertion-failure] — policy narrowing is not visible to the type checker.

    async def execute(
        self,
        *,
        action: OperationAction,
        context: OperationActionExecutionContext,
    ) -> OperationActionExecutionResult:
        """Execute one typed operation through its registered domain owner."""
        service = self.session_git_worktree_service
        match action:
            case RoutineJudgmentAction():
                judgment = context.routine_judgment
                if judgment is None or context.active_run_id is None:
                    raise RuntimeError(
                        "Routine judgment requires its ordinary Run context"
                    )
                if (
                    judgment.scope.agent_id != context.agent_id
                    or judgment.scope.session_id != context.session_id
                ):
                    raise ValueError("Routine judgment scope does not match its host")

                async def prepare() -> RoutineJudgmentContext:
                    prepared = await judgment.prepare_context()
                    if prepared.turn.run_id != context.active_run_id:
                        raise ValueError(
                            "Routine judgment context has another host Run"
                        )
                    return prepared

                result = await self.routine_judgment_service.execute(
                    scope=judgment.scope,
                    action=action,
                    execution=context.execution,
                    owner=SessionExecutionOwner(
                        session_id=context.session_id,
                        owner_generation=context.owner_generation,
                    ),
                    prepare_context=prepare,
                )
                if result.observation is not None:
                    await context.on_history_event_appended(result.observation)
                else:
                    await context.on_action_removed(context.execution.id)
                return OperationActionExecutionResult(
                    completed=True, context_invalidated=False, complete_run=False
                )
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

    async def cancel(
        self,
        *,
        action: OperationAction,
        execution: ActionExecution,
        owner_generation: int,
        reason: str,
        predecessor_run_id: str | None,
        on_history_event_appended: HistoryEventAppended,
        on_action_removed: ActionRemoved,
    ) -> None:
        """Use ordinary owner recovery with the action's registered domain cleanup."""
        match action:
            case RoutineJudgmentAction():
                await self.routine_judgment_service.cancel(
                    execution=execution,
                    owner=SessionExecutionOwner(
                        session_id=execution.session_id,
                        owner_generation=owner_generation,
                    ),
                )
                await on_action_removed(execution.id)
            case (
                CreateGitWorktreeAction()
                | CleanupOrphanGitWorktreesAction()
                | CreateSessionWorkingFolderAction()
                | AgentCreateGitWorktreeAction()
                | AgentRemoveGitWorktreeAction()
            ):
                await self.session_git_worktree_service.cancel_action_execution(
                    execution=execution,
                    owner_generation=owner_generation,
                    reason=reason,
                    on_history_event_appended=on_history_event_appended,
                    predecessor_run_id=predecessor_run_id,
                )
            case _:
                assert_never(action)
