"""SessionRunner input queue management."""

import asyncio
import dataclasses
from typing import Protocol

from azents.broker.types import BrokerMessage, SessionStopSignal, SessionWakeUp


class StopSignalController(Protocol):
    """Controller contract that can reflect Stop signal."""

    @property
    def user_stop_requested(self) -> bool:
        """Return whether a User stop is already being handled."""
        ...

    def request_user_stop(self) -> bool:
        """Record User stop and cancel active task when present."""
        ...

    def notify_stop_signal(self) -> None:
        """Wake durable stop-intent validation without authorizing cancellation."""
        ...


class SessionRunnerInbox:
    """Encapsulate SessionRunner input queue and stop signal drain."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue[BrokerMessage] = asyncio.Queue()

    def enqueue(
        self,
        message: BrokerMessage,
        *,
        stop_controller: StopSignalController,
    ) -> None:
        """Put Broker message into the queue.

        Stop signals are only wake-up hints. The runner validates the durable stop
        intent before canceling so a delayed broker delivery cannot stop a later run.
        """
        if isinstance(message, SessionStopSignal):
            stop_controller.notify_stop_signal()
            self.queue.put_nowait(message)
            return
        self.queue.put_nowait(message)

    def requeue_wake_up(self, message: SessionWakeUp) -> None:
        """Clone same wake-up envelope and put it back at queue tail."""
        self.queue.put_nowait(dataclasses.replace(message))

    async def get(self) -> BrokerMessage:
        """Wait for next broker message."""
        return await self.queue.get()

    def empty(self) -> bool:
        """Return whether queue is empty."""
        return self.queue.empty()

    def qsize(self) -> int:
        """Return current queue length."""
        return self.queue.qsize()

    def drain(self) -> list[BrokerMessage]:
        """Remove and return every queued message in FIFO order."""
        messages: list[BrokerMessage] = []
        while True:
            try:
                messages.append(self.queue.get_nowait())
            except asyncio.QueueEmpty:
                return messages

    def drain_stop_signals(self, stop_controller: StopSignalController) -> None:
        """Drain stop requests accumulated in queue and preserve remaining messages."""
        preserved: list[BrokerMessage] = []
        while not self.queue.empty():
            try:
                message = self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if isinstance(message, SessionStopSignal):
                # A signal is not authority to cancel. The caller checks the
                # committed stop intent immediately after draining it.
                stop_controller.notify_stop_signal()
                continue
            else:
                preserved.append(message)
        for message in preserved:
            self.queue.put_nowait(message)

    def has_wake_up_queued(self, session_id: str) -> bool:
        """Check whether queue already has wake-up for same session."""
        found = False
        preserved: list[BrokerMessage] = []
        while not self.queue.empty():
            try:
                message = self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if isinstance(message, SessionWakeUp) and message.session_id == session_id:
                found = True
            preserved.append(message)
        for message in preserved:
            self.queue.put_nowait(message)
        return found

    def discard_wake_ups(self, session_id: str) -> int:
        """Remove remaining wake-ups for same session from queue and return count."""
        discarded = 0
        preserved: list[BrokerMessage] = []
        while not self.queue.empty():
            try:
                message = self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if isinstance(message, SessionWakeUp) and message.session_id == session_id:
                discarded += 1
                continue
            preserved.append(message)
        for message in preserved:
            self.queue.put_nowait(message)
        return discarded
