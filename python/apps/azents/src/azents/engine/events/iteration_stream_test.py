"""Shared native-stream tests without public event or Session envelopes."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest

from azents.engine.events.iteration import IterationValue
from azents.engine.events.iteration_stream import (
    InterruptedIterationStream,
    consume_iteration_stream,
)


@dataclass
class _TextStream:
    """Transient normalizer with a string-only output shape."""

    chunks: list[str]
    interrupted: bool

    def process_event(self, event: str) -> str:
        self.chunks.append(event)
        return event.upper()

    def interrupt(self) -> str:
        self.interrupted = True
        return "".join(self.chunks)


def _user_stop(error: asyncio.CancelledError) -> bool:
    return error.args == ("user-stop",)


async def _events(error: BaseException | None) -> AsyncIterator[str]:
    yield "one"
    yield "two"
    if error is not None:
        raise error


async def test_transient_native_output_is_normalized_before_incremental_delivery() -> (
    None
):
    stream = _TextStream(chunks=[], interrupted=False)
    delivered: list[str] = []

    async def on_incremental(delta: str) -> None:
        assert len(stream.chunks) == len(delivered) + 1
        delivered.append(delta)

    result = await consume_iteration_stream(
        events_factory=lambda: _events(None),
        output_stream=stream,
        on_incremental=on_incremental,
        is_user_stop=_user_stop,
    )
    assert isinstance(result, IterationValue)
    assert result.value is stream
    assert delivered == ["ONE", "TWO"]
    assert not stream.interrupted


async def test_user_stop_returns_partial_output_and_original_cancellation() -> None:
    stream = _TextStream(chunks=[], interrupted=False)
    cancellation = asyncio.CancelledError("user-stop")
    result = await consume_iteration_stream(
        events_factory=lambda: _events(cancellation),
        output_stream=stream,
        on_incremental=None,
        is_user_stop=_user_stop,
    )
    assert isinstance(result, InterruptedIterationStream)
    assert result.partial == "onetwo"
    assert result.cancellation is cancellation
    assert stream.interrupted


async def test_shutdown_cancellation_is_not_a_user_stop_or_completed_stream() -> None:
    stream = _TextStream(chunks=[], interrupted=False)
    cancellation = asyncio.CancelledError("worker-shutdown")
    with pytest.raises(asyncio.CancelledError) as raised:
        await consume_iteration_stream(
            events_factory=lambda: _events(cancellation),
            output_stream=stream,
            on_incremental=None,
            is_user_stop=_user_stop,
        )
    assert raised.value is cancellation
    assert not stream.interrupted


async def test_provider_failure_is_not_normalized_as_success() -> None:
    stream = _TextStream(chunks=[], interrupted=False)
    error = ValueError("native provider failure")
    with pytest.raises(ValueError) as raised:
        await consume_iteration_stream(
            events_factory=lambda: _events(error),
            output_stream=stream,
            on_incremental=None,
            is_user_stop=_user_stop,
        )
    assert raised.value is error
    assert not stream.interrupted


async def test_incremental_sink_failure_propagates_without_continuing_stream() -> None:
    stream = _TextStream(chunks=[], interrupted=False)
    error = RuntimeError("sink failed")

    async def on_incremental(delta: str) -> None:
        raise error

    with pytest.raises(RuntimeError) as raised:
        await consume_iteration_stream(
            events_factory=lambda: _events(None),
            output_stream=stream,
            on_incremental=on_incremental,
            is_user_stop=_user_stop,
        )
    assert raised.value is error
    assert stream.chunks == ["one"]
    assert not stream.interrupted


async def test_user_stop_during_synchronous_factory_is_normalized() -> None:
    stream = _TextStream(chunks=[], interrupted=False)
    cancellation = asyncio.CancelledError("user-stop")

    def factory() -> AsyncIterator[str]:
        raise cancellation

    result = await consume_iteration_stream(
        events_factory=factory,
        output_stream=stream,
        on_incremental=None,
        is_user_stop=_user_stop,
    )
    assert isinstance(result, InterruptedIterationStream)
    assert result.partial == ""
    assert result.cancellation is cancellation
    assert stream.interrupted


async def test_synchronous_factory_failure_is_not_hidden() -> None:
    stream = _TextStream(chunks=[], interrupted=False)
    error = RuntimeError("factory failed")

    def factory() -> AsyncIterator[str]:
        raise error

    with pytest.raises(RuntimeError) as raised:
        await consume_iteration_stream(
            events_factory=factory,
            output_stream=stream,
            on_incremental=None,
            is_user_stop=_user_stop,
        )
    assert raised.value is error
    assert not stream.interrupted
