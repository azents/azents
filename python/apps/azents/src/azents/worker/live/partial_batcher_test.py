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
