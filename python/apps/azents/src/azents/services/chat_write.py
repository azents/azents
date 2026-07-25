"""REST chat write service."""

import dataclasses
from typing import Annotated, assert_never

from azcommon.result import Failure, Success
from azcommon.uuid import uuid7
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentLifecycleStatus,
    AgentSessionKind,
    AgentSessionRunState,
    AgentSessionStatus,
    EventKind,
    InputBufferKind,
    InputBufferSchedulingMode,
)
from azents.core.inference_profile import RequestedInferenceProfile
from azents.engine.events.types import FileOutputPart, SystemErrorPayload
from azents.rdb.deps import get_session_manager
from azents.rdb.models.chat_write_request import ChatWriteRequestType
from azents.rdb.models.event import RDBEvent
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSession
from azents.repos.chat_write_request import ChatWriteRequestRepository
from azents.repos.chat_write_request.data import (
    ChatWriteRequest,
    ChatWriteRequestCreate,
)
from azents.repos.input_buffer.data import InputBuffer
from azents.repos.message import MessageRepository
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.services.exchange_file import (
    ExchangeFileService,
    FileAccessDenied,
    FileExpired,
    FileNotFound,
    FileRetentionOwnerConflict,
    FileUnavailable,
)
from azents.services.input_buffer import InputBufferEnqueue, InputBufferService


def _raise_attachment_claim_error(error: object) -> None:
    """Raise the public-safe edit rejection for an attachment claim failure."""
    match error:
        case FileNotFound():
            raise ValueError("Attachment was not found.")
        case FileAccessDenied():
            raise ValueError("Attachment is outside this session.")
        case FileExpired():
            raise ValueError("Attachment has expired.")
        case FileUnavailable():
            raise ValueError("Attachment is unavailable.")
        case FileRetentionOwnerConflict():
            raise ValueError("Attachment is already used by another session.")
        case _:
            raise TypeError("Unexpected ExchangeFile claim error")


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
    stopped_session_ids: list[str]


@dataclasses.dataclass
class ChatWriteService:
    """REST chat write idempotency facade."""

    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    workspace_user_repository: Annotated[
        WorkspaceUserRepository, Depends(WorkspaceUserRepository)
    ]
    agent_run_repository: Annotated[AgentRunRepository, Depends(AgentRunRepository)]
    chat_write_request_repository: Annotated[
        ChatWriteRequestRepository, Depends(ChatWriteRequestRepository)
    ]
    message_repository: Annotated[MessageRepository, Depends(MessageRepository)]
    exchange_file_service: Annotated[ExchangeFileService, Depends(ExchangeFileService)]
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
            locked = await self._lock_and_reauthorize_session(
                session,
                agent_id=agent_id,
                session_id=session_id,
                user_id=user_id,
            )
            existing = await self._get_existing_idempotent_record(
                session,
                session_id=session_id,
                user_id=user_id,
                client_request_id=client_request_id,
                write_type=ChatWriteRequestType.EDIT_MESSAGE,
                payload=payload,
            )
            if existing is not None:
                return AcceptedEditInput(
                    request=AcceptedChatWriteRequest(
                        session_id=existing.session_id,
                        record=existing,
                        created=False,
                    ),
                    input_buffer=None,
                )
            self._validate_idle_control_state(locked)
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
                    kind=InputBufferKind.USER_MESSAGE,
                    scheduling_mode=InputBufferSchedulingMode.WAKE_SESSION,
                    requested_model_target_label=inference_profile.model_target_label,
                    requested_reasoning_effort=inference_profile.reasoning_effort,
                    sender_user_id=user_id,
                    content=text,
                    idempotency_key=client_request_id,
                    metadata=metadata,
                    action=None,
                    attachments=attachments,
                    file_parts=file_parts,
                ),
            )
            claim = await self.exchange_file_service.claim_input_attachments(
                session,
                agent_id=agent_id,
                session_id=session_id,
                user_id=user_id,
                attachment_uris=result.input_buffer.attachments,
            )
            match claim:
                case Success():
                    pass
                case Failure(error):
                    _raise_attachment_claim_error(error)
                case _:
                    assert_never(claim)
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
            locked = await self._lock_and_reauthorize_session(
                session,
                agent_id=agent_id,
                session_id=session_id,
                user_id=user_id,
            )
            existing = await self._get_existing_idempotent_record(
                session,
                session_id=session_id,
                user_id=user_id,
                client_request_id=client_request_id,
                write_type=ChatWriteRequestType.COMMAND,
                payload=payload,
            )
            if existing is not None:
                return AcceptedPendingCommand(
                    request=AcceptedChatWriteRequest(
                        session_id=existing.session_id,
                        record=existing,
                        created=False,
                    ),
                    command_id=None,
                )
            self._validate_idle_control_state(locked)
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
                requester_user_id=user_id,
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
            locked = await self._lock_and_reauthorize_session(
                session,
                agent_id=agent_id,
                session_id=session_id,
                user_id=user_id,
            )
            existing = await self._get_existing_idempotent_record(
                session,
                session_id=session_id,
                user_id=user_id,
                client_request_id=client_request_id,
                write_type=ChatWriteRequestType.FAILED_RUN_RETRY,
                payload=payload,
            )
            if existing is not None:
                return AcceptedFailedRunRetry(
                    request=AcceptedChatWriteRequest(
                        session_id=existing.session_id,
                        record=existing,
                        created=False,
                    ),
                    failed_event_id=existing.accepted_id,
                )

            self._validate_idle_control_state(locked)
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
                created=created,
            ),
            failed_event_id=record.accepted_id,
        )

    async def request_session_stop(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
    ) -> AcceptedStopRequest:
        """Record Session stop intent in durable state."""
        stop_request_id = uuid7().hex
        runtime_was_running = False
        async with self.session_manager() as session:
            locked = await self._lock_and_reauthorize_session(
                session,
                agent_id=agent_id,
                session_id=session_id,
                user_id=user_id,
            )
            locked_tree = await self.agent_session_repository.lock_root_tree_sessions(
                session,
                root_session_id=locked.id,
            )
            if not locked_tree or any(
                target.agent_id != locked.agent_id
                or target.workspace_id != locked.workspace_id
                for target in locked_tree
            ):
                raise ValueError("Session subtree is outside the root tree")
            stopped_session_ids = [target.id for target in locked_tree]
            for target_session_id in stopped_session_ids:
                updated = await self.agent_session_repository.request_stop(
                    session,
                    session_id=target_session_id,
                    stop_request_id=stop_request_id,
                    stop_requester_user_id=user_id,
                )
                runtime_was_running = runtime_was_running or updated is not None
        return AcceptedStopRequest(
            session_id=session_id,
            stop_request_id=stop_request_id,
            runtime_was_running=runtime_was_running,
            stopped_session_ids=stopped_session_ids,
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

    async def _lock_and_reauthorize_session(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
    ) -> AgentSession:
        """Lock one writable root Session and reauthorize its requester."""
        locked = await self.agent_session_repository.lock_by_id(
            session,
            session_id,
        )
        if locked is None:
            raise ValueError("AgentSession not found")
        if locked.agent_id != agent_id:
            raise ValueError("AgentSession does not belong to the agent")
        if locked.session_kind is AgentSessionKind.SUBAGENT:
            raise ValueError("Subagent sessions are read-only")
        if locked.status is not AgentSessionStatus.ACTIVE:
            raise ValueError("AgentSession is not active")
        agent = await self.agent_repository.lock_by_id(session, agent_id)
        if (
            agent is None
            or agent.lifecycle_status is not AgentLifecycleStatus.ACTIVE
            or agent.workspace_id != locked.workspace_id
        ):
            raise ValueError("AgentSession is not active")
        root = await self.agent_session_repository.get_root_session_agent_by_session_id(
            session,
            session_id,
        )
        if root is None or root.agent_session_id != locked.id:
            raise ValueError("AgentSession root lineage is invalid")
        workspace_user = (
            await self.workspace_user_repository.lock_by_workspace_and_user(
                session,
                workspace_id=locked.workspace_id,
                user_id=user_id,
            )
        )
        if workspace_user is None:
            raise ValueError("Requester does not have session access")
        return locked

    @staticmethod
    def _validate_idle_control_state(locked: AgentSession) -> None:
        """Validate mutable idle state after authorization and idempotency."""
        if locked.run_state != AgentSessionRunState.IDLE:
            raise ValueError("Session is running")
        if locked.pending_command_id is not None:
            raise ValueError("Session has pending command")

    async def _get_existing_idempotent_record(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        user_id: str,
        client_request_id: str,
        write_type: ChatWriteRequestType,
        payload: dict[str, object],
    ) -> ChatWriteRequest | None:
        """Resolve a reauthorized replay before mutable state validation."""
        existing = await self.chat_write_request_repository.get_by_client_request_id(
            session,
            session_id=session_id,
            requester_user_id=user_id,
            client_request_id=client_request_id,
        )
        if existing is None:
            return None
        self._validate_existing_record(
            existing,
            write_type=write_type,
            payload=payload,
        )
        return existing

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
                requester_user_id=user_id,
                creation_agent_id=None,
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
