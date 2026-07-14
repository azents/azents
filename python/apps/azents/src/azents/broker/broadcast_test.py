"""WebSocket broadcast subscription barrier tests."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
from redis.asyncio import Redis
from redis.exceptions import TimeoutError as RedisTimeoutError

import azents.broker.broadcast as broadcast_module
from azents.broker.broadcast import (
    WebSocketBroadcast,
    WebSocketBroadcastPublishError,
)


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


class _HangingSubscribePubSub(_PubSub):
    """PubSub whose initial subscribe command never returns."""

    async def subscribe(self, channel: str) -> None:
        """Record the channel, then force the registration deadline to fire."""
        self.subscribed_channel = channel
        await asyncio.Event().wait()


class _HangingCleanupPubSub(_PubSub):
    """PubSub whose cleanup operations both stall indefinitely."""

    def __init__(self) -> None:
        super().__init__()
        self.unsubscribe_started = False
        self.close_started = False

    async def unsubscribe(self, channel: str) -> None:
        """Record cleanup and force its independent deadline to fire."""
        assert channel == self.subscribed_channel
        self.unsubscribe_started = True
        await asyncio.Event().wait()

    async def aclose(self) -> None:
        """Record close and force its independent deadline to fire."""
        self.close_started = True
        await asyncio.Event().wait()


class _TimeoutRedis:
    """Redis double whose publish attempt times out."""

    async def publish(self, channel: str, data: str) -> None:
        """Raise the Redis client timeout surfaced by a stalled publish."""
        del channel, data
        raise RedisTimeoutError("publish timed out")


class _HangingRedis:
    """Redis double whose publish never completes on its own."""

    async def publish(self, channel: str, data: str) -> None:
        """Wait forever so the broadcast deadline must cancel the call."""
        del channel, data
        await asyncio.Event().wait()


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


@pytest.mark.asyncio
async def test_subscribe_hard_bounds_hanging_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stuck Redis subscribe cannot leave the WebSocket handshake pending."""
    monkeypatch.setattr(
        broadcast_module,
        "_SUBSCRIPTION_CONFIRMATION_TIMEOUT_SECONDS",
        0.01,
    )
    pubsub = _HangingSubscribePubSub()
    broadcast = WebSocketBroadcast(cast(Redis, cast(Any, _Redis(pubsub))))

    with pytest.raises(TimeoutError):
        async with broadcast.subscribe("session-1"):
            pytest.fail("subscription must not open without Redis confirmation")

    assert pubsub.closed


@pytest.mark.asyncio
async def test_subscribe_hard_bounds_each_cleanup_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broken Redis connection cannot delay WebSocket teardown forever."""
    monkeypatch.setattr(
        broadcast_module,
        "_SUBSCRIPTION_CLEANUP_TIMEOUT_SECONDS",
        0.01,
    )
    pubsub = _HangingCleanupPubSub()
    pubsub.confirmation_ready.set()
    broadcast = WebSocketBroadcast(cast(Redis, cast(Any, _Redis(pubsub))))

    async def subscribe_once() -> None:
        async with broadcast.subscribe("session-1"):
            return

    await asyncio.wait_for(subscribe_once(), timeout=1)

    assert pubsub.unsubscribe_started
    assert pubsub.close_started


@pytest.mark.asyncio
async def test_publish_normalizes_redis_timeout() -> None:
    """Redis timeouts are normalized for post-commit best-effort callers."""
    broadcast = WebSocketBroadcast(cast(Redis, cast(Any, _TimeoutRedis())))

    with pytest.raises(WebSocketBroadcastPublishError) as exc_info:
        await broadcast.publish("session-1", {"type": "event"})

    assert isinstance(exc_info.value.__cause__, RedisTimeoutError)


@pytest.mark.asyncio
async def test_publish_hard_bounds_hanging_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every caller gets a hard deadline even without Redis socket timeout."""
    monkeypatch.setattr(broadcast_module, "_PUBLISH_TIMEOUT_SECONDS", 0.01)
    broadcast = WebSocketBroadcast(cast(Redis, cast(Any, _HangingRedis())))

    with pytest.raises(WebSocketBroadcastPublishError) as exc_info:
        await asyncio.wait_for(
            broadcast.publish("session-1", {"type": "event"}),
            timeout=1,
        )

    assert isinstance(exc_info.value.__cause__, TimeoutError)
