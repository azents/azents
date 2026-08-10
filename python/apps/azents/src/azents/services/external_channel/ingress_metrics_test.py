"""Tests for bounded External Channel ingress metrics."""

from types import SimpleNamespace
from typing import cast

from azents.job_runtime.types import JobRuntime
from azents.services.external_channel.ingress_metrics import (
    ExternalChannelIngressMetrics,
)


def test_metrics_record_only_bounded_counters_and_runtime_state() -> None:
    """Metrics expose aggregate lifecycle evidence without ingress identities."""
    metrics = ExternalChannelIngressMetrics()
    metrics.record_claim(3)
    metrics.record_processing_duration(1.25)
    metrics.record_finalization(
        retries=1,
        bounded_failures=2,
        cursor_suppressions=3,
        mailbox_rows=4,
    )
    metrics.record_wake_attempt(failed=True)
    runtime = cast(
        JobRuntime,
        SimpleNamespace(active_count=2, shutdown_drain_seconds=0.75),
    )

    snapshot = metrics.snapshot(
        runtime,
        active_backlog_size=9,
        oldest_queue_age_seconds=12,
    )

    assert snapshot.active_backlog_size == 9
    assert snapshot.oldest_queue_age_seconds == 12
    assert snapshot.claimed_batch_count == 1
    assert snapshot.claimed_item_count == 3
    assert snapshot.last_claimed_batch_size == 3
    assert snapshot.processing_duration_seconds == 1.25
    assert snapshot.retry_count == 1
    assert snapshot.bounded_failure_count == 2
    assert snapshot.cursor_suppression_count == 3
    assert snapshot.mailbox_rows_committed == 4
    assert snapshot.post_commit_wake_attempt_count == 1
    assert snapshot.post_commit_wake_failure_count == 1
    assert snapshot.runtime_active_task_count == 2
    assert snapshot.runtime_shutdown_drain_seconds == 0.75
    serialized = snapshot.model_dump_json()
    assert "session_id" not in serialized
    assert "connection_id" not in serialized
