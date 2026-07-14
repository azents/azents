"""LivePartialBatcher tests."""

import asyncio
from typing import Any, cast

import pytest

from azents.worker.live.partial_batcher import (
    LivePartialBatcher,
    LivePartialFlush,
    LivePartialFlushAttemptedError,
    LivePartialFlushCommittedCancellation,
)

RUN_ID = "run-1"


@pytest.mark.asyncio
async def test_content_deltas_flush_as_single_batch() -> None:
    """Flush multiple content deltas as one batch."""
    flushed: list[LivePartialFlush] = []

    async def flush(batch: LivePartialFlush) -> None:
        flushed.append(batch)

    batcher = LivePartialBatcher(flush, max_delay_seconds=10, max_chars=100)

    await batcher.append_content_delta(
        session_id="session-1",
        run_id=RUN_ID,
        delta="hel",
        content_index=0,
    )
    await batcher.append_content_delta(
        session_id="session-1",
        run_id=RUN_ID,
        delta="lo",
        content_index=0,
    )
    await batcher.flush_session("session-1")

    assert flushed == [
        LivePartialFlush(
            session_id="session-1",
            run_id=RUN_ID,
            kind="content",
            content_index=0,
            delta="hello",
        )
    ]


@pytest.mark.asyncio
async def test_content_index_buffers_are_separate() -> None:
    """Delta with different content index remains separate batch."""
    flushed: list[LivePartialFlush] = []

    async def flush(batch: LivePartialFlush) -> None:
        flushed.append(batch)

    batcher = LivePartialBatcher(flush, max_delay_seconds=10, max_chars=100)

    await batcher.append_content_delta(
        session_id="session-1",
        run_id=RUN_ID,
        delta="a",
        content_index=0,
    )
    await batcher.append_content_delta(
        session_id="session-1",
        run_id=RUN_ID,
        delta="b",
        content_index=1,
    )
    await batcher.flush_session("session-1")

    assert flushed == [
        LivePartialFlush(
            session_id="session-1",
            run_id=RUN_ID,
            kind="content",
            content_index=0,
            delta="a",
        ),
        LivePartialFlush(
            session_id="session-1",
            run_id=RUN_ID,
            kind="content",
            content_index=1,
            delta="b",
        ),
    ]


@pytest.mark.asyncio
async def test_reasoning_deltas_flush_as_single_batch() -> None:
    """Flush Reasoning delta as one batch."""
    flushed: list[LivePartialFlush] = []

    async def flush(batch: LivePartialFlush) -> None:
        flushed.append(batch)

    batcher = LivePartialBatcher(flush, max_delay_seconds=10, max_chars=100)

    await batcher.append_reasoning_delta(
        session_id="session-1", run_id=RUN_ID, delta="think"
    )
    await batcher.append_reasoning_delta(
        session_id="session-1", run_id=RUN_ID, delta="ing"
    )
    await batcher.flush_session("session-1")

    assert flushed == [
        LivePartialFlush(
            session_id="session-1",
            run_id=RUN_ID,
            kind="reasoning",
            content_index=None,
            delta="thinking",
        )
    ]


@pytest.mark.asyncio
async def test_size_threshold_flushes_immediately() -> None:
    """Flush immediately when character threshold is exceeded."""
    flushed: list[LivePartialFlush] = []

    async def flush(batch: LivePartialFlush) -> None:
        flushed.append(batch)

    batcher = LivePartialBatcher(flush, max_delay_seconds=10, max_chars=5)

    await batcher.append_content_delta(
        session_id="session-1",
        run_id=RUN_ID,
        delta="hello",
        content_index=0,
    )

    assert flushed == [
        LivePartialFlush(
            session_id="session-1",
            run_id=RUN_ID,
            kind="content",
            content_index=0,
            delta="hello",
        )
    ]


@pytest.mark.asyncio
async def test_timer_flushes_pending_batch() -> None:
    """Flush pending batch when timer expires."""
    flushed: list[LivePartialFlush] = []

    async def flush(batch: LivePartialFlush) -> None:
        flushed.append(batch)

    batcher = LivePartialBatcher(flush, max_delay_seconds=0.01, max_chars=100)

    await batcher.append_reasoning_delta(
        session_id="session-1", run_id=RUN_ID, delta="a"
    )
    await asyncio.sleep(0.05)

    assert flushed == [
        LivePartialFlush(
            session_id="session-1",
            run_id=RUN_ID,
            kind="reasoning",
            content_index=None,
            delta="a",
        )
    ]


@pytest.mark.asyncio
async def test_discard_session_drops_pending_batches_and_timer() -> None:
    """A new Run boundary removes old partials without invoking the callback."""
    flushed: list[LivePartialFlush] = []

    async def flush(batch: LivePartialFlush) -> None:
        flushed.append(batch)

    batcher = LivePartialBatcher(flush, max_delay_seconds=0.01, max_chars=100)
    await batcher.append_content_delta(
        session_id="session-1",
        run_id=RUN_ID,
        delta="stale",
        content_index=0,
    )

    await batcher.discard_session("session-1")
    await asyncio.sleep(0.05)
    await batcher.flush_session("session-1")

    assert flushed == []
    batcher_state = cast(Any, batcher)
    assert batcher_state._buffers == {}
    assert batcher_state._timers == {}
    assert batcher_state._flush_states == {}


@pytest.mark.asyncio
async def test_same_session_flush_callbacks_are_serialized() -> None:
    """Timer/manual and size flushes cannot overlap one live RMW projection."""
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    observed: list[str] = []
    projected = ""

    async def flush(batch: LivePartialFlush) -> None:
        nonlocal projected
        snapshot = projected
        observed.append(batch.delta)
        if batch.delta == "a":
            first_started.set()
            await release_first.wait()
        projected = snapshot + batch.delta

    batcher = LivePartialBatcher(flush, max_delay_seconds=10, max_chars=2)
    await batcher.append_content_delta(
        session_id="session-1",
        run_id=RUN_ID,
        delta="a",
        content_index=0,
    )
    first_flush = asyncio.create_task(batcher.flush_session("session-1"))
    await first_started.wait()

    size_flush = asyncio.create_task(
        batcher.append_content_delta(
            session_id="session-1",
            run_id=RUN_ID,
            delta="bb",
            content_index=0,
        )
    )
    await asyncio.sleep(0)

    assert observed == ["a"]
    release_first.set()
    await asyncio.gather(first_flush, size_flush)
    await asyncio.sleep(0)

    assert observed == ["a", "bb"]
    assert projected == "abb"
    batcher_state = cast(Any, batcher)
    assert batcher_state._buffers == {}
    assert batcher_state._timers == {}
    assert batcher_state._flush_states == {}


@pytest.mark.asyncio
async def test_cancelled_flush_waiter_releases_session_state() -> None:
    """Cancellation while waiting for a flush lock does not deadlock cleanup."""
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    projected = ""

    async def flush(batch: LivePartialFlush) -> None:
        nonlocal projected
        if batch.delta == "a":
            first_started.set()
            await release_first.wait()
        projected += batch.delta

    batcher = LivePartialBatcher(flush, max_delay_seconds=10, max_chars=2)
    await batcher.append_content_delta(
        session_id="session-1",
        run_id=RUN_ID,
        delta="a",
        content_index=0,
    )
    first_flush = asyncio.create_task(batcher.flush_session("session-1"))
    await first_started.wait()
    waiting_flush = asyncio.create_task(
        batcher.append_content_delta(
            session_id="session-1",
            run_id=RUN_ID,
            delta="bb",
            content_index=0,
        )
    )
    await asyncio.sleep(0)
    waiting_flush.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting_flush

    release_first.set()
    await first_flush
    await batcher.close_session("session-1")
    await asyncio.sleep(0)

    assert projected == "abb"
    batcher_state = cast(Any, batcher)
    assert batcher_state._buffers == {}
    assert batcher_state._timers == {}
    assert batcher_state._flush_states == {}


@pytest.mark.asyncio
async def test_failed_flush_restores_only_failed_and_pending_batches() -> None:
    """A callback failure preserves pending order without replaying prior success."""
    second_started = asyncio.Event()
    release_second = asyncio.Event()
    fail_second = True
    successful: list[LivePartialFlush] = []

    async def flush(batch: LivePartialFlush) -> None:
        nonlocal fail_second
        if batch.content_index == 1 and fail_second:
            second_started.set()
            await release_second.wait()
            fail_second = False
            raise RuntimeError("projection failed")
        successful.append(batch)

    batcher = LivePartialBatcher(flush, max_delay_seconds=10, max_chars=100)
    for content_index, delta in enumerate(("a", "b", "c")):
        await batcher.append_content_delta(
            session_id="session-1",
            run_id=RUN_ID,
            delta=delta,
            content_index=content_index,
        )

    first_flush = asyncio.create_task(batcher.flush_session("session-1"))
    await second_started.wait()
    await batcher.append_content_delta(
        session_id="session-1",
        run_id=RUN_ID,
        delta="B",
        content_index=1,
    )
    await batcher.append_content_delta(
        session_id="session-1",
        run_id=RUN_ID,
        delta="d",
        content_index=3,
    )
    release_second.set()

    with pytest.raises(RuntimeError, match="projection failed"):
        await first_flush
    await batcher.flush_session("session-1")

    assert successful == [
        LivePartialFlush(
            session_id="session-1",
            run_id=RUN_ID,
            kind="content",
            content_index=0,
            delta="a",
        ),
        LivePartialFlush(
            session_id="session-1",
            run_id=RUN_ID,
            kind="content",
            content_index=1,
            delta="bB",
        ),
        LivePartialFlush(
            session_id="session-1",
            run_id=RUN_ID,
            kind="content",
            content_index=2,
            delta="c",
        ),
        LivePartialFlush(
            session_id="session-1",
            run_id=RUN_ID,
            kind="content",
            content_index=3,
            delta="d",
        ),
    ]


@pytest.mark.asyncio
async def test_cancelled_callback_restores_older_delta_before_new_delta() -> None:
    """Cancellation restores the in-flight delta ahead of concurrent appends."""
    callback_started = asyncio.Event()
    block_callback = True
    successful: list[LivePartialFlush] = []

    async def flush(batch: LivePartialFlush) -> None:
        if block_callback:
            callback_started.set()
            await asyncio.Event().wait()
        successful.append(batch)

    batcher = LivePartialBatcher(flush, max_delay_seconds=10, max_chars=100)
    await batcher.append_content_delta(
        session_id="session-1",
        run_id=RUN_ID,
        delta="old",
        content_index=0,
    )
    flush_task = asyncio.create_task(batcher.flush_session("session-1"))
    await callback_started.wait()
    await batcher.append_content_delta(
        session_id="session-1",
        run_id=RUN_ID,
        delta="new",
        content_index=0,
    )

    flush_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await flush_task
    block_callback = False
    await batcher.flush_session("session-1")

    assert successful == [
        LivePartialFlush(
            session_id="session-1",
            run_id=RUN_ID,
            kind="content",
            content_index=0,
            delta="oldnew",
        )
    ]


@pytest.mark.asyncio
async def test_committed_cancellation_restores_only_pending_batches() -> None:
    """Cancellation after projection does not replay the committed partial."""
    committed: list[LivePartialFlush] = []
    cancel_first = True

    async def flush(batch: LivePartialFlush) -> None:
        nonlocal cancel_first
        committed.append(batch)
        if cancel_first:
            cancel_first = False
            raise LivePartialFlushCommittedCancellation

    batcher = LivePartialBatcher(flush, max_delay_seconds=10, max_chars=100)
    await batcher.append_content_delta(
        session_id="session-1",
        run_id=RUN_ID,
        delta="first",
        content_index=0,
    )
    await batcher.append_content_delta(
        session_id="session-1",
        run_id=RUN_ID,
        delta="second",
        content_index=1,
    )

    with pytest.raises(LivePartialFlushCommittedCancellation):
        await batcher.flush_session("session-1")
    await batcher.flush_session("session-1")

    assert committed == [
        LivePartialFlush(
            session_id="session-1",
            run_id=RUN_ID,
            kind="content",
            content_index=0,
            delta="first",
        ),
        LivePartialFlush(
            session_id="session-1",
            run_id=RUN_ID,
            kind="content",
            content_index=1,
            delta="second",
        ),
    ]


@pytest.mark.asyncio
async def test_ambiguous_attempt_restores_only_unattempted_batches() -> None:
    """A response-loss retry cannot duplicate the current live partial."""
    attempted: list[LivePartialFlush] = []
    fail_first = True

    async def flush(batch: LivePartialFlush) -> None:
        nonlocal fail_first
        attempted.append(batch)
        if fail_first:
            fail_first = False
            raise LivePartialFlushAttemptedError

    batcher = LivePartialBatcher(flush, max_delay_seconds=10, max_chars=100)
    await batcher.append_content_delta(
        session_id="session-1",
        run_id=RUN_ID,
        delta="ambiguous",
        content_index=0,
    )
    await batcher.append_content_delta(
        session_id="session-1",
        run_id=RUN_ID,
        delta="pending",
        content_index=1,
    )

    with pytest.raises(LivePartialFlushAttemptedError):
        await batcher.flush_session("session-1")
    await batcher.flush_session("session-1")

    assert attempted == [
        LivePartialFlush(
            session_id="session-1",
            run_id=RUN_ID,
            kind="content",
            content_index=0,
            delta="ambiguous",
        ),
        LivePartialFlush(
            session_id="session-1",
            run_id=RUN_ID,
            kind="content",
            content_index=1,
            delta="pending",
        ),
    ]


@pytest.mark.asyncio
async def test_timed_out_callback_restores_pending_batch() -> None:
    """Timeout cancellation leaves the popped batch available for retry."""
    block_callback = True
    successful: list[LivePartialFlush] = []

    async def flush(batch: LivePartialFlush) -> None:
        if block_callback:
            await asyncio.Event().wait()
        successful.append(batch)

    batcher = LivePartialBatcher(flush, max_delay_seconds=10, max_chars=100)
    await batcher.append_reasoning_delta(
        session_id="session-1", run_id=RUN_ID, delta="thought"
    )

    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.01):
            await batcher.flush_session("session-1")
    block_callback = False
    await batcher.flush_session("session-1")

    assert successful == [
        LivePartialFlush(
            session_id="session-1",
            run_id=RUN_ID,
            kind="reasoning",
            content_index=None,
            delta="thought",
        )
    ]
