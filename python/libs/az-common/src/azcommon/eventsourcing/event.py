import dataclasses
from typing import Generic, Never

from typing_extensions import TypeVar

T = TypeVar("T", default=Never)


@dataclasses.dataclass(frozen=True, eq=False)
class Event(Generic[T]):
    """
    이벤트 소싱을 위한 이벤트 클래스.
    """

    namespace: str
    name: str

    @property
    def key(self) -> str:
        return f"{self.namespace}:{self.name}"
