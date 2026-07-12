"""Web chat live event projection management."""

import logging
from typing import Annotated

from fastapi import Depends

from azents.broker.broadcast import WebSocketBroadcast
from azents.broker.types import PublishedEvent
from azents.engine.events.engine_events import (
    ContentDelta,
    ReasoningDelta,
    RunComplete,
    RunStarted,
    RunStopped,
)
from azents.engine.events.types import ActiveToolCall, Event
from azents.services.chat.data import ChatLiveRunState
from azents.services.chat.live_events import (
    RedisLiveEventStore,
    active_tool_call_to_live_event,
)
from azents.transport.chat import (
    chat_live_event_removed_dump,
    chat_live_event_upserted_dump,
    chat_live_run_cleared_dump,
    chat_live_run_updated_dump,
)
from azents.worker.deps import get_broadcast, get_live_event_store
from azents.worker.live.partial_batcher import LivePartialBatcher, LivePartialFlush

logger = logging.getLogger(__name__)


class LiveEventProjector:
    """Reflect Runtime event into Web chat live projection."""

    def __init__(
        self,
        *,
        live_event_store: Annotated[RedisLiveEventStore, Depends(get_live_event_store)],
        broadcast: Annotated[WebSocketBroadcast, Depends(get_broadcast)],
    ) -> None:
        self._live_event_store = live_event_store
        self._broadcast = broadcast
        self._partial_batcher = LivePartialBatcher(self._flush_partial_batch)
        self._active_run_ids: dict[str, str] = {}
        self._active_tool_events: dict[str, dict[str, Event]] = {}

    async def flush_session(self, session_id: str) -> None:
        """Reflect pending live partial batch of session to store and WebSocket."""
        await self._partial_batcher.flush_session(session_id)

    async def update(
        self,
        session_id: str,
        event: PublishedEvent,
    ) -> None:
        """Reflect Runtime event to live projection store best-effort."""
        try:
            match event:
                case Event() | RunComplete() | RunStopped():
                    await self.flush_session(session_id)
                case _:
                    pass

            match event:
                case RunStarted(run_id=run_id):
                    await self.clear_session(session_id)
                    self._active_run_ids[session_id] = run_id
                case ContentDelta(delta=delta, content_index=content_index):
                    await self._partial_batcher.append_content_delta(
                        session_id=session_id,
                        delta=delta,
                        content_index=content_index,
                    )
                case ReasoningDelta(delta=delta):
                    await self._partial_batcher.append_reasoning_delta(
                        session_id=session_id,
                        delta=delta,
                    )
                case Event():
                    before = await self._live_event_store.list_by_session_id(session_id)
                    await self._live_event_store.remove_live_counterpart(event)
                    after = await self._live_event_store.list_by_session_id(session_id)
                    await self._publish_removed_events(
                        session_id,
                        before=before,
                        after=after,
                    )
                case RunComplete(run_id=run_id) | RunStopped(run_id=run_id):
                    active_run_id = self._active_run_ids.get(session_id)
                    if active_run_id is None or active_run_id == run_id:
                        await self.clear_session(session_id)
                        self._active_run_ids.pop(session_id, None)
                case _:
                    pass
        except Exception:
            logger.exception(
                "Failed to update event live event projection",
                extra={"session_id": session_id},
            )

    async def replace_active_tool_calls(
        self,
        session_id: str,
        active_tool_calls: list[ActiveToolCall],
    ) -> None:
        """Broadcast the PostgreSQL-backed active-call projection best-effort."""
        try:
            before = self._active_tool_events.get(session_id, {})
            after = {
                event.id: event
                for event in (
                    active_tool_call_to_live_event(session_id, active)
                    for active in active_tool_calls
                )
            }
            for event_id in before.keys() - after.keys():
                await self._publish_event_removed(session_id, event_id)
            for event_id, event in after.items():
                if before.get(event_id) != event:
                    await self._publish_event_upserted(event)
            if after:
                self._active_tool_events[session_id] = after
            else:
                self._active_tool_events.pop(session_id, None)
        except Exception:
            logger.exception(
                "Failed to broadcast live active tool calls",
                extra={"session_id": session_id},
            )

    async def clear_session(self, session_id: str) -> None:
        """Clear streaming and active live projections and broadcast removals."""
        events = await self._live_event_store.list_by_session_id(session_id)
        active_events = self._active_tool_events.pop(session_id, {})
        await self._live_event_store.clear_session(session_id)
        event_ids = {event.id for event in events} | set(active_events)
        for event_id in event_ids:
            await self._publish_event_removed(session_id, event_id)

    async def publish_live_run_updated(
        self,
        session_id: str,
        run: ChatLiveRunState,
    ) -> None:
        """Broadcast current live run state."""
        self._active_run_ids[session_id] = run.run_id
        await self._broadcast.publish(
            session_id, chat_live_run_updated_dump(session_id, run)
        )

    async def publish_live_run_cleared(
        self,
        session_id: str,
        *,
        run_id: str,
    ) -> None:
        """Broadcast live run state removal."""
        active_run_id = self._active_run_ids.get(session_id)
        if active_run_id is not None and active_run_id != run_id:
            return
        self._active_run_ids.pop(session_id, None)
        await self._broadcast.publish(
            session_id,
            chat_live_run_cleared_dump(session_id, run_id),
        )

    async def remove_event(self, session_id: str, event_id: str) -> None:
        """Remove event from streaming or active projection and broadcast removal."""
        await self._live_event_store.remove(session_id, event_id)
        active = self._active_tool_events.get(session_id)
        if active is not None:
            active.pop(event_id, None)
            if not active:
                self._active_tool_events.pop(session_id, None)
        await self._publish_event_removed(session_id, event_id)

    async def _flush_partial_batch(self, batch: LivePartialFlush) -> None:
        """Reflect batched live partial delta to store and broadcast."""
        if batch.kind == "content":
            if batch.content_index is None:
                return
            live_event = await self._live_event_store.append_assistant_delta(
                batch.session_id,
                delta=batch.delta,
                content_index=batch.content_index,
            )
        else:
            live_event = await self._live_event_store.append_reasoning_delta(
                batch.session_id,
                delta=batch.delta,
            )
        await self._publish_event_upserted(live_event)

    async def _publish_removed_events(
        self,
        session_id: str,
        *,
        before: list[Event],
        after: list[Event],
    ) -> None:
        """Broadcast live event removal action removed from Store diff."""
        after_ids = {event.id for event in after}
        for event in before:
            if event.id not in after_ids:
                await self._publish_event_removed(session_id, event.id)

    async def _publish_event_upserted(self, event: Event) -> None:
        """Deliver Live event upsert action to WebSocket broadcast."""
        await self._broadcast.publish(
            event.session_id,
            chat_live_event_upserted_dump(event),
        )

    async def _publish_event_removed(
        self,
        session_id: str,
        event_id: str,
    ) -> None:
        """Deliver Live event removal action to WebSocket broadcast."""
        await self._broadcast.publish(
            session_id,
            chat_live_event_removed_dump(session_id, event_id),
        )
