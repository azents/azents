"""Tests for bounded HTTP file response lifecycle."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from starlette.requests import ClientDisconnect
from starlette.types import Message, Scope

from azents.api.public.file_download import FileDownloadResponse


class _BodyStream:
    """Single-use body stream double with terminal action evidence."""

    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.index = 0
        self.eof_reached = False
        self.complete_calls = 0
        self.abandon_calls = 0
        self.close_calls = 0
        self.events: list[str] = []

    def __aiter__(self) -> AsyncIterator[bytes]:
        """Return this body stream."""
        return self

    async def __anext__(self) -> bytes:
        """Yield one configured body chunk and then exact EOF."""
        if self.index == len(self.chunks):
            self.eof_reached = True
            raise StopAsyncIteration
        chunk = self.chunks[self.index]
        self.index += 1
        return chunk

    async def complete(self) -> None:
        """Record successful completion."""
        self.complete_calls += 1
        self.events.append("complete")

    async def abandon(self) -> None:
        """Record unsuccessful completion."""
        self.abandon_calls += 1
        self.events.append("abandon")

    async def aclose(self) -> None:
        """Record source closure."""
        self.close_calls += 1
        self.events.append("close")


def _scope(spec_version: str) -> Scope:
    """Return the smallest HTTP scope accepted by StreamingResponse."""
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": spec_version},
        "method": "GET",
        "path": "/download",
        "raw_path": b"/download",
        "query_string": b"",
        "headers": [],
        "scheme": "http",
        "client": ("127.0.0.1", 1),
        "server": ("127.0.0.1", 80),
    }


async def _never_receive() -> Message:
    """Keep the ASGI disconnect listener pending until response completion."""
    await asyncio.Event().wait()
    raise AssertionError("unreachable")


@pytest.mark.asyncio
async def test_normal_response_commits_only_after_final_send() -> None:
    """Normal response completion commits after final marker send returns."""
    body = _BodyStream([b"ab", b"cd"])
    messages: list[Message] = []

    async def send(message: Message) -> None:
        messages.append(message)
        if message["type"] == "http.response.body" and not message.get(
            "more_body", False
        ):
            body.events.append("final-send")

    response = FileDownloadResponse(
        body,
        media_type="application/octet-stream",
        headers={"Content-Disposition": "attachment; filename*=UTF-8''file.bin"},
    )
    await response(_scope("2.3"), _never_receive, send)

    assert body.eof_reached
    assert body.events.index("final-send") < body.events.index("complete")
    assert body.complete_calls == 1
    assert body.abandon_calls == 0
    assert body.close_calls == 1
    assert messages[-1] == {
        "type": "http.response.body",
        "body": b"",
        "more_body": False,
    }


@pytest.mark.asyncio
async def test_disconnect_during_final_send_abandons_even_after_source_eof() -> None:
    """ASGI 2.3 disconnect before final-send return is unsuccessful."""
    body = _BodyStream([b"data"])
    final_started = asyncio.Event()
    final_block = asyncio.Event()

    async def receive() -> Message:
        await final_started.wait()
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        if message["type"] == "http.response.body" and not message.get(
            "more_body", False
        ):
            final_started.set()
            await final_block.wait()

    response = FileDownloadResponse(
        body,
        media_type="application/octet-stream",
        headers={},
    )
    await response(_scope("2.3"), receive, send)

    assert body.eof_reached
    assert not response.final_send_succeeded
    assert body.complete_calls == 0
    assert body.abandon_calls == 1
    assert body.close_calls == 1


@pytest.mark.asyncio
async def test_send_error_abandons_under_asgi_24() -> None:
    """ASGI 2.4 send-side OSError does not become successful completion."""
    body = _BodyStream([b"data"])

    async def send(message: Message) -> None:
        if message["type"] == "http.response.body" and message.get("more_body"):
            raise OSError("client disconnected")

    response = FileDownloadResponse(
        body,
        media_type="application/octet-stream",
        headers={},
    )
    with pytest.raises(ClientDisconnect):
        await response(_scope("2.4"), _never_receive, send)

    assert not body.eof_reached
    assert not response.final_send_succeeded
    assert body.complete_calls == 0
    assert body.abandon_calls == 1
    assert body.close_calls == 1


@pytest.mark.asyncio
async def test_cancellation_after_final_send_keeps_completion_committed() -> None:
    """Cancellation scheduled after final send cannot switch to abandonment."""
    body = _BodyStream([b"data"])
    final_send_returned = False

    async def send(message: Message) -> None:
        nonlocal final_send_returned
        if message["type"] == "http.response.body" and not message.get(
            "more_body", False
        ):
            final_send_returned = True
            task = asyncio.current_task()
            assert task is not None
            task.cancel()

    response = FileDownloadResponse(
        body,
        media_type="application/octet-stream",
        headers={},
    )
    await response(_scope("2.4"), _never_receive, send)

    assert final_send_returned
    assert response.final_send_succeeded
    assert body.complete_calls == 1
    assert body.abandon_calls == 0
    assert body.close_calls == 1
