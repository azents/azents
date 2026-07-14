"""Correct redis.asyncio method return types from ``Awaitable[T] | T`` to ``T``.

redis-py aliases sync and async classes in a way that exposes union return types.
https://github.com/redis/redis-py/issues/3107
"""

from redis.asyncio.client import PubSub as PubSub
from redis.asyncio.client import Redis as Redis

__all__ = ["Redis", "PubSub"]
