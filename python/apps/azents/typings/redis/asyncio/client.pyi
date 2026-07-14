"""Correct redis.asyncio client return types for static analysis.

redis-py declares async methods as ``Awaitable[T] | T``, which makes pyright
report errors such as ``int is not awaitable`` for the asyncio client.
https://github.com/redis/redis-py/issues/3107
"""

import datetime
from collections.abc import AsyncIterator, Callable
from typing import Any, Self, overload

class PubSub:
    async def subscribe(
        self, *args: bytes | str | memoryview, **kwargs: Callable[..., Any]
    ) -> None: ...
    async def unsubscribe(self, *args: bytes | str | memoryview) -> None: ...
    def listen(self) -> AsyncIterator[dict[str, Any]]: ...
    async def get_message(
        self, ignore_subscribe_messages: bool = False, timeout: float | None = 0.0
    ) -> dict[str, Any] | None: ...
    async def aclose(self) -> None: ...
    async def close(self) -> None: ...

class Redis:
    @classmethod
    def from_url(
        cls, url: str, *, single_connection_client: bool = False, **kwargs: Any
    ) -> Self: ...
    def pubsub(self, **kwargs: Any) -> PubSub: ...
    async def rpush(
        self, name: bytes | str | memoryview, *values: bytes | str | int | float
    ) -> int: ...
    async def lpush(
        self, name: bytes | str | memoryview, *values: bytes | str | int | float
    ) -> int: ...
    async def lrem(
        self,
        name: bytes | str | memoryview,
        count: int,
        value: bytes | str | int | float,
    ) -> int: ...
    async def lrange(
        self, name: bytes | str | memoryview, start: int, end: int
    ) -> list[bytes]: ...
    @overload
    async def lpop(
        self, name: bytes | str | memoryview, count: None = None
    ) -> bytes | None: ...
    @overload
    async def lpop(
        self, name: bytes | str | memoryview, count: int
    ) -> list[bytes] | None: ...
    async def xadd(
        self,
        name: bytes | str | memoryview,
        fields: dict[str | bytes, str | bytes | int | float],
        id: str | bytes | int = "*",
        maxlen: int | None = None,
        approximate: bool = True,
        nomkstream: bool = False,
        minid: str | bytes | int | None = None,
        limit: int | None = None,
    ) -> bytes: ...
    async def xgroup_create(
        self,
        name: bytes | str | memoryview,
        groupname: bytes | str | memoryview,
        id: str | bytes | int = "$",
        mkstream: bool = False,
        entries_read: int | None = None,
    ) -> bool: ...
    async def xreadgroup(
        self,
        groupname: str,
        consumername: str,
        streams: dict[bytes | str | memoryview, str | bytes | int],
        count: int | None = None,
        block: int | None = None,
        noack: bool = False,
    ) -> list[Any]: ...
    async def xack(
        self,
        name: bytes | str | memoryview,
        groupname: bytes | str | memoryview,
        *ids: str | bytes | int,
    ) -> int: ...
    async def xautoclaim(
        self,
        name: bytes | str | memoryview,
        groupname: bytes | str | memoryview,
        consumername: bytes | str | memoryview,
        min_idle_time: int,
        start_id: int | bytes | str | memoryview = "0-0",
        count: int | None = None,
        justid: bool = False,
    ) -> list[Any]: ...
    async def set(
        self,
        name: bytes | str | memoryview,
        value: bytes | str | int | float,
        ex: int | datetime.timedelta | None = None,
        px: int | datetime.timedelta | None = None,
        nx: bool = False,
        xx: bool = False,
        keepttl: bool = False,
        get: bool = False,
        exat: int | datetime.datetime | None = None,
        pxat: int | datetime.datetime | None = None,
    ) -> bool | None: ...
    async def get(self, name: bytes | str | memoryview) -> bytes | None: ...
    async def mget(
        self,
        keys: bytes | str | memoryview | list[bytes | str | memoryview],
        *args: bytes | str | memoryview,
    ) -> list[bytes | None]: ...
    async def eval(
        self,
        script: str,
        numkeys: int,
        *keys_and_args: bytes | str | memoryview | int | float,
    ) -> Any: ...
    async def publish(
        self,
        channel: bytes | str | memoryview,
        message: bytes | str | int | float,
        **kwargs: Any,
    ) -> int: ...
    async def expire(
        self,
        name: bytes | str | memoryview,
        time: int | datetime.timedelta,
        nx: bool = False,
        xx: bool = False,
        gt: bool = False,
        lt: bool = False,
    ) -> bool: ...
    async def delete(self, *names: bytes | str | memoryview) -> int: ...
    async def flushall(self, asynchronous: bool = False, **kwargs: Any) -> bool: ...
    async def xinfo_groups(
        self, name: bytes | str | memoryview
    ) -> list[dict[str, Any]]: ...
    async def xlen(self, name: bytes | str | memoryview) -> int: ...
    async def ttl(self, name: bytes | str | memoryview) -> int: ...
    async def aclose(self) -> None: ...
    async def close(self) -> None: ...
