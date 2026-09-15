"""Absolute credit accounting and bounded fair scheduling for Runtime Web."""

from __future__ import annotations

import dataclasses
import enum
from collections import deque
from typing import Generic, TypeVar

from azents_runtime_control.runtime_web_session import (
    CONTROL_RESERVE_BYTES,
    MANDATORY_DATA_FRAME_BYTES,
    MAX_CONTROL_FRAME_BYTES,
    SESSION_WINDOW_BYTES,
    STREAM_WINDOW_BYTES,
)

T = TypeVar("T")
_MAX_UINT64 = (1 << 64) - 1
_MIN_QUANTUM_BYTES = MANDATORY_DATA_FRAME_BYTES // 4


class QueueLane(enum.StrEnum):
    """Bounded writer lane."""

    CONTROL = "control"
    LATENCY = "latency"
    DATA = "data"


class AbsoluteCreditWindow:
    """Track sender credit from absolute peer consumption totals."""

    def __init__(self, *, initial_bytes: int, maximum_bytes: int) -> None:
        if initial_bytes <= 0 or maximum_bytes < initial_bytes:
            raise ValueError("Runtime Web credit window bounds are invalid")
        self.initial_bytes = initial_bytes
        self.maximum_bytes = maximum_bytes
        self.sent_total = 0
        self.consumed_total = 0

    @property
    def available_bytes(self) -> int:
        """Return current sender credit."""
        return min(
            self.maximum_bytes,
            self.initial_bytes + self.consumed_total - self.sent_total,
        )

    def reserve(self, size: int) -> None:
        """Reserve credit before queueing bytes for transport."""
        self.validate_reserve(size)
        self.sent_total += size

    def validate_reserve(self, size: int) -> None:
        """Validate one reservation without mutating local credit."""
        if size <= 0:
            raise ValueError("Runtime Web credit reservation must be positive")
        if size > self.available_bytes:
            raise ValueError("Runtime Web credit is exhausted")
        if self.sent_total > _MAX_UINT64 - size:
            raise ValueError("Runtime Web sent total would overflow")

    def validate_consumed(self, consumed_total: int) -> bool:
        """Validate one absolute total without mutating local credit."""
        if consumed_total < self.consumed_total:
            raise ValueError("Runtime Web consumed total must not decrease")
        if consumed_total > self.sent_total:
            raise ValueError("Runtime Web peer consumed unsent bytes")
        return consumed_total != self.consumed_total

    def update_consumed(self, consumed_total: int) -> bool:
        """Apply a monotonic absolute peer-consumption observation."""
        changed = self.validate_consumed(consumed_total)
        self.consumed_total = consumed_total
        return changed


class HierarchicalCredit:
    """Reserve and update one stream and its containing session atomically."""

    def __init__(
        self,
        *,
        stream: AbsoluteCreditWindow,
        session: AbsoluteCreditWindow,
    ) -> None:
        self.stream = stream
        self.session = session
        self.closed = False

    @classmethod
    def approved(cls) -> HierarchicalCredit:
        """Create the approved directional window pair."""
        return cls(
            stream=AbsoluteCreditWindow(
                initial_bytes=STREAM_WINDOW_BYTES,
                maximum_bytes=STREAM_WINDOW_BYTES,
            ),
            session=AbsoluteCreditWindow(
                initial_bytes=SESSION_WINDOW_BYTES,
                maximum_bytes=SESSION_WINDOW_BYTES,
            ),
        )

    @property
    def available_bytes(self) -> int:
        """Return credit available at both hierarchy levels."""
        if self.closed:
            return 0
        return min(self.stream.available_bytes, self.session.available_bytes)

    def reserve(self, size: int) -> None:
        """Atomically reserve stream and session credit."""
        if self.closed:
            raise ValueError("Runtime Web hierarchical credit is closed")
        if size > self.available_bytes:
            raise ValueError("Runtime Web hierarchical credit is exhausted")
        self.stream.validate_reserve(size)
        self.session.validate_reserve(size)
        self.stream.reserve(size)
        self.session.reserve(size)

    def update_consumed(
        self, *, stream_consumed_total: int, session_consumed_total: int
    ) -> bool:
        """Prevalidate and atomically apply both wire consumption totals."""
        if self.closed:
            raise ValueError("Runtime Web hierarchical credit is closed")
        stream_changed = self.stream.validate_consumed(stream_consumed_total)
        session_changed = self.session.validate_consumed(session_consumed_total)
        self.stream.consumed_total = stream_consumed_total
        self.session.consumed_total = session_consumed_total
        return stream_changed or session_changed

    def close(self) -> None:
        """Fence later reservations and WINDOW_UPDATE observations."""
        self.closed = True


@dataclasses.dataclass(frozen=True)
class ScheduledItem(Generic[T]):
    """One bounded item submitted to the writer scheduler."""

    lane: QueueLane
    stream_id: int | None
    size_bytes: int
    value: T

    def __post_init__(self) -> None:
        """Reject invalid lane identity and cost."""
        if self.size_bytes <= 0:
            raise ValueError("Runtime Web scheduled item size must be positive")
        if self.lane is QueueLane.DATA and (
            self.stream_id is None or self.stream_id <= 0
        ):
            raise ValueError("Runtime Web data item requires a positive stream ID")


class FairFrameScheduler(Generic[T]):
    """Bound priority service and fairly serve application-data streams."""

    def __init__(
        self,
        *,
        latency_capacity_bytes: int,
        data_capacity_bytes: int,
        quantum_bytes: int,
        maximum_priority_items_before_data: int,
    ) -> None:
        if latency_capacity_bytes <= 0 or data_capacity_bytes <= 0:
            raise ValueError("Runtime Web scheduler capacities must be positive")
        if not _MIN_QUANTUM_BYTES <= quantum_bytes <= MANDATORY_DATA_FRAME_BYTES:
            raise ValueError("Runtime Web scheduler quantum is outside approved bounds")
        if maximum_priority_items_before_data <= 0:
            raise ValueError("Runtime Web scheduler priority burst must be positive")
        self.latency_capacity_bytes = latency_capacity_bytes
        self.data_capacity_bytes = data_capacity_bytes
        self.quantum_bytes = quantum_bytes
        self.maximum_priority_items_before_data = maximum_priority_items_before_data
        self.control: deque[ScheduledItem[T]] = deque()
        self.latency: deque[ScheduledItem[T]] = deque()
        self.data: dict[int, deque[ScheduledItem[T]]] = {}
        self.active_streams: deque[int] = deque()
        self.deficits: dict[int, int] = {}
        self.weights: dict[int, int] = {}
        self.control_bytes = 0
        self.latency_bytes = 0
        self.data_bytes = 0
        self.priority_items_since_data = 0
        self.control_items_since_latency = 0

    def set_weight(self, stream_id: int, weight: int) -> None:
        """Set one positive bounded stream weight."""
        if stream_id <= 0 or not 1 <= weight <= 16:
            raise ValueError("Runtime Web scheduler weight is invalid")
        self.weights[stream_id] = weight

    def enqueue(self, item: ScheduledItem[T]) -> None:
        """Enqueue one item without exceeding its lane capacity."""
        if item.lane is QueueLane.CONTROL:
            if item.size_bytes > MAX_CONTROL_FRAME_BYTES:
                raise ValueError("Runtime Web control frame is too large")
            if self.control_bytes + item.size_bytes > CONTROL_RESERVE_BYTES:
                raise ValueError("Runtime Web control reserve is exhausted")
            self.control.append(item)
            self.control_bytes += item.size_bytes
            return
        if item.lane is QueueLane.LATENCY:
            if self.latency_bytes + item.size_bytes > self.latency_capacity_bytes:
                raise ValueError("Runtime Web latency lane is exhausted")
            self.latency.append(item)
            self.latency_bytes += item.size_bytes
            return
        assert item.stream_id is not None
        if self.data_bytes + item.size_bytes > self.data_capacity_bytes:
            raise ValueError("Runtime Web data lane is exhausted")
        stream_queue = self.data.setdefault(item.stream_id, deque())
        if not stream_queue:
            self.active_streams.append(item.stream_id)
            self.deficits.setdefault(item.stream_id, 0)
        stream_queue.append(item)
        self.data_bytes += item.size_bytes

    def pop(self) -> ScheduledItem[T] | None:
        """Pop the next bounded item without starving application data."""
        data_waiting = bool(self.active_streams)
        priority_allowed = (
            not data_waiting
            or self.priority_items_since_data < self.maximum_priority_items_before_data
        )
        control_allowed = (
            not self.latency
            or self.control_items_since_latency
            < self.maximum_priority_items_before_data
        )
        if self.control and priority_allowed and control_allowed:
            item = self.control.popleft()
            self.control_bytes -= item.size_bytes
            self.priority_items_since_data += 1
            self.control_items_since_latency += 1
            return item
        if self.latency and priority_allowed:
            item = self.latency.popleft()
            self.latency_bytes -= item.size_bytes
            self.priority_items_since_data += 1
            self.control_items_since_latency = 0
            return item
        item = self._pop_data()
        if item is not None:
            self.priority_items_since_data = 0
            return item
        if self.control:
            item = self.control.popleft()
            self.control_bytes -= item.size_bytes
            self.control_items_since_latency += 1
            return item
        if self.latency:
            item = self.latency.popleft()
            self.latency_bytes -= item.size_bytes
            self.control_items_since_latency = 0
            return item
        return None

    def _pop_data(self) -> ScheduledItem[T] | None:
        if not self.active_streams:
            return None
        attempts = sum(
            (
                self.data[stream_id][0].size_bytes
                + self.quantum_bytes * self.weights.get(stream_id, 1)
                - 1
            )
            // (self.quantum_bytes * self.weights.get(stream_id, 1))
            for stream_id in self.active_streams
        )
        for _ in range(attempts):
            stream_id = self.active_streams[0]
            stream_queue = self.data[stream_id]
            self.deficits[stream_id] += self.quantum_bytes * self.weights.get(
                stream_id, 1
            )
            item = stream_queue[0]
            if item.size_bytes <= self.deficits[stream_id]:
                stream_queue.popleft()
                self.deficits[stream_id] -= item.size_bytes
                self.data_bytes -= item.size_bytes
                self.active_streams.rotate(-1)
                if not stream_queue:
                    self.data.pop(stream_id)
                    self.active_streams.remove(stream_id)
                    self.deficits.pop(stream_id, None)
                    self.weights.pop(stream_id, None)
                return item
            self.active_streams.rotate(-1)
        return None

    def remove_stream(self, stream_id: int) -> None:
        """Remove queued data and all metadata for one terminal stream."""
        stream_queue = self.data.pop(stream_id, None)
        if stream_queue is not None:
            self.data_bytes -= sum(item.size_bytes for item in stream_queue)
        if stream_id in self.active_streams:
            self.active_streams.remove(stream_id)
        self.deficits.pop(stream_id, None)
        self.weights.pop(stream_id, None)
