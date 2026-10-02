"""Stuck RUNNING session recovery."""

import asyncio
import dataclasses
import datetime
import logging
from typing import Annotated

from fastapi import Depends

from azents.broker.types import SessionBroker, SessionWakeUp
from azents.repos.worker_session_data import StuckWorkerSession
from azents.repos.worker_session_recovery import (
    WorkerSessionRecoveryOperationRepository,
)
from azents.worker.deps import get_worker_broker
from azents.worker.session.lifecycle import SessionLifecycleService

logger = logging.getLogger(__name__)

_DEFAULT_STUCK_SESSION_THRESHOLD = datetime.timedelta(
    minutes=3
)  # worker is considered abnormally terminated when run_heartbeat_at is older than this
_DEFAULT_STUCK_RECOVERY_LIMIT = 100  # processing limit per scan
_DEFAULT_STUCK_RECOVERY_INTERVAL = datetime.timedelta(
    minutes=1
)  # periodic scan interval (ensures OOMKill recovery even with single Worker)


@dataclasses.dataclass(frozen=True)
class StuckSessionRecovery:
    """Find Stuck RUNNING sessions and re-enqueue RESUME."""

    broker: Annotated[SessionBroker, Depends(get_worker_broker)]
    repository: Annotated[
        WorkerSessionRecoveryOperationRepository,
        Depends(WorkerSessionRecoveryOperationRepository),
    ]
    session_lifecycle: Annotated[
        SessionLifecycleService, Depends(SessionLifecycleService)
    ]
    stale_threshold: datetime.timedelta = _DEFAULT_STUCK_SESSION_THRESHOLD
    limit: int = _DEFAULT_STUCK_RECOVERY_LIMIT
    interval: datetime.timedelta = _DEFAULT_STUCK_RECOVERY_INTERVAL

    def start(self, shutdown_event: asyncio.Event) -> asyncio.Task[None]:
        """Start recovery loop as background task."""
        return asyncio.create_task(self.run(shutdown_event))

    async def run(self, shutdown_event: asyncio.Event) -> None:
        """Periodically find Stuck RUNNING sessions and re-enqueue RESUME.

        Runs once right after Worker startup, then repeats every ``interval``.
        This lets even a single Worker pick up stuck sessions left by a prior
        instance after OOMKill and restart.
        """
        while not shutdown_event.is_set():
            try:
                await self.recover_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Stuck recovery scan failed")
            try:
                await asyncio.wait_for(
                    shutdown_event.wait(),
                    timeout=self.interval.total_seconds(),
                )
                return
            except asyncio.TimeoutError:
                continue

    async def recover_once(self) -> None:
        """Find stuck RUNNING sessions in DB and re-enqueue RESUME.

        Partial index lets it scan only RUNNING sessions. Re-enqueue uses existing
        broker queue path, and receive_messages reacquires lock then dispatches.
        """
        stuck = await self.repository.find_stuck_running(
            stale_threshold=self.stale_threshold, limit=self.limit
        )
        for rec in stuck:
            logger.info(
                "Recovering stuck running session",
                extra={"session_id": rec.id, "agent_id": rec.agent_id},
            )
            try:
                await self.session_lifecycle.mark_session_running(rec.id)
                await self.broker.send_message(_build_resume_message(rec))
            except Exception:
                logger.exception(
                    "Failed to enqueue RESUME for stuck session",
                    extra={"session_id": rec.id},
                )


def _build_resume_message(rec: StuckWorkerSession) -> SessionWakeUp:
    """Create SessionWakeUp for stuck recovery / shutdown recovery."""
    return SessionWakeUp(session_id=rec.id)
