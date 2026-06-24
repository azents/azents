"""SessionRunner idle waiting and owner heartbeat timing."""

import asyncio
import contextlib
import dataclasses

from azents.broker.types import BrokerMessage
from azents.worker.session.inbox import SessionRunnerInbox

_IDLE_TIMEOUT = (
    30 * 60.0
)  # seconds — default idle window for session owner sticky lease
_OWNER_HEARTBEAT_INTERVAL = 30.0  # seconds — idle owner heartbeat interval


@dataclasses.dataclass(frozen=True)
class MessageResult:
    message: BrokerMessage


@dataclasses.dataclass(frozen=True)
class ShutdownResult:
    pass


@dataclasses.dataclass(frozen=True)
class HeartbeatResult:
    pass


@dataclasses.dataclass(frozen=True)
class IdleTimeoutResult:
    pass


RunnerWaitResult = MessageResult | ShutdownResult | HeartbeatResult | IdleTimeoutResult


class SessionRunnerWaiter:
    """Provide queue/shutdown/idle timeout waiting as one state machine."""

    async def wait_next(
        self,
        *,
        inbox: SessionRunnerInbox,
        runner_shutdown: asyncio.Event,
        current_session_id: str | None,
        idle_started_at: float,
    ) -> RunnerWaitResult:
        """Wait for next runner action."""
        get_task = asyncio.ensure_future(inbox.get())
        shutdown_task = asyncio.ensure_future(runner_shutdown.wait())
        wait_timeout = self._wait_timeout(
            current_session_id=current_session_id,
            idle_started_at=idle_started_at,
        )
        done, pending = await asyncio.wait(
            [get_task, shutdown_task],
            timeout=wait_timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        for task in pending:
            with contextlib.suppress(asyncio.CancelledError):
                await task

        if not done:
            if self._should_heartbeat(
                current_session_id=current_session_id,
                idle_started_at=idle_started_at,
            ):
                return HeartbeatResult()
            return IdleTimeoutResult()

        if shutdown_task in done and get_task not in done:
            return ShutdownResult()

        return MessageResult(message=get_task.result())

    def _wait_timeout(
        self,
        *,
        current_session_id: str | None,
        idle_started_at: float,
    ) -> float:
        """Return wait timeout matching current idle state."""
        if current_session_id is None:
            return _IDLE_TIMEOUT
        now = asyncio.get_running_loop().time()
        idle_remaining = _IDLE_TIMEOUT - (now - idle_started_at)
        return max(0.0, min(_OWNER_HEARTBEAT_INTERVAL, idle_remaining))

    def _should_heartbeat(
        self,
        *,
        current_session_id: str | None,
        idle_started_at: float,
    ) -> bool:
        """Return whether only owner heartbeat should refresh before idle timeout."""
        if current_session_id is None:
            return False
        return asyncio.get_running_loop().time() - idle_started_at < _IDLE_TIMEOUT
