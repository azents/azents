"""Shared failed-run finalization and post-commit publication."""

import dataclasses
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends

from azents.engine.events.engine_events import RunComplete
from azents.engine.events.types import Event
from azents.engine.run.emit import PublishedEvent
from azents.engine.run.failure import (
    FailedRunFinalizationReason,
    FailedRunRetryState,
)
from azents.repos.failed_run_finalization_operation import (
    FailedRunFinalization,
    FailedRunFinalizationOperationRepository,
)


@dataclasses.dataclass(frozen=True)
class FailedRunFinalizationInput:
    """Input for terminal failed-run finalization."""

    session_id: str
    owner_generation: int
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
    """Publish completed failed-run output unless a serialized Stop intent won."""

    repository: Annotated[
        FailedRunFinalizationOperationRepository,
        Depends(FailedRunFinalizationOperationRepository),
    ]

    async def finalize(
        self,
        input: FailedRunFinalizationInput,
        *,
        dispatch_event: Callable[[str, PublishedEvent], Awaitable[None]],
    ) -> FailedRunFinalizationResult | None:
        """Close the run through one repository operation, then dispatch in order."""
        finalized = await self.repository.finalize(
            FailedRunFinalization(
                session_id=input.session_id,
                owner_generation=input.owner_generation,
                run_id=input.run_id,
                user_message=input.user_message,
                retry_state=input.retry_state,
                reason=input.reason,
                action_hint=input.action_hint,
            ),
        )
        if finalized is None:
            return None
        await dispatch_event(input.session_id, finalized.error_event)
        await dispatch_event(input.session_id, finalized.run_marker)
        await dispatch_event(input.session_id, RunComplete(run_id=input.run_id))
        return FailedRunFinalizationResult(
            error_event=finalized.error_event,
            run_marker=finalized.run_marker,
        )
