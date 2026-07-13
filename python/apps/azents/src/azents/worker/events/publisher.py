"""Worker event publishing orchestration."""

import asyncio
import dataclasses
import logging
from typing import Annotated

from fastapi import Depends

from azents.broker.broadcast import WebSocketBroadcast
from azents.broker.serialization import serialize_event
from azents.broker.types import PublishedEvent, SessionBroker
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


@dataclasses.dataclass(frozen=True)
class WorkerEventPublisher:
    """Publish Worker runtime event to live projection and WebSocket."""

    broker: Annotated[SessionBroker, Depends(get_worker_broker)]
    broadcast: Annotated[WebSocketBroadcast, Depends(get_broadcast)]
    live_event_projector: Annotated[LiveEventProjector, Depends(LiveEventProjector)]

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
        if isinstance(event, Event):
            await self._broadcast_history_event(session_id, event)
        elif isinstance(event, PUBLIC_CHAT_CONTROL_EVENT_TYPES):
            await self._broadcast_control_event(session_id, event)
        await self._renew_session_ttl(session_id)
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
        except Exception:
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
