"""Worker event publishing orchestration."""

import dataclasses
import logging
from typing import Annotated

from fastapi import Depends

from azents.broker.broadcast import WebSocketBroadcast
from azents.broker.serialization import serialize_event
from azents.broker.types import PublishedEvent, SessionBroker
from azents.engine.events.types import Event
from azents.repos.session_initialization.data import SessionInitializationEvent
from azents.services.session_initialization import SessionInitializationProjection
from azents.transport.chat import (
    chat_history_event_appended_dump,
    chat_session_initialization_event_appended_dump,
    chat_session_initialization_updated_dump,
)
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

    async def dispatch_initialization_event(
        self,
        event: SessionInitializationEvent,
    ) -> None:
        """Deliver a session initialization event to WebSocket subscribers."""
        try:
            await self.broadcast.publish(
                event.session_id,
                chat_session_initialization_event_appended_dump(event),
            )
        except Exception:
            logger.exception(
                "Failed to broadcast initialization event to WebSocket",
                extra={"session_id": event.session_id},
            )
        await self.broker.renew_session_ttl(event.session_id)

    async def dispatch_initialization_projection(
        self,
        projection: SessionInitializationProjection,
    ) -> None:
        """Deliver a session initialization projection to WebSocket subscribers."""
        session_id = projection.initialization.session_id
        try:
            await self.broadcast.publish(
                session_id,
                chat_session_initialization_updated_dump(projection),
            )
        except Exception:
            logger.exception(
                "Failed to broadcast initialization projection to WebSocket",
                extra={"session_id": session_id},
            )
        await self.broker.renew_session_ttl(session_id)

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
