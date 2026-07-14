"""Session Runner waiter tests."""

import asyncio
from typing import cast

import pytest

from azents.broker.types import SessionWakeUp
from azents.worker.session.inbox import SessionRunnerInbox, StopSignalController
from azents.worker.session.waiter import SessionRunnerWaiter


class _StopController:
    """No-op stop controller for inbox tests."""

    @property
    def user_stop_requested(self) -> bool:
        """Return that no stop has been requested."""
        return False

    def request_user_stop(self) -> bool:
        """Record no stop request."""
        return False

    def notify_stop_signal(self) -> None:
        """Ignore stop-signal notification."""


@pytest.mark.asyncio
async def test_cancelled_waiter_cannot_consume_a_later_message() -> None:
    """Waiter cancellation drains its child queue-get task before returning."""
    inbox = SessionRunnerInbox()
    waiter = SessionRunnerWaiter()
    waiting = asyncio.create_task(
        waiter.wait_next(
            inbox=inbox,
            runner_shutdown=asyncio.Event(),
            running_session_id=None,
            idle_started_at=asyncio.get_running_loop().time(),
        )
    )
    await asyncio.sleep(0)

    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting

    message = SessionWakeUp(
        agent_id="agent-1",
        session_id="session-1",
        user_id="user-1",
        additional_system_prompt=None,
        interface=None,
        workspace_id="workspace-1",
        workspace_handle=None,
    )
    inbox.enqueue(
        message,
        stop_controller=cast(StopSignalController, _StopController()),
    )
    await asyncio.sleep(0)

    assert inbox.drain() == [message]
