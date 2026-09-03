"""redis.asyncio stub — correct async method return types from Awaitable[T] | T to T.

Avoid the union return types declared when redis-py aliases sync and async classes.
https://github.com/redis/redis-py/issues/3107
"""

from redis.asyncio.client import PubSub as PubSub
from redis.asyncio.client import Redis as Redis

__all__ = ["Redis", "PubSub"]
