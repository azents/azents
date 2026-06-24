"""
FastAPI 의존성 주입 기반 이벤트 리스너 컴포넌트.
"""

import abc
from typing import Annotated, Any, Callable, Generic, Self, TypeVar, overload

from fastapi import Depends

from azcommon import di

from .emitter import EventEmitter, EventListener
from .event import Event

T = TypeVar("T")


class EventListenerComponent(abc.ABC, Generic[T]):
    """
    이벤트 리스너 컴포넌트의 추상 기반 클래스.
    """

    @abc.abstractmethod
    async def handle(self, event: T) -> None: ...


EventListenerComponentDependency = (
    Callable[..., EventListenerComponent[T]] | type[EventListenerComponent[T]]
)

D = TypeVar("D", bound=EventListenerComponentDependency[Any])


class ListenerBinder(object):
    """
    이벤트 리스너 컴포넌트를 이벤트에 바인딩합니다.
    """

    def __init__(self) -> None:
        super().__init__()
        self.listeners: list[
            tuple[Event[Any], EventListenerComponentDependency[Any]]
        ] = []

    @classmethod
    def concat(cls, *listeners: "ListenerBinder") -> "ListenerBinder":
        """
        여러 ListenerBinder를 하나로 합칩니다.
        """
        instance = cls()
        for listener in listeners:
            instance.extend(listener)
        return instance

    @overload
    def listen(
        self,
        event: Event[T],
        component_dependency: EventListenerComponentDependency[T],
    ) -> Self: ...

    @overload
    def listen(
        self,
        event: Event[T],
    ) -> Callable[[D], D]: ...

    def listen(
        self,
        event: Event[T],
        component_dependency: EventListenerComponentDependency[T] | None = None,
    ) -> Self | Callable[[D], D]:
        """
        이벤트 리스너 컴포넌트를 등록합니다.

        메서드 호출 또는 데코레이터로 사용할 수 있습니다.
        """
        if component_dependency is not None:
            self.listen(event)(component_dependency)
            return self

        def decorator(component_dependency: D) -> D:
            self.listeners.append((event, component_dependency))
            return component_dependency

        return decorator

    def extend(self, other: "ListenerBinder") -> Self:
        """
        다른 바인더의 리스너들을 이 바인더에 추가합니다.
        """
        self.listeners.extend(other.listeners)
        return self

    def as_event_emitter(
        self, container: Annotated[di.Container, Depends(di.get_container)]
    ) -> EventEmitter:
        """
        이 바인더를 EventEmitter로 변환합니다.
        """
        builder = EventEmitter.builder()
        for event, component_dependency in self.listeners:
            builder.listen(
                event, self._component_to_listener(container, component_dependency)
            )
        return builder.build()

    def _component_to_listener(
        self,
        container: di.Container,
        component_dependency: EventListenerComponentDependency[T],
    ) -> EventListener[T]:
        async def listen(event: T) -> None:
            async with container.copy() as listener_container:
                listener = await listener_container.solve(component_dependency)
                await listener.handle(event)

        return listen
