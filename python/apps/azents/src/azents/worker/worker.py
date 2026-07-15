"""Agent Worker.

Receives messages from broker and runs engine in per-session asyncio tasks.
Messages for same session are processed sequentially in same task;
different sessions run concurrently.

On graceful shutdown, waits for current engine.run() to finish,
then releases session lock and exits.
"""

import asyncio
import contextlib
import dataclasses
import logging
from typing import Annotated

from fastapi import Depends

from azents.broker.types import (
    BrokerMessage,
    SessionBroker,
)
from azents.engine.model_stream import ModelStreamWatchdog, get_model_stream_watchdog
from azents.worker.deps import get_worker_broker
from azents.worker.session.recovery import StuckSessionRecovery
from azents.worker.session.runner import SessionRunner
from azents.worker.session.runner_factory import SessionRunnerFactory

logger = logging.getLogger(__name__)

_INITIAL_BACKOFF = 0.1  # seconds
_MAX_BACKOFF = 30.0  # seconds


class _ShutdownRequested(Exception):
    """Internal sentinel representing Worker shutdown request."""


@dataclasses.dataclass(frozen=True)
class _ActiveSessionRunner:
    """Session runner execution handle owned by AgentWorker."""

    runner: SessionRunner
    task: asyncio.Task[None]

    @property
    def terminated(self) -> bool:
        """Return whether Runner task ended."""
        return self.task.done()

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
    model_stream_watchdog: Annotated[
        ModelStreamWatchdog,
        Depends(get_model_stream_watchdog),
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
                    if runner is None or runner.terminated:
                        logger.info(
                            "Starting session runner",
                            extra={"session_id": session_id},
                        )
                        session_runner = self.session_runner_factory.create(
                            shutdown_event=self.shutdown_event,
                        )
                        runner = _ActiveSessionRunner(
                            runner=session_runner,
                            task=asyncio.create_task(session_runner.run()),
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
            await self.model_stream_watchdog.cleanup_registry.drain(
                grace_seconds=self.model_stream_watchdog.close_grace_seconds
            )
            logger.info("Agent worker stopped")

    def shutdown(self) -> None:
        """Request Worker shutdown from outside."""
        self.shutdown_event.set()

    async def _receive_or_shutdown(
        self, shutdown_event: asyncio.Event
    ) -> list[BrokerMessage]:
        """Wait for message receive or shutdown.

        When shutdown_event is set, exit immediately regardless of message receipt.
        shutdown takes priority even if messages were already received — those messages
        are reprocessed by another worker after lock release.

        :param shutdown_event: Shutdown event
        :return: Received broker message list
        :raises _ShutdownRequested: When shutdown event is set
        """
        if shutdown_event.is_set():
            raise _ShutdownRequested

        receive_task = asyncio.ensure_future(self.broker.receive_messages())
        shutdown_task = asyncio.ensure_future(shutdown_event.wait())
        done, pending = await asyncio.wait(
            [receive_task, shutdown_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for p in pending:
            p.cancel()
        if pending:
            for p in pending:
                with contextlib.suppress(asyncio.CancelledError):
                    await p

        if shutdown_task in done:
            raise _ShutdownRequested

        return receive_task.result()
