"""Worker event publishing orchestration."""

import dataclasses
import logging
from typing import Annotated

from fastapi import Depends

from azents.broker.broadcast import WebSocketBroadcast
from azents.broker.serialization import serialize_event
from azents.broker.types import PublishedEvent, SessionBroker
from azents.engine.events.types import Event
from azents.transport.chat import chat_history_event_appended_dump
from azents.worker.deps import get_broadcast, get_worker_broker
from azents.worker.live.event_projector import LiveEventProjector

logger = logging.getLogger(__name__)


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
        """Deliver session event to WebSocket subscribers.

        Publish Event broadcast first, then reflect live projection changes.
        For Durable event, history append arrives before live projection removal.

        :param session_id: Session ID
        :param event: Engine event
        """
        await self._broadcast_event(session_id, event)
        await self.live_event_projector.update(session_id, event)

    async def _broadcast_event(
        self,
        session_id: str,
        event: PublishedEvent,
    ) -> None:
        """Deliver Runtime event to WebSocket broadcast."""
        try:
            serialized = serialize_event(event)
            await self.broadcast.publish(session_id, serialized)
            if isinstance(event, Event):
                await self.broadcast.publish(
                    session_id,
                    chat_history_event_appended_dump(event),
                )
        except Exception:
            # broadcast failure only breaks Web UI sync; runtime processing continues.
            # Log with stack trace for production root-cause analysis.
            logger.exception(
                "Failed to broadcast event to WebSocket",
                extra={"session_id": session_id},
            )
        await self.broker.renew_session_ttl(session_id)
