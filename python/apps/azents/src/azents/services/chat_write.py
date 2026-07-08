"""REST chat write service."""

import dataclasses
from typing import Annotated

from azcommon.uuid import uuid7
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentSessionRunState, EventKind, InputBufferKind
from azents.engine.events.types import FileOutputPart, SystemErrorPayload
from azents.rdb.deps import get_session_manager
from azents.rdb.models.chat_write_request import ChatWriteRequestType
from azents.rdb.models.event import RDBEvent
from azents.rdb.session import SessionManager
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSession
from azents.repos.chat_write_request import ChatWriteRequestRepository
from azents.repos.chat_write_request.data import (
    ChatWriteRequest,
    ChatWriteRequestCreate,
)
from azents.repos.input_buffer.data import InputBuffer
from azents.repos.message import MessageRepository
from azents.services.input_buffer import InputBufferEnqueue, InputBufferService


@dataclasses.dataclass(frozen=True)
class AcceptedChatWriteRequest:
    """REST write request acceptance result."""

    session_id: str
    record: ChatWriteRequest
    created: bool


@dataclasses.dataclass(frozen=True)
class AcceptedEditInput:
    """REST edit acceptance and edited input buffer creation result."""

    request: AcceptedChatWriteRequest
    input_buffer: InputBuffer | None


@dataclasses.dataclass(frozen=True)
class AcceptedPendingCommand:
    """REST command acceptance and pending command storage result."""

    request: AcceptedChatWriteRequest
    command_id: str | None


@dataclasses.dataclass(frozen=True)
class AcceptedFailedRunRetry:
    """REST failed-run retry acceptance result."""

    request: AcceptedChatWriteRequest
    failed_event_id: str


@dataclasses.dataclass(frozen=True)
class AcceptedStopRequest:
    """REST stop intent recording result."""

    session_id: str
    stop_request_id: str
    runtime_was_running: bool


@dataclasses.dataclass
class ChatWriteService:
    """REST chat write idempotency facade."""

    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    chat_write_request_repository: Annotated[
        ChatWriteRequestRepository, Depends(ChatWriteRequestRepository)
    ]
    message_repository: Annotated[MessageRepository, Depends(MessageRepository)]
    input_buffer_service: Annotated[InputBufferService, Depends(InputBufferService)]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]

    async def create_idempotent_edit_input(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
        client_request_id: str,
        message_id: str,
        text: str,
        metadata: dict[str, str],
        attachments: list[str],
        file_parts: list[FileOutputPart],
        payload: dict[str, object],
    ) -> AcceptedEditInput:
        """Accept idle session edit idempotently and create edited buffer."""
        async with self.session_manager() as session:
            await self._lock_session_for_idle_control(
                session,
                agent_id=agent_id,
                session_id=session_id,
            )
            record, created = await self._create_idempotent_record(
                session,
                session_id=session_id,
                user_id=user_id,
                client_request_id=client_request_id,
                write_type=ChatWriteRequestType.EDIT_MESSAGE,
                accepted_type=ChatWriteRequestType.EDIT_MESSAGE,
                accepted_id=message_id,
                history_reload_required=True,
                payload=payload,
            )
            if not created:
                return AcceptedEditInput(
                    request=AcceptedChatWriteRequest(
                        session_id=record.session_id,
                        record=record,
                        created=False,
                    ),
                    input_buffer=None,
                )

            target = await self.message_repository.get_by_id(session, message_id)
            if (
                target is None
                or target.session_id != session_id
                or target.reverted
                or target.kind != EventKind.USER_MESSAGE
            ):
                raise ValueError("Message is not editable")
            await self.message_repository.mark_reverted_from_model_order(
                session,
                session_id,
                target.model_order,
            )
            await self.input_buffer_service.delete_by_session_id(
                session,
                session_id,
            )
            result = await self.input_buffer_service.enqueue(
                session,
                InputBufferEnqueue(
                    session_id=session_id,
                    kind=InputBufferKind.EDITED_USER_MESSAGE,
                    actor_user_id=user_id,
                    content=text,
                    idempotency_key=client_request_id,
                    metadata=metadata,
                    action=None,
                    attachments=attachments,
                    file_parts=file_parts,
                ),
            )
            await self.agent_session_repository.mark_running_for_input_wakeup(
                session,
                session_id,
            )
            input_buffer = result.input_buffer

        return AcceptedEditInput(
            request=AcceptedChatWriteRequest(
                session_id=record.session_id,
                record=record,
                created=True,
            ),
            input_buffer=input_buffer,
        )

    async def create_idempotent_pending_command(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
        client_request_id: str,
        command_name: str,
        payload: dict[str, object],
    ) -> AcceptedPendingCommand:
        """Store idle session command as single pending command."""
        async with self.session_manager() as session:
            await self._lock_session_for_idle_control(
                session,
                agent_id=agent_id,
                session_id=session_id,
            )
            pending_inputs = await self.input_buffer_service.list_by_session_id(
                session,
                session_id,
            )
            if pending_inputs:
                raise ValueError("Session has pending input")
            command_id = uuid7().hex
            record, created = await self._create_idempotent_record(
                session,
                session_id=session_id,
                user_id=user_id,
                client_request_id=client_request_id,
                write_type=ChatWriteRequestType.COMMAND,
                accepted_type=ChatWriteRequestType.COMMAND,
                accepted_id=command_id,
                history_reload_required=True,
                payload=payload,
            )
            if not created:
                return AcceptedPendingCommand(
                    request=AcceptedChatWriteRequest(
                        session_id=record.session_id,
                        record=record,
                        created=False,
                    ),
                    command_id=None,
                )
            updated = await self.agent_session_repository.enqueue_pending_command(
                session,
                session_id=session_id,
                command_id=command_id,
                command_name=command_name,
                payload=payload,
                user_id=user_id,
            )
            if updated is None:
                raise ValueError("Session cannot accept command")

        return AcceptedPendingCommand(
            request=AcceptedChatWriteRequest(
                session_id=record.session_id,
                record=record,
                created=True,
            ),
            command_id=command_id,
        )

    async def create_idempotent_failed_run_retry(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
        client_request_id: str,
        failed_event_id: str,
        payload: dict[str, object],
    ) -> AcceptedFailedRunRetry:
        """Accept idle failed-run retry idempotently and reopen normal dispatch."""
        async with self.session_manager() as session:
            existing = (
                await self.chat_write_request_repository.get_by_client_request_id(
                    session,
                    session_id=session_id,
                    user_id=user_id,
                    client_request_id=client_request_id,
                )
            )
            if existing is not None:
                self._validate_existing_record(
                    existing,
                    write_type=ChatWriteRequestType.FAILED_RUN_RETRY,
                    payload=payload,
                )
                return AcceptedFailedRunRetry(
                    request=AcceptedChatWriteRequest(
                        session_id=existing.session_id,
                        record=existing,
                        created=False,
                    ),
                    failed_event_id=existing.accepted_id,
                )

            await self._lock_session_for_idle_control(
                session,
                agent_id=agent_id,
                session_id=session_id,
            )
            pending_inputs = await self.input_buffer_service.list_by_session_id(
                session,
                session_id,
            )
            if pending_inputs:
                raise ValueError("Session has pending input")

            target = await self.message_repository.get_by_id(session, failed_event_id)
            self._validate_failed_run_retry_target(target, session_id=session_id)
            if target is None:
                raise ValueError("Failed-run error not found")
            latest_visible = (
                await self.message_repository.get_latest_retry_visible_event(
                    session,
                    session_id,
                )
            )
            if latest_visible is None or latest_visible.id != failed_event_id:
                raise ValueError(
                    "Failed-run error is no longer the latest visible event"
                )

            record, created = await self._create_idempotent_record(
                session,
                session_id=session_id,
                user_id=user_id,
                client_request_id=client_request_id,
                write_type=ChatWriteRequestType.FAILED_RUN_RETRY,
                accepted_type=ChatWriteRequestType.FAILED_RUN_RETRY,
                accepted_id=failed_event_id,
                history_reload_required=True,
                payload=payload,
            )
            if created:
                await self.message_repository.mark_reverted_from_model_order(
                    session,
                    session_id,
                    target.model_order,
                )
                await self.input_buffer_service.delete_by_session_id(
                    session,
                    session_id,
                )
                await self.agent_session_repository.mark_running(session, session_id)

        return AcceptedFailedRunRetry(
            request=AcceptedChatWriteRequest(
                session_id=record.session_id,
                record=record,
                created=created,
            ),
            failed_event_id=record.accepted_id,
        )

    async def request_session_stop(
        self,
        *,
        session_id: str,
        user_id: str,
    ) -> AcceptedStopRequest:
        """Record Session stop intent in durable state."""
        stop_request_id = uuid7().hex
        async with self.session_manager() as session:
            updated = await self.agent_session_repository.request_stop(
                session,
                session_id=session_id,
                stop_request_id=stop_request_id,
                user_id=user_id,
            )
        return AcceptedStopRequest(
            session_id=session_id,
            stop_request_id=stop_request_id,
            runtime_was_running=updated is not None,
        )

    def _validate_failed_run_retry_target(
        self,
        target: RDBEvent | None,
        *,
        session_id: str,
    ) -> None:
        """Verify that target is a visible terminal failed-run error event."""
        if target is None or target.session_id != session_id or target.reverted:
            raise ValueError("Failed-run error not found")
        if target.kind != EventKind.SYSTEM_ERROR:
            raise ValueError("Event is not a failed-run error")
        payload = SystemErrorPayload.model_validate(target.payload)
        if payload.failure is None or payload.failure.kind != "failed_run":
            raise ValueError("Event is not a failed-run error")

    def _validate_existing_record(
        self,
        record: ChatWriteRequest,
        *,
        write_type: ChatWriteRequestType,
        payload: dict[str, object],
    ) -> None:
        """Verify a previously accepted idempotent write record."""
        if record.write_type != write_type:
            raise ValueError("Client request ID already used for another write type")
        if record.payload != payload:
            raise ValueError("Client request ID already used for another payload")

    async def _lock_session_for_idle_control(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
    ) -> AgentSession:
        """Acquire session row lock for idle-only control action."""
        locked = await self.agent_session_repository.lock_by_id(
            session,
            session_id,
        )
        if locked is None:
            raise ValueError("AgentSession not found")
        if locked.agent_id != agent_id:
            raise ValueError("AgentSession does not belong to the agent")
        if locked.run_state != AgentSessionRunState.IDLE:
            raise ValueError("Session is running")
        if locked.pending_command_id is not None:
            raise ValueError("Session has pending command")
        return locked

    async def _create_idempotent_record(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        user_id: str,
        client_request_id: str,
        write_type: ChatWriteRequestType,
        accepted_type: ChatWriteRequestType,
        accepted_id: str,
        history_reload_required: bool,
        payload: dict[str, object],
    ) -> tuple[ChatWriteRequest, bool]:
        """Create REST write idempotency record and verify payload match."""
        record, created = await self.chat_write_request_repository.create_idempotent(
            session,
            ChatWriteRequestCreate(
                session_id=session_id,
                user_id=user_id,
                client_request_id=client_request_id,
                write_type=write_type,
                accepted_type=accepted_type,
                accepted_id=accepted_id,
                history_reload_required=history_reload_required,
                payload=payload,
            ),
        )
        if record.write_type != write_type:
            raise ValueError("Client request ID already used for another write type")
        if record.session_id != session_id:
            raise ValueError("Client request ID already used for another session")
        if record.payload != payload:
            raise ValueError("Client request ID already used for another payload")
        return record, created
