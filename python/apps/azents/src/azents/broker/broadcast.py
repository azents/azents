"""WebSocketBroadcast: Worker to WebSocket event broadcast.

Based on Redis Pub/Sub, allowing multiple WebSockets or tabs to receive events.
Operates independently from the existing broker ``publish_event()`` and
``subscribe_events()``.
"""

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager, suppress
from typing import TYPE_CHECKING, Protocol

from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

if TYPE_CHECKING:
    from azents.services.chat.live_events import InMemoryLiveEventStore

logger = logging.getLogger(__name__)

_CHANNEL_PREFIX = "azents:ws:"
_LIVE_EVENT_KEY_PREFIX = "azents:chat:"
_LIVE_EVENT_KEY_SUFFIX = ":live_events"
_LIVE_OWNER_GENERATION_FIELD = "__owner_generation__"
_SUBSCRIPTION_CONFIRMATION_TIMEOUT_SECONDS = 5.0

_PUBLISH_LIVE_PROJECTION_SCRIPT = """
if redis.call("HGET", KEYS[1], ARGV[1]) ~= ARGV[2] then
  return 0
end
redis.call("PUBLISH", KEYS[2], ARGV[3])
return 1
"""


class WebSocketBroadcastPublishError(Exception):
    """WebSocket broadcast publish failed."""


class _RedisPubSub(Protocol):
    """Redis PubSub operations used by WebSocket broadcast helpers."""

    async def get_message(
        self,
        *,
        ignore_subscribe_messages: bool,
        timeout: float,
    ) -> dict[str, object] | None:
        """Return the next available PubSub message."""
        ...

    def listen(self) -> AsyncIterator[dict[str, object]]:
        """Return the PubSub message stream."""
        ...


class BaseWebSocketBroadcast(ABC):
    """Transport-neutral opaque JSON event broadcast contract."""

    @abstractmethod
    async def publish(self, session_id: str, event_json: dict[str, object]) -> None:
        """Publish one JSON-serializable event."""
        ...

    @abstractmethod
    async def publish_live_projection(
        self,
        session_id: str,
        event_json: dict[str, object],
        *,
        owner_generation: int,
    ) -> bool:
        """Publish only while the current live projection owner matches."""
        ...

    @abstractmethod
    def subscribe(
        self, session_id: str
    ) -> AbstractAsyncContextManager[AsyncIterator[dict[str, object]]]:
        """Register a subscriber before entering the context."""
        ...


class WebSocketBroadcast(BaseWebSocketBroadcast):
    """Worker to WebSocket event broadcast based on Redis Pub/Sub."""

    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def publish(self, session_id: str, event_json: dict[str, object]) -> None:
        """Broadcast an event to every WebSocket for the session.

        :param session_id: Target session ID
        :param event_json: JSON-serializable event dict
        """
        channel = f"{_CHANNEL_PREFIX}{session_id}"
        data = json.dumps(event_json, ensure_ascii=False)
        try:
            await self.redis.publish(channel, data)
        except (RedisConnectionError, OSError) as exc:
            raise WebSocketBroadcastPublishError from exc

    async def publish_live_projection(
        self,
        session_id: str,
        event_json: dict[str, object],
        *,
        owner_generation: int,
    ) -> bool:
        """Publish only while the PostgreSQL-derived live writer fence matches."""
        channel = f"{_CHANNEL_PREFIX}{session_id}"
        live_key = f"{_LIVE_EVENT_KEY_PREFIX}{session_id}{_LIVE_EVENT_KEY_SUFFIX}"
        data = json.dumps(event_json, ensure_ascii=False)
        try:
            result = await self.redis.eval(
                _PUBLISH_LIVE_PROJECTION_SCRIPT,
                2,
                live_key,
                channel,
                _LIVE_OWNER_GENERATION_FIELD,
                owner_generation,
                data,
            )
        except (RedisConnectionError, OSError) as exc:
            raise WebSocketBroadcastPublishError from exc
        return result == 1

    @asynccontextmanager
    async def subscribe(
        self, session_id: str
    ) -> AsyncIterator[AsyncIterator[dict[str, object]]]:
        """Subscribe to session events for use by the WebSocket send_loop.

        :param session_id: Session ID to subscribe to
        """
        channel = f"{_CHANNEL_PREFIX}{session_id}"
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(channel)
        try:
            await self._wait_for_subscription_confirmation(pubsub, channel)
            yield self._iter_events(pubsub)
        finally:
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.aclose()
            except RedisConnectionError, OSError:
                logger.debug(
                    "Redis connection lost during broadcast cleanup",
                    extra={"channel": channel},
                )
                with suppress(RedisConnectionError, OSError):
                    await pubsub.aclose()

    @staticmethod
    async def _wait_for_subscription_confirmation(
        pubsub: _RedisPubSub,
        channel: str,
    ) -> None:
        """Wait until Redis confirms registration for the requested channel."""
        async with asyncio.timeout(_SUBSCRIPTION_CONFIRMATION_TIMEOUT_SECONDS):
            while True:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=False,
                    timeout=1.0,
                )
                if not isinstance(message, dict) or message.get("type") != "subscribe":
                    continue
                confirmed_channel = message.get("channel")
                if isinstance(confirmed_channel, bytes):
                    confirmed_channel = confirmed_channel.decode("utf-8")
                if confirmed_channel == channel:
                    return

    @staticmethod
    async def _iter_events(
        pubsub: _RedisPubSub,
    ) -> AsyncIterator[dict[str, object]]:
        """Convert Pub/Sub messages to dict and yield them."""
        async for raw_message in pubsub.listen():
            if raw_message["type"] != "message":
                continue
            raw_data = raw_message["data"]
            assert isinstance(raw_data, (str, bytes))
            yield json.loads(raw_data)


class InMemoryWebSocketBroadcast(BaseWebSocketBroadcast):
    """Process-local fan-out sharing the actual in-memory live owner store.

    This adapter supports only subscribers in the same application context.
    It is explicitly selected, never a fallback for a Redis failure.
    """

    def __init__(self, live_store: "InMemoryLiveEventStore") -> None:
        self.live_store = live_store
        self._subscribers: dict[str, set[asyncio.Queue[str | None]]] = {}
        self._closed = False

    def _publish_serialized(self, session_id: str, data: str) -> None:
        if self._closed:
            raise WebSocketBroadcastPublishError("Broadcast is closed")
        for queue in self._subscribers.get(session_id, ()):
            queue.put_nowait(data)

    async def publish(self, session_id: str, event_json: dict[str, object]) -> None:
        """Serialize before fan-out, just like the Redis transport."""
        self._publish_serialized(session_id, json.dumps(event_json, ensure_ascii=False))

    async def publish_live_projection(
        self,
        session_id: str,
        event_json: dict[str, object],
        *,
        owner_generation: int,
    ) -> bool:
        """Check the shared fence and fan out without yielding between them."""
        data = json.dumps(event_json, ensure_ascii=False)
        if not self.live_store.owns_generation(session_id, owner_generation):
            return False
        self._publish_serialized(session_id, data)
        return True

    @asynccontextmanager
    async def subscribe(
        self, session_id: str
    ) -> AsyncIterator[AsyncIterator[dict[str, object]]]:
        """Register synchronously; unregister on exit, including cancellation."""
        if self._closed:
            raise WebSocketBroadcastPublishError("Broadcast is closed")
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        subscribers = self._subscribers.setdefault(session_id, set())
        subscribers.add(queue)
        try:
            yield self._iter_queue(queue)
        finally:
            subscribers.discard(queue)
            if not subscribers:
                self._subscribers.pop(session_id, None)

    @staticmethod
    async def _iter_queue(
        queue: asyncio.Queue[str | None],
    ) -> AsyncIterator[dict[str, object]]:
        while (data := await queue.get()) is not None:
            yield json.loads(data)

    async def aclose(self) -> None:
        """End all local subscriptions and reject further publication."""
        self._closed = True
        for subscribers in self._subscribers.values():
            for queue in subscribers:
                queue.put_nowait(None)
        self._subscribers.clear()
