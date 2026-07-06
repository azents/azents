"""Background task lifecycle tools.

Provides companion tools for LLM to query running background task status
(``task_status``) and stop it (``task_stop``).
Shares ``BackgroundTaskRegistry`` and accesses only tasks in same worker.
Permission check: ``task_stop`` can stop only tasks owned by parent session.
"""

import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from textwrap import dedent
from typing import Any

from pydantic import BaseModel, Field

from azents.core.tools import (
    Toolkit,
    ToolkitState,
    ToolkitStatus,
    TurnContext,
)
from azents.engine.run.background import BackgroundTaskRegistry
from azents.engine.run.types import FunctionToolError
from azents.engine.tooling.make_tool import make_tool

logger = logging.getLogger(__name__)


class TaskStatusInput(BaseModel):
    """``task_status`` input."""

    task_id: str = Field(
        description=(
            "The background task ID returned by a previous tool call "
            "(e.g., from a delegated background operation)."
        )
    )


class TaskStopInput(BaseModel):
    """``task_stop`` input."""

    task_id: str = Field(description="The background task ID to cancel.")
    reason: str | None = Field(
        default=None,
        description="Optional human-readable reason for cancellation (for logs).",
    )


def _make_task_status_handler(
    registry: BackgroundTaskRegistry,
) -> Callable[[TaskStatusInput], Awaitable[str]]:
    """``task_status`` handler factory. Captures Registry in closure."""

    async def task_status(input: TaskStatusInput) -> str:
        """Get the current status of a background task.

        Returns JSON with fields: task_id, status (running/not_found),
        tool_name, elapsed_seconds, started_at.
        Completed tasks are removed from the registry; their results are
        delivered as a new conversation turn rather than via this tool.
        """
        task = registry.get(input.task_id)
        if task is None:
            return json.dumps(
                {
                    "task_id": input.task_id,
                    "status": "not_found",
                    "note": (
                        "Task not found in registry. It may have completed "
                        "(result is delivered as a separate conversation turn) "
                        "or been cancelled."
                    ),
                },
                ensure_ascii=False,
            )
        elapsed = (datetime.now(UTC) - task.started_at).total_seconds()
        return json.dumps(
            {
                "task_id": task.task_id,
                "status": "running",
                "tool_name": task.tool_name,
                "elapsed_seconds": elapsed,
                "started_at": task.started_at.isoformat(),
            },
            ensure_ascii=False,
        )

    return task_status


def _make_task_stop_handler(
    registry: BackgroundTaskRegistry,
    parent_session_id: str,
) -> Callable[[TaskStopInput], Awaitable[str]]:
    """``task_stop`` handler factory with captured parent_session_id."""

    async def task_stop(input: TaskStopInput) -> str:
        """Cancel a running background task.

        Only tasks owned by the current session can be stopped.
        Returns JSON with fields: task_id, cancelled (bool), reason.
        """
        task = registry.get(input.task_id)
        if task is None:
            return json.dumps(
                {
                    "task_id": input.task_id,
                    "cancelled": False,
                    "reason": "not_found",
                },
                ensure_ascii=False,
            )
        if task.parent_session_id != parent_session_id:
            # Return explicit error for task from different session
            raise FunctionToolError(
                f"Cannot stop task {input.task_id}: it is owned by another session."
            )
        cancelled = await registry.cancel(input.task_id)
        if cancelled:
            logger.info(
                "Background task cancelled by task_stop",
                extra={
                    "task_id": input.task_id,
                    "tool_name": task.tool_name,
                    "reason": input.reason,
                },
            )
        return json.dumps(
            {
                "task_id": input.task_id,
                "cancelled": cancelled,
                "reason": input.reason,
            },
            ensure_ascii=False,
        )

    return task_stop


BACKGROUND_TASK_TOOLKIT_SLUG = "background_task"


class BackgroundTaskToolkit(Toolkit[Any]):
    """Toolkit providing both ``task_status`` and ``task_stop`` tools.

    Injected into agents with Background tools, allowing LLM to query/stop tasks.
    Registry is worker-scoped, so it is injected at creation.
    session_id is used for task_stop permission check.
    """

    display_name = "Background Tasks"

    def __init__(
        self,
        registry: BackgroundTaskRegistry,
        session_id: str,
    ) -> None:
        """Initialize Toolkit.

        :param registry: Shared worker-scoped background task registry
        :param session_id: Current parent session for task_stop permission check
        """
        self._registry = registry
        self._session_id = session_id

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Called every turn. Return Toolkit state + tool list."""
        del context
        task_status_tool = make_tool(
            _make_task_status_handler(self._registry),
            name="task_status",
            input_model=TaskStatusInput,
        )
        task_stop_tool = make_tool(
            _make_task_stop_handler(self._registry, self._session_id),
            name="task_stop",
            input_model=TaskStopInput,
        )
        return ToolkitState(
            status=ToolkitStatus.ENABLED,
            tools=[task_status_tool, task_stop_tool],
        )

    async def get_static_prompt(self, context: TurnContext) -> str:
        """Return static background task prompt for the current run."""
        del context
        return dedent(
            """\
            When you call a tool with ``run_in_background=true``, it returns a
            task_id immediately and the actual result arrives later as a
            separate conversation turn. Use ``task_status`` to check if a
            background task is still running, or ``task_stop`` to cancel it.
            """
        )
