"""Cancellation leaves projection failure ownership with the caller."""

import asyncio
from unittest.mock import AsyncMock, create_autospec

import pytest

from azents.core.action_execution_data import ActionExecution
from azents.repos.session_git_worktree.data import SessionGitWorktree
from azents.services.agent_runtime.lifecycle_data import RuntimeOperationTarget
from azents.services.session_git_worktree import SessionGitWorktreeService


@pytest.mark.parametrize("agent_owned", [False, True])
@pytest.mark.parametrize("catalog", [False, True])
async def test_project_step_cancellation_does_not_record_failure(
    agent_owned: bool, catalog: bool
) -> None:
    """Four registration/catalog boundaries propagate cancellation unchanged."""
    service = create_autospec(SessionGitWorktreeService, instance=True)
    service._append_action_execution_event = AsyncMock()
    service._mark_action_execution_failed = AsyncMock()
    service._fail_agent_create_git_worktree = AsyncMock()
    service.runtime_target_resolver.resolve_operation_target = AsyncMock(
        side_effect=asyncio.CancelledError
    )
    runtime = create_autospec(RuntimeOperationTarget, instance=True)
    runtime.configuration_sequence = 1
    runtime.configuration_digest = "digest"
    runtime.desired_generation = 1
    execution = create_autospec(ActionExecution, instance=True)
    allocation = create_autospec(SessionGitWorktree, instance=True)
    with pytest.raises(asyncio.CancelledError):
        if agent_owned:
            step = (
                SessionGitWorktreeService._catalog_agent_created_project
                if catalog
                else SessionGitWorktreeService._register_agent_created_project
            )
            await step(
                service,
                agent_id="agent",
                runtime=runtime,
                execution=execution,
                allocation=allocation,
                worktree_path="/workspace/agent/project",
                predecessor_run_id="run",
                on_projection_updated=None,
                on_history_event_appended=None,
            )
        else:
            step = (
                SessionGitWorktreeService._run_action_catalog_step
                if catalog
                else SessionGitWorktreeService._run_action_register_project_step
            )
            await step(
                service,
                agent_id="agent",
                runtime=runtime,
                execution=execution,
                allocation=allocation,
                worktree_path="/workspace/agent/project",
                on_projection_updated=None,
                on_history_event_appended=None,
            )
    service._mark_action_execution_failed.assert_not_awaited()
    service._fail_agent_create_git_worktree.assert_not_awaited()
    service._append_action_execution_event.assert_awaited_once()


async def test_refresh_cancellation_does_not_record_warning() -> None:
    """A canceled refresh emits only its already-started event, never a warning."""
    service = create_autospec(SessionGitWorktreeService, instance=True)
    service._append_action_execution_event = AsyncMock()
    service.agent_project_catalog_service.refresh_project_status = AsyncMock(
        side_effect=asyncio.CancelledError
    )
    with pytest.raises(asyncio.CancelledError):
        await SessionGitWorktreeService._run_action_refresh_project_status_step(
            service,
            agent_id="agent",
            execution=create_autospec(ActionExecution, instance=True),
            path="/workspace/agent/project",
            on_projection_updated=None,
        )
    service._append_action_execution_event.assert_awaited_once()
