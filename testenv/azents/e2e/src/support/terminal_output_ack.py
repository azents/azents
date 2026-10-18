"""Cumulative Terminal fixture ACKs bounded by the live output window and time."""

from collections.abc import Callable

# Half of the product's 256 KiB unacknowledged-output window.
_ACK_BYTES = 128 * 1024
_ACK_DELAY_SECONDS = 0.05


class TerminalOutputAcknowledgements:
    """Coalesce frame ACKs while keeping small, slow output acknowledged promptly."""

    def __init__(self, sequence: int, clock: Callable[[], float]) -> None:
        self.sequence = sequence
        self.acknowledged_sequence = sequence
        self.pending_bytes = 0
        self.deadline: float | None = None
        self.clock = clock

    def observe(self, sequence: int, size: int) -> int | None:
        assert sequence > self.sequence
        assert size >= 0
        self.sequence = sequence
        self.pending_bytes += size
        if self.deadline is None:
            self.deadline = self.clock() + _ACK_DELAY_SECONDS
        return self.flush() if self.pending_bytes >= _ACK_BYTES else None

    def flush(self) -> int | None:
        if self.sequence == self.acknowledged_sequence:
            return None
        self.acknowledged_sequence = self.sequence
        self.pending_bytes = 0
        self.deadline = None
        return self.sequence
