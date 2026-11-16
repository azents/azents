"""Worker event publishing orchestration."""

import asyncio
import dataclasses
import logging
from typing import Annotated, Protocol

from fastapi import Depends

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

PUBLIC_CHAT_CONTROL_EVENT_TYPES = (
    RuntimeErrorEvent,
    AuthorizationRequestEvent,
    AccountLinkNudgeEvent,
    CompactionStarted,
    CompactionComplete,
    TodoStateChanged,
    SubagentTreeChanged,
)


class SessionTTLRenewer(Protocol):
    """Only session liveness renewal belongs to the publisher's broker boundary."""

    async def renew_session_ttl(self, session_id: str) -> None: ...


class HistoryFramePublisher(Protocol):
    """Publish canonical history without requiring subscription operations."""

    async def publish(self, session_id: str, event: dict[str, object], /) -> None: ...


class EventProjectionPublisher(Protocol):
    """The publisher coordinates projections, not projector storage internals."""

    async def flush_session(
        self, session_id: str, *, owner_generation: int
    ) -> None: ...

    async def update(
        self, session_id: str, event: PublishedEvent, /, *, owner_generation: int
    ) -> None: ...

    async def publish_control_event(
        self,
        session_id: str,
        event: dict[str, object],
        /,
        *,
        owner_generation: int,
    ) -> None: ...


@dataclasses.dataclass(frozen=True)
class WorkerEventPublisher:
    """Publish Worker runtime event to live projection and WebSocket."""

    broker: Annotated[SessionTTLRenewer, Depends(get_worker_broker)]
    broadcast: Annotated[HistoryFramePublisher, Depends(get_broadcast)]
    live_event_projector: Annotated[
        EventProjectionPublisher, Depends(LiveEventProjector)
    ]

    async def dispatch_event(
        self,
        session_id: str,
        event: PublishedEvent,
        *,
        owner_generation: int,
    ) -> None:
        """Project one runtime event and publish its canonical public frame.

        Durable Event history is published first, then matching live state is removed.
        Public control events retain their direct wire contract, while internal runtime
        telemetry is exposed only through canonical live projections.

        :param session_id: Session ID
        :param event: Engine event
        """
        if isinstance(event, Event):
            await self.live_event_projector.flush_session(
                session_id,
                owner_generation=owner_generation,
            )
            await self._broadcast_history_event(session_id, event)
        elif isinstance(event, PUBLIC_CHAT_CONTROL_EVENT_TYPES):
            await self._broadcast_control_event(
                session_id,
                event,
                owner_generation=owner_generation,
            )
        await self._renew_session_ttl(session_id)
        await self.live_event_projector.update(
            session_id,
            event,
            owner_generation=owner_generation,
        )

    async def _broadcast_control_event(
        self,
        session_id: str,
        event: PublicChatControlEvent,
        *,
        owner_generation: int,
    ) -> None:
        """Deliver one canonical public control event best-effort."""
        await self.live_event_projector.publish_control_event(
            session_id,
            serialize_event(event),
            owner_generation=owner_generation,
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
        except Exception:
            logger.exception(
                "Failed to broadcast history event to WebSocket",
                extra={"session_id": session_id},
            )

    async def _renew_session_ttl(self, session_id: str) -> None:
        """Renew ephemeral session metadata best-effort."""
        try:
            await self.broker.renew_session_ttl(session_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Failed to renew session TTL after event dispatch",
                extra={"session_id": session_id},
            )
