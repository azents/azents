"""FastAPI dependency-injected event listener components."""

import abc
from typing import Annotated, Any, Callable, Generic, Self, TypeVar, overload

from fastapi import Depends

from azcommon import di

from .emitter import EventEmitter, EventListener
from .event import Event

T = TypeVar("T")


class EventListenerComponent(abc.ABC, Generic[T]):
    """
    Abstract base class for event listener components.
    """

    @abc.abstractmethod
    async def handle(self, event: T) -> None: ...


EventListenerComponentDependency = (
    Callable[..., EventListenerComponent[T]] | type[EventListenerComponent[T]]
)

D = TypeVar("D", bound=EventListenerComponentDependency[Any])


class ListenerBinder(object):
    """
    Bind event listener components to events.
    """

    def __init__(self) -> None:
        super().__init__()
        self.listeners: list[
            tuple[Event[Any], EventListenerComponentDependency[Any]]
        ] = []

    @classmethod
    def concat(cls, *listeners: "ListenerBinder") -> "ListenerBinder":
        """
        Combine multiple ListenerBinder instances.
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
        Register an event listener component.

        This method may be called directly or used as a decorator.
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
        Add another binder's listeners to this binder.
        """
        self.listeners.extend(other.listeners)
        return self

    def as_event_emitter(
        self, container: Annotated[di.Container, Depends(di.get_container)]
    ) -> EventEmitter:
        """
        Convert this binder to an EventEmitter.
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
