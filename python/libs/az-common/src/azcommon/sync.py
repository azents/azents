import asyncio
import collections
import contextlib
from typing import AsyncGenerator


class KeyLock(object):
    """
    Per-key async lock.
    """

    def __init__(self) -> None:
        super().__init__()
        self._locks: dict[str, asyncio.Lock] = {}
        self._waiters = collections.Counter[str]()

    async def acquire(self, key: str) -> None:
        """
        Acquire the lock for a key.
        """
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        self._waiters[key] += 1
        await self._locks[key].acquire()

    def release(self, key: str) -> None:
        """
        Release the lock for a key.
        """
        if key in self._locks:
            self._locks[key].release()
            self._waiters[key] -= 1
            if self._waiters[key] == 0:
                del self._locks[key]
                del self._waiters[key]

    @contextlib.asynccontextmanager
    async def __call__(self, key: str) -> AsyncGenerator[None, None]:
        """
        Enter a critical section for a key.
        """
        await self.acquire(key)
        try:
            yield
        finally:
            self.release(key)
