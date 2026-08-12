"""Run-scoped boundary for registered TurnAction bridge admissions."""

import dataclasses


@dataclasses.dataclass(frozen=True)
class TurnActionBridgeObservation:
    """One consumed snapshot of admitted bridge client-tool calls."""

    revision: int
    call_ids: frozenset[str]


class TurnActionBridgeBoundary:
    """Latch registered bridge admissions until the Engine observes the batch."""

    def __init__(self) -> None:
        """Create an empty Run-scoped bridge boundary."""
        self._revision = 0
        self._consumed_revision = 0
        self._call_ids: set[str] = set()

    def mark_admitted(self, call_id: str) -> None:
        """Record one durably admitted registered bridge call."""
        if not call_id:
            raise ValueError("Bridge client tool call ID is required")
        if call_id in self._call_ids:
            return
        self._call_ids.add(call_id)
        self._revision += 1

    def consume(self) -> TurnActionBridgeObservation | None:
        """Consume one revision snapshot after a foreground tool batch."""
        if self._revision == self._consumed_revision:
            return None
        self._consumed_revision = self._revision
        observation = TurnActionBridgeObservation(
            revision=self._revision,
            call_ids=frozenset(self._call_ids),
        )
        self._call_ids.clear()
        return observation
