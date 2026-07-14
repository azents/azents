"""Worker event publishing orchestration."""

import asyncio
import dataclasses
import logging
from typing import Annotated, Protocol

from fastapi import Depends

from azents.broker.broadcast import WebSocketBroadcastPublishError
from azents.broker.serialization import serialize_event
from azents.broker.types import PublishedEvent
from azents.engine.events.engine_events import (
    AccountLinkNudgeEvent,
    AuthorizationRequestEvent,
    CompactionComplete,
    CompactionStarted,
    RuntimeErrorEvent,
    SubagentTreeChanged,
    TodoStateChanged,
)
from azents.engine.events.types import Event
from azents.transport.chat import (
    chat_history_event_appended_dump,
)
from azents.worker.deps import get_broadcast, get_worker_broker
from azents.worker.live.event_projector import LiveEventProjector

logger = logging.getLogger(__name__)


type PublicChatControlEvent = (
    RuntimeErrorEvent
    | AuthorizationRequestEvent
    | AccountLinkNudgeEvent
    | CompactionStarted
    | CompactionComplete
    | TodoStateChanged
    | SubagentTreeChanged
)

OWNER_SCOPED_PUBLIC_CHAT_CONTROL_EVENT_TYPES = (
    RuntimeErrorEvent,
    AuthorizationRequestEvent,
    AccountLinkNudgeEvent,
    CompactionStarted,
    CompactionComplete,
    TodoStateChanged,
)


class _SessionLeaseBroker(Protocol):
    """Broker capability required by event publication."""

    async def renew_session_ttl(self, session_id: str) -> None:
        """Validate and renew Session ownership."""
        ...


class _EventBroadcast(Protocol):
    """WebSocket broadcast capability required by event publication."""

    async def publish(
        self,
        session_id: str,
        event_json: dict[str, object],
        /,
    ) -> None:
        """Publish one public frame."""
        ...


class _LiveEventProjection(Protocol):
    """Live projection capability required by event publication."""

    async def flush_session(self, session_id: str) -> None:
        """Flush pending partial events for one Session."""
        ...

    async def update(self, session_id: str, event: PublishedEvent) -> None:
        """Apply one event to the live projection."""
        ...


@dataclasses.dataclass(frozen=True)
class WorkerEventPublisher:
    """Publish Worker runtime event to live projection and WebSocket."""

    broker: Annotated[_SessionLeaseBroker, Depends(get_worker_broker)]
    broadcast: Annotated[_EventBroadcast, Depends(get_broadcast)]
    live_event_projector: Annotated[
        _LiveEventProjection,
        Depends(LiveEventProjector),
    ]

    async def dispatch_event(
        self,
        session_id: str,
        event: PublishedEvent,
    ) -> None:
        """Project one runtime event and publish its canonical public frame.

        Durable Event history is published first, then matching live state is removed.
        Public control events retain their direct wire contract, while internal runtime
        telemetry is exposed only through canonical live projections.

        :param session_id: Session ID
        :param event: Engine event
        """
        if isinstance(event, SubagentTreeChanged):
            # This invalidation is intentionally fanned out to participant Sessions
            # that the current worker does not own. It carries no projection state;
            # recipients refetch the authoritative tree.
            await self._broadcast_control_event(session_id, event)
            return

        # Ownership must be checked before flushing, broadcasting, or mutating live
        # state. A stale worker must not publish into a newer owner's projection.
        await self._renew_session_ttl(session_id)
        if isinstance(event, Event):
            await self.live_event_projector.flush_session(session_id)
            await self._broadcast_history_event(session_id, event)
        elif isinstance(event, OWNER_SCOPED_PUBLIC_CHAT_CONTROL_EVENT_TYPES):
            await self._broadcast_control_event(session_id, event)
        await self.live_event_projector.update(session_id, event)

    async def _broadcast_control_event(
        self,
        session_id: str,
        event: PublicChatControlEvent,
    ) -> None:
        """Deliver one canonical public control event best-effort."""
        try:
            await self.broadcast.publish(session_id, serialize_event(event))
        except asyncio.CancelledError:
            raise
        except WebSocketBroadcastPublishError:
            logger.exception(
                "Failed to broadcast control event to WebSocket",
                extra={"session_id": session_id},
            )

    async def _broadcast_history_event(
        self,
        session_id: str,
        event: Event,
    ) -> None:
        """Deliver one canonical durable-history action best-effort."""
        try:
            await self.broadcast.publish(
                session_id,
                chat_history_event_appended_dump(event),
            )
        except asyncio.CancelledError:
            raise
        except WebSocketBroadcastPublishError:
            logger.exception(
                "Failed to broadcast history event to WebSocket",
                extra={"session_id": session_id},
            )

    async def _renew_session_ttl(self, session_id: str) -> None:
        """Validate ownership before any owner-scoped projection side effect."""
        # RedisBroker treats activity TTL refreshes as best-effort after its
        # compare-and-renew succeeds. Any exception reaching this boundary means
        # ownership could not be verified, so dispatch must fail closed.
        await self.broker.renew_session_ttl(session_id)
