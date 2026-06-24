"""redis.asyncio stub — async 메서드의 반환 타입을 Awaitable[T] | T에서 T로 교정.

redis-py가 sync/async 클래스를 앨리어싱하면서 반환 타입이 union으로 선언되는 문제 회피.
https://github.com/redis/redis-py/issues/3107
"""

from redis.asyncio.client import PubSub as PubSub
from redis.asyncio.client import Redis as Redis

__all__ = ["Redis", "PubSub"]
