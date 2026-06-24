"""WebSocketBroadcast: Worker to WebSocket event broadcast.

Based on Redis Pub/Sub, allowing multiple WebSockets or tabs to receive events.
Operates independently from the existing broker ``publish_event()`` and
``subscribe_events()``.
"""

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

logger = logging.getLogger(__name__)

_CHANNEL_PREFIX = "azents:ws:"


class WebSocketBroadcast:
    """Worker to WebSocket event broadcast based on Redis Pub/Sub."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def publish(self, session_id: str, event_json: dict[str, object]) -> None:
        """Broadcast an event to every WebSocket for the session.

        :param session_id: Target session ID
        :param event_json: JSON-serializable event dict
        """
        channel = f"{_CHANNEL_PREFIX}{session_id}"
        data = json.dumps(event_json, ensure_ascii=False)
        await self._redis.publish(channel, data)

    @asynccontextmanager
    async def subscribe(
        self, session_id: str
    ) -> AsyncIterator[AsyncIterator[dict[str, object]]]:
        """Subscribe to session events for use by the WebSocket send_loop.

        :param session_id: Session ID to subscribe to
        """
        channel = f"{_CHANNEL_PREFIX}{session_id}"
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(channel)
        try:
            yield self._iter_events(pubsub)
        finally:
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.aclose()
            except RedisConnectionError, OSError:
                logger.debug(
                    "Redis connection lost during broadcast cleanup channel=%s",
                    channel,
                )
                with suppress(RedisConnectionError, OSError):
                    await pubsub.aclose()

    @staticmethod
    async def _iter_events(
        pubsub: object,
    ) -> AsyncIterator[dict[str, object]]:
        """Convert Pub/Sub messages to dict and yield them."""
        async for raw_message in pubsub.listen():  # pyright: ignore[reportAttributeAccessIssue]  # redis.asyncio PubSub listen() typing is incomplete
            if raw_message["type"] != "message":
                continue
            raw_data = raw_message["data"]
            assert isinstance(raw_data, (str, bytes))
            yield json.loads(raw_data)
