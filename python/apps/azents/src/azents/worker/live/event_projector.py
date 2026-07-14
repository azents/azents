"""Web chat live event projection management."""

import asyncio
import dataclasses
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Annotated

from fastapi import Depends
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

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
from azents.rdb.deps import get_session_manager
from azents.repos.agent_execution import AgentRunRepository
from azents.services.chat.data import ChatLiveRunState
from azents.services.chat.live_events import (
    RedisLiveEventStore,
    active_tool_call_live_event_id,
    active_tool_call_to_live_event,
)
from azents.transport.chat import (
    chat_live_event_removed_dump,
    chat_live_event_upserted_dump,
    chat_live_run_cleared_dump,
    chat_live_run_updated_dump,
)
from azents.worker.deps import get_broadcast, get_live_event_store
from azents.worker.live.partial_batcher import (
    LivePartialBatcher,
    LivePartialFlush,
    LivePartialFlushAttemptedError,
    LivePartialFlushCommittedCancellation,
)

logger = logging.getLogger(__name__)

SessionManagerFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
_CLEARED_RUN_DEDUPE_LIMIT = 4096


@dataclasses.dataclass
class _SessionRunProjectionState:
    """Serialize one Session's live Run projection mutations."""

    lock: asyncio.Lock = dataclasses.field(default_factory=asyncio.Lock)
    users: int = 0


class LiveEventProjector:
    """Reflect Runtime event into Web chat live projection."""

    def __init__(
        self,
        *,
        live_event_store: Annotated[RedisLiveEventStore, Depends(get_live_event_store)],
        broadcast: Annotated[WebSocketBroadcast, Depends(get_broadcast)],
        session_manager: Annotated[SessionManagerFactory, Depends(get_session_manager)],
        agent_run_repository: Annotated[
            AgentRunRepository, Depends(AgentRunRepository)
        ],
    ) -> None:
        self._live_event_store = live_event_store
        self._broadcast = broadcast
        self._session_manager = session_manager
        self._agent_run_repository = agent_run_repository
        self._partial_batcher = LivePartialBatcher(self._flush_partial_batch)
        self._active_run_ids: dict[str, str] = {}
        self._cleared_run_ids: dict[str, str] = {}
        self._active_tool_events: dict[str, dict[str, Event]] = {}
        self._run_projection_states: dict[str, _SessionRunProjectionState] = {}

    @asynccontextmanager
    async def _serialize_run_projection(
        self,
        session_id: str,
    ) -> AsyncIterator[None]:
        """Serialize Run projection writers without retaining idle lock entries."""
        state = self._run_projection_states.get(session_id)
        if state is None:
            state = _SessionRunProjectionState()
            self._run_projection_states[session_id] = state
        state.users += 1
        try:
            async with state.lock:
                yield
        finally:
            state.users -= 1
            if (
                state.users == 0
                and self._run_projection_states.get(session_id) is state
            ):
                self._run_projection_states.pop(session_id, None)

    async def flush_session(self, session_id: str) -> None:
        """Reflect pending live partial batches best-effort."""
        try:
            await self._partial_batcher.flush_session(session_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Failed to flush session live partial batches",
                extra={"session_id": session_id},
            )

    async def _run_matches_current_authority(
        self,
        session_id: str,
        run_id: str,
    ) -> bool:
        """Validate one projection mutation against the durable latest Run."""
        active_run_id = self._active_run_ids.get(session_id)
        if active_run_id is not None and active_run_id != run_id:
            return False
        async with self._session_manager() as session:
            latest_by_session_id = (
                await self._agent_run_repository.list_latest_by_session_ids(
                    session,
                    session_ids=[session_id],
                )
            )
        latest = latest_by_session_id.get(session_id)
        return latest is None or latest.id == run_id

    async def _run_is_durable_active(
        self,
        session_id: str,
        run_id: str,
    ) -> bool:
        """Return whether PostgreSQL still names this Run as active."""
        async with self._session_manager() as session:
            active = await self._agent_run_repository.get_active_by_session_id(
                session,
                session_id=session_id,
            )
        return active is not None and active.id == run_id

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
                    # Reject a delayed start before it can discard a newer Run's
                    # pending partials. The second check closes the ownership race
                    # while waiting for the Session projection writer lock.
                    if not await self._run_is_durable_active(session_id, run_id):
                        return
                    async with self._serialize_run_projection(session_id):
                        if not await self._run_is_durable_active(session_id, run_id):
                            return
                        await self._partial_batcher.discard_session(session_id)
                        await self._clear_session_unlocked(session_id)
                        self._active_run_ids[session_id] = run_id
                        self._cleared_run_ids.pop(session_id, None)
                case ContentDelta(
                    run_id=run_id,
                    delta=delta,
                    content_index=content_index,
                ):
                    async with self._serialize_run_projection(session_id):
                        if self._active_run_ids.get(session_id) != run_id:
                            return
                        should_flush = await self._partial_batcher.buffer_content_delta(
                            session_id=session_id,
                            run_id=run_id,
                            delta=delta,
                            content_index=content_index,
                        )
                    if should_flush:
                        await self.flush_session(session_id)
                case ReasoningDelta(run_id=run_id, delta=delta):
                    async with self._serialize_run_projection(session_id):
                        if self._active_run_ids.get(session_id) != run_id:
                            return
                        should_flush = (
                            await self._partial_batcher.buffer_reasoning_delta(
                                session_id=session_id,
                                run_id=run_id,
                                delta=delta,
                            )
                        )
                    if should_flush:
                        await self.flush_session(session_id)
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
                    async with self._serialize_run_projection(session_id):
                        if await self._run_matches_current_authority(
                            session_id, run_id
                        ):
                            await self._clear_session_unlocked(session_id)
                            if self._active_run_ids.get(session_id) == run_id:
                                self._active_run_ids.pop(session_id, None)
                case _:
                    pass
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Failed to update live event projection",
                extra={"session_id": session_id},
            )

    async def replace_active_tool_calls(
        self,
        session_id: str,
        active_tool_calls: list[ActiveToolCall],
        *,
        run_id: str,
        removed_call_ids: set[str],
    ) -> None:
        """Broadcast the PostgreSQL-backed active-call projection best-effort."""
        try:

            async def has_authority() -> bool:
                if active_tool_calls:
                    return await self._run_is_durable_active(session_id, run_id)
                return await self._run_matches_current_authority(
                    session_id,
                    run_id,
                )

            if not await has_authority():
                return
            async with self._serialize_run_projection(session_id):
                if not await has_authority():
                    return
                active_run_id = self._active_run_ids.get(session_id)
                if active_run_id is not None and active_run_id != run_id:
                    return
                before = self._active_tool_events.get(session_id, {})
                after = {
                    event.id: event
                    for event in (
                        active_tool_call_to_live_event(session_id, active)
                        for active in active_tool_calls
                    )
                }
                removed_event_ids = before.keys() - after.keys()
                removed_event_ids |= {
                    active_tool_call_live_event_id(session_id, call_id)
                    for call_id in removed_call_ids
                }
                for event_id in removed_event_ids:
                    await self._publish_event_removed(session_id, event_id)
                for event_id, event in after.items():
                    if before.get(event_id) != event:
                        await self._publish_event_upserted(event)
                if after:
                    self._active_tool_events[session_id] = after
                else:
                    self._active_tool_events.pop(session_id, None)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Failed to broadcast live active tool calls",
                extra={"session_id": session_id},
            )

    async def clear_session(self, session_id: str) -> None:
        """Clear streaming and active live projections and broadcast removals."""
        async with self._serialize_run_projection(session_id):
            await self._clear_session_unlocked(session_id)

    async def clear_session_if_no_active_run(self, session_id: str) -> bool:
        """Clear orphan projections only while no durable Run is active."""
        async with self._serialize_run_projection(session_id):
            async with self._session_manager() as session:
                active = await self._agent_run_repository.get_active_by_session_id(
                    session,
                    session_id=session_id,
                )
            if active is not None:
                return False
            await self._clear_session_unlocked(session_id)
            self._active_run_ids.pop(session_id, None)
            return True

    async def _clear_session_unlocked(self, session_id: str) -> None:
        """Clear one Session while its Run projection writer is serialized."""
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
        """Broadcast current live run state best-effort."""
        try:
            if not await self._run_is_durable_active(session_id, run.run_id):
                return
            async with self._serialize_run_projection(session_id):
                if not await self._run_is_durable_active(
                    session_id,
                    run.run_id,
                ):
                    return
                self._active_run_ids[session_id] = run.run_id
                self._cleared_run_ids.pop(session_id, None)
                await self._broadcast.publish(
                    session_id, chat_live_run_updated_dump(session_id, run)
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Failed to broadcast live run update",
                extra={"session_id": session_id, "run_id": run.run_id},
            )

    async def publish_live_run_cleared(
        self,
        session_id: str,
        *,
        run_id: str,
    ) -> None:
        """Broadcast live run state removal best-effort."""
        try:
            # Durable correlation can yield while a newer Run update arrives. Do a
            # cheap serialized pre-check, then revalidate local authority after the
            # DB session has closed before mutating or publishing anything.
            async with self._serialize_run_projection(session_id):
                if self._cleared_run_ids.get(session_id) == run_id:
                    return
                active_run_id = self._active_run_ids.get(session_id)
                if active_run_id is not None and active_run_id != run_id:
                    return
            if not await self._run_matches_current_authority(session_id, run_id):
                return
            async with self._serialize_run_projection(session_id):
                if self._cleared_run_ids.get(session_id) == run_id:
                    return
                active_run_id = self._active_run_ids.get(session_id)
                if active_run_id is not None and active_run_id != run_id:
                    return
                if active_run_id == run_id:
                    self._active_run_ids.pop(session_id, None)
                await self._broadcast.publish(
                    session_id,
                    chat_live_run_cleared_dump(session_id, run_id),
                )
                self._cleared_run_ids[session_id] = run_id
                if len(self._cleared_run_ids) > _CLEARED_RUN_DEDUPE_LIMIT:
                    oldest_session_id = next(iter(self._cleared_run_ids))
                    self._cleared_run_ids.pop(oldest_session_id, None)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Failed to broadcast live run removal",
                extra={"session_id": session_id, "run_id": run_id},
            )

    async def remove_event(
        self,
        session_id: str,
        event_id: str,
        *,
        run_id: str,
    ) -> None:
        """Remove a live event and broadcast the removal best-effort."""
        try:
            if not await self._run_matches_current_authority(session_id, run_id):
                return
            async with self._serialize_run_projection(session_id):
                active_run_id = self._active_run_ids.get(session_id)
                if active_run_id is not None and active_run_id != run_id:
                    return
                await self._live_event_store.remove(session_id, event_id)
                active = self._active_tool_events.get(session_id)
                if active is not None:
                    active.pop(event_id, None)
                    if not active:
                        self._active_tool_events.pop(session_id, None)
                await self._publish_event_removed(session_id, event_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Failed to remove live event projection",
                extra={"session_id": session_id, "event_id": event_id},
            )

    async def _flush_partial_batch(self, batch: LivePartialFlush) -> None:
        """Reflect batched live partial delta to store and broadcast."""
        async with self._serialize_run_projection(batch.session_id):
            if self._active_run_ids.get(batch.session_id) != batch.run_id:
                return
            if not await self._run_is_durable_active(
                batch.session_id,
                batch.run_id,
            ):
                return
            try:
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
            except asyncio.CancelledError as exc:
                # Cancellation may arrive after Redis accepted HSET but before the
                # response. Preserve cancellation, but do not let the batcher replay
                # an ambiguously committed delta.
                raise LivePartialFlushCommittedCancellation from exc
            except (TimeoutError, RedisError, OSError) as exc:
                # A timed-out/failed Redis response is commit-ambiguous. This live
                # projection is non-durable, so dropping the current batch is safer
                # than replaying it and duplicating text. The batcher restores later,
                # not-yet-attempted batches through this explicit signal.
                raise LivePartialFlushAttemptedError from exc
            try:
                await self._publish_event_upserted(live_event)
            except asyncio.CancelledError as exc:
                # The Redis projection already contains this delta. Propagate
                # cancellation without asking the batcher to replay the committed
                # delta; a later snapshot or upsert reconciles a missed broadcast.
                raise LivePartialFlushCommittedCancellation from exc
            except Exception:
                # Redis is the live projection authority. Replaying after only the
                # best-effort WebSocket publish failed would duplicate streamed text.
                logger.exception(
                    "Failed to broadcast committed live partial batch",
                    extra={
                        "session_id": batch.session_id,
                        "run_id": batch.run_id,
                        "kind": batch.kind,
                        "content_index": batch.content_index,
                    },
                )

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
