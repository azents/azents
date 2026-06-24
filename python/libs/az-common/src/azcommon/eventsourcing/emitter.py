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
    로컬 이벤트 에미터.

    로컬 리스너에게 이벤트를 발행하는 이벤트 에미터입니다.
    분산 시스템에는 적합하지 않습니다.

    """

    @classmethod
    def builder(cls) -> "EventEmitterBuilder":
        return EventEmitterBuilder(cls)

    def __init__(
        self,
        listeners: Mapping[str, Collection[EventListener[Any]]],
    ) -> None:
        """
        직접 호출하지 마세요. EventEmitter.builder()를 사용하세요.

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
        등록된 모든 리스너에게 페이로드와 함께 이벤트를 발행합니다.

        :param event: 발행할 이벤트
        :param payload: 이벤트와 함께 전송할 페이로드
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
        리스너를 실행하고 발생하는 예외를 억제합니다.
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
        이벤트에 리스너를 등록합니다.

        :param event: 수신할 이벤트
        :param listener: 등록할 리스너
        :raises ValueError: 이벤트 키가 고유하지 않은 경우

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
        다른 빌더의 리스너들을 이 빌더에 병합합니다.
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
