"""Runtime Web absolute credit and fair scheduler tests."""

import pytest

from azents_runtime_control.runtime_web_flow import (
    AbsoluteCreditWindow,
    FairFrameScheduler,
    HierarchicalCredit,
    QueueLane,
    ScheduledItem,
)

KIB = 1024


def test_absolute_credit_uses_monotonic_consumed_totals() -> None:
    credit = AbsoluteCreditWindow(initial_bytes=10, maximum_bytes=10)
    credit.reserve(7)
    assert credit.available_bytes == 3
    assert credit.update_consumed(5)
    assert credit.available_bytes == 8
    assert not credit.update_consumed(5)
    with pytest.raises(ValueError, match="decrease"):
        credit.update_consumed(4)
    with pytest.raises(ValueError, match="unsent"):
        credit.update_consumed(8)


def test_hierarchical_credit_prechecks_both_windows() -> None:
    stream = AbsoluteCreditWindow(initial_bytes=10, maximum_bytes=10)
    session = AbsoluteCreditWindow(initial_bytes=5, maximum_bytes=5)
    credit = HierarchicalCredit(stream=stream, session=session)
    with pytest.raises(ValueError, match="exhausted"):
        credit.reserve(6)
    assert stream.sent_total == 0
    assert session.sent_total == 0


def test_hierarchical_credit_prechecks_overflow_in_both_windows() -> None:
    stream = AbsoluteCreditWindow(initial_bytes=10, maximum_bytes=10)
    session = AbsoluteCreditWindow(initial_bytes=10, maximum_bytes=10)
    session.sent_total = (1 << 64) - 1
    session.consumed_total = (1 << 64) - 1
    credit = HierarchicalCredit(stream=stream, session=session)
    with pytest.raises(ValueError, match="overflow"):
        credit.reserve(1)
    assert stream.sent_total == 0
    assert session.sent_total == (1 << 64) - 1


def test_hierarchical_credit_consumption_update_is_atomic_and_closed_fenced() -> None:
    stream = AbsoluteCreditWindow(initial_bytes=10, maximum_bytes=10)
    session = AbsoluteCreditWindow(initial_bytes=10, maximum_bytes=10)
    credit = HierarchicalCredit(stream=stream, session=session)
    credit.reserve(8)
    with pytest.raises(ValueError, match="unsent"):
        credit.update_consumed(
            stream_consumed_total=5,
            session_consumed_total=9,
        )
    assert stream.consumed_total == 0
    assert session.consumed_total == 0
    credit.close()
    with pytest.raises(ValueError, match="closed"):
        credit.reserve(1)
    with pytest.raises(ValueError, match="closed"):
        credit.update_consumed(
            stream_consumed_total=1,
            session_consumed_total=1,
        )


def test_scheduler_prioritizes_control_then_latency() -> None:
    scheduler: FairFrameScheduler[str] = FairFrameScheduler(
        latency_capacity_bytes=1024,
        data_capacity_bytes=256 * KIB,
        quantum_bytes=64 * KIB,
        maximum_priority_items_before_data=4,
    )
    scheduler.enqueue(ScheduledItem(QueueLane.DATA, 1, 64 * KIB, "data"))
    scheduler.enqueue(ScheduledItem(QueueLane.LATENCY, None, 1, "head"))
    scheduler.enqueue(ScheduledItem(QueueLane.CONTROL, None, 1, "cancel"))
    assert scheduler.pop() == ScheduledItem(QueueLane.CONTROL, None, 1, "cancel")
    assert scheduler.pop() == ScheduledItem(QueueLane.LATENCY, None, 1, "head")
    assert scheduler.pop() == ScheduledItem(QueueLane.DATA, 1, 64 * KIB, "data")
    assert scheduler.pop() is None


def test_scheduler_serves_independent_data_streams_fairly() -> None:
    scheduler: FairFrameScheduler[str] = FairFrameScheduler(
        latency_capacity_bytes=1024,
        data_capacity_bytes=1024 * KIB,
        quantum_bytes=64 * KIB,
        maximum_priority_items_before_data=4,
    )
    scheduler.enqueue(ScheduledItem(QueueLane.DATA, 1, 128 * KIB, "one-a"))
    scheduler.enqueue(ScheduledItem(QueueLane.DATA, 1, 128 * KIB, "one-b"))
    scheduler.enqueue(ScheduledItem(QueueLane.DATA, 2, 64 * KIB, "two"))
    assert scheduler.pop() == ScheduledItem(QueueLane.DATA, 2, 64 * KIB, "two")
    assert scheduler.pop() == ScheduledItem(QueueLane.DATA, 1, 128 * KIB, "one-a")
    assert scheduler.pop() == ScheduledItem(QueueLane.DATA, 1, 128 * KIB, "one-b")


def test_scheduler_enforces_control_reserve() -> None:
    scheduler: FairFrameScheduler[bytes] = FairFrameScheduler(
        latency_capacity_bytes=1024,
        data_capacity_bytes=64 * KIB,
        quantum_bytes=64 * KIB,
        maximum_priority_items_before_data=4,
    )
    for _ in range(16):
        scheduler.enqueue(ScheduledItem(QueueLane.CONTROL, None, 16 * KIB, b"control"))
    with pytest.raises(ValueError, match="control reserve"):
        scheduler.enqueue(ScheduledItem(QueueLane.CONTROL, None, 1, b"overflow"))


def test_scheduler_enforces_control_frame_limit() -> None:
    scheduler: FairFrameScheduler[bytes] = FairFrameScheduler(
        latency_capacity_bytes=1024,
        data_capacity_bytes=64 * KIB,
        quantum_bytes=64 * KIB,
        maximum_priority_items_before_data=4,
    )
    with pytest.raises(ValueError, match="control frame"):
        scheduler.enqueue(
            ScheduledItem(QueueLane.CONTROL, None, 16 * KIB + 1, b"oversized")
        )


def test_scheduler_accumulates_deficit_for_large_frame() -> None:
    scheduler: FairFrameScheduler[str] = FairFrameScheduler(
        latency_capacity_bytes=1024,
        data_capacity_bytes=512 * KIB,
        quantum_bytes=64 * KIB,
        maximum_priority_items_before_data=4,
    )
    scheduler.enqueue(ScheduledItem(QueueLane.DATA, 1, 256 * KIB, "large"))
    assert scheduler.pop() == ScheduledItem(QueueLane.DATA, 1, 256 * KIB, "large")


def test_scheduler_bounds_priority_burst_and_cleans_terminal_metadata() -> None:
    scheduler: FairFrameScheduler[str] = FairFrameScheduler(
        latency_capacity_bytes=1024,
        data_capacity_bytes=256 * KIB,
        quantum_bytes=64 * KIB,
        maximum_priority_items_before_data=2,
    )
    scheduler.set_weight(1, 4)
    scheduler.enqueue(ScheduledItem(QueueLane.DATA, 1, 64 * KIB, "data"))
    for value in ("control-1", "control-2", "control-3"):
        scheduler.enqueue(ScheduledItem(QueueLane.CONTROL, None, 1, value))
    first = scheduler.pop()
    second = scheduler.pop()
    third = scheduler.pop()
    assert first is not None and first.value == "control-1"
    assert second is not None and second.value == "control-2"
    assert third is not None and third.value == "data"
    assert 1 not in scheduler.data
    assert 1 not in scheduler.deficits
    assert 1 not in scheduler.weights
    assert 1 not in scheduler.active_streams


def test_scheduler_bounds_control_burst_before_latency_with_data_waiting() -> None:
    scheduler: FairFrameScheduler[str] = FairFrameScheduler(
        latency_capacity_bytes=1024,
        data_capacity_bytes=256 * KIB,
        quantum_bytes=64 * KIB,
        maximum_priority_items_before_data=2,
    )
    scheduler.enqueue(ScheduledItem(QueueLane.DATA, 1, 64 * KIB, "data"))
    scheduler.enqueue(ScheduledItem(QueueLane.LATENCY, None, 1, "head"))
    for value in ("control-1", "control-2", "control-3"):
        scheduler.enqueue(ScheduledItem(QueueLane.CONTROL, None, 1, value))
    values = []
    for _ in range(4):
        item = scheduler.pop()
        assert item is not None
        values.append(item.value)
    assert values == ["control-1", "control-2", "data", "head"]
