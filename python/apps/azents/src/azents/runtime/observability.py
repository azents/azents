"""Process-local bounded observability for Runtime reply delivery."""

import dataclasses
import threading
from collections.abc import AsyncIterator
from typing import Annotated, Literal

from fastapi import Depends

from azents.core.config import Config
from azents.core.deps import get_appctx
from azents.utils.appctx import AppContext

type RuntimeReplyWaitOutcome = Literal["event", "timeout", "cancel", "error"]

WAIT_DURATION_BUCKET_SECONDS = (0.005, 0.025, 0.1, 0.25, 0.5, 1.0)
OBSERVATION_LATENCY_BUCKET_SECONDS = (0.005, 0.025, 0.1, 0.25, 0.5, 1.0, 5.0)


@dataclasses.dataclass(frozen=True)
class RuntimeReplyDeliveryMetricSnapshot:
    """Immutable aggregate observations without Runtime or request identity."""

    active_waiters: int
    maximum_active_waiters: int
    wait_duration_bucket_counts: tuple[int, ...]
    wait_event_count: int
    wait_timeout_count: int
    wait_cancel_count: int
    wait_error_count: int
    examined_reply_count: int
    filtered_reply_count: int
    observation_latency_bucket_counts: tuple[int, ...]
    event_loop_lag_latest_seconds: float
    event_loop_lag_maximum_seconds: float
    event_loop_lag_sample_count: int


class RuntimeReplyDeliveryMetrics:
    """Retain bounded Runtime reply observations for one process lifetime."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active_waiters = 0
        self._maximum_active_waiters = 0
        self._wait_duration_bucket_counts = [
            0 for _ in range(len(WAIT_DURATION_BUCKET_SECONDS) + 1)
        ]
        self._wait_outcome_counts: dict[RuntimeReplyWaitOutcome, int] = {
            "event": 0,
            "timeout": 0,
            "cancel": 0,
            "error": 0,
        }
        self._examined_reply_count = 0
        self._filtered_reply_count = 0
        self._observation_latency_bucket_counts = [
            0 for _ in range(len(OBSERVATION_LATENCY_BUCKET_SECONDS) + 1)
        ]
        self._event_loop_lag_latest_seconds = 0.0
        self._event_loop_lag_maximum_seconds = 0.0
        self._event_loop_lag_sample_count = 0

    def begin_wait(self) -> None:
        """Record entry into one blocking reply wait."""
        with self._lock:
            self._active_waiters += 1
            self._maximum_active_waiters = max(
                self._maximum_active_waiters,
                self._active_waiters,
            )

    def finish_wait(
        self,
        *,
        outcome: RuntimeReplyWaitOutcome,
        duration_seconds: float,
    ) -> None:
        """Record one completed blocking reply wait."""
        with self._lock:
            self._active_waiters = max(0, self._active_waiters - 1)
            self._wait_outcome_counts[outcome] += 1
            _increment_bucket(
                self._wait_duration_bucket_counts,
                WAIT_DURATION_BUCKET_SECONDS,
                duration_seconds,
            )

    def record_replies(self, *, examined: int, filtered: int) -> None:
        """Record bounded reply observation and identity filtering counts."""
        with self._lock:
            self._examined_reply_count += max(0, examined)
            self._filtered_reply_count += max(0, filtered)

    def record_observation_latency(self, seconds: float) -> None:
        """Record append-to-observation latency for one reply."""
        with self._lock:
            _increment_bucket(
                self._observation_latency_bucket_counts,
                OBSERVATION_LATENCY_BUCKET_SECONDS,
                seconds,
            )

    def record_event_loop_lag(self, seconds: float) -> None:
        """Record one non-negative Worker event-loop timer drift sample."""
        lag = max(0.0, seconds)
        with self._lock:
            self._event_loop_lag_latest_seconds = lag
            self._event_loop_lag_maximum_seconds = max(
                self._event_loop_lag_maximum_seconds,
                lag,
            )
            self._event_loop_lag_sample_count += 1

    def snapshot(self) -> RuntimeReplyDeliveryMetricSnapshot:
        """Return the current immutable aggregate snapshot."""
        with self._lock:
            return RuntimeReplyDeliveryMetricSnapshot(
                active_waiters=self._active_waiters,
                maximum_active_waiters=self._maximum_active_waiters,
                wait_duration_bucket_counts=tuple(self._wait_duration_bucket_counts),
                wait_event_count=self._wait_outcome_counts["event"],
                wait_timeout_count=self._wait_outcome_counts["timeout"],
                wait_cancel_count=self._wait_outcome_counts["cancel"],
                wait_error_count=self._wait_outcome_counts["error"],
                examined_reply_count=self._examined_reply_count,
                filtered_reply_count=self._filtered_reply_count,
                observation_latency_bucket_counts=tuple(
                    self._observation_latency_bucket_counts
                ),
                event_loop_lag_latest_seconds=(self._event_loop_lag_latest_seconds),
                event_loop_lag_maximum_seconds=(self._event_loop_lag_maximum_seconds),
                event_loop_lag_sample_count=self._event_loop_lag_sample_count,
            )


async def get_runtime_reply_delivery_metrics(
    appctx: Annotated[AppContext[Config], Depends(get_appctx)],
) -> RuntimeReplyDeliveryMetrics:
    """Return one AppContext-owned Runtime reply metric recorder."""

    async def create() -> AsyncIterator[RuntimeReplyDeliveryMetrics]:
        yield RuntimeReplyDeliveryMetrics()

    return await appctx.get_variable(
        f"{__name__}.get_runtime_reply_delivery_metrics",
        create,
    )


def _increment_bucket(
    counts: list[int],
    boundaries: tuple[float, ...],
    seconds: float,
) -> None:
    value = max(0.0, seconds)
    for index, boundary in enumerate(boundaries):
        if value <= boundary:
            counts[index] += 1
            return
    counts[-1] += 1
