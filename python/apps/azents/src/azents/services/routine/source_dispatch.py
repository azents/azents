"""Source-only Routine admission through the existing Scheduler and Session inbox."""

import datetime
from collections.abc import Callable
from dataclasses import dataclass

from azents.broker.types import SessionBroker, SessionWakeUp
from azents.core.routine import RoutineUnavailable
from azents.repos.routine.judgment_inbox import RoutineJudgmentInboxRepository
from azents.repos.routine.source_dispatch import RoutineSourceRepository


@dataclass(frozen=True)
class RoutineSourceDispatchSummary:
    """Outcome of one bounded source pass, with no model execution statistics."""

    checked: int
    enqueued: int
    unavailable: int
    deadline_reached: bool


@dataclass(frozen=True)
class RoutineSourceDispatcher:
    """Collect source opportunities and publish ordinary wakes after DB commit."""

    sources: RoutineSourceRepository
    inbox: RoutineJudgmentInboxRepository
    broker: SessionBroker
    clock: Callable[[], datetime.datetime]
    batch_size: int

    async def dispatch_once(
        self, *, now: datetime.datetime, deadline: datetime.datetime
    ) -> RoutineSourceDispatchSummary:
        """Page due roots until exhausted or the existing Scheduler deadline."""
        if (
            now.tzinfo is None
            or now.utcoffset() is None
            or deadline.tzinfo is None
            or deadline.utcoffset() is None
        ):
            raise ValueError("Routine source times must be timezone-aware.")
        if self.batch_size < 1:
            raise ValueError("Routine source batch size must be positive.")
        checked = enqueued = unavailable = 0
        while self.clock() < deadline:
            scopes = await self.sources.list_due_scopes(now=now, limit=self.batch_size)
            if not scopes:
                return RoutineSourceDispatchSummary(
                    checked=checked,
                    enqueued=enqueued,
                    unavailable=unavailable,
                    deadline_reached=False,
                )
            for scope in scopes:
                if self.clock() >= deadline:
                    return RoutineSourceDispatchSummary(
                        checked=checked,
                        enqueued=enqueued,
                        unavailable=unavailable,
                        deadline_reached=True,
                    )
                try:
                    admission = await self.inbox.admit_tick(scope=scope, now=now)
                except RoutineUnavailable:
                    # A root can archive or retire after the read-only scan.
                    unavailable += 1
                    continue
                checked += 1
                if admission is not None:
                    enqueued += 1
                    await self.broker.send_message(
                        SessionWakeUp(session_id=scope.session_id)
                    )
        return RoutineSourceDispatchSummary(
            checked=checked,
            enqueued=enqueued,
            unavailable=unavailable,
            deadline_reached=True,
        )
