"""REST chat write service."""

import dataclasses
from typing import Annotated

from azcommon.result import Failure, Result, Success
from azcommon.uuid import uuid7
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentSessionKind,
    AgentSessionRunState,
    AgentSessionStatus,
    EventKind,
    InputBufferKind,
)
from azents.core.inference_profile import RequestedInferenceProfile
from azents.engine.events.types import FileOutputPart, SystemErrorPayload
from azents.rdb.deps import get_session_manager
from azents.rdb.models.chat_write_request import ChatWriteRequestType
from azents.rdb.models.event import RDBEvent
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSession
from azents.repos.chat_write_request.data import (
    ChatWriteRequest,
    ChatWriteRequestCreate,
    ChatWriteRequestCreateResult,
)
from azents.repos.chat_write_request.repository import ChatWriteRequestRepository
from azents.repos.input_buffer.data import InputBuffer
from azents.repos.message import MessageRepository
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.services.chat.data import SessionAccessDenied, SessionNotFound
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
    wake_needed: bool


class ChatWriteSessionNotFound(LookupError):
    """Final write transaction could not find the selected Session."""


class ChatWriteSessionAccessDenied(PermissionError):
    """Final write transaction found that Workspace access was revoked."""


@dataclasses.dataclass(frozen=True)
class AcceptedStopRequest:
    """REST stop intent recording result."""

    session_id: str
    stop_request_id: str
    runtime_was_running: bool
    stopped_session_ids: list[str]
    stop_request_ids_by_session: dict[str, str]


@dataclasses.dataclass
class ChatWriteService:
    """REST chat write idempotency facade."""

    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    agent_run_repository: Annotated[AgentRunRepository, Depends(AgentRunRepository)]
    chat_write_request_repository: Annotated[
        ChatWriteRequestRepository, Depends(ChatWriteRequestRepository)
    ]
    message_repository: Annotated[MessageRepository, Depends(MessageRepository)]
    workspace_user_repository: Annotated[
        WorkspaceUserRepository, Depends(WorkspaceUserRepository)
    ]
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
        inference_profile: RequestedInferenceProfile,
        metadata: dict[str, str],
        attachments: list[str],
        file_parts: list[FileOutputPart],
        payload: dict[str, object],
    ) -> AcceptedEditInput:
        """Accept idle session edit idempotently and create edited buffer."""
        async with self.session_manager() as session:
            locked = await self._lock_authorized_session(
                session,
                agent_id=agent_id,
                session_id=session_id,
                user_id=user_id,
            )
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
                    write_type=ChatWriteRequestType.EDIT_MESSAGE,
                    payload=payload,
                )
                pending = await self._find_pending_edit_input(
                    session,
                    session_id=session_id,
                    record=existing,
                )
                return AcceptedEditInput(
                    request=AcceptedChatWriteRequest(
                        session_id=existing.session_id,
                        record=existing,
                        created=False,
                    ),
                    input_buffer=pending,
                )
            self._validate_idle_control(locked)
            create_result = await self._create_idempotent_record(
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
            record = create_result.record
            if not create_result.created:
                pending = await self._find_pending_edit_input(
                    session,
                    session_id=session_id,
                    record=record,
                )
                return AcceptedEditInput(
                    request=AcceptedChatWriteRequest(
                        session_id=record.session_id,
                        record=record,
                        created=False,
                    ),
                    input_buffer=pending,
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
                    kind=InputBufferKind.USER_MESSAGE,
                    requested_model_target_label=inference_profile.model_target_label,
                    requested_reasoning_effort=inference_profile.reasoning_effort,
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
            locked = await self._lock_authorized_session(
                session,
                agent_id=agent_id,
                session_id=session_id,
                user_id=user_id,
            )
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
                    write_type=ChatWriteRequestType.COMMAND,
                    payload=payload,
                )
                return AcceptedPendingCommand(
                    request=AcceptedChatWriteRequest(
                        session_id=existing.session_id,
                        record=existing,
                        created=False,
                    ),
                    command_id=(
                        existing.accepted_id
                        if locked.pending_command_id == existing.accepted_id
                        else None
                    ),
                )
            self._validate_idle_control(locked)
            pending_inputs = await self.input_buffer_service.list_by_session_id(
                session,
                session_id,
            )
            if pending_inputs:
                raise ValueError("Session has pending input")
            command_id = uuid7().hex
            create_result = await self._create_idempotent_record(
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
            record = create_result.record
            if not create_result.created:
                return AcceptedPendingCommand(
                    request=AcceptedChatWriteRequest(
                        session_id=record.session_id,
                        record=record,
                        created=False,
                    ),
                    command_id=(
                        record.accepted_id
                        if locked.pending_command_id == record.accepted_id
                        else None
                    ),
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
            locked = await self._lock_authorized_session(
                session,
                agent_id=agent_id,
                session_id=session_id,
                user_id=user_id,
            )
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
                    wake_needed=True,
                )

            self._validate_idle_control(locked)
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
            original_run = (
                await self.agent_run_repository.get_failed_by_terminal_result_event_id(
                    session,
                    session_id=session_id,
                    terminal_result_event_id=failed_event_id,
                )
            )
            if original_run is None:
                raise ValueError("Failed AgentRun not found")
            original_input_event_ids = (
                await self.agent_run_repository.list_input_event_ids(
                    session,
                    run_id=original_run.id,
                )
            )
            if not original_input_event_ids:
                raise ValueError("Failed AgentRun has no input events")

            create_result = await self._create_idempotent_record(
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
            record = create_result.record
            if create_result.created:
                await self.message_repository.mark_reverted_from_model_order(
                    session,
                    session_id,
                    target.model_order,
                )
                await self.input_buffer_service.delete_by_session_id(
                    session,
                    session_id,
                )
                retry_run = await self.agent_run_repository.create_pending(
                    session,
                    session_id=session_id,
                    parent_agent_run_id=None,
                )
                await self.agent_run_repository.associate_input_events(
                    session,
                    run_id=retry_run.id,
                    event_ids=original_input_event_ids,
                )
                await self.agent_session_repository.mark_running(session, session_id)

        return AcceptedFailedRunRetry(
            request=AcceptedChatWriteRequest(
                session_id=record.session_id,
                record=record,
                created=create_result.created,
            ),
            failed_event_id=record.accepted_id,
            wake_needed=True,
        )

    async def request_session_stop(
        self,
        *,
        session_id: str,
        user_id: str,
    ) -> Result[AcceptedStopRequest, SessionNotFound | SessionAccessDenied]:
        """Authorize and record Session subtree stop intent in one transaction."""
        stop_request_id = uuid7().hex
        runtime_was_running = False
        async with self.session_manager() as session:
            list_subtree_session_ids = (
                self.agent_session_repository.list_session_agent_subtree_session_ids
            )
            subtree_session_ids = await list_subtree_session_ids(
                session,
                agent_session_id=session_id,
            )
            # The subtree lookup acquires the root SessionAgent fence first. Lock
            # every Session in the same deterministic order as tree deletion before
            # membership. Otherwise a child write can hold child Session and wait
            # for WorkspaceUser while this transaction holds WorkspaceUser and waits
            # for that child Session.
            locked_sessions = await self.agent_session_repository.lock_by_ids(
                session,
                agent_session_ids=subtree_session_ids,
            )
            requested_session = locked_sessions.get(session_id)
            if requested_session is None:
                return Failure(SessionNotFound())
            missing_session_ids = set(subtree_session_ids) - locked_sessions.keys()
            if missing_session_ids:
                raise RuntimeError(
                    "SessionAgent subtree references missing AgentSessions"
                )
            if any(
                locked.workspace_id != requested_session.workspace_id
                for locked in locked_sessions.values()
            ):
                raise RuntimeError("SessionAgent subtree crossed Workspace authority")
            workspace_user = (
                await self.workspace_user_repository.lock_by_workspace_and_user(
                    session,
                    requested_session.workspace_id,
                    user_id,
                )
            )
            if workspace_user is None:
                return Failure(SessionAccessDenied())
            stopped_session_ids: list[str] = []
            stop_request_ids_by_session: dict[str, str] = {}
            for target_session_id in subtree_session_ids:
                updated = await self.agent_session_repository.request_stop(
                    session,
                    session_id=target_session_id,
                    stop_request_id=stop_request_id,
                    user_id=user_id,
                )
                if updated is not None:
                    persisted_stop_request_id = updated.stop_request_id
                    if persisted_stop_request_id is None:
                        raise RuntimeError(
                            "Durable stop intent is missing its request ID"
                        )
                    stopped_session_ids.append(target_session_id)
                    stop_request_ids_by_session[target_session_id] = (
                        persisted_stop_request_id
                    )
                    runtime_was_running = True
        return Success(
            AcceptedStopRequest(
                session_id=session_id,
                stop_request_id=stop_request_id,
                runtime_was_running=runtime_was_running,
                stopped_session_ids=stopped_session_ids,
                stop_request_ids_by_session=stop_request_ids_by_session,
            )
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
        if record.write_type != write_type or record.accepted_type != write_type:
            raise ValueError("Client request ID already used for another write type")
        if not record.history_reload_required:
            raise ValueError("Client request ID has invalid response semantics")
        if record.payload != payload:
            raise ValueError("Client request ID already used for another payload")

    async def _lock_authorized_session(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
    ) -> AgentSession:
        """Lock the Session and, for user writes, its Workspace membership."""
        locked = await self.agent_session_repository.lock_by_id(
            session,
            session_id,
        )
        if locked is None:
            raise ChatWriteSessionNotFound("AgentSession not found")
        if locked.agent_id != agent_id:
            raise ChatWriteSessionNotFound("AgentSession does not belong to the agent")
        workspace_user = (
            await self.workspace_user_repository.lock_by_workspace_and_user(
                session,
                locked.workspace_id,
                user_id,
            )
        )
        if workspace_user is None:
            raise ChatWriteSessionAccessDenied("Session access denied")
        if locked.status is not AgentSessionStatus.ACTIVE:
            raise ValueError("Session is not active")
        if locked.session_kind is AgentSessionKind.SUBAGENT:
            raise ValueError("Subagent sessions are read-only")

        return locked

    def _validate_idle_control(self, locked: AgentSession) -> None:
        """Reject a new idle-only action when the locked Session is busy."""
        if locked.run_state != AgentSessionRunState.IDLE:
            raise ValueError("Session is running")
        if locked.pending_command_id is not None:
            raise ValueError("Session has pending command")

    async def _find_pending_edit_input(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        record: ChatWriteRequest,
    ) -> InputBuffer | None:
        """Recover an accepted edit buffer that still needs a worker wake."""
        pending = await self.input_buffer_service.list_by_session_id(
            session,
            session_id,
        )
        return next(
            (
                item
                for item in pending
                if item.kind is InputBufferKind.USER_MESSAGE
                and item.actor_user_id == record.user_id
                and item.idempotency_key == record.client_request_id
            ),
            None,
        )

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
    ) -> ChatWriteRequestCreateResult:
        """Create REST write idempotency record and verify payload match."""
        create_result = await self.chat_write_request_repository.create_idempotent(
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
        record = create_result.record
        if record.write_type != write_type:
            raise ValueError("Client request ID already used for another write type")
        if record.session_id != session_id:
            raise ValueError("Client request ID already used for another session")
        if record.payload != payload:
            raise ValueError("Client request ID already used for another payload")
        return create_result
