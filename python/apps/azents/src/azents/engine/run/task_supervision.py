"""Common task stop and shutdown ordering with domain-owned durable finalization."""

import asyncio
import contextlib
import dataclasses
import logging
from collections.abc import Awaitable, Callable

from azcommon.logging import bind_extra

logger = logging.getLogger(__name__)

SHUTDOWN_COMPLETION_TIMEOUT = 30.0
EXPLICIT_STOP_POLL_INTERVAL = 0.5
SESSION_OWNER_HEARTBEAT_INTERVAL = 30.0


@dataclasses.dataclass(frozen=True)
class ExecutionTaskSupervision[TResult]:
    """Supervise one admitted task without assuming public Conversation state."""

    session_id: str
    shutdown_event: asyncio.Event
    wait_for_explicit_stop: Callable[[], Awaitable[None]]
    finalize_explicit_stop: Callable[[], Awaitable[None]]
    user_stop_requested: Callable[[], bool]
    request_handover_stop: Callable[[], None]
    close_tool_admission: Callable[[], Awaitable[None]]
    cancelled_result: Callable[[bool], TResult]
    shutdown_timeout: float
    user_stop_cancel_message: str
    shutdown_cancel_message: str

    async def run(self, task: asyncio.Task[TResult]) -> TResult:
        """Preserve common cancellation ordering while the host owns settlement."""
        if self.shutdown_event.is_set():
            self.request_handover_stop()
            await self.close_tool_admission()
            return await self._wait_for_shutdown_completion(task)

        async def wait_for_stop() -> None:
            await self.wait_for_explicit_stop()

        explicit_stop = asyncio.create_task(wait_for_stop())
        shutdown = asyncio.create_task(self.shutdown_event.wait())
        try:
            done, _ = await asyncio.wait(
                [task, explicit_stop, shutdown],
                return_when=asyncio.FIRST_COMPLETED,
            )
            if task in done:
                if task.cancelled() and self.user_stop_requested():
                    await self.finalize_explicit_stop()
                    return self.cancelled_result(True)
                return task.result()
            if explicit_stop in done:
                bind_extra(logger, {"session_id": self.session_id}).info(
                    "Explicit stop detected during engine run, canceling"
                )
                await self.finalize_explicit_stop()
                return await self._cancel_now(task)
            self.request_handover_stop()
            await self.close_tool_admission()
            bind_extra(logger, {"session_id": self.session_id}).info(
                "Shutdown detected during engine run, applying timeout",
                extra={"timeout": self.shutdown_timeout},
            )
            return await self._wait_for_shutdown_completion(task)
        finally:
            for waiter in (explicit_stop, shutdown):
                if not waiter.done():
                    waiter.cancel()
            for waiter in (explicit_stop, shutdown):
                with contextlib.suppress(asyncio.CancelledError):
                    await waiter

    async def _cancel_now(self, task: asyncio.Task[TResult]) -> TResult:
        """Wait for cancellation settlement before returning terminal disposition."""
        if not task.done() and task.cancelling() == 0:
            task.cancel(self.user_stop_cancel_message)
        try:
            await task
        except asyncio.CancelledError:
            pass
        return self.cancelled_result(True)

    async def _wait_for_shutdown_completion(
        self, task: asyncio.Task[TResult]
    ) -> TResult:
        """Give every domain the same graceful completion and handover ordering."""
        try:
            return await asyncio.wait_for(
                asyncio.shield(task), timeout=self.shutdown_timeout
            )
        except TimeoutError:
            logger.warning(
                "Engine task timed out after shutdown, canceling",
                extra={
                    "session_id": self.session_id,
                    "timeout": self.shutdown_timeout,
                },
            )
            task.cancel(self.shutdown_cancel_message)
            try:
                await task
            except asyncio.CancelledError:
                pass
            return self.cancelled_result(False)
