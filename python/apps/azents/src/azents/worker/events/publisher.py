"""Worker event publishing orchestration."""

import asyncio
import dataclasses
import logging
from typing import Annotated

from fastapi import Depends

from azents.broker.broadcast import WebSocketBroadcast
from azents.broker.serialization import serialize_event
from azents.broker.types import PublishedEvent, SessionBroker
from azents.engine.events.types import Event
from azents.transport.chat import (
    chat_history_event_appended_dump,
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
        if isinstance(event, Event):
            await self.live_event_projector.flush_session(session_id)
        await self._broadcast_event(session_id, event)
        await self.live_event_projector.update(session_id, event)

    async def _broadcast_event(
        self,
        session_id: str,
        event: PublishedEvent,
    ) -> None:
        """Deliver Runtime event to WebSocket broadcast best-effort."""
        try:
            if isinstance(event, Event):
                await self.broadcast.publish(
                    session_id,
                    chat_history_event_appended_dump(event),
                )
            else:
                await self.broadcast.publish(session_id, serialize_event(event))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Failed to broadcast event to WebSocket",
                extra={"session_id": session_id},
            )
        try:
            await self.broker.renew_session_ttl(session_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Failed to renew session TTL after event publication",
                extra={"session_id": session_id},
            )
