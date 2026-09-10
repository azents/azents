"""Runtime reply delivery observability tests."""

from azents.runtime.observability import RuntimeReplyDeliveryMetrics


def test_runtime_reply_metrics_record_bounded_aggregate_snapshot() -> None:
    metrics = RuntimeReplyDeliveryMetrics()

    metrics.begin_wait()
    metrics.begin_wait()
    metrics.finish_wait(outcome="event", duration_seconds=0.01)
    metrics.finish_wait(outcome="timeout", duration_seconds=2.0)
    metrics.record_replies(examined=4, filtered=3)
    metrics.record_observation_latency(-1.0)
    metrics.record_observation_latency(6.0)
    metrics.record_event_loop_lag(-1.0)
    metrics.record_event_loop_lag(0.25)

    snapshot = metrics.snapshot()

    assert snapshot.active_waiters == 0
    assert snapshot.maximum_active_waiters == 2
    assert snapshot.wait_duration_bucket_counts == (0, 1, 0, 0, 0, 0, 1)
    assert snapshot.wait_event_count == 1
    assert snapshot.wait_timeout_count == 1
    assert snapshot.wait_cancel_count == 0
    assert snapshot.wait_error_count == 0
    assert snapshot.examined_reply_count == 4
    assert snapshot.filtered_reply_count == 3
    assert snapshot.observation_latency_bucket_counts == (1, 0, 0, 0, 0, 0, 0, 1)
    assert snapshot.event_loop_lag_latest_seconds == 0.25
    assert snapshot.event_loop_lag_maximum_seconds == 0.25
    assert snapshot.event_loop_lag_sample_count == 2


def test_runtime_reply_metrics_track_cancel_and_error_outcomes() -> None:
    metrics = RuntimeReplyDeliveryMetrics()

    metrics.begin_wait()
    metrics.finish_wait(outcome="cancel", duration_seconds=0.0)
    metrics.begin_wait()
    metrics.finish_wait(outcome="error", duration_seconds=0.0)

    snapshot = metrics.snapshot()

    assert snapshot.wait_cancel_count == 1
    assert snapshot.wait_error_count == 1
