"""Run-scoped mailbox activity observation."""

import asyncio


class MailboxActivityObserver:
    """Monotonic, coalescing activity signal scoped to one Engine Run."""

    def __init__(self) -> None:
        """Initialize an open observer."""
        self._revision = 0
        self._event = asyncio.Event()
        self._closed = False

    def current_revision(self) -> int:
        """Return the latest monotonic activity revision."""
        return self._revision

    def notify(self) -> None:
        """Advance the revision and wake all current waiters."""
        if self._closed:
            return
        self._revision += 1
        self._event.set()

    async def wait_after(self, revision: int, timeout_seconds: float) -> bool:
        """Wait for activity newer than ``revision`` or observer closure."""
        if self._revision > revision or self._closed:
            return True
        self._event.clear()
        if self._revision > revision or self._closed:
            return True
        try:
            await asyncio.wait_for(self._event.wait(), timeout_seconds)
        except TimeoutError:
            return False
        return self._revision > revision or self._closed

    def close(self) -> None:
        """Close the observer and settle waiting tools."""
        if self._closed:
            return
        self._closed = True
        self._revision += 1
        self._event.set()
