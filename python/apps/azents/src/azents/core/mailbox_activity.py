"""Run-scoped mailbox activity capability shared by Engine contexts."""

from typing import Protocol


class MailboxActivityObserverProtocol(Protocol):
    """Observe activity revisions without consuming pending input."""

    def current_revision(self) -> int:
        """Return the latest observed activity revision."""
        ...

    async def wait_after(self, revision: int, timeout_seconds: float) -> bool:
        """Wait for a newer revision through the bounded timeout."""
        ...
