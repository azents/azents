"""SessionRunner creation dependency assembly."""

import asyncio
import dataclasses
from typing import Annotated

from fastapi import Depends

from azents.engine.events.engine_adapter import AgentEngineAdapter
from azents.engine.run.contracts import AgentEngineProtocol
from azents.engine.run.model_transport import InMemoryModelTransportState
from azents.repos.historical_memory_consolidation.execution import (
    MemoryExecutionRepository,
)
from azents.repos.worker_session import WorkerSessionOperationRepository
from azents.services.mailbox import MailboxService
from azents.worker.config import AgentWorkerConfig
from azents.worker.deps import get_worker_config
from azents.worker.events.publisher import WorkerEventPublisher
from azents.worker.run.executor import RunExecutor
from azents.worker.run.memory_execution import MemoryRunExecutor
from azents.worker.session.execution_snapshot import CanonicalExecutionSnapshotLoader
from azents.worker.session.idle_continuation import IdleContinuationService
from azents.worker.session.lifecycle import SessionLifecycleService
from azents.worker.session.runner import SessionRunner
from azents.worker.session.user_stop_finalizer import UserStopFinalizer


@dataclasses.dataclass(frozen=True)
class SessionRunnerFactory:
    """Store worker-side collaborators required to create SessionRunner."""

    worker_config: Annotated[AgentWorkerConfig, Depends(get_worker_config)]
    event_publisher: Annotated[WorkerEventPublisher, Depends(WorkerEventPublisher)]
    session_lifecycle: Annotated[
        SessionLifecycleService, Depends(SessionLifecycleService)
    ]
    execution_snapshot_loader: Annotated[
        CanonicalExecutionSnapshotLoader, Depends(CanonicalExecutionSnapshotLoader)
    ]
    worker_session_repository: Annotated[
        WorkerSessionOperationRepository, Depends(WorkerSessionOperationRepository)
    ]
    mailbox_item_service: Annotated[MailboxService, Depends(MailboxService)]
    idle_continuation_service: Annotated[
        IdleContinuationService, Depends(IdleContinuationService)
    ]
    user_stop_finalizer: Annotated[UserStopFinalizer, Depends(UserStopFinalizer)]
    run_executor: Annotated[RunExecutor, Depends(RunExecutor)]
    memory_execution_repository: Annotated[
        MemoryExecutionRepository, Depends(MemoryExecutionRepository)
    ]
    memory_run_executor: Annotated[MemoryRunExecutor, Depends(MemoryRunExecutor)]
    engine: Annotated[AgentEngineProtocol, Depends(AgentEngineAdapter)]

    def create(self, *, shutdown_event: asyncio.Event) -> SessionRunner:
        """Create new SessionRunner bound to global shutdown event."""
        return SessionRunner(
            shutdown_event=shutdown_event,
            event_publisher=self.event_publisher,
            session_lifecycle=self.session_lifecycle,
            execution_snapshot_loader=self.execution_snapshot_loader,
            worker_session_repository=self.worker_session_repository,
            mailbox_item_service=self.mailbox_item_service,
            idle_continuation_service=self.idle_continuation_service,
            user_stop_finalizer=self.user_stop_finalizer,
            run_executor=self.run_executor,
            memory_execution_repository=self.memory_execution_repository,
            memory_run_executor=self.memory_run_executor,
            engine=self.engine,
            model_transport_state=InMemoryModelTransportState(
                websocket_enabled=(
                    self.worker_config.openai_responses_websocket_enabled
                ),
            ),
        )
