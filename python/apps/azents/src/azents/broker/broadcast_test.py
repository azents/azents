"""WebSocket broadcast subscription barrier tests."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
from redis.asyncio import Redis

from azents.broker.broadcast import WebSocketBroadcast


class _PubSub:
    """Controllable Redis PubSub test double."""

    def __init__(self) -> None:
        self.confirmation_ready = asyncio.Event()
        self.subscribed_channel: str | None = None
        self.closed = False

    async def subscribe(self, channel: str) -> None:
        """Record the requested channel without confirming it yet."""
        self.subscribed_channel = channel

    async def get_message(
        self,
        *,
        ignore_subscribe_messages: bool,
        timeout: float,
    ) -> dict[str, object]:
        """Return confirmation only after the test releases the barrier."""
        del ignore_subscribe_messages, timeout
        await self.confirmation_ready.wait()
        assert self.subscribed_channel is not None
        return {
            "type": "subscribe",
            "channel": self.subscribed_channel.encode(),
            "data": 1,
        }

    async def unsubscribe(self, channel: str) -> None:
        """Verify cleanup targets the subscribed channel."""
        assert channel == self.subscribed_channel

    async def aclose(self) -> None:
        """Record cleanup."""
        self.closed = True

    async def listen(self) -> AsyncIterator[object]:
        """Provide an empty async iterator when requested."""
        if False:
            yield None


class _Redis:
    """Redis test double exposing one PubSub instance."""

    def __init__(self, pubsub: _PubSub) -> None:
        self.value = pubsub

    def pubsub(self) -> _PubSub:
        """Return the controlled PubSub instance."""
        return self.value


@pytest.mark.asyncio
async def test_subscribe_context_waits_for_redis_confirmation() -> None:
    """The public subscription barrier opens only after Redis confirms it."""
    pubsub = _PubSub()
    broadcast = WebSocketBroadcast(cast(Redis, cast(Any, _Redis(pubsub))))
    entered = asyncio.Event()

    async def consume() -> None:
        async with broadcast.subscribe("session-1"):
            entered.set()

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    assert not entered.is_set()

    pubsub.confirmation_ready.set()
    await task

    assert entered.is_set()
    assert pubsub.closed
