"""Bounded Scheduled Task dispatch sequencing after completed database operations."""

import datetime
import logging
from collections.abc import Callable
from dataclasses import dataclass

from azents.broker.types import SessionBroker, SessionWakeUp
from azents.repos.scheduled_task.data import ScheduledTask
from azents.repos.scheduled_task.dispatch import ScheduledTaskDispatchRepository

logger = logging.getLogger(__name__)
_DEFAULT_BATCH_SIZE = 50


@dataclass(frozen=True)
class ScheduledTaskDispatchSummary:
    """Aggregate outcome returned by one bounded dispatcher pass."""

    claimed: int = 0
    admitted: int = 0
    coalesced: int = 0
    skipped: int = 0
    wake_failed: int = 0

    def plus(
        self, other: "ScheduledTaskDispatchSummary"
    ) -> "ScheduledTaskDispatchSummary":
        """Add two aggregate outcomes."""
        return ScheduledTaskDispatchSummary(
            claimed=self.claimed + other.claimed,
            admitted=self.admitted + other.admitted,
            coalesced=self.coalesced + other.coalesced,
            skipped=self.skipped + other.skipped,
            wake_failed=self.wake_failed + other.wake_failed,
        )


class ScheduledTaskDispatcher:
    """Sequence completed Task claims/admissions and post-commit broker wakes."""

    def __init__(
        self,
        *,
        operations: ScheduledTaskDispatchRepository,
        broker: SessionBroker,
        clock: Callable[[], datetime.datetime],
        batch_size: int = _DEFAULT_BATCH_SIZE,
    ) -> None:
        self.operations = operations
        self.broker = broker
        self.clock = clock
        self.batch_size = batch_size

    async def dispatch_once(
        self,
        *,
        lease_owner: str,
        now: datetime.datetime | None = None,
    ) -> ScheduledTaskDispatchSummary:
        """Claim and admit due Tasks at one optional controlled pass instant."""
        controlled_now = _utc(now) if now is not None else None
        summary = ScheduledTaskDispatchSummary()
        for _ in range(self.batch_size):
            claim_now = (
                controlled_now if controlled_now is not None else _utc(self.clock())
            )
            task = await self.operations.claim_due(
                now=claim_now, lease_owner=lease_owner
            )
            if task is None:
                break
            summary = summary.plus(ScheduledTaskDispatchSummary(claimed=1))
            outcome = await self.operations.admit_claimed(
                task_id=task.id,
                lease_owner=lease_owner,
                lease_token=_lease_token(task),
                now=(
                    controlled_now if controlled_now is not None else _utc(self.clock())
                ),
                controlled_now=controlled_now,
            )
            summary = summary.plus(
                ScheduledTaskDispatchSummary(
                    admitted=int(outcome.admitted),
                    coalesced=int(outcome.coalesced),
                    skipped=int(outcome.skipped),
                )
            )
            if outcome.admitted:
                try:
                    await self.broker.send_message(
                        SessionWakeUp(session_id=task.session_id)
                    )
                except Exception:
                    logger.exception(
                        "Scheduled Task Session wake failed",
                        extra={"session_id": task.session_id},
                    )
                    summary = summary.plus(ScheduledTaskDispatchSummary(wake_failed=1))
        return summary


def _lease_token(task: ScheduledTask) -> datetime.datetime:
    if task.lease_until is None:
        raise RuntimeError("Scheduled Task claim is missing its lease token.")
    return task.lease_until


def _utc(value: datetime.datetime) -> datetime.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Datetime values must be timezone-aware.")
    return value.astimezone(datetime.UTC)
