"""Stuck RUNNING session recovery."""

import asyncio
import dataclasses
import datetime
import logging
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.types import SessionBroker, SessionWakeUp
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime
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
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    agent_runtime_repository: Annotated[
        AgentRuntimeRepository, Depends(AgentRuntimeRepository)
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
        async with self.session_manager() as db_session:
            stuck = await self.agent_runtime_repository.find_stuck_running(
                db_session,
                stale_threshold=self.stale_threshold,
                limit=self.limit,
            )
        for rec in stuck:
            logger.info(
                "Recovering stuck running session",
                extra={"session_id": rec.current_session_id, "agent_id": rec.agent_id},
            )
            try:
                if rec.current_session_id is not None:
                    await self.session_lifecycle.mark_session_running(
                        rec.current_session_id
                    )
                await self.broker.send_message(_build_resume_message(rec))
            except Exception:
                logger.exception(
                    "Failed to enqueue RESUME for stuck session",
                    extra={"session_id": rec.current_session_id},
                )


def _build_resume_message(rec: AgentRuntime) -> SessionWakeUp:
    """Create SessionWakeUp for stuck recovery / shutdown recovery."""
    if rec.current_session_id is None:
        raise ValueError("AgentRuntime has no current AgentSession")
    return SessionWakeUp(
        agent_id=rec.agent_id,
        session_id=rec.current_session_id,
        user_id=None,
        additional_system_prompt=None,
        interface=None,
        workspace_id=rec.workspace_id,
        workspace_handle=None,
    )
