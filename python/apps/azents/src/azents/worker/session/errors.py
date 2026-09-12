"""SessionRunner error event storage and dispatch."""

import logging

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
        *,
        owner_generation: int,
    ) -> None:
        """Store and propagate runtime error that can be shown to user."""
        logger.warning(
            "Unhandled user-visible error in session runner",
            extra={
                "session_id": session_id,
                "error": exc.user_message,
            },
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
            logger.exception(
                "Failed to dispatch error message",
                extra={"session_id": session_id},
            )

    async def report_unhandled(
        self,
        session_id: str,
        exc: Exception,
        *,
        owner_generation: int,
    ) -> None:
        """Store and propagate unexpected turn error as internal error event."""
        logger.exception(
            "Unhandled error in process_message",
            extra={
                "session_id": session_id,
                "error_type": exc.__class__.__name__,
            },
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
            logger.exception(
                "Failed to publish error event",
                extra={"session_id": session_id},
            )
