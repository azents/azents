"""Web chat live event projection management."""

import asyncio
import functools
import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Annotated, Literal

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.broadcast import WebSocketBroadcast
from azents.broker.types import PublishedEvent
from azents.core.enums import EventKind
from azents.engine.events.engine_events import (
    ContentDelta,
    ProviderToolActivityChanged,
    ReasoningDelta,
    RunComplete,
    RunStarted,
    RunStopped,
)
from azents.engine.events.types import ActiveToolCall, Event
from azents.rdb.deps import get_session_manager
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.services.chat.data import ChatLiveRunState
from azents.services.chat.live_events import (
    BaseLiveEventStore,
    RedisLiveEventStore,
    active_tool_call_live_event_id,
    active_tool_call_to_live_event,
)
from azents.transport.chat import (
    chat_live_event_removed_dump,
    chat_live_event_upserted_dump,
    chat_live_projection_reset_dump,
    chat_live_run_cleared_dump,
    chat_live_run_updated_dump,
)
from azents.worker.deps import get_broadcast, get_live_event_store
from azents.worker.live.partial_batcher import LivePartialBatcher, LivePartialFlush

logger = logging.getLogger(__name__)

SessionManagerFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class LiveEventProjector:
    """Reflect Runtime events through a PostgreSQL-derived live writer fence."""

    def __init__(
        self,
        *,
        live_event_store: Annotated[RedisLiveEventStore, Depends(get_live_event_store)],
        broadcast: Annotated[WebSocketBroadcast, Depends(get_broadcast)],
        session_manager: Annotated[SessionManagerFactory, Depends(get_session_manager)],
        agent_run_repository: Annotated[
            AgentRunRepository, Depends(AgentRunRepository)
        ],
        agent_session_repository: Annotated[
            AgentSessionRepository, Depends(AgentSessionRepository)
        ],
    ) -> None:
        self._live_event_store = live_event_store
        self._broadcast = broadcast
        self._session_manager = session_manager
        self._agent_run_repository = agent_run_repository
        self._agent_session_repository = agent_session_repository
        self._partial_batchers: dict[tuple[str, int], LivePartialBatcher] = {}
        self._active_run_ids: dict[tuple[str, int], str] = {}
        self._active_tool_events: dict[tuple[str, int], dict[str, Event]] = {}

    @staticmethod
    def _owner_key(session_id: str, owner_generation: int) -> tuple[str, int]:
        return (session_id, owner_generation)

    def _partial_batcher(
        self,
        session_id: str,
        owner_generation: int,
    ) -> LivePartialBatcher:
        key = self._owner_key(session_id, owner_generation)
        batcher = self._partial_batchers.get(key)
        if batcher is None:
            batcher = LivePartialBatcher(
                functools.partial(
                    self._flush_partial_batch,
                    owner_generation=owner_generation,
                )
            )
            self._partial_batchers[key] = batcher
        return batcher

    @staticmethod
    async def _discard_without_projection() -> None:
        """Discard one local batch without mutating shared live state."""

    async def _evict_generation(
        self,
        session_id: str,
        owner_generation: int,
    ) -> set[str]:
        """Cancel one generation's local buffers and release correlation state."""
        key = self._owner_key(session_id, owner_generation)
        batcher = self._partial_batchers.pop(key, None)
        if batcher is not None:
            await batcher.discard_session(
                session_id,
                self._discard_without_projection,
            )
        self._active_run_ids.pop(key, None)
        active_events = self._active_tool_events.pop(key, {})
        return set(active_events)

    async def _evict_superseded_generations(
        self,
        session_id: str,
        owner_generation: int,
    ) -> set[str]:
        """Release every older in-process generation after durable takeover."""
        keys = (
            set(self._partial_batchers)
            | set(self._active_run_ids)
            | set(self._active_tool_events)
        )
        removed_event_ids: set[str] = set()
        for candidate_session_id, candidate_generation in sorted(keys):
            if (
                candidate_session_id != session_id
                or candidate_generation == owner_generation
            ):
                continue
            removed_event_ids.update(
                await self._evict_generation(
                    candidate_session_id,
                    candidate_generation,
                )
            )
        return removed_event_ids

    async def _owned_store(
        self,
        session_id: str,
        owner_generation: int,
    ) -> BaseLiveEventStore | None:
        """Validate PostgreSQL authority before seeding the ephemeral fence."""
        async with self._session_manager() as session:
            current = await self._agent_session_repository.get_by_id(
                session,
                session_id,
            )
        if current is None or current.owner_generation != owner_generation:
            return None
        advance = await self._live_event_store.advance_owner(
            session_id,
            owner_generation,
        )
        if not advance.accepted:
            return None
        removed_local_event_ids = await self._evict_superseded_generations(
            session_id,
            owner_generation,
        )
        removed_event_ids = {
            event.id for event in advance.removed_events
        } | removed_local_event_ids
        if advance.advanced:
            await self._broadcast.publish_live_projection(
                session_id,
                chat_live_projection_reset_dump(session_id),
                owner_generation=owner_generation,
            )
        for event_id in sorted(removed_event_ids):
            await self._publish_event_removed(
                session_id,
                event_id,
                owner_generation=owner_generation,
            )
        return self._live_event_store.for_owner(session_id, owner_generation)

    async def flush_session(
        self,
        session_id: str,
        *,
        owner_generation: int,
    ) -> None:
        """Reflect pending live partial batches best-effort."""
        try:
            batcher = self._partial_batchers.get(
                self._owner_key(session_id, owner_generation)
            )
            if batcher is not None:
                await batcher.flush_session(session_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Failed to flush session live partial batches",
                extra={"session_id": session_id},
            )

    async def _terminal_matches_current_run(
        self,
        session_id: str,
        run_id: str,
        owner_generation: int,
    ) -> bool:
        """Validate terminal cleanup against durable current Run authority."""
        active_run_id = self._active_run_ids.get(
            self._owner_key(session_id, owner_generation)
        )
        if active_run_id is not None and active_run_id != run_id:
            return False
        async with self._session_manager() as session:
            current = await self._agent_run_repository.get_running_by_session_id(
                session,
                session_id=session_id,
            )
        return current is None or current.id == run_id

    async def update(
        self,
        session_id: str,
        event: PublishedEvent,
        *,
        owner_generation: int,
    ) -> None:
        """Reflect Runtime event to live projection store best-effort."""
        try:
            match event:
                case RunComplete() | RunStopped():
                    await self.flush_session(
                        session_id,
                        owner_generation=owner_generation,
                    )
                case _:
                    pass

            match event:
                case RunStarted(run_id=run_id):
                    await self.clear_session(
                        session_id,
                        owner_generation=owner_generation,
                    )
                    self._active_run_ids[
                        self._owner_key(session_id, owner_generation)
                    ] = run_id
                case ContentDelta(delta=delta, content_index=content_index):
                    await self._partial_batcher(
                        session_id,
                        owner_generation,
                    ).append_content_delta(
                        session_id=session_id,
                        delta=delta,
                        content_index=content_index,
                    )
                case ReasoningDelta(
                    delta=delta,
                    item_id=item_id,
                    output_index=output_index,
                    summary_index=summary_index,
                ):
                    await self._partial_batcher(
                        session_id,
                        owner_generation,
                    ).append_reasoning_delta(
                        session_id=session_id,
                        delta=delta,
                        item_id=item_id,
                        output_index=output_index,
                        summary_index=summary_index,
                    )
                case ProviderToolActivityChanged(
                    call_id=call_id,
                    name=name,
                    status=status,
                    arguments=arguments,
                ):
                    await self._partial_batcher(
                        session_id,
                        owner_generation,
                    ).flush_session_and_transition(
                        session_id,
                        lambda: self._upsert_provider_tool_activity(
                            session_id=session_id,
                            call_id=call_id,
                            name=name,
                            status=status,
                            arguments=arguments,
                            owner_generation=owner_generation,
                        ),
                    )
                case Event():
                    await self._partial_batcher(
                        session_id,
                        owner_generation,
                    ).flush_session_and_transition(
                        session_id,
                        lambda: self._replace_live_counterpart(
                            session_id,
                            event,
                            owner_generation=owner_generation,
                        ),
                    )
                case RunComplete(run_id=run_id) | RunStopped(run_id=run_id):
                    if await self._terminal_matches_current_run(
                        session_id,
                        run_id,
                        owner_generation,
                    ):
                        await self.clear_session(
                            session_id,
                            owner_generation=owner_generation,
                        )
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
        removed_call_ids: set[str],
        owner_generation: int,
    ) -> None:
        """Broadcast PostgreSQL-backed active calls under one writer generation."""
        try:
            if await self._owned_store(session_id, owner_generation) is None:
                return
            owner_key = self._owner_key(session_id, owner_generation)
            before = self._active_tool_events.get(owner_key, {})
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
                await self._publish_event_removed(
                    session_id,
                    event_id,
                    owner_generation=owner_generation,
                )
            for event_id, event in after.items():
                if before.get(event_id) != event:
                    await self._publish_event_upserted(
                        event,
                        owner_generation=owner_generation,
                    )
            if after:
                self._active_tool_events[owner_key] = after
            else:
                self._active_tool_events.pop(owner_key, None)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Failed to broadcast live active tool calls",
                extra={"session_id": session_id},
            )

    async def _upsert_provider_tool_activity(
        self,
        *,
        session_id: str,
        call_id: str,
        name: str,
        status: Literal["running", "completed", "failed"],
        arguments: str | None,
        owner_generation: int,
    ) -> None:
        owned_store = await self._owned_store(session_id, owner_generation)
        if owned_store is None:
            return
        live_event = await owned_store.upsert_provider_tool_activity(
            session_id,
            call_id=call_id,
            name=name,
            status=status,
            arguments=arguments,
        )
        await self._publish_event_upserted(
            live_event,
            owner_generation=owner_generation,
        )

    async def _replace_live_counterpart(
        self,
        session_id: str,
        event: Event,
        *,
        owner_generation: int,
    ) -> None:
        owned_store = await self._owned_store(session_id, owner_generation)
        if owned_store is None:
            return
        before = await owned_store.list_by_session_id(session_id)
        await owned_store.remove_live_counterpart(event)
        after = await owned_store.list_by_session_id(session_id)
        await self._publish_removed_events(
            session_id,
            before=before,
            after=after,
            owner_generation=owner_generation,
        )

    async def discard_failed_attempt(
        self,
        session_id: str,
        *,
        owner_generation: int,
    ) -> None:
        """Discard failed-attempt model partials after earlier mutations settle."""
        try:
            await self._partial_batcher(
                session_id,
                owner_generation,
            ).discard_session(
                session_id,
                lambda: self._remove_model_partials(
                    session_id,
                    owner_generation=owner_generation,
                ),
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Failed to discard failed-attempt live model partials",
                extra={"session_id": session_id},
            )

    async def _remove_model_partials(
        self,
        session_id: str,
        *,
        owner_generation: int,
    ) -> None:
        owned_store = await self._owned_store(session_id, owner_generation)
        if owned_store is None:
            return
        events = await owned_store.list_by_session_id(session_id)
        model_partials = [
            event
            for event in events
            if event.adapter == "azents-live"
            and event.kind
            in {
                EventKind.ASSISTANT_MESSAGE,
                EventKind.REASONING,
                EventKind.PROVIDER_TOOL_CALL,
            }
        ]
        for event in model_partials:
            await owned_store.remove(session_id, event.id)
            await self._publish_event_removed(
                session_id,
                event.id,
                owner_generation=owner_generation,
            )

    async def clear_session(
        self,
        session_id: str,
        *,
        owner_generation: int,
    ) -> None:
        """Clear projections and broadcast removals under one writer generation."""
        owner_key = self._owner_key(session_id, owner_generation)
        batcher = self._partial_batchers.get(owner_key)
        try:
            if batcher is None:
                await self._clear_session_projections(
                    session_id,
                    owner_generation=owner_generation,
                )
            else:
                await batcher.discard_session(
                    session_id,
                    lambda: self._clear_session_projections(
                        session_id,
                        owner_generation=owner_generation,
                    ),
                )
        finally:
            self._partial_batchers.pop(owner_key, None)
            self._active_run_ids.pop(owner_key, None)
            self._active_tool_events.pop(owner_key, None)

    async def _clear_session_projections(
        self,
        session_id: str,
        *,
        owner_generation: int,
    ) -> None:
        owned_store = await self._owned_store(session_id, owner_generation)
        if owned_store is None:
            return
        owner_key = self._owner_key(session_id, owner_generation)
        events = await owned_store.list_by_session_id(session_id)
        active_events = self._active_tool_events.pop(owner_key, {})
        await owned_store.clear_session(session_id)
        for event_id in {event.id for event in events} | set(active_events):
            await self._publish_event_removed(
                session_id,
                event_id,
                owner_generation=owner_generation,
            )

    async def publish_live_run_updated(
        self,
        session_id: str,
        run: ChatLiveRunState,
        *,
        owner_generation: int,
    ) -> None:
        """Broadcast current live Run state under one writer generation."""
        try:
            if await self._owned_store(session_id, owner_generation) is None:
                return
            self._active_run_ids[self._owner_key(session_id, owner_generation)] = (
                run.run_id
            )
            await self._broadcast.publish_live_projection(
                session_id,
                chat_live_run_updated_dump(session_id, run),
                owner_generation=owner_generation,
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
        owner_generation: int,
    ) -> None:
        """Broadcast live Run removal under one writer generation."""
        eligible = False
        try:
            if not await self._terminal_matches_current_run(
                session_id,
                run_id,
                owner_generation,
            ):
                return
            eligible = True
            if await self._owned_store(session_id, owner_generation) is None:
                return
            self._active_run_ids.pop(
                self._owner_key(session_id, owner_generation),
                None,
            )
            await self._broadcast.publish_live_projection(
                session_id,
                chat_live_run_cleared_dump(session_id, run_id),
                owner_generation=owner_generation,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Failed to broadcast live run removal",
                extra={"session_id": session_id, "run_id": run_id},
            )
        finally:
            if eligible:
                await self._evict_generation(session_id, owner_generation)

    async def publish_control_event(
        self,
        session_id: str,
        event_json: dict[str, object],
        *,
        owner_generation: int,
    ) -> None:
        """Publish a public control after seeding the current live generation."""
        try:
            if await self._owned_store(session_id, owner_generation) is None:
                return
            await self._broadcast.publish_live_projection(
                session_id,
                event_json,
                owner_generation=owner_generation,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Failed to broadcast live control event",
                extra={"session_id": session_id},
            )

    async def remove_event(
        self,
        session_id: str,
        event_id: str,
        *,
        owner_generation: int,
    ) -> None:
        """Remove one live projection under one writer generation."""
        try:
            owned_store = await self._owned_store(session_id, owner_generation)
            if owned_store is None:
                return
            await owned_store.remove(session_id, event_id)
            owner_key = self._owner_key(session_id, owner_generation)
            active = self._active_tool_events.get(owner_key)
            if active is not None:
                active.pop(event_id, None)
                if not active:
                    self._active_tool_events.pop(owner_key, None)
            await self._publish_event_removed(
                session_id,
                event_id,
                owner_generation=owner_generation,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Failed to remove live event projection",
                extra={"session_id": session_id, "event_id": event_id},
            )

    async def _flush_partial_batch(
        self,
        batch: LivePartialFlush,
        *,
        owner_generation: int,
    ) -> None:
        owned_store = await self._owned_store(batch.session_id, owner_generation)
        if owned_store is None:
            return
        if batch.kind == "content":
            if batch.content_index is None:
                return
            live_event = await owned_store.append_assistant_delta(
                batch.session_id,
                delta=batch.delta,
                content_index=batch.content_index,
            )
        else:
            before = await owned_store.list_by_session_id(batch.session_id)
            live_event = await owned_store.append_reasoning_delta(
                batch.session_id,
                delta=batch.delta,
                item_id=batch.item_id,
                output_index=batch.output_index,
                summary_index=batch.summary_index,
            )
            after = await owned_store.list_by_session_id(batch.session_id)
            await self._publish_removed_events(
                batch.session_id,
                before=before,
                after=after,
                owner_generation=owner_generation,
            )
        await self._publish_event_upserted(
            live_event,
            owner_generation=owner_generation,
        )

    async def _publish_removed_events(
        self,
        session_id: str,
        *,
        before: list[Event],
        after: list[Event],
        owner_generation: int,
    ) -> None:
        after_ids = {event.id for event in after}
        for event in before:
            if event.id not in after_ids:
                await self._publish_event_removed(
                    session_id,
                    event.id,
                    owner_generation=owner_generation,
                )

    async def _publish_event_upserted(
        self,
        event: Event,
        *,
        owner_generation: int,
    ) -> None:
        await self._broadcast.publish_live_projection(
            event.session_id,
            chat_live_event_upserted_dump(event),
            owner_generation=owner_generation,
        )

    async def _publish_event_removed(
        self,
        session_id: str,
        event_id: str,
        *,
        owner_generation: int,
    ) -> None:
        await self._broadcast.publish_live_projection(
            session_id,
            chat_live_event_removed_dump(session_id, event_id),
            owner_generation=owner_generation,
        )
