"""SessionRunner error event storage and dispatch."""

import logging
from typing import Protocol

from azcommon.logging import bind_extra

from azents.engine.events.types import Event
from azents.engine.run.errors import UserVisibleRuntimeError
from azents.worker.events.publisher import WorkerEventPublisher

logger = logging.getLogger(__name__)

_INTERNAL_ERROR_MESSAGE = "An internal error occurred."


class ErrorEventEngine(Protocol):
    """The completed error-persistence operation actually used by the reporter."""

    async def save_error_message(
        self, session_id: str, content: str, *, owner_generation: int
    ) -> Event:
        """Persist one owner-fenced error event."""
        ...


class SessionRunnerErrorReporter:
    """Convert SessionRunner turn error to user event."""

    def __init__(
        self,
        *,
        engine: ErrorEventEngine,
        event_publisher: WorkerEventPublisher,
    ) -> None:
        self.engine = engine
        self.event_publisher = event_publisher

    async def report_user_visible(
        self,
        session_id: str,
        exc: UserVisibleRuntimeError,
        *,
        owner_generation: int,
    ) -> None:
        """Store and propagate runtime error that can be shown to user."""
        operation_logger = bind_extra(logger, {"session_id": session_id})
        operation_logger.warning(
            "Unhandled user-visible error in session runner",
            extra={"error": exc.user_message},
        )
        error_event = await self.engine.save_error_message(
            session_id,
            exc.user_message,
            owner_generation=owner_generation,
        )
        try:
            await self.event_publisher.dispatch_event(
                session_id,
                error_event,
                owner_generation=owner_generation,
            )
        except Exception:
            operation_logger.exception("Failed to dispatch error message")

    async def report_unhandled(
        self,
        session_id: str,
        exc: Exception,
        *,
        owner_generation: int,
    ) -> None:
        """Store and propagate unexpected turn error as internal error event."""
        operation_logger = bind_extra(logger, {"session_id": session_id})
        operation_logger.exception(
            "Unhandled error in process_message",
            extra={"error_type": exc.__class__.__name__},
        )
        error_event = await self.engine.save_error_message(
            session_id,
            _INTERNAL_ERROR_MESSAGE,
            owner_generation=owner_generation,
        )
        try:
            await self.event_publisher.dispatch_event(
                session_id,
                error_event,
                owner_generation=owner_generation,
            )
        except Exception:
            operation_logger.exception("Failed to publish error event")
