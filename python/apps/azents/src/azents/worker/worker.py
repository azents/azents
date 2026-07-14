"""Agent Worker.

Receives messages from broker and runs engine in per-session asyncio tasks.
Messages for same session are processed sequentially in same task;
different sessions run concurrently.

On graceful shutdown, waits for current engine.run() to finish,
then releases session lock and exits.
"""

import asyncio
import dataclasses
import logging
from collections.abc import Sequence
from typing import Annotated, Any

from fastapi import Depends

from azents.broker.types import (
    BrokerMessage,
    SessionBroker,
    SessionOwnershipLostError,
)
from azents.worker.deps import get_worker_broker
from azents.worker.session.recovery import StuckSessionRecovery
from azents.worker.session.runner import SessionRunner
from azents.worker.session.runner_factory import SessionRunnerFactory

logger = logging.getLogger(__name__)

_INITIAL_BACKOFF = 0.1  # seconds
_MAX_BACKOFF = 30.0  # seconds


class _ShutdownRequested(Exception):
    """Internal sentinel representing Worker shutdown request."""


async def _cancel_and_drain_tasks(
    tasks: Sequence[asyncio.Task[Any]],
    *,
    failure_message: str,
) -> None:
    """Cancel child waits and consume every terminal outcome."""
    for task in tasks:
        if not task.done():
            task.cancel()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for result in results:
        if not isinstance(result, Exception):
            continue
        logger.warning(
            failure_message,
            exc_info=(type(result), result, result.__traceback__),
        )


@dataclasses.dataclass(frozen=True)
class _ActiveSessionRunner:
    """Session runner execution handle owned by AgentWorker."""

    runner: SessionRunner
    task: asyncio.Task[None]

    def __post_init__(self) -> None:
        """Observe Runner termination immediately at the Worker boundary."""
        self.task.add_done_callback(self._consume_task_result)

    def _consume_task_result(self, task: asyncio.Task[None]) -> None:
        """Consume and report a background Runner result exactly once."""
        try:
            exception = task.exception()
        except asyncio.CancelledError:
            logger.warning(
                "Session runner task was cancelled",
                extra={"session_id": self.runner.running_session_id},
            )
            return
        if exception is None:
            return
        if isinstance(exception, SessionOwnershipLostError):
            logger.warning(
                "Session runner exited after ownership loss",
                extra={"session_id": exception.session_id},
            )
            return
        logger.error(
            "Session runner task failed",
            extra={"session_id": self.runner.running_session_id},
            exc_info=(type(exception), exception, exception.__traceback__),
        )

    @property
    def terminated(self) -> bool:
        """Return whether Runner task ended."""
        return self.task.done()

    @property
    def accepts_messages(self) -> bool:
        """Return whether messages can still be handed to this Runner."""
        return not self.task.done() and self.runner.accepting_messages

    def enqueue(self, message: BrokerMessage) -> None:
        """Deliver message to Runner queue."""
        self.runner.enqueue(message)

    async def shutdown(self) -> None:
        """Request Runner shutdown and wait for task completion."""
        self.runner.request_shutdown()
        await self.task


@dataclasses.dataclass
class AgentWorker:
    """Agent Worker.

    Receives messages from broker and runs engine in per-session asyncio tasks.
    """

    broker: Annotated[SessionBroker, Depends(get_worker_broker)]
    stuck_session_recovery: Annotated[
        StuckSessionRecovery, Depends(StuckSessionRecovery)
    ]
    session_runner_factory: Annotated[
        SessionRunnerFactory, Depends(SessionRunnerFactory)
    ]
    shutdown_event: asyncio.Event = dataclasses.field(
        init=False,
        default_factory=asyncio.Event,
    )

    async def run(self, *, shutdown_event: asyncio.Event) -> None:
        """Main loop.

        Receive messages and dispatch to per-session SessionRunner.
        When shutdown_event is set, stop receiving new messages,
        wait for current processing of all Runners, then release session locks and exit.

        :param shutdown_event: Event signaling shutdown from outside
        """
        self.shutdown_event = shutdown_event

        logger.info("Agent worker starting")
        runners: dict[str, _ActiveSessionRunner] = {}
        runner_tasks: set[asyncio.Task[None]] = set()
        backoff = _INITIAL_BACKOFF
        recovery_task = self.stuck_session_recovery.start(shutdown_event)
        try:
            while not shutdown_event.is_set():
                try:
                    messages = await self._receive_or_shutdown(shutdown_event)
                except _ShutdownRequested:
                    break
                except Exception:
                    logger.exception(
                        "Failed to receive message, retrying",
                        extra={"backoff": backoff},
                    )
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, _MAX_BACKOFF)
                    continue

                backoff = _INITIAL_BACKOFF
                for message in messages:
                    session_id = message.session_id
                    runner = runners.get(session_id)
                    if runner is None or not runner.accepts_messages:
                        logger.info(
                            "Starting session runner",
                            extra={"session_id": session_id},
                        )
                        session_runner = self.session_runner_factory.create(
                            shutdown_event=self.shutdown_event,
                        )
                        task = asyncio.create_task(session_runner.run())
                        runner_tasks.add(task)
                        task.add_done_callback(runner_tasks.discard)
                        runner = _ActiveSessionRunner(
                            runner=session_runner,
                            task=task,
                        )
                        runners[session_id] = runner
                    runner.enqueue(message)
        finally:
            logger.info(
                "Shutting down agent worker",
                extra={"active_sessions": len(runners)},
            )
            recovery_task.cancel()
            try:
                await recovery_task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Stuck recovery loop failed on shutdown")
            await asyncio.gather(
                *(r.shutdown() for r in runners.values()),
                return_exceptions=True,
            )
            if runner_tasks:
                await asyncio.gather(*tuple(runner_tasks), return_exceptions=True)
            logger.info("Agent worker stopped")

    def shutdown(self) -> None:
        """Request Worker shutdown from outside."""
        self.shutdown_event.set()

    async def _receive_or_shutdown(
        self, shutdown_event: asyncio.Event
    ) -> list[BrokerMessage]:
        """Wait for message receive or shutdown.

        A successful receive takes priority over simultaneous shutdown because broker
        receive is destructive. This hands already-popped messages to their Runner
        before the Worker begins graceful shutdown.

        :param shutdown_event: Shutdown event
        :return: Received broker message list
        :raises _ShutdownRequested: When shutdown event is set
        """
        if shutdown_event.is_set():
            raise _ShutdownRequested

        receive_task = asyncio.ensure_future(self.broker.receive_messages())
        shutdown_task = asyncio.ensure_future(shutdown_event.wait())
        tasks = (receive_task, shutdown_task)
        try:
            done, pending = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )
        except asyncio.CancelledError:
            await _cancel_and_drain_tasks(
                tasks,
                failure_message="Worker child wait failed during cancellation cleanup",
            )
            raise
        if pending:
            await _cancel_and_drain_tasks(
                tuple(pending),
                failure_message="Worker child wait failed during race cleanup",
            )

        receive_succeeded = (
            receive_task in done
            and not receive_task.cancelled()
            and receive_task.exception() is None
        )
        if receive_succeeded:
            return receive_task.result()
        if shutdown_task in done:
            raise _ShutdownRequested

        return receive_task.result()
