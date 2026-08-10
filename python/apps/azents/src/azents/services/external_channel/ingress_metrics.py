"""Process-local bounded metrics for External Channel ingress."""

import threading
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from pydantic import BaseModel, ConfigDict

from azents.core.config import Config
from azents.core.deps import get_appctx
from azents.job_runtime.types import JobRuntime
from azents.utils.appctx import AppContext


class ExternalChannelIngressMetricSnapshot(BaseModel):
    """Process-local bounded metric snapshot without item content."""

    model_config = ConfigDict(frozen=True)

    active_backlog_size: int
    oldest_queue_age_seconds: int | None
    claimed_batch_count: int
    claimed_item_count: int
    last_claimed_batch_size: int
    processing_duration_seconds: float
    retry_count: int
    bounded_failure_count: int
    cursor_suppression_count: int
    mailbox_rows_committed: int
    post_commit_wake_attempt_count: int
    post_commit_wake_failure_count: int
    runtime_active_task_count: int
    runtime_shutdown_drain_seconds: float | None


class ExternalChannelIngressMetrics:
    """Retain bounded process counters for the current runtime lifetime."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._claimed_batch_count = 0
        self._claimed_item_count = 0
        self._last_claimed_batch_size = 0
        self._processing_duration_seconds = 0.0
        self._retry_count = 0
        self._bounded_failure_count = 0
        self._cursor_suppression_count = 0
        self._mailbox_rows_committed = 0
        self._post_commit_wake_attempt_count = 0
        self._post_commit_wake_failure_count = 0

    def record_claim(self, size: int) -> None:
        """Record one bounded claimed batch."""
        with self._lock:
            self._claimed_batch_count += 1
            self._claimed_item_count += size
            self._last_claimed_batch_size = size

    def record_processing_duration(self, seconds: float) -> None:
        """Accumulate processing time for completed claim attempts."""
        with self._lock:
            self._processing_duration_seconds += max(0.0, seconds)

    def record_finalization(
        self,
        *,
        retries: int,
        bounded_failures: int,
        cursor_suppressions: int,
        mailbox_rows: int,
    ) -> None:
        """Record committed queue transitions without durable outcomes."""
        with self._lock:
            self._retry_count += retries
            self._bounded_failure_count += bounded_failures
            self._cursor_suppression_count += cursor_suppressions
            self._mailbox_rows_committed += mailbox_rows

    def record_wake_attempt(self, *, failed: bool) -> None:
        """Record one post-commit routing wake attempt."""
        with self._lock:
            self._post_commit_wake_attempt_count += 1
            if failed:
                self._post_commit_wake_failure_count += 1

    def snapshot(
        self,
        runtime: JobRuntime,
        *,
        active_backlog_size: int,
        oldest_queue_age_seconds: int | None,
    ) -> ExternalChannelIngressMetricSnapshot:
        """Return one immutable bounded process snapshot."""
        with self._lock:
            return ExternalChannelIngressMetricSnapshot(
                active_backlog_size=active_backlog_size,
                oldest_queue_age_seconds=oldest_queue_age_seconds,
                claimed_batch_count=self._claimed_batch_count,
                claimed_item_count=self._claimed_item_count,
                last_claimed_batch_size=self._last_claimed_batch_size,
                processing_duration_seconds=self._processing_duration_seconds,
                retry_count=self._retry_count,
                bounded_failure_count=self._bounded_failure_count,
                cursor_suppression_count=self._cursor_suppression_count,
                mailbox_rows_committed=self._mailbox_rows_committed,
                post_commit_wake_attempt_count=self._post_commit_wake_attempt_count,
                post_commit_wake_failure_count=self._post_commit_wake_failure_count,
                runtime_active_task_count=runtime.active_count,
                runtime_shutdown_drain_seconds=runtime.shutdown_drain_seconds,
            )


async def get_external_channel_ingress_metrics(
    appctx: Annotated[AppContext[Config], Depends(get_appctx)],
) -> ExternalChannelIngressMetrics:
    """Return one AppContext-owned ingress metric recorder."""

    async def create() -> AsyncIterator[ExternalChannelIngressMetrics]:
        yield ExternalChannelIngressMetrics()

    return await appctx.get_variable(
        f"{__name__}.get_external_channel_ingress_metrics",
        create,
    )
