"""Shared failed-run finalization helpers."""

import dataclasses
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.types import PublishedEvent
from azents.engine.events.engine_events import RunComplete
from azents.engine.events.finalization import FailedRunEventStore
from azents.engine.events.types import Event
from azents.engine.run.failure import (
    FailedRunFinalizationReason,
    FailedRunRetryState,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.worker.session.lifecycle import SessionLifecycleService


@dataclasses.dataclass(frozen=True)
class FailedRunFinalizationInput:
    """Input for terminal failed-run finalization."""

    session_id: str
    run_id: str
    user_message: str
    retry_state: FailedRunRetryState
    reason: FailedRunFinalizationReason
    action_hint: str | None = None


@dataclasses.dataclass(frozen=True)
class FailedRunFinalizationResult:
    """Events created/emitted during failed-run finalization."""

    error_event: Event
    run_marker: Event


@dataclasses.dataclass(frozen=True)
class FailedRunErrorFinalizer:
    """Promote the latest failed attempt to terminal durable failed-run output."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    event_store: Annotated[FailedRunEventStore, Depends(FailedRunEventStore)]
    session_lifecycle: Annotated[
        SessionLifecycleService, Depends(SessionLifecycleService)
    ]

    async def finalize(
        self,
        input: FailedRunFinalizationInput,
        *,
        dispatch_event: Callable[[str, PublishedEvent], Awaitable[None]],
    ) -> FailedRunFinalizationResult:
        """Append terminal failed-run output and close the run as failed."""
        async with self.session_manager() as session:
            finalized = await self.event_store.append_terminal_failed_run(
                session,
                session_id=input.session_id,
                run_id=input.run_id,
                user_message=input.user_message,
                retry_state=input.retry_state,
                reason=input.reason,
                action_hint=input.action_hint,
            )
            error_event = finalized.error_event
            run_marker = finalized.run_marker
        await dispatch_event(input.session_id, error_event)
        await dispatch_event(input.session_id, run_marker)
        await dispatch_event(input.session_id, RunComplete(run_id=input.run_id))
        await self.session_lifecycle.clear_session_activity(input.session_id)
        return FailedRunFinalizationResult(
            error_event=error_event,
            run_marker=run_marker,
        )
