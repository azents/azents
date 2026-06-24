"""Session manager protocol."""

from typing import AsyncContextManager, Generic, Protocol, TypeVar

S_co = TypeVar("S_co", covariant=True)


class SessionManager(Generic[S_co], Protocol):
    """Factory protocol that creates sessions."""

    def __call__(self) -> AsyncContextManager[S_co]: ...
