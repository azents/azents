"""SessionRunner creation dependency assembly."""

import asyncio
import dataclasses
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.engine.events.engine_adapter import AgentEngineAdapter
from azents.engine.run.contracts import AgentEngineProtocol
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent_session import AgentSessionRepository
from azents.services.input_buffer import InputBufferService
from azents.services.session_git_worktree import SessionGitWorktreeService
from azents.worker.events.publisher import WorkerEventPublisher
from azents.worker.run.executor import RunExecutor
from azents.worker.session.idle_continuation import IdleContinuationService
from azents.worker.session.lifecycle import SessionLifecycleService
from azents.worker.session.runner import SessionRunner
from azents.worker.session.user_stop_finalizer import UserStopFinalizer


@dataclasses.dataclass(frozen=True)
class SessionRunnerFactory:
    """Store worker-side collaborators required to create SessionRunner."""

    event_publisher: Annotated[WorkerEventPublisher, Depends(WorkerEventPublisher)]
    session_lifecycle: Annotated[
        SessionLifecycleService, Depends(SessionLifecycleService)
    ]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    input_buffer_service: Annotated[InputBufferService, Depends(InputBufferService)]
    idle_continuation_service: Annotated[
        IdleContinuationService, Depends(IdleContinuationService)
    ]
    user_stop_finalizer: Annotated[UserStopFinalizer, Depends(UserStopFinalizer)]
    run_executor: Annotated[RunExecutor, Depends(RunExecutor)]
    engine: Annotated[AgentEngineProtocol, Depends(AgentEngineAdapter)]
    session_git_worktree_service: Annotated[
        SessionGitWorktreeService, Depends(SessionGitWorktreeService)
    ]

    def create(self, *, shutdown_event: asyncio.Event) -> SessionRunner:
        """Create new SessionRunner bound to global shutdown event."""
        return SessionRunner(
            shutdown_event=shutdown_event,
            event_publisher=self.event_publisher,
            session_lifecycle=self.session_lifecycle,
            session_manager=self.session_manager,
            agent_session_repository=self.agent_session_repository,
            input_buffer_service=self.input_buffer_service,
            idle_continuation_service=self.idle_continuation_service,
            user_stop_finalizer=self.user_stop_finalizer,
            run_executor=self.run_executor,
            engine=self.engine,
            initialization_processor=self.session_git_worktree_service,
        )
