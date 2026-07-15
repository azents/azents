"""LivePartialBatcher tests."""

import asyncio

import pytest

from azents.worker.live.partial_batcher import LivePartialBatcher, LivePartialFlush


@pytest.mark.asyncio
async def test_content_deltas_flush_as_single_batch() -> None:
    """Flush multiple content deltas as one batch."""
    flushed: list[LivePartialFlush] = []

    async def flush(batch: LivePartialFlush) -> None:
        flushed.append(batch)

    batcher = LivePartialBatcher(flush, max_delay_seconds=10, max_chars=100)

    await batcher.append_content_delta(
        session_id="session-1",
        delta="hel",
        content_index=0,
    )
    await batcher.append_content_delta(
        session_id="session-1",
        delta="lo",
        content_index=0,
    )
    await batcher.flush_session("session-1")

    assert flushed == [
        LivePartialFlush(
            session_id="session-1",
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
        delta="a",
        content_index=0,
    )
    await batcher.append_content_delta(
        session_id="session-1",
        delta="b",
        content_index=1,
    )
    await batcher.flush_session("session-1")

    assert flushed == [
        LivePartialFlush(
            session_id="session-1",
            kind="content",
            content_index=0,
            delta="a",
        ),
        LivePartialFlush(
            session_id="session-1",
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

    await batcher.append_reasoning_delta(session_id="session-1", delta="think")
    await batcher.append_reasoning_delta(session_id="session-1", delta="ing")
    await batcher.flush_session("session-1")

    assert flushed == [
        LivePartialFlush(
            session_id="session-1",
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
        delta="hello",
        content_index=0,
    )

    assert flushed == [
        LivePartialFlush(
            session_id="session-1",
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

    await batcher.append_reasoning_delta(session_id="session-1", delta="a")
    await asyncio.sleep(0.05)

    assert flushed == [
        LivePartialFlush(
            session_id="session-1",
            kind="reasoning",
            content_index=None,
            delta="a",
        )
    ]


@pytest.mark.asyncio
async def test_discard_drops_buffer_and_cancels_timer() -> None:
    """Discard prevents buffered output from being published later."""
    flushed: list[LivePartialFlush] = []
    discarded: list[str] = []

    async def flush(batch: LivePartialFlush) -> None:
        flushed.append(batch)

    async def discard() -> None:
        discarded.append("session-1")

    batcher = LivePartialBatcher(flush, max_delay_seconds=0.01, max_chars=100)

    await batcher.append_content_delta(
        session_id="session-1",
        delta="failed prefix",
        content_index=0,
    )
    await batcher.discard_session("session-1", discard)
    await asyncio.sleep(0.05)

    assert discarded == ["session-1"]
    assert flushed == []


@pytest.mark.asyncio
async def test_discard_waits_for_in_flight_flush_before_removal() -> None:
    """Discard removal follows an already-started mutation."""
    flush_started = asyncio.Event()
    allow_flush = asyncio.Event()
    order: list[str] = []

    async def flush(batch: LivePartialFlush) -> None:
        del batch
        flush_started.set()
        await allow_flush.wait()
        order.append("flush")

    async def discard() -> None:
        order.append("discard")

    batcher = LivePartialBatcher(flush, max_delay_seconds=10, max_chars=1)
    append_task = asyncio.create_task(
        batcher.append_content_delta(
            session_id="session-1",
            delta="x",
            content_index=0,
        )
    )
    await flush_started.wait()

    discard_task = asyncio.create_task(batcher.discard_session("session-1", discard))
    await asyncio.sleep(0)

    assert order == []

    allow_flush.set()
    await append_task
    await discard_task

    assert order == ["flush", "discard"]


@pytest.mark.asyncio
async def test_next_attempt_appends_after_discard() -> None:
    """A clean buffer accepts output from the next attempt."""
    flushed: list[LivePartialFlush] = []

    async def flush(batch: LivePartialFlush) -> None:
        flushed.append(batch)

    async def discard() -> None:
        return

    batcher = LivePartialBatcher(flush, max_delay_seconds=10, max_chars=100)
    await batcher.append_reasoning_delta(session_id="session-1", delta="failed")
    await batcher.discard_session("session-1", discard)
    await batcher.append_reasoning_delta(session_id="session-1", delta="recovered")
    await batcher.flush_session("session-1")

    assert flushed == [
        LivePartialFlush(
            session_id="session-1",
            kind="reasoning",
            content_index=None,
            delta="recovered",
        )
    ]


@pytest.mark.asyncio
async def test_durable_transition_runs_after_flush_failure() -> None:
    """Durable replacement still removes a partially published live batch."""
    transitioned: list[str] = []

    async def flush(batch: LivePartialFlush) -> None:
        del batch
        raise RuntimeError("publish failed")

    async def transition() -> None:
        transitioned.append("durable")

    batcher = LivePartialBatcher(flush, max_delay_seconds=10, max_chars=100)
    await batcher.append_content_delta(
        session_id="session-1",
        delta="partial",
        content_index=0,
    )

    with pytest.raises(RuntimeError, match="publish failed"):
        await batcher.flush_session_and_transition("session-1", transition)

    assert transitioned == ["durable"]


@pytest.mark.asyncio
async def test_durable_transition_serializes_following_append() -> None:
    """Durable replacement holds the Session boundary through its mutation."""
    transition_started = asyncio.Event()
    allow_transition = asyncio.Event()
    order: list[str] = []

    async def flush(batch: LivePartialFlush) -> None:
        order.append(f"flush:{batch.delta}")

    async def transition() -> None:
        transition_started.set()
        await allow_transition.wait()
        order.append("transition")

    batcher = LivePartialBatcher(flush, max_delay_seconds=10, max_chars=100)
    await batcher.append_content_delta(
        session_id="session-1",
        delta="before",
        content_index=0,
    )
    transition_task = asyncio.create_task(
        batcher.flush_session_and_transition("session-1", transition)
    )
    await transition_started.wait()

    append_task = asyncio.create_task(
        batcher.append_content_delta(
            session_id="session-1",
            delta="after",
            content_index=0,
        )
    )
    await asyncio.sleep(0)

    assert not append_task.done()
    assert order == ["flush:before"]

    allow_transition.set()
    await transition_task
    await append_task
    await batcher.flush_session("session-1")

    assert order == ["flush:before", "transition", "flush:after"]
