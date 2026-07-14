"""Shared failed-run finalization helpers."""

import asyncio
import dataclasses
import logging
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

logger = logging.getLogger(__name__)
_EXTERNAL_STEP_TIMEOUT_SECONDS = 1.0
_POST_COMMIT_DELIVERY_TIMEOUT_SECONDS = 10.0
_RETAINED_POST_COMMIT_TASKS: set[asyncio.Task[Exception | None]] = set()


def _on_post_commit_task_done(
    task: asyncio.Task[Exception | None],
    *,
    session_id: str,
) -> None:
    """Release and observe a retained post-commit delivery task."""
    _RETAINED_POST_COMMIT_TASKS.discard(task)
    try:
        delivery_error = task.result()
    except asyncio.CancelledError:
        logger.warning(
            "Failed-run post-commit delivery task was cancelled",
            extra={"session_id": session_id},
        )
    except Exception:
        logger.exception(
            "Failed-run post-commit delivery task failed",
            extra={"session_id": session_id},
        )
    else:
        if delivery_error is not None:
            logger.error(
                "Failed-run post-commit delivery task failed",
                exc_info=(
                    type(delivery_error),
                    delivery_error,
                    delivery_error.__traceback__,
                ),
                extra={"session_id": session_id},
            )


def _retain_post_commit_task(
    task: asyncio.Task[Exception | None],
    *,
    session_id: str,
) -> None:
    """Keep a post-commit delivery alive and always consume its outcome."""
    _RETAINED_POST_COMMIT_TASKS.add(task)
    task.add_done_callback(
        lambda done_task: _on_post_commit_task_done(
            done_task,
            session_id=session_id,
        )
    )


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

        delivery_task = asyncio.create_task(
            self._deliver_committed_finalization(
                input,
                error_event=error_event,
                run_marker=run_marker,
                dispatch_event=dispatch_event,
            ),
            name=f"failed-run-post-commit:{input.session_id}",
        )
        _retain_post_commit_task(delivery_task, session_id=input.session_id)
        delivery_error = await asyncio.shield(delivery_task)
        if delivery_error is not None:
            raise delivery_error
        return FailedRunFinalizationResult(
            error_event=error_event,
            run_marker=run_marker,
        )

    async def _deliver_committed_finalization(
        self,
        input: FailedRunFinalizationInput,
        *,
        error_event: Event,
        run_marker: Event,
        dispatch_event: Callable[[str, PublishedEvent], Awaitable[None]],
    ) -> Exception | None:
        """Deliver one committed terminal sequence under a hard deadline."""
        try:
            async with asyncio.timeout(_POST_COMMIT_DELIVERY_TIMEOUT_SECONDS):
                await self._deliver_committed_finalization_steps(
                    input,
                    error_event=error_event,
                    run_marker=run_marker,
                    dispatch_event=dispatch_event,
                )
        except TimeoutError:
            logger.warning(
                "Failed-run post-commit delivery timed out",
                extra={"session_id": input.session_id},
            )
        except Exception as exc:
            return exc
        return None

    async def _deliver_committed_finalization_steps(
        self,
        input: FailedRunFinalizationInput,
        *,
        error_event: Event,
        run_marker: Event,
        dispatch_event: Callable[[str, PublishedEvent], Awaitable[None]],
    ) -> None:
        """Deliver committed failed-run signals and cleanup in order."""
        for step, event in (
            ("dispatch_failed_run_error", error_event),
            ("dispatch_failed_run_marker", run_marker),
            ("dispatch_failed_run_complete", RunComplete(run_id=input.run_id)),
        ):
            await self._run_external_step(
                input.session_id,
                step=step,
                action=lambda event=event: dispatch_event(input.session_id, event),
            )
        await self._run_external_step(
            input.session_id,
            step="clear_failed_run_activity",
            action=lambda: self.session_lifecycle.clear_session_activity(
                input.session_id
            ),
        )

    async def _run_external_step(
        self,
        session_id: str,
        *,
        step: str,
        action: Callable[[], Awaitable[None]],
    ) -> None:
        """Run one post-commit projection step with an independent deadline."""
        try:
            async with asyncio.timeout(_EXTERNAL_STEP_TIMEOUT_SECONDS):
                await action()
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            logger.warning(
                "Failed-run external step timed out",
                extra={"session_id": session_id, "step": step},
            )
        except Exception:
            logger.exception(
                "Failed-run external step failed",
                extra={"session_id": session_id, "step": step},
            )
