import dataclasses
from typing import Generic, Never

from typing_extensions import TypeVar

T = TypeVar("T", default=Never)


@dataclasses.dataclass(frozen=True, eq=False)
class Event(Generic[T]):
    """
    Event type used by the event-sourcing helpers.
    """

    namespace: str
    name: str

    @property
    def key(self) -> str:
        return f"{self.namespace}:{self.name}"
