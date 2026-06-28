"""Session lifecycle state and ownership management."""

import asyncio
import dataclasses
import datetime
import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Annotated, TypeVar

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.types import SessionBroker, SessionWakeUp
from azents.core.enums import AgentRunPhase, AgentRunStatus
from azents.engine.events.types import ActiveToolCall
from azents.engine.run.failure import FailedRunRetryState
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_execution.data import AgentRunCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.worker.deps import get_worker_broker

logger = logging.getLogger(__name__)
_T = TypeVar("_T")


@dataclasses.dataclass(frozen=True)
class SessionLifecycleService:
    """Manage Session runtime state and broker ownership/activity."""

    broker: Annotated[SessionBroker, Depends(get_worker_broker)]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    agent_run_repository: Annotated[AgentRunRepository, Depends(AgentRunRepository)]

    async def release_session_lock(self, session_id: str) -> None:
        """Release session lock."""
        await self.broker.release_session_lock(session_id)

    async def clear_session_activity(self, session_id: str) -> None:
        """Remove session activity."""
        await self.broker.clear_session_activity(session_id)

    async def send_session_wake_up(self, message: SessionWakeUp) -> None:
        """Send wake-up through the existing session broker path."""
        await self.broker.send_message(message)

    async def set_session_activity(
        self,
        session_id: str,
        *,
        run_id: str,
        phase: AgentRunPhase | None = None,
        active_tool_calls: Sequence[ActiveToolCall] = (),
    ) -> None:
        """Record session activity and refresh TTL."""
        await self.broker.set_session_activity(
            session_id,
            run_id=run_id,
            phase=phase,
            active_tool_calls=active_tool_calls,
        )

    async def renew_session_owner_heartbeat(self, session_id: str) -> None:
        """Refresh Redis session owner heartbeat."""
        await self.broker.renew_session_owner_heartbeat(session_id)

    async def mark_session_running(self, session_id: str) -> None:
        """Transition ``run_state`` to RUNNING and initialize heartbeat."""
        await self.run_short_db(
            lambda db: self.agent_session_repository.mark_running(db, session_id),
            error_log="Failed to mark session running",
            session_id=session_id,
        )

    async def mark_session_idle(self, session_id: str) -> bool:
        """Revert ``run_state`` to IDLE only after all runs are terminal."""

        async def mark_idle_if_no_run(db_session: AsyncSession) -> bool:
            running_run = await self.agent_run_repository.get_running_by_session_id(
                db_session,
                session_id=session_id,
            )
            if running_run is not None:
                logger.info(
                    "Skipped session idle transition because an AgentRun is active",
                    extra={
                        "session_id": session_id,
                        "run_id": running_run.id,
                    },
                )
                return False
            await self.agent_session_repository.mark_idle(db_session, session_id)
            return True

        marked_idle = await self.run_short_db(
            mark_idle_if_no_run,
            error_log="Failed to mark session idle",
            session_id=session_id,
            default=False,
        )
        return bool(marked_idle)

    async def has_running_agent_run(self, session_id: str) -> bool:
        """Return whether the session still has a running AgentRun."""

        async def get_running(db_session: AsyncSession) -> bool:
            running_run = await self.agent_run_repository.get_running_by_session_id(
                db_session,
                session_id=session_id,
            )
            return running_run is not None

        running = await self.run_short_db(
            get_running,
            error_log="Failed to check running agent run",
            session_id=session_id,
            default=True,
        )
        return bool(running)

    async def heartbeat_session(self, session_id: str) -> None:
        """Refresh DB heartbeat and Redis owner heartbeat of RUNNING session."""
        await self.run_short_db(
            lambda db: self.agent_session_repository.heartbeat_running(db, session_id),
            error_log="Failed to heartbeat session",
            session_id=session_id,
        )
        await self.broker.renew_session_owner_heartbeat(session_id)

    async def has_stop_request(self, session_id: str) -> bool:
        """Return whether Durable stop intent exists."""
        async with self.session_manager() as db_session:
            return await self.agent_session_repository.has_stop_request(
                db_session,
                session_id,
            )

    async def create_agent_run_projection(
        self,
        session_id: str,
        *,
        run_id: str,
        phase: AgentRunPhase | None,
    ) -> None:
        """Create AgentRun projection for Worker-owned transient run."""
        await self.run_short_db(
            lambda db: self.agent_run_repository.create(
                db,
                AgentRunCreate(
                    id=run_id,
                    session_id=session_id,
                    phase=phase or AgentRunPhase.IDLE,
                ),
            ),
            error_log="Failed to create agent run projection",
            session_id=session_id,
        )

    async def mark_session_agent_runs_terminal(
        self,
        session_id: str,
        *,
        status: AgentRunStatus,
    ) -> None:
        """Close remaining running AgentRun projections when session is idle."""
        await self.run_short_db(
            lambda db: self.agent_run_repository.mark_session_running_terminal(
                db,
                session_id=session_id,
                status=status,
                ended_at=datetime.datetime.now(datetime.UTC),
            ),
            error_log="Failed to mark session agent runs terminal",
            session_id=session_id,
        )

    async def mark_agent_run_terminal_if_running(
        self,
        session_id: str,
        *,
        run_id: str,
        status: AgentRunStatus,
    ) -> None:
        """Close AgentRun row as terminal state if still running."""
        await self.run_short_db(
            lambda db: self.agent_run_repository.mark_terminal_if_running(
                db,
                run_id,
                status,
                ended_at=datetime.datetime.now(datetime.UTC),
            ),
            error_log="Failed to mark agent run terminal",
            session_id=session_id,
        )

    async def update_agent_run_retry_state(
        self,
        session_id: str,
        *,
        run_id: str,
        retry_state: FailedRunRetryState | None,
    ) -> None:
        """Set or clear the AgentRun retry state."""
        await self.run_short_db(
            lambda db: self.agent_run_repository.update_retry_state(
                db,
                run_id,
                retry_state,
            ),
            error_log="Failed to update agent run retry state",
            session_id=session_id,
        )

    async def run_short_db(
        self,
        action: Callable[[AsyncSession], Awaitable[_T]],
        *,
        error_log: str,
        session_id: str,
        default: _T | None = None,
    ) -> _T | None:
        """Run ``action`` in short-lived DB transaction."""
        try:
            async with self.session_manager() as db_session:
                return await action(db_session)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(error_log, extra={"session_id": session_id})
            return default
