"""Application context.

Container managing resources that live during application lifetime
(DB connections, AWS clients, etc.).
"""

from contextlib import AsyncExitStack, asynccontextmanager
from typing import (
    Any,
    AsyncIterator,
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


class AppContext(Generic[C]):
    """Application context.

    Holds Config and lazily creates/caches resources that live during
    application lifetime (DB connections, AWS clients, etc.).
    """

    def __init__(self, config: C) -> None:
        super().__init__()
        self.config = config
        self._lock = KeyLock()
        self._stack = AsyncExitStack()
        self._variables: dict[str, Any] = {}

    async def get_variable(self, key: str, factory: VariableFactory[T_co]) -> T_co:
        """Lazily create variable or return from cache."""
        if key not in self._variables:
            async with self._lock(key):
                cm = asynccontextmanager(factory)
                if key not in self._variables:
                    self._variables[key] = await self._stack.enter_async_context(cm())
        return cast(T_co, self._variables[key])

    async def close(self) -> None:
        """Clean up all resources."""
        stack = self._stack
        self._stack = AsyncExitStack()
        self._variables = {}
        await stack.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        await self.close()
