"""User stop finalization over separate completed database stages."""

import dataclasses
from collections.abc import Sequence
from typing import Annotated

from fastapi import Depends

from azents.core.enums import AgentRunStatus
from azents.engine.events.engine_events import RunStopped
from azents.engine.events.types import (
    ActiveToolCall,
    AssistantMessagePayload,
    ClientToolCallPayload,
    Event,
    ReasoningPayload,
)
from azents.repos.user_stop import UserStopOperationRepository
from azents.repos.user_stop_data import (
    UserStopCancelledCallsInput,
    UserStopDurableEvents,
    UserStopMarkerInput,
    UserStopOwnerInput,
    UserStopPartialInput,
)
from azents.services.chat.live_events import BaseLiveEventStore
from azents.worker.deps import get_live_event_store
from azents.worker.events.publisher import WorkerEventPublisher
from azents.worker.live.event_projector import LiveEventProjector
from azents.worker.session.lifecycle import SessionLifecycleService


@dataclasses.dataclass(frozen=True)
class UserStopFinalizer:
    """Clean up run observation state after receiving User stop."""

    repository: Annotated[
        UserStopOperationRepository, Depends(UserStopOperationRepository)
    ]
    live_event_store: Annotated[BaseLiveEventStore, Depends(get_live_event_store)]
    live_event_projector: Annotated[LiveEventProjector, Depends(LiveEventProjector)]
    event_publisher: Annotated[WorkerEventPublisher, Depends(WorkerEventPublisher)]
    session_lifecycle: Annotated[
        SessionLifecycleService, Depends(SessionLifecycleService)
    ]

    async def finalize(
        self,
        session_id: str,
        *,
        owner_generation: int,
        run_id: str | None,
        active_tool_calls: Sequence[ActiveToolCall],
    ) -> None:
        """Immediately clean run observation state as terminal after User stop."""
        del active_tool_calls
        running_run = await self.session_lifecycle.get_running_agent_run(
            session_id, owner_generation=owner_generation
        )
        effective_run_id = run_id or (
            running_run.id if running_run is not None else None
        )
        effective_tool_calls = (
            list(running_run.active_tool_calls) if running_run is not None else []
        )
        await self.live_event_projector.flush_session(
            session_id, owner_generation=owner_generation
        )
        await self._persist_live_events_for_user_stop(
            session_id,
            owner_generation=owner_generation,
            run_id=effective_run_id,
            active_tool_calls=effective_tool_calls,
        )
        await self.live_event_projector.replace_active_tool_calls(
            session_id,
            [],
            removed_call_ids={call.call_id for call in effective_tool_calls},
            owner_generation=owner_generation,
        )
        if effective_run_id is None:
            transitioned_run_ids = (
                await self.session_lifecycle.mark_session_agent_runs_terminal(
                    session_id,
                    owner_generation=owner_generation,
                    status=AgentRunStatus.STOPPED,
                )
            )
            for transitioned_run_id in transitioned_run_ids:
                await self.session_lifecycle.notify_parent_result_activity(
                    transitioned_run_id
                )
        else:
            await self._mark_agent_run_stopped_for_user_stop(
                session_id, owner_generation=owner_generation, run_id=effective_run_id
            )
            await self.session_lifecycle.notify_parent_result_activity(effective_run_id)
            durable_events = await self._append_user_stop_events(
                session_id, owner_generation=owner_generation, run_id=effective_run_id
            )
            await self.event_publisher.dispatch_event(
                session_id,
                durable_events.interrupted,
                owner_generation=owner_generation,
            )
            await self.event_publisher.dispatch_event(
                session_id, durable_events.run_marker, owner_generation=owner_generation
            )
            await self.event_publisher.dispatch_event(
                session_id,
                RunStopped(run_id=effective_run_id),
                owner_generation=owner_generation,
            )
        await self._clear_stop_request(session_id, owner_generation=owner_generation)

    async def record_interrupted_run(
        self, session_id: str, *, owner_generation: int, run_id: str
    ) -> None:
        """Record and publish durable User stop history after terminal state."""
        await self._mark_agent_run_stopped_for_user_stop(
            session_id, owner_generation=owner_generation, run_id=run_id
        )
        durable_events = await self._append_user_stop_events(
            session_id, owner_generation=owner_generation, run_id=run_id
        )
        await self.event_publisher.dispatch_event(
            session_id, durable_events.interrupted, owner_generation=owner_generation
        )
        await self.event_publisher.dispatch_event(
            session_id, durable_events.run_marker, owner_generation=owner_generation
        )
        await self.event_publisher.dispatch_event(
            session_id, RunStopped(run_id=run_id), owner_generation=owner_generation
        )
        await self._clear_stop_request(session_id, owner_generation=owner_generation)

    async def _persist_live_events_for_user_stop(
        self,
        session_id: str,
        *,
        owner_generation: int,
        run_id: str | None,
        active_tool_calls: Sequence[ActiveToolCall],
    ) -> None:
        """Promote live projection to durable history on Stop critical path."""
        live_events = await self.live_event_store.list_by_session_id(session_id)
        await self._append_live_partial_events(
            session_id, owner_generation=owner_generation, live_events=live_events
        )
        await self._append_cancelled_tool_results(
            session_id,
            owner_generation=owner_generation,
            run_id=run_id,
            active_tool_calls=active_tool_calls,
        )
        await self._remove_persisted_stop_live_events(
            session_id, live_events, owner_generation=owner_generation
        )

    async def _append_live_partial_events(
        self, session_id: str, *, owner_generation: int, live_events: Sequence[Event]
    ) -> None:
        """Complete eligible idempotent partial admission before other Stop stages."""
        await self.repository.append_partial_events(
            UserStopPartialInput(
                session_id=session_id,
                owner_generation=owner_generation,
                events=tuple(live_events),
            )
        )

    async def _append_user_stop_events(
        self, session_id: str, *, owner_generation: int, run_id: str
    ) -> UserStopDurableEvents:
        """Complete the interrupted/marker pair before dispatching either event."""
        return await self.repository.append_user_stop_events(
            UserStopMarkerInput(
                session_id=session_id, owner_generation=owner_generation, run_id=run_id
            )
        )

    async def _clear_stop_request(
        self, session_id: str, *, owner_generation: int
    ) -> None:
        """Clear Stop intent in its guarded later transaction."""
        await self.repository.clear_stop_request(
            UserStopOwnerInput(session_id=session_id, owner_generation=owner_generation)
        )

    async def _append_cancelled_tool_results(
        self,
        session_id: str,
        *,
        owner_generation: int,
        run_id: str | None,
        active_tool_calls: Sequence[ActiveToolCall],
    ) -> None:
        """Complete cancelled durable active-call admission as its own stage."""
        await self.repository.append_cancelled_tool_results(
            UserStopCancelledCallsInput(
                session_id=session_id,
                owner_generation=owner_generation,
                run_id=run_id,
                active_tool_calls=tuple(active_tool_calls),
            )
        )

    async def _remove_persisted_stop_live_events(
        self, session_id: str, live_events: Sequence[Event], *, owner_generation: int
    ) -> None:
        """Remove stop-related live projections converged to History."""
        for event in live_events:
            if isinstance(event.payload, AssistantMessagePayload | ReasoningPayload):
                await self.live_event_projector.remove_event(
                    session_id, event.id, owner_generation=owner_generation
                )
                continue
            if isinstance(event.payload, ClientToolCallPayload):
                await self.live_event_projector.remove_event(
                    session_id, event.id, owner_generation=owner_generation
                )

    async def _mark_agent_run_stopped_for_user_stop(
        self, session_id: str, *, owner_generation: int, run_id: str
    ) -> None:
        """Converge one Run through the User Stop terminal coordinator."""
        await self.session_lifecycle.mark_agent_run_stopped_for_user_stop(
            session_id, owner_generation=owner_generation, run_id=run_id
        )
