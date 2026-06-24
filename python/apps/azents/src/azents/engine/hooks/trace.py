"""runtime hook trace event and sink implementations."""

import dataclasses
from typing import Protocol

from azents.engine.hooks.types import HookTraceStatus, RuntimeHookName


@dataclasses.dataclass(frozen=True)
class RuntimeHookTraceEvent:
    """Hook dispatch trace event excluding raw payload."""

    provider_slug: str
    lifecycle: RuntimeHookName
    status: HookTraceStatus
    result_kind: str | None
    exception_class: str | None
    duration_ms: float | None
    short_circuit: bool
    cancelled: bool
    reason: str | None


class RuntimeHookTraceSink(Protocol):
    """Hook trace event storage protocol."""

    async def record(self, event: RuntimeHookTraceEvent) -> None:
        """Record trace event."""


class NoopRuntimeHookTraceSink:
    """Default sink that discards trace events."""

    async def record(self, event: RuntimeHookTraceEvent) -> None:
        """Do nothing."""


class InMemoryRuntimeHookTraceSink:
    """In-memory sink for verifying dispatch trace in tests."""

    def __init__(self) -> None:
        self.events: list[RuntimeHookTraceEvent] = []

    async def record(self, event: RuntimeHookTraceEvent) -> None:
        """Store events in order."""
        self.events.append(event)

    def by_lifecycle(self, lifecycle: RuntimeHookName) -> list[RuntimeHookTraceEvent]:
        """Return only events for specific lifecycle."""
        return [event for event in self.events if event.lifecycle == lifecycle]

    def contains_marker(self, marker: str) -> bool:
        """Check whether trace event string representation contains marker."""
        return any(marker in repr(event) for event in self.events)
