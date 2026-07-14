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
async def test_discard_session_waits_for_inflight_flush() -> None:
    """Do not let clear ordering overtake a partial flush already in progress."""
    flush_started = asyncio.Event()
    release_flush = asyncio.Event()

    async def flush(batch: LivePartialFlush) -> None:
        del batch
        flush_started.set()
        await release_flush.wait()

    batcher = LivePartialBatcher(flush, max_delay_seconds=10, max_chars=100)
    await batcher.append_content_delta(
        session_id="session-1",
        delta="stale",
        content_index=0,
    )
    flush_task = asyncio.create_task(batcher.flush_session("session-1"))
    await asyncio.wait_for(flush_started.wait(), timeout=1)
    discard_task = asyncio.create_task(batcher.discard_session("session-1"))
    await asyncio.sleep(0)

    assert not discard_task.done()

    release_flush.set()
    await flush_task
    await discard_task


@pytest.mark.asyncio
async def test_discard_session_drops_pending_batch_and_timer() -> None:
    """Discard pending deltas without allowing their timer to flush later."""
    flushed: list[LivePartialFlush] = []

    async def flush(batch: LivePartialFlush) -> None:
        flushed.append(batch)

    batcher = LivePartialBatcher(flush, max_delay_seconds=0.01, max_chars=100)

    await batcher.append_content_delta(
        session_id="session-1",
        delta="stale",
        content_index=0,
    )
    await batcher.discard_session("session-1")
    await asyncio.sleep(0.05)
    await batcher.flush_session("session-1")

    assert flushed == []


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
