import contextvars
import logging
from collections.abc import Collection, Mapping
from typing import Any, Callable, Coroutine, Self

from typing_extensions import TypeVar

from azcommon.sync import KeyLock

from .event import Event

logger = logging.getLogger(__name__)

T = TypeVar("T")

EventListener = Callable[[T], Coroutine[Any, Any, None]]


class EventEmitter(object):
    """
    Local event emitter.

    Emits events to in-process listeners. This emitter is not suitable for
    distributed systems.

    """

    @classmethod
    def builder(cls) -> "EventEmitterBuilder":
        return EventEmitterBuilder(cls)

    def __init__(
        self,
        listeners: Mapping[str, Collection[EventListener[Any]]],
    ) -> None:
        """
        Use EventEmitter.builder() instead of calling this directly.

        """
        super().__init__()
        self._listeners = listeners
        self._event_lock = KeyLock()
        self._event_locked_vars: dict[str, contextvars.ContextVar[bool]] = {
            event_key: contextvars.ContextVar(
                f"event_locked_{event_key}", default=False
            )
            for event_key in listeners.keys()
        }

    async def emit(self, event: Event[T], payload: T) -> None:
        """
        Emit an event and payload to every registered listener.

        :param event: Event to emit.
        :param payload: Payload sent with the event.
        """
        if event.key not in self._listeners:
            return
        if self._event_locked_vars[event.key].get():
            raise RuntimeError(
                f"Circular event emission detected for event key: {event.key}. "
                "Do not emit self-referencing events."
            )
        async with self._event_lock(event.key):
            token = self._event_locked_vars[event.key].set(True)
            try:
                for listener in self._listeners[event.key]:
                    await self._safe_run_listener(event.key, listener, payload)
            finally:
                self._event_locked_vars[event.key].reset(token)

    async def _safe_run_listener(
        self, event_key: str, listener: EventListener[T], payload: T
    ) -> None:
        """
        Run a listener and log any exception it raises.
        """
        try:
            await listener(payload)
        except Exception:
            logger.exception(
                "Background listener task failed",
                extra={"payload": payload, "event_key": event_key},
            )


class EventEmitterBuilder(object):
    def __init__(self, emitter_class: type[EventEmitter]) -> None:
        super().__init__()
        self.emitter_class = emitter_class
        self.events: dict[str, Event[Any]] = {}
        self.listeners: dict[str, list[EventListener[Any]]] = {}

    def listen(self, event: Event[T], listener: EventListener[T]) -> Self:
        """
        Register a listener for an event.

        :param event: Event to receive.
        :param listener: Listener to register.
        :raises ValueError: If the event key conflicts with another event.

        """
        if event.key not in self.events:
            self.events[event.key] = event
            self.listeners[event.key] = []
        elif self.events[event.key] != event:
            raise ValueError(
                f"Cannot register different events with the same key: {event.key}"
            )
        self.listeners[event.key].append(listener)
        return self

    def update(self, other: "EventEmitterBuilder") -> Self:
        """
        Merge another builder's listeners into this builder.
        """
        for event_key in self.events.keys() & other.events.keys():
            if self.events[event_key] != other.events[event_key]:
                raise ValueError(
                    f"Cannot update builders with different events with the "
                    f"same key: {event_key}"
                )
        self.events.update(other.events)
        for event_key in other.listeners.keys():
            if event_key not in self.listeners:
                self.listeners[event_key] = []
            self.listeners[event_key].extend(other.listeners[event_key])
        return self

    def build(self) -> EventEmitter:
        return self.emitter_class(self.listeners)
