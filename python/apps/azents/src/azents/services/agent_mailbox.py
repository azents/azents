"""Typed agent-to-agent mailbox operations."""

import dataclasses
from typing import Annotated, Literal

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentRunStatus,
    AgentSessionStatus,
    InputBufferKind,
    InputBufferSchedulingMode,
    SessionAgentKind,
)
from azents.engine.events.types import AgentRunState
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import SessionAgent
from azents.repos.input_buffer.data import InputBuffer
from azents.services.input_buffer import InputBufferEnqueue, InputBufferService

InstructionMessageKind = Literal["spawn_agent", "send_message", "followup_task"]


@dataclasses.dataclass(frozen=True)
class AgentMailboxService:
    """Persist operation-specific agent mailbox messages."""

    input_buffer_service: Annotated[InputBufferService, Depends(InputBufferService)]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]

    async def enqueue_spawn_assignment(
        self,
        session: AsyncSession,
        *,
        source: SessionAgent,
        target: SessionAgent,
        content: str,
    ) -> InputBuffer:
        """Enqueue a wake-producing initial child assignment."""
        return await self._enqueue_instruction(
            session,
            source=source,
            target=target,
            message_kind="spawn_agent",
            content=content,
            scheduling_mode=InputBufferSchedulingMode.WAKE_SESSION,
        )

    async def enqueue_message(
        self,
        session: AsyncSession,
        *,
        source: SessionAgent,
        target: SessionAgent,
        content: str,
    ) -> InputBuffer:
        """Enqueue an ordinary message without waking the target session."""
        return await self._enqueue_instruction(
            session,
            source=source,
            target=target,
            message_kind="send_message",
            content=content,
            scheduling_mode=InputBufferSchedulingMode.QUEUE_ONLY,
        )

    async def enqueue_followup_task(
        self,
        session: AsyncSession,
        *,
        source: SessionAgent,
        target: SessionAgent,
        content: str,
    ) -> InputBuffer:
        """Enqueue a wake-producing follow-up assignment."""
        return await self._enqueue_instruction(
            session,
            source=source,
            target=target,
            message_kind="followup_task",
            content=content,
            scheduling_mode=InputBufferSchedulingMode.WAKE_SESSION,
        )

    async def enqueue_terminal_result(
        self,
        session: AsyncSession,
        *,
        source: SessionAgent,
        target: SessionAgent,
        run: AgentRunState,
        content: str,
    ) -> InputBuffer:
        """Enqueue one queue-only terminal result for the direct parent."""
        self._validate_tree(source, target)
        if source.kind != SessionAgentKind.SUBAGENT:
            raise ValueError("Terminal result source must be a subagent")
        if source.parent_session_agent_id != target.id:
            raise ValueError("Terminal result target must be the direct parent")
        if run.session_id != source.agent_session_id:
            raise ValueError("Terminal result Run does not belong to source agent")
        if run.status not in {
            AgentRunStatus.COMPLETED,
            AgentRunStatus.FAILED,
            AgentRunStatus.STOPPED,
            AgentRunStatus.INTERRUPTED,
            AgentRunStatus.CANCELLED,
        }:
            raise ValueError("Terminal result Run is not terminal")
        metadata = self._base_metadata(
            source=source,
            target=target,
            message_kind="agent_result",
        )
        metadata.update(
            {
                "source_run_id": run.id,
                "source_run_index": str(run.run_index),
                "run_status": run.status.value,
            }
        )
        if run.terminal_result_event_id is not None:
            metadata["source_terminal_result_event_id"] = run.terminal_result_event_id
        return await self._enqueue(
            session,
            source=source,
            target=target,
            content=content,
            scheduling_mode=InputBufferSchedulingMode.QUEUE_ONLY,
            idempotency_key=f"agent_result:{run.id}",
            metadata=metadata,
        )

    async def _enqueue_instruction(
        self,
        session: AsyncSession,
        *,
        source: SessionAgent,
        target: SessionAgent,
        message_kind: InstructionMessageKind,
        content: str,
        scheduling_mode: InputBufferSchedulingMode,
    ) -> InputBuffer:
        self._validate_tree(source, target)
        return await self._enqueue(
            session,
            source=source,
            target=target,
            content=content,
            scheduling_mode=scheduling_mode,
            idempotency_key=None,
            metadata=self._base_metadata(
                source=source,
                target=target,
                message_kind=message_kind,
            ),
        )

    async def _enqueue(
        self,
        session: AsyncSession,
        *,
        source: SessionAgent,
        target: SessionAgent,
        content: str,
        scheduling_mode: InputBufferSchedulingMode,
        idempotency_key: str | None,
        metadata: dict[str, str],
    ) -> InputBuffer:
        locked_root = await self.agent_session_repository.lock_session_agent_by_id(
            session,
            source.root_session_agent_id,
        )
        if locked_root is None:
            raise ValueError("Root SessionAgent not found")
        locked_target = await self.agent_session_repository.lock_by_id(
            session,
            target.agent_session_id,
        )
        if locked_target is None:
            raise ValueError("Target AgentSession not found")
        if locked_target.status is not AgentSessionStatus.ACTIVE:
            raise ValueError("Target AgentSession is not active")
        if (
            scheduling_mode is InputBufferSchedulingMode.WAKE_SESSION
            and locked_target.stop_requested_at is not None
        ):
            raise ValueError("Target AgentSession is stopping")
        result = await self.input_buffer_service.enqueue(
            session,
            InputBufferEnqueue(
                session_id=target.agent_session_id,
                kind=InputBufferKind.AGENT_MESSAGE,
                scheduling_mode=scheduling_mode,
                requested_model_target_label=None,
                requested_reasoning_effort=None,
                sender_user_id=None,
                content=content,
                idempotency_key=idempotency_key,
                metadata=metadata,
                action=None,
                attachments=[],
                file_parts=[],
            ),
        )
        mark_activity = (
            self.agent_session_repository.mark_session_agent_message_activity
        )
        await mark_activity(session, session_agent_id=source.id)
        if target.id != source.id:
            await mark_activity(session, session_agent_id=target.id)
        if scheduling_mode == InputBufferSchedulingMode.WAKE_SESSION:
            await self.agent_session_repository.mark_running_for_input_wakeup(
                session,
                target.agent_session_id,
            )
        return result.input_buffer

    @staticmethod
    def _base_metadata(
        *,
        source: SessionAgent,
        target: SessionAgent,
        message_kind: str,
    ) -> dict[str, str]:
        return {
            "source": "agent_mailbox",
            "message_kind": message_kind,
            "source_session_agent_id": source.id,
            "source_path": source.path,
            "target_session_agent_id": target.id,
            "target_path": target.path,
        }

    @staticmethod
    def _validate_tree(source: SessionAgent, target: SessionAgent) -> None:
        if source.root_session_agent_id != target.root_session_agent_id:
            raise ValueError("Mailbox agents must belong to the same root tree")
