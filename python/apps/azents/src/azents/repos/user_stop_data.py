"""Detached inputs and durable event outcomes for User Stop database stages."""

import dataclasses

from azents.engine.events.types import ActiveToolCall, Event


@dataclasses.dataclass(frozen=True)
class UserStopOwnerInput:
    """Current Worker identity required by one separate Stop database action."""

    session_id: str
    owner_generation: int


@dataclasses.dataclass(frozen=True)
class UserStopPartialInput(UserStopOwnerInput):
    """Live event snapshots eligible for idempotent durable partial admission."""

    events: tuple[Event, ...]


@dataclasses.dataclass(frozen=True)
class UserStopCancelledCallsInput(UserStopOwnerInput):
    """Durable running Run and its captured active-call ownership entries."""

    run_id: str | None
    active_tool_calls: tuple[ActiveToolCall, ...]


@dataclasses.dataclass(frozen=True)
class UserStopMarkerInput(UserStopOwnerInput):
    """Explicit Run identity for the atomic interrupted/marker event pair."""

    run_id: str


@dataclasses.dataclass(frozen=True)
class UserStopDurableEvents:
    """Durable transcript events emitted for a completed User stop."""

    interrupted: Event
    run_marker: Event
