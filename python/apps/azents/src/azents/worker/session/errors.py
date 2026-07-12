"""SessionRunner error event storage and dispatch."""

import asyncio
import logging

from azents.engine.events.builders import make_system_error_event
from azents.engine.run.contracts import AgentEngineProtocol
from azents.engine.run.errors import UserVisibleRuntimeError
from azents.worker.events.publisher import WorkerEventPublisher

logger = logging.getLogger(__name__)

_INTERNAL_ERROR_MESSAGE = "An internal error occurred."


class SessionRunnerErrorReporter:
    """Convert SessionRunner turn error to user event."""

    def __init__(
        self,
        *,
        engine: AgentEngineProtocol,
        event_publisher: WorkerEventPublisher,
    ) -> None:
        self.engine = engine
        self.event_publisher = event_publisher

    async def report_user_visible(
        self,
        session_id: str,
        exc: UserVisibleRuntimeError,
    ) -> None:
        """Store and propagate runtime error that can be shown to user."""
        logger.warning(
            "Unhandled user-visible error in session runner",
            extra={
                "session_id": session_id,
                "error": exc.user_message,
            },
        )
        try:
            error_event = await self.engine.save_error_message(
                session_id,
                exc.user_message,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Failed to save error message",
                extra={"session_id": session_id},
            )
            error_event = make_system_error_event(
                session_id=session_id,
                content=exc.user_message,
            )
        try:
            await self.event_publisher.dispatch_event(session_id, error_event)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Failed to dispatch error message",
                extra={"session_id": session_id},
            )

    async def report_unhandled(
        self,
        session_id: str,
        exc: Exception,
    ) -> None:
        """Store and propagate unexpected turn error as internal error event."""
        logger.exception(
            "Unhandled error in process_message",
            extra={
                "session_id": session_id,
                "error_type": exc.__class__.__name__,
            },
        )
        try:
            error_event = await self.engine.save_error_message(
                session_id,
                _INTERNAL_ERROR_MESSAGE,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Failed to save error message",
                extra={"session_id": session_id},
            )
            error_event = make_system_error_event(
                session_id=session_id,
                content=_INTERNAL_ERROR_MESSAGE,
            )
        try:
            await self.event_publisher.dispatch_event(session_id, error_event)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Failed to publish error event",
                extra={"session_id": session_id},
            )
