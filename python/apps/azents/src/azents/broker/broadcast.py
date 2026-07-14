"""WebSocketBroadcast: Worker to WebSocket event broadcast.

Based on Redis Pub/Sub, allowing multiple WebSockets or tabs to receive events.
Operates independently from the existing broker ``publish_event()`` and
``subscribe_events()``.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

_CHANNEL_PREFIX = "azents:ws:"
_SUBSCRIPTION_CONFIRMATION_TIMEOUT_SECONDS = 5.0
_SUBSCRIPTION_CLEANUP_TIMEOUT_SECONDS = 1.0
_PUBLISH_TIMEOUT_SECONDS = 0.25


class WebSocketBroadcastPublishError(Exception):
    """WebSocket broadcast publish failed."""


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
        try:
            async with asyncio.timeout(_PUBLISH_TIMEOUT_SECONDS):
                await self._redis.publish(channel, data)
        except asyncio.CancelledError:
            raise
        except (TimeoutError, RedisError, OSError) as exc:
            raise WebSocketBroadcastPublishError from exc

    @asynccontextmanager
    async def subscribe(
        self, session_id: str
    ) -> AsyncIterator[AsyncIterator[dict[str, object]]]:
        """Subscribe to session events for use by the WebSocket send_loop.

        :param session_id: Session ID to subscribe to
        """
        channel = f"{_CHANNEL_PREFIX}{session_id}"
        pubsub = self._redis.pubsub()
        try:
            async with asyncio.timeout(_SUBSCRIPTION_CONFIRMATION_TIMEOUT_SECONDS):
                await pubsub.subscribe(channel)
                await self._wait_for_subscription_confirmation(pubsub, channel)
            yield self._iter_events(pubsub)
        finally:
            await self._cleanup_subscription(pubsub, channel)

    @staticmethod
    async def _cleanup_subscription(pubsub: object, channel: str) -> None:
        """Best-effort close one subscription without delaying disconnects."""
        try:
            async with asyncio.timeout(_SUBSCRIPTION_CLEANUP_TIMEOUT_SECONDS):
                await pubsub.unsubscribe(channel)  # pyright: ignore[reportAttributeAccessIssue]  # redis.asyncio PubSub typing is incomplete
        except asyncio.CancelledError:
            raise
        except TimeoutError, RedisError, OSError:
            logger.debug(
                "Redis connection lost during broadcast unsubscribe channel=%s",
                channel,
            )

        try:
            async with asyncio.timeout(_SUBSCRIPTION_CLEANUP_TIMEOUT_SECONDS):
                await pubsub.aclose()  # pyright: ignore[reportAttributeAccessIssue]  # redis.asyncio PubSub typing is incomplete
        except asyncio.CancelledError:
            raise
        except TimeoutError, RedisError, OSError:
            logger.debug(
                "Redis connection lost during broadcast close channel=%s",
                channel,
            )

    @staticmethod
    async def _wait_for_subscription_confirmation(
        pubsub: object,
        channel: str,
    ) -> None:
        """Wait until Redis confirms registration for the requested channel."""
        while True:
            message = await pubsub.get_message(  # pyright: ignore[reportAttributeAccessIssue]  # redis.asyncio PubSub typing is incomplete
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
        pubsub: object,
    ) -> AsyncIterator[dict[str, object]]:
        """Convert Pub/Sub messages to dict and yield them."""
        async for raw_message in pubsub.listen():  # pyright: ignore[reportAttributeAccessIssue]  # redis.asyncio PubSub listen() typing is incomplete
            if raw_message["type"] != "message":
                continue
            raw_data = raw_message["data"]
            assert isinstance(raw_data, (str, bytes))
            yield json.loads(raw_data)
