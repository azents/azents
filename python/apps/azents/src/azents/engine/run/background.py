"""Background task registry.

Tracks background tool tasks running inside the worker process.
When a tool handler returns ``BackgroundHandle``, engine registers it here,
and calls ``on_complete`` when future completes to inject result into parent session.
"""

import asyncio
import contextlib
import dataclasses
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from azents.engine.run.types import FunctionToolResult

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class BackgroundTask:
    """Background task entry registered in registry."""

    task_id: str
    """Unique identifier (uuid7 hex)."""

    parent_session_id: str
    """Parent session ID that spawned background task."""

    agent_id: str
    """Parent agent ID for creating input buffer when injecting result."""

    workspace_id: str
    """Parent workspace ID for creating input buffer when injecting result."""

    tool_name: str
    """Running tool name for status lookup/debugging."""

    future: asyncio.Task[str | FunctionToolResult]
    """Actual running asyncio task."""

    started_at: datetime
    """Start time (UTC)."""


class BackgroundTaskRegistry:
    """Background task tracking inside worker process.

    When Engine returns ``BackgroundHandle``, it calls ``register()`` to register it,
    and handles results via ``on_complete`` callback injected in constructor when
    future completes.
    """

    def __init__(
        self,
        on_complete: Callable[[BackgroundTask], Awaitable[None]],
    ) -> None:
        """Initialize registry.

        :param on_complete: Callback called when task completes; performs input
            buffer injection, etc.
        """
        self._on_complete = on_complete
        self._tasks: dict[str, BackgroundTask] = {}
        self._by_session: dict[str, set[str]] = {}
        self._completion_tasks: set[asyncio.Task[None]] = set()

    def register(
        self,
        *,
        task_id: str,
        future: asyncio.Task[str | FunctionToolResult],
        parent_session_id: str,
        agent_id: str,
        workspace_id: str,
        tool_name: str,
    ) -> BackgroundTask:
        """Register task and attach future completion callback.

        :param task_id: Unique identifier
        :param future: Running asyncio task
        :param parent_session_id: Parent session that spawned it
        :param agent_id: parent agent ID
        :param workspace_id: parent workspace ID
        :param tool_name: Running tool name
        :return: Registered BackgroundTask
        """
        task = BackgroundTask(
            task_id=task_id,
            parent_session_id=parent_session_id,
            agent_id=agent_id,
            workspace_id=workspace_id,
            tool_name=tool_name,
            future=future,
            started_at=datetime.now(UTC),
        )
        self._tasks[task_id] = task
        self._by_session.setdefault(parent_session_id, set()).add(task_id)

        def on_done(fut: asyncio.Future[str | FunctionToolResult]) -> None:
            del fut  # Explicit unused marker
            completion_task = asyncio.create_task(
                self._handle_completion(task),
                name=f"bg_complete_{task_id}",
            )
            self._completion_tasks.add(completion_task)
            completion_task.add_done_callback(self._completion_tasks.discard)

        # Run on_complete when future completes, then remove from registry
        future.add_done_callback(on_done)
        logger.info(
            "Background task registered",
            extra={
                "task_id": task_id,
                "tool_name": tool_name,
                "parent_session_id": parent_session_id,
            },
        )
        return task

    async def _handle_completion(self, task: BackgroundTask) -> None:
        """Call on_complete after future completion, then cleanup registry."""
        try:
            await self._on_complete(task)
        except Exception:
            logger.exception(
                "Background task on_complete callback failed",
                extra={"task_id": task.task_id, "tool_name": task.tool_name},
            )
        finally:
            self._tasks.pop(task.task_id, None)
            session_tasks = self._by_session.get(task.parent_session_id)
            if session_tasks is not None:
                session_tasks.discard(task.task_id)
                if not session_tasks:
                    self._by_session.pop(task.parent_session_id, None)

    def get(self, task_id: str) -> BackgroundTask | None:
        """Get task.

        Completed tasks are removed from registry and not returned.
        """
        return self._tasks.get(task_id)

    def list_for_session(self, session_id: str) -> list[BackgroundTask]:
        """Return running task list for specific parent session."""
        return [self._tasks[tid] for tid in self._by_session.get(session_id, set())]

    async def cancel(self, task_id: str) -> bool:
        """Cancel task.

        Call ``asyncio.Task.cancel()`` and return True.
        Task is cleaned up by on_complete callback even after cancel.

        :param task_id: Task ID to cancel
        :return: True if found and cancel requested, otherwise False
        """
        task = self._tasks.get(task_id)
        if task is None:
            return False
        if not task.future.done():
            task.future.cancel()
        logger.info(
            "Background task cancellation requested",
            extra={"task_id": task_id, "tool_name": task.tool_name},
        )
        try:
            await task.future
        except asyncio.CancelledError:
            pass
        finally:
            await self._drain_completion_tasks()
        return True

    async def cancel_all_for_session(self, session_id: str) -> None:
        """Cancel all tasks for specific session.

        Used for session-level events such as user stop and session deletion.
        """
        task_ids = list(self._by_session.get(session_id, set()))
        for task_id in task_ids:
            await self.cancel(task_id)

    async def cancel_all(self) -> None:
        """Cancel all tasks. Used on worker shutdown."""
        task_ids = list(self._tasks.keys())
        for task_id in task_ids:
            await self.cancel(task_id)
        await self._drain_completion_tasks()

    async def _drain_completion_tasks(self) -> None:
        """Wait until completion callback tasks finish cleanup."""
        while self._completion_tasks:
            tasks = list(self._completion_tasks)
            for task in tasks:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
