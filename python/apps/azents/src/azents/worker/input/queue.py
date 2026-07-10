"""Runtime-generated input commit abstraction."""

import dataclasses
from typing import Literal, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.types import SessionBroker, SessionWakeUp
from azents.core.enums import InputBufferKind
from azents.rdb.session import SessionManager
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.services.input_buffer import InputBufferEnqueue, InputBufferService


@dataclasses.dataclass(frozen=True)
class BackgroundCompletionInput:
    """Runtime background operation completion input."""

    agent_id: str
    parent_session_id: str
    workspace_id: str
    task_id: str
    operation_id: str
    request_id: str
    tool_name: str
    status: Literal[
        "completed",
        "failed",
        "expired",
        "interrupted",
        "lost",
        "canceled",
    ]
    text: str
    created_at: str
    idempotency_key: str


class WorkerInputQueue(Protocol):
    """Runtime-generated input commit boundary."""

    async def enqueue_background_completion(
        self,
        item: BackgroundCompletionInput,
    ) -> bool:
        """Commit background completion."""
        ...


@dataclasses.dataclass
class InMemoryWorkerInputQueue:
    """In-memory Worker input queue for tests."""

    messages: list[BackgroundCompletionInput] = dataclasses.field(default_factory=list)
    seen: set[str] = dataclasses.field(default_factory=set)

    async def enqueue_background_completion(
        self,
        item: BackgroundCompletionInput,
    ) -> bool:
        """Store background completion only once."""
        if item.idempotency_key in self.seen:
            return False
        self.seen.add(item.idempotency_key)
        self.messages.append(item)
        return True


@dataclasses.dataclass(frozen=True)
class DatabaseWorkerInputQueue:
    """DB-backed Worker input queue."""

    broker: SessionBroker
    session_manager: SessionManager[AsyncSession]
    agent_runtime_repository: AgentRuntimeRepository
    agent_session_repository: AgentSessionRepository
    input_buffer_service: InputBufferService

    async def enqueue_background_completion(
        self,
        item: BackgroundCompletionInput,
    ) -> bool:
        """Commit background completion as input buffer and send wake-up."""
        async with self.session_manager() as session:
            await self.agent_runtime_repository.ensure_for_agent(
                session,
                item.agent_id,
            )
            result = await self.input_buffer_service.enqueue(
                session,
                InputBufferEnqueue(
                    session_id=item.parent_session_id,
                    kind=InputBufferKind.BACKGROUND_COMPLETION,
                    requested_model_target_label=None,
                    requested_reasoning_effort=None,
                    actor_user_id=None,
                    content=item.text,
                    idempotency_key=item.idempotency_key,
                    metadata={
                        "source": "background_runtime_operation",
                        "task_id": item.task_id,
                        "operation_id": item.operation_id,
                        "request_id": item.request_id,
                        "tool_name": item.tool_name,
                        "status": item.status,
                    },
                    action=None,
                    attachments=[],
                    file_parts=[],
                ),
            )
            if not result.created:
                return False
            await self.agent_session_repository.mark_running_for_input_wakeup(
                session,
                item.parent_session_id,
            )

        await self.broker.send_message(
            SessionWakeUp(
                agent_id=item.agent_id,
                session_id=item.parent_session_id,
                user_id=None,
                additional_system_prompt=None,
                interface=None,
                workspace_id=item.workspace_id,
                workspace_handle=None,
            )
        )
        return True
