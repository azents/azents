"""Application context.

Container managing resources that live during application lifetime
(DB connections, AWS clients, etc.).
"""

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from typing import (
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Generic,
    Protocol,
    Self,
    TypeVar,
    cast,
)

from azcommon.sync import KeyLock

C = TypeVar("C")
T_co = TypeVar("T_co", covariant=True)


class VariableFactory(Protocol[T_co]):
    """Variable factory protocol."""

    def __call__(self) -> AsyncIterator[T_co]: ...


class AppContextClosedError(RuntimeError):
    """Raised when resources are requested after context teardown starts."""


class AppContext(Generic[C]):
    """Application context.

    Holds Config and lazily creates/caches resources that live during
    application lifetime (DB connections, AWS clients, etc.).
    """

    def __init__(self, config: C) -> None:
        super().__init__()
        self.config = config
        self._lock = KeyLock()
        self._pre_close_stack = AsyncExitStack()
        self._stack = AsyncExitStack()
        self._variables: dict[str, Any] = {}
        self._variable_condition = asyncio.Condition()
        self._active_variable_operations = 0
        self._accept_variables = True
        self._accept_pre_close_callbacks = True
        self._close_lock = asyncio.Lock()
        self._closed = False

    async def get_variable(self, key: str, factory: VariableFactory[T_co]) -> T_co:
        """Lazily create variable or return from cache."""
        async with self._variable_condition:
            if not self._accept_variables:
                raise AppContextClosedError("Application context is closing.")
            self._active_variable_operations += 1
        try:
            if key not in self._variables:
                async with self._lock(key):
                    cm = asynccontextmanager(factory)
                    if key not in self._variables:
                        self._variables[key] = await self._stack.enter_async_context(
                            cm()
                        )
            return cast(T_co, self._variables[key])
        finally:
            async with self._variable_condition:
                self._active_variable_operations -= 1
                if self._active_variable_operations == 0:
                    self._variable_condition.notify_all()

    def add_pre_close_callback(
        self,
        callback: Callable[[], Awaitable[None]],
    ) -> None:
        """Register cleanup that runs before ordinary managed resources close."""
        if not self._accept_pre_close_callbacks:
            raise AppContextClosedError("Application context is closing.")
        self._pre_close_stack.push_async_callback(callback)

    async def close(self) -> None:
        """Drain pre-close owners, then close every managed resource."""
        async with self._close_lock:
            if self._closed:
                return
            self._accept_pre_close_callbacks = False
            try:
                await self._pre_close_stack.aclose()
            finally:
                async with self._variable_condition:
                    self._accept_variables = False
                    await self._variable_condition.wait_for(
                        lambda: self._active_variable_operations == 0
                    )
                    stack = self._stack
                    self._variables = {}
                    self._closed = True
                await stack.aclose()

    async def __aenter__(self) -> Self:
        if self._closed:
            raise AppContextClosedError("Application context is closed.")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        await self.close()
