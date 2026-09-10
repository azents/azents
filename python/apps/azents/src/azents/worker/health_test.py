"""Worker health observability tests."""

import asyncio
import contextlib

import pytest
from redis.asyncio import Redis

from azents.runtime.observability import RuntimeReplyDeliveryMetrics
from azents.worker import health
from azents.worker.health import HealthServer


class _ObservedMetrics(RuntimeReplyDeliveryMetrics):
    def __init__(self) -> None:
        super().__init__()
        self.recorded = asyncio.Event()

    def record_event_loop_lag(self, seconds: float) -> None:
        super().record_event_loop_lag(seconds)
        self.recorded.set()


@pytest.mark.asyncio
async def test_event_loop_observer_records_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metrics = _ObservedMetrics()
    server = HealthServer(
        Redis(),
        metrics=metrics,
    )
    monkeypatch.setattr(health, "_EVENT_LOOP_SAMPLE_INTERVAL_SECONDS", 0.0)
    observer = asyncio.create_task(server._observe_event_loop())
    try:
        await asyncio.wait_for(metrics.recorded.wait(), timeout=1)
    finally:
        observer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await observer

    assert metrics.snapshot().event_loop_lag_sample_count >= 1
