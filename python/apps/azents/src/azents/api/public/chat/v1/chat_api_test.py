"""Chat v1 public endpoint tests."""

import datetime
from collections.abc import Sequence
from typing import cast
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from azcommon.result import Failure, Result, Success
from fastapi import BackgroundTasks, HTTPException
from pydantic import ValidationError

from azents.api.public.chat.v1 import (
    _validate_rest_session,  # pyright: ignore[reportPrivateUsage]  # Pin the REST session validation helper directly.
    _write_command_via_rest,  # pyright: ignore[reportPrivateUsage]  # Pin the REST write boundary helper directly.
    _write_edit_message_via_rest,  # pyright: ignore[reportPrivateUsage]  # Pin the REST write boundary helper directly.
    _write_input_via_rest,  # pyright: ignore[reportPrivateUsage]  # Pin the REST write boundary helper directly.
    _write_message_via_rest,  # pyright: ignore[reportPrivateUsage]  # Pin the REST write boundary helper directly.
    _write_new_session_message_via_rest,  # pyright: ignore[reportPrivateUsage]  # Pin the REST write boundary helper directly.
    archive_agent_session,
    cleanup_session_git_worktree,
    create_team_agent_session,
    delete_input_buffer,
    get_agent_session,
    get_subagent_tree,
    get_team_primary_agent_session,
    list_agent_sessions,
    list_history_events,
    list_input_actions,
    list_live_events,
    stop_session_run,
    update_agent_session_title,
    update_session_goal_status,
)
from azents.api.public.chat.v1.data import (
    AgentSessionCreateRequest,
    AgentSessionTitleUpdateRequest,
    ChatCommandWriteRequest,
    ChatEditMessageWriteRequest,
    ChatInputWriteRequest,
    ChatMessageWriteRequest,
    ChatSessionCreateMessageWriteRequest,
    CleanupSessionGitWorktreeRequest,
    GoalStatusUpdateRequest,
)
from azents.broker.types import (
    BrokerMessage,
    PublishedEvent,
    SessionActivity,
    SessionStopSignal,
    SessionWakeUp,
)
from azents.core.auth.deps import CurrentUser
from azents.core.enums import (
    AgentRunPhase,
    AgentRunStatus,
    AgentSessionKind,
    AgentSessionPrimaryKind,
    AgentSessionRunState,
    AgentSessionStartReason,
    AgentSessionStatus,
    EventKind,
    InputBufferKind,
)
from azents.core.inference_profile import (
    AppliedInferenceProfile,
    RequestedInferenceProfile,
)
from azents.core.llm_catalog import ModelReasoningEffort
from azents.engine.events.action_messages import (
    CommandAction,
    CreateGitWorktreeAction,
    SkillAction,
)
from azents.engine.events.types import (
    ActiveToolCall,
    Event,
    UserMessagePayload,
)
from azents.engine.run.input import InputMessage
from azents.engine.tools.goal import GoalStateSnapshot
from azents.engine.tools.skill import SkillProjectionState
from azents.rdb.models.chat_write_request import ChatWriteRequestType
from azents.rdb.models.event import JSONValue
from azents.repos.agent_session.data import AgentSession
from azents.repos.chat_write_request.data import ChatWriteRequest
from azents.repos.input_buffer.data import InputBuffer
from azents.services.agent_session_input import (
    BufferedAgentSessionInputResult,
    CreatedAgentSessionInputResult,
)
from azents.services.chat.data import (
    ArchiveSessionResult,
    ChatLiveRunState,
    ChatLiveStateSnapshot,
    InvalidSessionTitle,
    PaginatedEvents,
    PrimarySessionArchiveBlocked,
    RunningSessionArchiveBlocked,
    SessionAccessDenied,
    SessionNotFound,
    SubagentTreeNode,
    SubagentTreeProjection,
    UpdateGoalResult,
    UpdateGoalStatusInput,
)
from azents.services.chat.live_events import InMemoryLiveEventStore, LiveEventStore
from azents.services.chat_write import (
    AcceptedChatWriteRequest,
    AcceptedEditInput,
    AcceptedPendingCommand,
    AcceptedStopRequest,
)
from azents.services.session_git_worktree import GitWorktreeCleanupRequest


class _MemoryBroker:
    """In-memory broker for tests."""

    def __init__(self) -> None:
        self.messages: list[BrokerMessage] = []
        self.activity: SessionActivity | None = None

    async def send_message(self, message: BrokerMessage) -> None:
        """Record sent broker messages."""
        self.messages.append(message)

    async def receive_messages(self) -> list[BrokerMessage]:
        """Not used in tests."""
        return []

    async def publish_event(self, _session_id: str, _event: PublishedEvent) -> None:
        """Not used in tests."""

    async def renew_session_ttl(self, _session_id: str) -> None:
        """Not used in tests."""

    async def renew_session_owner_heartbeat(self, _session_id: str) -> None:
        """Not used in tests."""

    async def release_session_lock(self, _session_id: str) -> None:
        """Not used in tests."""

    async def set_session_activity(
        self,
        _session_id: str,
        *,
        run_id: str,
        phase: AgentRunPhase | None = None,
        active_tool_calls: Sequence[ActiveToolCall] = (),
    ) -> None:
        """Not used in tests."""

    async def clear_session_activity(self, _session_id: str) -> None:
        """Not used in tests."""

    async def get_session_activity(self, _session_id: str) -> SessionActivity | None:
        """Return current test activity state."""
        return self.activity


class _MemoryBroadcast:
    """WebSocket broadcast for tests."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    async def publish(self, session_id: str, event_json: dict[str, object]) -> None:
        """Record published events."""
        self.events.append((session_id, event_json))


def _exchange_file_service() -> AsyncMock:
    """ExchangeFileService double for route helper calls without attachments."""
    return AsyncMock()


def _model_file_service() -> AsyncMock:
    """ModelFileService double for route helper calls without attachments."""
    return AsyncMock()


class _BufferedInputService:
    """AgentSessionInputService double for tests."""

    def __init__(self, target_session_id: str | None = None) -> None:
        self.calls: list[str] = []
        self.kwargs: list[dict[str, object]] = []
        self.target_session_id = target_session_id

    async def create_buffered_agent_input(
        self,
        **kwargs: object,
    ) -> Success[BufferedAgentSessionInputResult]:
        """Return InputBuffer creation result."""
        self.calls.append("create_buffered_agent_input")
        self.kwargs.append(kwargs)
        session_id = self.target_session_id or str(kwargs["agent_session_id"])
        input_buffer = self._input_buffer(kwargs, session_id=session_id)
        return Success(
            BufferedAgentSessionInputResult(
                agent_runtime_id="1123456789abcdef0123456789abcdef",
                agent_session_id=session_id,
                input_buffer=input_buffer,
            )
        )

    async def create_buffered_agent_action_input(
        self,
        **kwargs: object,
    ) -> Success[BufferedAgentSessionInputResult]:
        """Return action InputBuffer creation result."""
        self.calls.append("create_buffered_agent_action_input")
        self.kwargs.append(kwargs)
        session_id = self.target_session_id or str(kwargs["agent_session_id"])
        message = cast(InputMessage, kwargs["message"])
        input_buffer = InputBuffer(
            id="0123456789abcdef0123456789abcdef",
            session_id=session_id,
            kind=InputBufferKind.ACTION_MESSAGE,
            requested_model_target_label=None,
            requested_reasoning_effort=None,
            actor_user_id=str(kwargs["user_id"]),
            content=str(message.text),
            idempotency_key=(
                str(kwargs["client_request_id"])
                if kwargs.get("client_request_id") is not None
                else None
            ),
            metadata={"source": "chat"},
            action=cast(dict[str, JSONValue], kwargs["action"]),
            attachments=[],
            file_parts=[],
            created_at=datetime.datetime(2026, 5, 19, tzinfo=datetime.UTC),
        )
        return Success(
            BufferedAgentSessionInputResult(
                agent_runtime_id="1123456789abcdef0123456789abcdef",
                agent_session_id=session_id,
                input_buffer=input_buffer,
            )
        )

    async def create_team_session_with_buffered_input(
        self,
        **kwargs: object,
    ) -> Success[CreatedAgentSessionInputResult]:
        """Return AgentSession creation with InputBuffer result."""
        self.calls.append("create_team_session_with_buffered_input")
        self.kwargs.append(kwargs)
        session_id = self.target_session_id or "4123456789abcdef0123456789abcdef"
        input_buffer = self._input_buffer(kwargs, session_id=session_id)
        return Success(
            CreatedAgentSessionInputResult(
                agent_runtime_id="1123456789abcdef0123456789abcdef",
                agent_session=AgentSession(
                    inference_state=None,
                    id=session_id,
                    workspace_id="workspace-1",
                    agent_id=str(kwargs["agent_id"]),
                    handle="test-session-handle",
                    session_kind=AgentSessionKind.ROOT,
                    status=AgentSessionStatus.ACTIVE,
                    start_reason=AgentSessionStartReason.INITIAL,
                    title=None,
                    title_source=None,
                    title_generated_at=None,
                    title_generation_event_id=None,
                    last_user_input_at=datetime.datetime(
                        2026, 6, 5, tzinfo=datetime.UTC
                    ),
                    started_at=datetime.datetime(2026, 6, 5, tzinfo=datetime.UTC),
                    created_at=datetime.datetime(2026, 6, 5, tzinfo=datetime.UTC),
                    updated_at=datetime.datetime(2026, 6, 5, tzinfo=datetime.UTC),
                ),
                input_buffer=input_buffer,
            )
        )

    def _input_buffer(
        self,
        kwargs: dict[str, object],
        *,
        session_id: str,
    ) -> InputBuffer:
        """Create an InputBuffer for test responses."""
        message = cast(InputMessage, kwargs["message"])
        return InputBuffer(
            id="0123456789abcdef0123456789abcdef",
            session_id=session_id,
            kind=InputBufferKind.USER_MESSAGE,
            requested_model_target_label=None,
            requested_reasoning_effort=None,
            actor_user_id=str(kwargs["user_id"]),
            content=str(message.text),
            idempotency_key=(
                str(kwargs["client_request_id"])
                if kwargs.get("client_request_id") is not None
                else None
            ),
            metadata={"source": "chat"},
            attachments=message.attachments,
            file_parts=message.file_parts,
            created_at=datetime.datetime(2026, 5, 19, tzinfo=datetime.UTC),
        )


class _RestWriteChatService:
    """ChatSessionService double for REST write tests."""

    def __init__(
        self,
        session_id: str = "0123456789abcdef0123456789abcdef",
        *,
        session_kind: AgentSessionKind = AgentSessionKind.ROOT,
    ) -> None:
        self.session_id = session_id
        self.session_kind = session_kind
        self.get_agent_session_calls: list[tuple[str, str, str]] = []
        self.live_session_ids: list[str] = []
        self.event = Event(
            id="1123456789abcdef0123456789abcdef",
            session_id=session_id,
            kind=EventKind.USER_MESSAGE,
            payload=UserMessagePayload(
                content="hello",
                attachments=[],
                metadata={
                    "source": "chat",
                    "live_projection": "input_buffer",
                    "input_buffer_id": "0123456789abcdef0123456789abcdef",
                },
            ),
            model_order=0,
            external_id="0123456789abcdef0123456789abcdef",
            adapter=None,
            provider=None,
            model=None,
            native_format=None,
            schema_version="1",
            created_at=datetime.datetime(2026, 6, 5, tzinfo=datetime.UTC),
        )

    async def get_agent_session(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
    ) -> Success[AgentSession]:
        """Return the confirmed AgentSession."""
        self.get_agent_session_calls.append((agent_id, session_id, user_id))
        return Success(
            AgentSession(
                inference_state=None,
                id=self.session_id,
                workspace_id="workspace-1",
                agent_id=agent_id,
                handle="test-session-handle",
                session_kind=self.session_kind,
                status=AgentSessionStatus.ACTIVE,
                start_reason=AgentSessionStartReason.INITIAL,
                title=None,
                title_source=None,
                title_generated_at=None,
                title_generation_event_id=None,
                last_user_input_at=datetime.datetime(2026, 6, 5, tzinfo=datetime.UTC),
                started_at=datetime.datetime(2026, 6, 5, tzinfo=datetime.UTC),
                created_at=datetime.datetime(2026, 6, 5, tzinfo=datetime.UTC),
                updated_at=datetime.datetime(2026, 6, 5, tzinfo=datetime.UTC),
            )
        )

    async def list_live_events(
        self,
        session_id: str,
        *,
        user_id: str,
        live_event_store: LiveEventStore | None = None,
    ) -> Success[ChatLiveStateSnapshot]:
        """Return live snapshot after REST write."""
        del user_id, live_event_store
        self.live_session_ids.append(session_id)
        return Success(
            ChatLiveStateSnapshot(
                partial_history_events=[],
                input_buffer_events=[self.event],
                run=None,
            )
        )


class _StopChatService:
    """Stop access control service double for tests."""

    def __init__(self) -> None:
        self.session_ids: list[str] = []
        self.result: Success[AgentSession] | Failure[SessionAccessDenied] = Success(
            AgentSession(
                inference_state=None,
                id="1123456789abcdef0123456789abcdef",
                workspace_id="workspace-1",
                agent_id="agent-1",
                handle="test-session-handle",
                session_kind=AgentSessionKind.ROOT,
                status=AgentSessionStatus.ACTIVE,
                start_reason=AgentSessionStartReason.INITIAL,
                title=None,
                title_source=None,
                title_generated_at=None,
                title_generation_event_id=None,
                last_user_input_at=datetime.datetime(2026, 6, 5, tzinfo=datetime.UTC),
                started_at=datetime.datetime(2026, 6, 5, tzinfo=datetime.UTC),
                created_at=datetime.datetime(2026, 6, 5, tzinfo=datetime.UTC),
                updated_at=datetime.datetime(2026, 6, 5, tzinfo=datetime.UTC),
            )
        )

    async def get_session(
        self,
        session_id: str,
        *,
        user_id: str,
    ) -> Success[AgentSession] | Failure[SessionAccessDenied]:
        """Return session access validation result."""
        del user_id
        self.session_ids.append(session_id)
        return self.result


class _SubagentTreeChatService:
    """Subagent Tree service double for route tests."""

    def __init__(self) -> None:
        self.result: Success[SubagentTreeProjection] | Failure[SessionNotFound] = (
            Success(
                SubagentTreeProjection(
                    root_session_agent_id="root-agent",
                    root_agent_session_id="1123456789abcdef0123456789abcdef",
                    current_session_agent_id="root-agent",
                    nodes=[
                        SubagentTreeNode(
                            session_agent_id="root-agent",
                            agent_session_id="1123456789abcdef0123456789abcdef",
                            parent_session_agent_id=None,
                            name="root",
                            path="/root",
                            agent_type="default",
                            status="running",
                            last_task_message=None,
                            last_message_at=None,
                            unread_result=False,
                            latest_run_id=None,
                            latest_run_index=None,
                            latest_run_status=None,
                            terminal_result_event_id=None,
                            terminal_result_message=None,
                            children=[
                                SubagentTreeNode(
                                    session_agent_id="child-agent",
                                    agent_session_id=(
                                        "2123456789abcdef0123456789abcdef"
                                    ),
                                    parent_session_agent_id="root-agent",
                                    name="child",
                                    path="/root/child",
                                    agent_type="default",
                                    status="completed",
                                    last_task_message="work",
                                    last_message_at=datetime.datetime(
                                        2026, 7, 10, 4, 5, tzinfo=datetime.UTC
                                    ),
                                    unread_result=True,
                                    latest_run_id=("3123456789abcdef0123456789abcdef"),
                                    latest_run_index=1,
                                    latest_run_status=AgentRunStatus.COMPLETED,
                                    terminal_result_event_id=(
                                        "4123456789abcdef0123456789abcdef"
                                    ),
                                    terminal_result_message="done",
                                )
                            ],
                        )
                    ],
                )
            )
        )

    async def get_subagent_tree(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
    ) -> Success[SubagentTreeProjection] | Failure[SessionNotFound]:
        """Return configured Subagent Tree projection."""
        del agent_id, session_id, user_id
        return self.result


class _GoalStatusChatService:
    """Goal status service double for tests."""

    def __init__(self) -> None:
        self.inputs: list[UpdateGoalStatusInput] = []
        self.event = Event(
            id="2123456789abcdef0123456789abcdef",
            session_id="1123456789abcdef0123456789abcdef",
            kind=EventKind.GOAL_UPDATED,
            payload=UserMessagePayload(
                content="",
                attachments=[],
                metadata={
                    "source": "goal",
                    "goal_control_action": "resume",
                    "previous_goal_status": "blocked",
                    "resume_hint": "CI credentials are restored.",
                },
            ),
            created_at=datetime.datetime(2026, 6, 5, tzinfo=datetime.UTC),
        )

    async def update_goal_status(
        self,
        session_id: str,
        *,
        user_id: str,
        input: UpdateGoalStatusInput,
    ) -> Success[UpdateGoalResult]:
        """Return successful goal status update result."""
        del session_id, user_id
        self.inputs.append(input)
        return Success(
            UpdateGoalResult(
                goal=GoalStateSnapshot(
                    objective="Ship the feature",
                    status="active",
                    created_at="2026-06-05T00:00:00+00:00",
                    updated_at="2026-06-05T00:01:00+00:00",
                ),
                agent_id="agent-1",
                workspace_id="workspace-1",
                wake_up=True,
                event=self.event,
            )
        )


class _StopWriteService:
    """Stop write service double for tests."""

    def __init__(self) -> None:
        self.session_ids: list[str] = []
        self.user_ids: list[str] = []
        self.stopped_session_ids = ["1123456789abcdef0123456789abcdef"]

    async def request_session_stop(
        self,
        *,
        session_id: str,
        user_id: str,
    ) -> AcceptedStopRequest:
        """Store stop intent record requests."""
        self.session_ids.append(session_id)
        self.user_ids.append(user_id)
        return AcceptedStopRequest(
            session_id=session_id,
            stop_request_id="stop-request-1",
            runtime_was_running=True,
            stopped_session_ids=self.stopped_session_ids,
        )


class _RestWriteIdempotencyService:
    """REST edit/command idempotency service double."""

    def __init__(self, *, created: bool = True) -> None:
        self.created = created
        self.calls: list[dict[str, object]] = []

    async def create_idempotent_edit_input(
        self,
        **kwargs: object,
    ) -> AcceptedEditInput:
        """Return idempotent edit request acceptance result."""
        self.calls.append(kwargs)
        record = self._record(
            kwargs,
            write_type=ChatWriteRequestType.EDIT_MESSAGE,
            accepted_id=str(kwargs["message_id"]),
        )
        input_buffer = (
            InputBuffer(
                id="0123456789abcdef0123456789abcdef",
                session_id=str(kwargs["session_id"]),
                kind=InputBufferKind.USER_MESSAGE,
                requested_model_target_label=None,
                requested_reasoning_effort=None,
                actor_user_id=str(kwargs["user_id"]),
                content=str(kwargs["text"]),
                idempotency_key=str(kwargs["client_request_id"]),
                metadata=cast(dict[str, str], kwargs["metadata"]),
                attachments=cast(list[str], kwargs["attachments"]),
                file_parts=[],
                created_at=datetime.datetime(2026, 5, 19, tzinfo=datetime.UTC),
            )
            if self.created
            else None
        )
        return AcceptedEditInput(
            request=AcceptedChatWriteRequest(
                session_id=str(kwargs["session_id"]),
                record=record,
                created=self.created,
            ),
            input_buffer=input_buffer,
        )

    async def create_idempotent_pending_command(
        self,
        **kwargs: object,
    ) -> AcceptedPendingCommand:
        """Return idempotent command request acceptance result."""
        self.calls.append(kwargs)
        record = self._record(
            kwargs,
            write_type=ChatWriteRequestType.COMMAND,
            accepted_id="command-request-1",
        )
        return AcceptedPendingCommand(
            request=AcceptedChatWriteRequest(
                session_id=str(kwargs["session_id"]),
                record=record,
                created=self.created,
            ),
            command_id="command-request-1" if self.created else None,
        )

    def _record(
        self,
        kwargs: dict[str, object],
        *,
        write_type: ChatWriteRequestType,
        accepted_id: str,
    ) -> ChatWriteRequest:
        """Create an idempotency record for tests."""
        record = ChatWriteRequest(
            id="write-request-1",
            session_id=str(kwargs["session_id"]),
            user_id=str(kwargs["user_id"]),
            client_request_id=str(kwargs["client_request_id"]),
            write_type=write_type,
            accepted_type=write_type,
            accepted_id=accepted_id,
            history_reload_required=True,
            payload=cast(dict[str, object], kwargs["payload"]),
            created_at=datetime.datetime(2026, 6, 5, tzinfo=datetime.UTC),
        )
        return record


class _EmptySkillStore:
    """SkillStateStore double with empty projection."""

    async def load(self, agent_id: str, session_id: str) -> SkillProjectionState:
        """Return empty Skill projection state."""
        del agent_id, session_id
        return SkillProjectionState()


class _DeleteInputBufferService:
    """ChatSessionService double for tests."""

    async def delete_input_buffer(
        self,
        session_id: str,
        buffer_id: str,
        *,
        user_id: str,
    ) -> Success[None]:
        """Return successful deletion."""
        del session_id, buffer_id, user_id
        return Success(None)


class _EventService:
    """Event query service double for tests."""

    def __init__(self) -> None:
        self.event = Event(
            id="0123456789abcdef0123456789abcdef",
            session_id="1123456789abcdef0123456789abcdef",
            kind=EventKind.USER_MESSAGE,
            payload=UserMessagePayload(
                content="hello",
                attachments=[],
                metadata={"source": "chat"},
            ),
            model_order=1000,
            external_id="input-1",
            adapter=None,
            provider=None,
            model=None,
            native_format=None,
            schema_version="1",
            created_at=datetime.datetime(2026, 6, 4, tzinfo=datetime.UTC),
        )
        self.inference_profile = AppliedInferenceProfile(
            model_target_label="reasoning",
            reasoning_effort=ModelReasoningEffort.HIGH,
        )

    async def get_session(
        self,
        session_id: str,
        *,
        user_id: str,
    ) -> Success[AgentSession]:
        """Return session lookup result."""
        del user_id
        return Success(
            AgentSession(
                inference_state=None,
                id=session_id,
                workspace_id="workspace-1",
                agent_id="agent-1",
                handle="test-session-handle",
                session_kind=AgentSessionKind.ROOT,
                status=AgentSessionStatus.ACTIVE,
                start_reason=AgentSessionStartReason.INITIAL,
                title=None,
                title_source=None,
                title_generated_at=None,
                title_generation_event_id=None,
                last_user_input_at=datetime.datetime(2026, 6, 5, tzinfo=datetime.UTC),
                started_at=datetime.datetime(2026, 6, 5, tzinfo=datetime.UTC),
                created_at=datetime.datetime(2026, 6, 5, tzinfo=datetime.UTC),
                updated_at=datetime.datetime(2026, 6, 5, tzinfo=datetime.UTC),
            )
        )

    async def list_history_events(
        self,
        session_id: str,
        *,
        user_id: str,
        limit: int = 50,
        before: str | None = None,
        after: str | None = None,
    ) -> Success[PaginatedEvents]:
        """Return history query result."""
        del session_id, user_id, limit, before, after
        return Success(
            PaginatedEvents(
                items=[self.event],
                has_more=False,
                has_newer=False,
            )
        )

    async def list_live_events(
        self,
        session_id: str,
        *,
        user_id: str,
        live_event_store: LiveEventStore | None = None,
    ) -> Success[ChatLiveStateSnapshot]:
        """Return live query result."""
        del session_id, user_id, live_event_store
        return Success(
            ChatLiveStateSnapshot(
                partial_history_events=[self.event],
                input_buffer_events=[],
                run=ChatLiveRunState(
                    run_id="2123456789abcdef0123456789abcdef",
                    phase=AgentRunPhase.WAITING_FOR_MODEL,
                    status=AgentRunStatus.RUNNING,
                    inference_profile=self.inference_profile,
                ),
                session_run_state=AgentSessionRunState.RUNNING,
            )
        )


class _AgentSessionRouteChatService:
    """Agent session route service double for tests."""

    def __init__(self) -> None:
        self.agent_id: str | None = None
        self.session_id: str | None = None
        self.existing_project_paths: list[str] | None = None
        self.setup_actions: list[CreateGitWorktreeAction] | None = None
        self.primary_session = AgentSession(
            inference_state=None,
            id="1123456789abcdef0123456789abcdef",
            workspace_id="workspace-1",
            agent_id="agent-1",
            handle="test-session-handle",
            session_kind=AgentSessionKind.ROOT,
            status=AgentSessionStatus.ACTIVE,
            primary_kind=AgentSessionPrimaryKind.TEAM_PRIMARY,
            start_reason=AgentSessionStartReason.INITIAL,
            title=None,
            title_source=None,
            title_generated_at=None,
            title_generation_event_id=None,
            last_user_input_at=datetime.datetime(2026, 6, 5, tzinfo=datetime.UTC),
            started_at=datetime.datetime(2026, 6, 25, tzinfo=datetime.UTC),
            created_at=datetime.datetime(2026, 6, 25, tzinfo=datetime.UTC),
            updated_at=datetime.datetime(2026, 6, 25, tzinfo=datetime.UTC),
        )
        self.secondary_session = AgentSession(
            inference_state=None,
            id="2123456789abcdef0123456789abcdef",
            workspace_id="workspace-1",
            agent_id="agent-1",
            handle="test-session-handle",
            session_kind=AgentSessionKind.ROOT,
            status=AgentSessionStatus.ACTIVE,
            primary_kind=None,
            start_reason=AgentSessionStartReason.INITIAL,
            title=None,
            title_source=None,
            title_generated_at=None,
            title_generation_event_id=None,
            last_user_input_at=datetime.datetime(2026, 6, 5, tzinfo=datetime.UTC),
            run_state=AgentSessionRunState.RUNNING,
            started_at=datetime.datetime(2026, 6, 25, tzinfo=datetime.UTC),
            created_at=datetime.datetime(2026, 6, 25, tzinfo=datetime.UTC),
            updated_at=datetime.datetime(2026, 6, 25, tzinfo=datetime.UTC),
        )
        self.title: str | None = None
        self.result: Result[AgentSession, SessionNotFound] = Success(
            self.primary_session
        )
        self.archive_result: Result[
            ArchiveSessionResult,
            SessionNotFound
            | PrimarySessionArchiveBlocked
            | RunningSessionArchiveBlocked,
        ] = Success(
            ArchiveSessionResult(
                archived_session_id="2123456789abcdef0123456789abcdef",
                cleanup_requested=False,
            )
        )

    async def get_team_primary_session(
        self,
        *,
        agent_id: str,
        user_id: str,
    ) -> Result[AgentSession, SessionNotFound]:
        """Return team primary session lookup result."""
        del user_id
        self.agent_id = agent_id
        return self.result

    async def list_agent_sessions(
        self,
        *,
        agent_id: str,
        user_id: str,
    ) -> Result[list[AgentSession], SessionNotFound]:
        """Return agent session list result."""
        del user_id
        self.agent_id = agent_id
        return Success([self.primary_session, self.secondary_session])

    async def create_team_session(
        self,
        *,
        agent_id: str,
        user_id: str,
        existing_project_paths: list[str],
        setup_actions: list[CreateGitWorktreeAction],
    ) -> Result[AgentSession, SessionNotFound]:
        """Return created team session result."""
        del user_id
        self.agent_id = agent_id
        self.existing_project_paths = existing_project_paths
        self.setup_actions = setup_actions
        return Success(self.secondary_session)

    async def get_agent_session(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
    ) -> Result[AgentSession, SessionNotFound]:
        """Return agent/session lookup result."""
        del user_id
        self.agent_id = agent_id
        self.session_id = session_id
        return self.result

    async def archive_agent_session(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
    ) -> Result[
        ArchiveSessionResult,
        SessionNotFound | PrimarySessionArchiveBlocked | RunningSessionArchiveBlocked,
    ]:
        """Return archive operation result."""
        del user_id
        self.agent_id = agent_id
        self.session_id = session_id
        return self.archive_result

    async def update_session_title(
        self,
        *,
        session_id: str,
        user_id: str,
        title: str | None,
    ) -> Result[AgentSession, SessionNotFound | InvalidSessionTitle]:
        """Return title update result."""
        del user_id
        self.session_id = session_id
        self.title = title
        if title == "invalid":
            return Failure(InvalidSessionTitle(reason="Invalid title."))
        return Success(self.primary_session.model_copy(update={"title": title}))


class _RouteWorktreeCleanupService:
    """Session worktree cleanup service double for route tests."""

    def __init__(self) -> None:
        self.cleanup_calls: list[tuple[str, str, str | None]] = []
        self.manual_cleanup_calls: list[tuple[str, str, str, str | None]] = []

    async def request_manual_cleanup(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
        session_workspace_project_id: str | None,
    ) -> Result[GitWorktreeCleanupRequest, object]:
        """Record manual cleanup request."""
        self.manual_cleanup_calls.append(
            (agent_id, session_id, user_id, session_workspace_project_id)
        )
        return Success(GitWorktreeCleanupRequest(cleanup_requested=True))

    async def run_cleanup_for_session(
        self,
        *,
        agent_id: str,
        session_id: str,
        session_workspace_project_id: str | None,
        on_event_appended: object | None = None,
        on_projection_updated: object | None = None,
    ) -> None:
        """Record cleanup execution."""
        del on_event_appended, on_projection_updated
        self.cleanup_calls.append((agent_id, session_id, session_workspace_project_id))


class TestAgentSessionRoutes:
    """Agent session route behavior."""

    async def test_get_team_primary_agent_session_returns_session(self) -> None:
        """Team primary session route exposes the session response."""
        chat_service = _AgentSessionRouteChatService()

        response = await get_team_primary_agent_session(
            agent_id="agent-1",
            current_user=CurrentUser(user_id="user-1", session_id="auth-session"),
            chat_service=chat_service,  # pyright: ignore[reportArgumentType]  # Service double exposes the route method surface.
        )

        assert response.id == "1123456789abcdef0123456789abcdef"
        assert response.agent_id == "agent-1"
        assert response.title is None
        assert chat_service.agent_id == "agent-1"

    async def test_list_agent_sessions_returns_primary_metadata(self) -> None:
        """Agent session list preserves primary metadata for the UI contract."""
        chat_service = _AgentSessionRouteChatService()

        response = await list_agent_sessions(
            agent_id="agent-1",
            current_user=CurrentUser(user_id="user-1", session_id="auth-session"),
            chat_service=chat_service,  # pyright: ignore[reportArgumentType]  # Service double exposes the route method surface.
        )

        assert [item.id for item in response.items] == [
            "1123456789abcdef0123456789abcdef",
            "2123456789abcdef0123456789abcdef",
        ]
        assert response.items[0].primary_kind == AgentSessionPrimaryKind.TEAM_PRIMARY
        assert response.items[0].run_state == AgentSessionRunState.IDLE
        assert response.items[1].primary_kind is None
        assert response.items[1].run_state == AgentSessionRunState.RUNNING

    async def test_create_team_agent_session_returns_non_primary_session(self) -> None:
        """Team session creation route returns the created non-primary session."""
        chat_service = _AgentSessionRouteChatService()

        response = await create_team_agent_session(
            agent_id="agent-1",
            request=AgentSessionCreateRequest(
                existing_project_paths=["/workspace/agent/app"],
                setup_actions=[],
            ),
            current_user=CurrentUser(user_id="user-1", session_id="auth-session"),
            chat_service=chat_service,  # pyright: ignore[reportArgumentType]  # Service double exposes the route method surface.
            broker=_MemoryBroker(),  # pyright: ignore[reportArgumentType]  # Service double exposes the route method surface.
        )

        assert response.id == "2123456789abcdef0123456789abcdef"
        assert response.agent_id == "agent-1"
        assert response.primary_kind is None
        assert chat_service.existing_project_paths == ["/workspace/agent/app"]
        assert chat_service.setup_actions == []

    async def test_create_team_agent_session_accepts_setup_actions(self) -> None:
        """Team session creation route accepts ordered setup actions."""
        chat_service = _AgentSessionRouteChatService()
        broker = _MemoryBroker()
        action = CreateGitWorktreeAction(
            source_project_path="/workspace/agent/source",
            starting_ref="main",
        )

        response = await create_team_agent_session(
            agent_id="agent-1",
            request=AgentSessionCreateRequest(
                existing_project_paths=[],
                setup_actions=[action],
            ),
            current_user=CurrentUser(user_id="user-1", session_id="auth-session"),
            chat_service=chat_service,  # pyright: ignore[reportArgumentType]  # Service double exposes the route method surface.
            broker=broker,  # pyright: ignore[reportArgumentType]  # Service double exposes the route method surface.
        )

        assert response.id == "2123456789abcdef0123456789abcdef"
        assert chat_service.existing_project_paths == []
        assert chat_service.setup_actions == [action]
        assert len(broker.messages) == 1
        assert isinstance(broker.messages[0], SessionWakeUp)

    async def test_update_agent_session_title_returns_updated_session(self) -> None:
        """Session title update route returns updated session metadata."""
        chat_service = _AgentSessionRouteChatService()

        response = await update_agent_session_title(
            session_id="1123456789abcdef0123456789abcdef",
            request=AgentSessionTitleUpdateRequest(title="Design review"),
            current_user=CurrentUser(user_id="user-1", session_id="auth-session"),
            chat_service=chat_service,  # pyright: ignore[reportArgumentType]  # Service double exposes the route method surface.
        )

        assert response.title == "Design review"
        assert chat_service.session_id == "1123456789abcdef0123456789abcdef"
        assert chat_service.title == "Design review"

    async def test_archive_agent_session_returns_no_content(self) -> None:
        """Archive route returns no content for an allowed non-primary session."""
        chat_service = _AgentSessionRouteChatService()

        response = await archive_agent_session(
            agent_id="agent-1",
            session_id="2123456789abcdef0123456789abcdef",
            background_tasks=BackgroundTasks(),
            current_user=CurrentUser(user_id="user-1", session_id="auth-session"),
            chat_service=chat_service,  # pyright: ignore[reportArgumentType]  # Service double exposes the route method surface.
            session_git_worktree_service=_RouteWorktreeCleanupService(),  # pyright: ignore[reportArgumentType]  # Service double exposes the route method surface.
        )

        assert response is None
        assert chat_service.agent_id == "agent-1"
        assert chat_service.session_id == "2123456789abcdef0123456789abcdef"

    async def test_cleanup_session_git_worktree_targets_project_id(self) -> None:
        """Cleanup route forwards the optional worktree Project target."""
        service = _RouteWorktreeCleanupService()
        background_tasks = BackgroundTasks()

        response = await cleanup_session_git_worktree(
            agent_id="1123456789abcdef0123456789abcdef",
            session_id="2123456789abcdef0123456789abcdef",
            request=CleanupSessionGitWorktreeRequest(
                project_id="3123456789abcdef0123456789abcdef"
            ),
            background_tasks=background_tasks,
            current_user=CurrentUser(user_id="user-1", session_id="auth-session"),
            session_git_worktree_service=service,  # pyright: ignore[reportArgumentType]  # Service double exposes the route method surface.
        )

        assert response is None
        assert service.manual_cleanup_calls == [
            (
                "1123456789abcdef0123456789abcdef",
                "2123456789abcdef0123456789abcdef",
                "user-1",
                "3123456789abcdef0123456789abcdef",
            )
        ]
        assert len(background_tasks.tasks) == 1

    async def test_archive_primary_session_returns_conflict(self) -> None:
        """Team primary session archive attempts are blocked."""
        chat_service = _AgentSessionRouteChatService()
        chat_service.archive_result = Failure(PrimarySessionArchiveBlocked())

        try:
            await archive_agent_session(
                agent_id="agent-1",
                session_id="1123456789abcdef0123456789abcdef",
                background_tasks=BackgroundTasks(),
                current_user=CurrentUser(user_id="user-1", session_id="auth-session"),
                chat_service=chat_service,  # pyright: ignore[reportArgumentType]  # Service double exposes the route method surface.
                session_git_worktree_service=_RouteWorktreeCleanupService(),  # pyright: ignore[reportArgumentType]  # Service double exposes the route method surface.
            )
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 409
            assert getattr(exc, "detail", None) == (
                "Team primary session cannot be archived."
            )
        else:
            raise AssertionError("Expected HTTPException")

    async def test_archive_running_session_returns_conflict(self) -> None:
        """Running session archive attempts are blocked."""
        chat_service = _AgentSessionRouteChatService()
        chat_service.archive_result = Failure(RunningSessionArchiveBlocked())

        try:
            await archive_agent_session(
                agent_id="agent-1",
                session_id="2123456789abcdef0123456789abcdef",
                background_tasks=BackgroundTasks(),
                current_user=CurrentUser(user_id="user-1", session_id="auth-session"),
                chat_service=chat_service,  # pyright: ignore[reportArgumentType]  # Service double exposes the route method surface.
                session_git_worktree_service=_RouteWorktreeCleanupService(),  # pyright: ignore[reportArgumentType]  # Service double exposes the route method surface.
            )
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 409
            assert getattr(exc, "detail", None) == "Running session cannot be archived."
        else:
            raise AssertionError("Expected HTTPException")

    async def test_update_agent_session_title_rejects_invalid_title(self) -> None:
        """Session title update route maps service validation to HTTP 400."""
        chat_service = _AgentSessionRouteChatService()

        try:
            await update_agent_session_title(
                session_id="1123456789abcdef0123456789abcdef",
                request=AgentSessionTitleUpdateRequest(title="invalid"),
                current_user=CurrentUser(user_id="user-1", session_id="auth-session"),
                chat_service=chat_service,  # pyright: ignore[reportArgumentType]  # Service double exposes the route method surface.
            )
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 400
        else:
            raise AssertionError("Expected HTTPException")

    async def test_get_agent_session_mismatch_is_not_found(self) -> None:
        """Agent/session mismatch and access denial are exposed as 404."""
        chat_service = _AgentSessionRouteChatService()
        chat_service.result = Failure(SessionNotFound())

        try:
            await get_agent_session(
                agent_id="agent-1",
                session_id="2223456789abcdef0123456789abcdef",
                current_user=CurrentUser(user_id="user-1", session_id="auth-session"),
                chat_service=chat_service,  # pyright: ignore[reportArgumentType]  # Service double exposes the route method surface.
            )
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 404
        else:
            raise AssertionError("Expected HTTPException")


class TestUpdateSessionGoalStatus:
    """Tests for PATCH /chat/v1/sessions/{session_id}/goal/status."""

    async def test_resume_passes_hint_and_wakes_session(self) -> None:
        """Pass resume hint to service input and wake-up event."""
        broker = _MemoryBroker()
        broadcast = _MemoryBroadcast()
        chat_service = _GoalStatusChatService()

        response = await update_session_goal_status(
            "1123456789abcdef0123456789abcdef",
            GoalStatusUpdateRequest(
                status="active",
                resume_hint=" CI credentials are restored. ",
            ),
            CurrentUser(user_id="user-1", session_id="auth-session"),
            chat_service,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
            broker,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
            broadcast,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
        )

        assert response.status == "active"
        assert chat_service.inputs == [
            UpdateGoalStatusInput(
                status="active",
                resume_hint="CI credentials are restored.",
            )
        ]
        assert len(broker.messages) == 1
        assert isinstance(broker.messages[0], SessionWakeUp)
        assert len(broadcast.events) == 2


class TestGetSubagentTree:
    """Tests for GET /chat/v1/.../subagents/tree."""

    async def test_returns_subagent_tree_projection(self) -> None:
        """Return nested Subagent Tree projection."""
        response = await get_subagent_tree(
            "1123456789abcdef0123456789abcdef",
            "1123456789abcdef0123456789abcdef",
            CurrentUser(user_id="user-1", session_id="auth-session"),
            _SubagentTreeChatService(),  # pyright: ignore[reportArgumentType]  # Test double implements only the required method.
        )

        dumped = response.model_dump(mode="json")
        assert dumped["root_session_agent_id"] == "root-agent"
        assert dumped["nodes"][0]["children"][0] == {
            "session_agent_id": "child-agent",
            "agent_session_id": "2123456789abcdef0123456789abcdef",
            "parent_session_agent_id": "root-agent",
            "name": "child",
            "path": "/root/child",
            "agent_type": "default",
            "status": "completed",
            "last_task_message": "work",
            "last_message_at": "2026-07-10T04:05:00Z",
            "unread_result": True,
            "latest_run_id": "3123456789abcdef0123456789abcdef",
            "latest_run_index": 1,
            "latest_run_status": "completed",
            "terminal_result_event_id": "4123456789abcdef0123456789abcdef",
            "terminal_result_message": "done",
            "children": [],
        }

    async def test_denies_subagent_tree_without_session_access(self) -> None:
        """Do not expose Subagent Tree without session access."""
        service = _SubagentTreeChatService()
        service.result = Failure(SessionNotFound())

        try:
            await get_subagent_tree(
                "1123456789abcdef0123456789abcdef",
                "1123456789abcdef0123456789abcdef",
                CurrentUser(user_id="user-1", session_id="auth-session"),
                service,  # pyright: ignore[reportArgumentType]  # Test double implements only the required method.
            )
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 404
        else:
            raise AssertionError("Expected HTTPException")


class TestStopSessionRun:
    """Tests for POST /chat/v1/sessions/{session_id}/stop."""

    async def test_sends_stop_request_after_access_check(self) -> None:
        """REST stop endpoint records DB intent, then publishes broker stop signal."""
        broker = _MemoryBroker()
        chat_service = _StopChatService()
        chat_write_service = _StopWriteService()

        response = await stop_session_run(
            "1123456789abcdef0123456789abcdef",
            CurrentUser(user_id="user-1", session_id="auth-session"),
            chat_service,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
            chat_write_service,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
            broker,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
        )

        assert response.session_id == "1123456789abcdef0123456789abcdef"
        assert chat_service.session_ids == ["1123456789abcdef0123456789abcdef"]
        assert chat_write_service.session_ids == ["1123456789abcdef0123456789abcdef"]
        assert chat_write_service.user_ids == ["user-1"]
        assert len(broker.messages) == 1
        message = broker.messages[0]
        assert isinstance(message, SessionStopSignal)
        assert message.session_id == "1123456789abcdef0123456789abcdef"
        assert message.user_id == "user-1"

    async def test_sends_stop_signal_for_each_subtree_session(self) -> None:
        """REST stop endpoint publishes stop signals for the requested subtree."""
        broker = _MemoryBroker()
        chat_service = _StopChatService()
        chat_write_service = _StopWriteService()
        chat_write_service.stopped_session_ids = [
            "1123456789abcdef0123456789abcdef",
            "2123456789abcdef0123456789abcdef",
            "3123456789abcdef0123456789abcdef",
        ]

        await stop_session_run(
            "1123456789abcdef0123456789abcdef",
            CurrentUser(user_id="user-1", session_id="auth-session"),
            chat_service,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
            chat_write_service,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
            broker,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
        )

        assert [
            message.session_id
            for message in broker.messages
            if isinstance(message, SessionStopSignal)
        ] == chat_write_service.stopped_session_ids

    async def test_denies_stop_without_session_access(self) -> None:
        """Do not issue stop request without session access."""
        broker = _MemoryBroker()
        chat_service = _StopChatService()
        chat_write_service = _StopWriteService()
        chat_service.result = Failure(SessionAccessDenied())

        try:
            await stop_session_run(
                "1123456789abcdef0123456789abcdef",
                CurrentUser(user_id="user-1", session_id="auth-session"),
                chat_service,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
                chat_write_service,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
                broker,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
            )
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 404
        else:
            raise AssertionError("Expected HTTPException")

        assert broker.messages == []
        assert chat_write_service.session_ids == []


class TestListInputActions:
    """Tests for GET /chat/v1/sessions/{session_id}/actions."""

    async def test_returns_server_managed_input_actions(self) -> None:
        """Return registered composer actions."""
        response = await list_input_actions(
            "1123456789abcdef0123456789abcdef",
            CurrentUser(user_id="user-1", session_id="auth-session"),
            _EventService(),  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
            _EmptySkillStore(),  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
        )

        items = response.model_dump(mode="json")["items"]
        assert items[0] == {
            "id": "command:compact",
            "keyword": "compact",
            "label": "Compact",
            "description": ("Compact chat context."),
            "action": {"type": "command", "name": "compact"},
            "category": "command",
            "message": {
                "policy": "optional",
                "placeholder": "Send to run this command.",
                "max_length": None,
            },
            "attachments": {"policy": "unsupported"},
            "availability_hint": None,
            "source_label": None,
            "relative_hint": None,
        }
        assert items[1]["id"] == "goal"
        assert items[1]["action"] == {"type": "goal"}
        assert items[1]["message"]["policy"] == "required"


class TestEventRoutes:
    """Event history/live route contract tests."""

    async def test_list_history_events_returns_event_page(self) -> None:
        """History route returns an event page."""
        response = await list_history_events(
            "1123456789abcdef0123456789abcdef",
            CurrentUser(user_id="user-1", session_id="auth-session"),
            _EventService(),  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
        )

        assert response.model_dump(mode="json") == {
            "items": [
                {
                    "id": "0123456789abcdef0123456789abcdef",
                    "session_id": "1123456789abcdef0123456789abcdef",
                    "kind": "user_message",
                    "payload": {
                        "content": "hello",
                        "attachments": [],
                        "metadata": {"source": "chat"},
                    },
                    "model_order": 1000,
                    "external_id": "input-1",
                    "adapter": None,
                    "provider": None,
                    "model": None,
                    "native_format": None,
                    "schema_version": "1",
                    "created_at": "2026-06-04T00:00:00Z",
                }
            ],
            "has_more": False,
            "has_newer": False,
            "next_cursor": "0123456789abcdef0123456789abcdef",
            "previous_cursor": "0123456789abcdef0123456789abcdef",
        }

    async def test_list_live_events_returns_taxonomy_snapshot(self) -> None:
        """Live route returns a taxonomy snapshot."""
        response = await list_live_events(
            "1123456789abcdef0123456789abcdef",
            CurrentUser(user_id="user-1", session_id="auth-session"),
            _EventService(),  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
            InMemoryLiveEventStore(),
        )

        dump = response.model_dump(mode="json")
        assert "items" not in dump
        assert dump["partial_history"]["items"][0]["kind"] == "user_message"
        assert dump["input_buffers"] == []
        assert dump["run"] == {
            "run_id": "2123456789abcdef0123456789abcdef",
            "phase": "waiting_for_model",
            "status": "running",
            "inference_profile": {
                "model_target_label": "reasoning",
                "reasoning_effort": "high",
            },
        }
        assert dump["session_run_state"] == "running"


class TestRestMessageWriteContract:
    """REST message write contract tests."""

    async def test_validate_rest_session_rejects_subagent_before_write(
        self,
    ) -> None:
        """REST write validation rejects child subagents before side effects."""
        chat_service = _RestWriteChatService(
            session_kind=AgentSessionKind.SUBAGENT,
        )

        try:
            await _validate_rest_session(
                chat_service,  # pyright: ignore[reportArgumentType]  # Test double implements only the required method.
                agent_id="agent-1",
                session_id="0123456789abcdef0123456789abcdef",
                user_id="user-1",
            )
        except HTTPException as exc:
            assert exc.status_code == 409
            assert exc.detail == "Subagent sessions are read-only."
        else:
            raise AssertionError("Expected HTTPException")

    async def test_existing_session_message_commits_buffer_and_returns_snapshot(
        self,
    ) -> None:
        """Existing-session REST write returns a snapshot after buffer commit."""
        broker = _MemoryBroker()
        broadcast = _MemoryBroadcast()
        chat_service = _RestWriteChatService()
        input_service = _BufferedInputService()

        response = await _write_message_via_rest(
            chat_service,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
            input_service,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
            _exchange_file_service(),
            _model_file_service(),
            broker,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
            broadcast,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
            InMemoryLiveEventStore(),
            ChatMessageWriteRequest(
                agent_id="agent-1",
                client_request_id="client-1",
                message="hello",
                inference_profile=RequestedInferenceProfile(
                    model_target_label="Primary",
                    reasoning_effort=None,
                ),
            ),
            session_id="0123456789abcdef0123456789abcdef",
            user_id="user-1",
            tz=ZoneInfo("UTC"),
        )

        assert input_service.calls == ["create_buffered_agent_input"]
        assert input_service.kwargs[0]["client_request_id"] == "client-1"
        assert response.session_id == "0123456789abcdef0123456789abcdef"
        assert response.client_request_id == "client-1"
        assert response.accepted.id == "0123456789abcdef0123456789abcdef"
        assert response.snapshot.input_buffer_events[0].kind == EventKind.USER_MESSAGE
        assert response.snapshot.partial_history_events == []
        assert response.snapshot.session_run_state == AgentSessionRunState.IDLE
        assert response.history_reload_required is False
        assert broadcast.events[0][1]["type"] == "live_event_upserted"
        assert len(broker.messages) == 1
        assert isinstance(broker.messages[0], SessionWakeUp)

    async def test_new_session_message_creates_session_and_returns_snapshot(
        self,
    ) -> None:
        """Draft-session REST write returns the created session id and snapshot."""
        broker = _MemoryBroker()
        broadcast = _MemoryBroadcast()
        chat_service = _RestWriteChatService(
            session_id="4123456789abcdef0123456789abcdef"
        )
        input_service = _BufferedInputService()

        response = await _write_new_session_message_via_rest(
            chat_service,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
            input_service,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
            broker,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
            broadcast,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
            InMemoryLiveEventStore(),
            ChatSessionCreateMessageWriteRequest(
                client_request_id="client-new-1",
                message="hello from draft",
                inference_profile=RequestedInferenceProfile(
                    model_target_label="Primary",
                    reasoning_effort=None,
                ),
                existing_project_paths=["/workspace/agent/app"],
                setup_actions=[],
            ),
            agent_id="agent-1",
            user_id="user-1",
            tz=ZoneInfo("UTC"),
        )

        assert input_service.calls == ["create_team_session_with_buffered_input"]
        assert input_service.kwargs[0]["client_request_id"] == "client-new-1"
        assert input_service.kwargs[0]["existing_project_paths"] == [
            "/workspace/agent/app"
        ]
        assert input_service.kwargs[0]["setup_actions"] == []
        assert response.session_id == "4123456789abcdef0123456789abcdef"
        assert response.accepted.id == "0123456789abcdef0123456789abcdef"
        snapshot_buffer = response.snapshot.input_buffer_events[0]
        assert snapshot_buffer.session_id == response.session_id
        assert response.history_reload_required is False
        assert broadcast.events[0][0] == response.session_id
        assert len(broker.messages) == 1
        assert isinstance(broker.messages[0], SessionWakeUp)

    async def test_new_session_message_accepts_setup_actions(self) -> None:
        """Draft-session REST write accepts setup actions before the message."""
        broker = _MemoryBroker()
        broadcast = _MemoryBroadcast()
        chat_service = _RestWriteChatService(
            session_id="4123456789abcdef0123456789abcdef"
        )
        input_service = _BufferedInputService()
        action = CreateGitWorktreeAction(
            source_project_path="/workspace/agent/source",
            starting_ref="refs/heads/main",
        )

        response = await _write_new_session_message_via_rest(
            chat_service,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
            input_service,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
            broker,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
            broadcast,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
            InMemoryLiveEventStore(),
            ChatSessionCreateMessageWriteRequest(
                client_request_id="client-new-mixed",
                message="hello from mixed workspace",
                inference_profile=RequestedInferenceProfile(
                    model_target_label="Primary",
                    reasoning_effort=None,
                ),
                existing_project_paths=["/workspace/agent/app"],
                setup_actions=[action],
            ),
            agent_id="agent-1",
            user_id="user-1",
            tz=ZoneInfo("UTC"),
        )

        assert input_service.calls == ["create_team_session_with_buffered_input"]
        assert input_service.kwargs[0]["existing_project_paths"] == [
            "/workspace/agent/app"
        ]
        assert input_service.kwargs[0]["setup_actions"] == [action]
        assert response.session_id == "4123456789abcdef0123456789abcdef"
        assert len(broker.messages) == 1
        assert isinstance(broker.messages[0], SessionWakeUp)

    async def test_session_validation_requires_explicit_session_id(self) -> None:
        """REST write validation checks the explicit session target."""
        chat_service = _RestWriteChatService()

        session_id = await _validate_rest_session(
            chat_service,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
            session_id="0123456789abcdef0123456789abcdef",
            agent_id="agent-1",
            user_id="user-1",
        )

        assert session_id == "0123456789abcdef0123456789abcdef"
        assert chat_service.get_agent_session_calls == [
            ("agent-1", "0123456789abcdef0123456789abcdef", "user-1")
        ]

    async def test_message_write_rejects_changed_input_target(self) -> None:
        """REST boundary rejects an input service result for another session."""
        broker = _MemoryBroker()
        broadcast = _MemoryBroadcast()
        chat_service = _RestWriteChatService(
            session_id="2223456789abcdef0123456789abcdef"
        )
        input_service = _BufferedInputService(
            target_session_id="3333456789abcdef0123456789abcdef"
        )

        try:
            await _write_message_via_rest(
                chat_service,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
                input_service,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
                _exchange_file_service(),
                _model_file_service(),
                broker,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
                broadcast,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
                InMemoryLiveEventStore(),
                ChatMessageWriteRequest(
                    agent_id="agent-1",
                    client_request_id="client-mismatch",
                    message="hello",
                    inference_profile=RequestedInferenceProfile(
                        model_target_label="Primary",
                        reasoning_effort=None,
                    ),
                ),
                session_id="2223456789abcdef0123456789abcdef",
                user_id="user-1",
                tz=ZoneInfo("UTC"),
            )
        except RuntimeError as exc:
            assert str(exc) == "AgentSession input target changed during REST write"
        else:
            raise AssertionError("Expected RuntimeError")

        assert broker.messages == []

    async def test_existing_session_create_git_worktree_action_commits_action_buffer(
        self,
    ) -> None:
        """REST input write accepts CreateGitWorktreeAction turn actions."""
        broker = _MemoryBroker()
        broadcast = _MemoryBroadcast()
        chat_service = _RestWriteChatService()
        input_service = _BufferedInputService()

        response = await _write_input_via_rest(
            chat_service,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
            input_service,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
            AsyncMock(),  # ChatWriteService is not used for CreateGitWorktreeAction.
            _exchange_file_service(),
            _model_file_service(),
            broker,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
            broadcast,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
            InMemoryLiveEventStore(),
            ChatInputWriteRequest(
                agent_id="agent-1",
                client_request_id="worktree-1",
                message="",
                inference_profile=RequestedInferenceProfile(
                    model_target_label="Primary",
                    reasoning_effort=None,
                ),
                action=CreateGitWorktreeAction(
                    source_project_path="/workspace/agent/source",
                    starting_ref="refs/heads/main",
                ),
            ),
            session_id="0123456789abcdef0123456789abcdef",
            user_id="user-1",
            tz=ZoneInfo("UTC"),
        )

        assert input_service.calls == ["create_buffered_agent_action_input"]
        assert input_service.kwargs[0]["action"] == {
            "type": "create_git_worktree",
            "source_project_path": "/workspace/agent/source",
            "starting_ref": "refs/heads/main",
        }
        assert response.accepted.type == "input_buffer"
        assert len(broker.messages) == 1
        assert isinstance(broker.messages[0], SessionWakeUp)

    async def test_skill_action_write_commits_action_buffer_and_wakes_once(
        self,
    ) -> None:
        """REST input write accepts SkillAction turn actions."""
        broker = _MemoryBroker()
        broadcast = _MemoryBroadcast()
        chat_service = _RestWriteChatService()
        input_service = _BufferedInputService()

        response = await _write_input_via_rest(
            chat_service,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
            input_service,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
            AsyncMock(),  # ChatWriteService is not used for SkillAction.
            _exchange_file_service(),
            _model_file_service(),
            broker,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
            broadcast,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
            InMemoryLiveEventStore(),
            ChatInputWriteRequest(
                agent_id="agent-1",
                client_request_id="skill-1",
                message="Review this change",
                inference_profile=RequestedInferenceProfile(
                    model_target_label="Primary",
                    reasoning_effort=None,
                ),
                action=SkillAction(
                    skill_path="/workspace/agent/app/.claude/skills/review/SKILL.md"
                ),
            ),
            session_id="0123456789abcdef0123456789abcdef",
            user_id="user-1",
            tz=ZoneInfo("UTC"),
        )

        assert input_service.calls == ["create_buffered_agent_action_input"]
        assert input_service.kwargs[0]["action"] == {
            "type": "skill",
            "skill_path": "/workspace/agent/app/.claude/skills/review/SKILL.md",
        }
        assert response.accepted.type == "input_buffer"
        assert len(broker.messages) == 1
        assert isinstance(broker.messages[0], SessionWakeUp)


class TestRestEditCommandWriteContract:
    """REST edit/command write contract tests."""

    async def test_edit_message_commits_buffer_and_wakes_once(self) -> None:
        """REST edit creates an edited buffer from a new request and sends wake-up."""
        broker = _MemoryBroker()
        chat_service = _RestWriteChatService()
        idempotency = _RestWriteIdempotencyService(created=True)

        response = await _write_edit_message_via_rest(
            chat_service,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
            idempotency,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
            _exchange_file_service(),
            _model_file_service(),
            broker,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
            InMemoryLiveEventStore(),
            ChatEditMessageWriteRequest(
                agent_id="agent-1",
                client_request_id="edit-1",
                message_id="message-1",
                message="edited",
                inference_profile=RequestedInferenceProfile(
                    model_target_label="Primary",
                    reasoning_effort=None,
                ),
            ),
            session_id="0123456789abcdef0123456789abcdef",
            user_id="user-1",
            tz=ZoneInfo("UTC"),
        )

        assert response.accepted.type == "edit_message"
        assert response.accepted.id == "message-1"
        assert response.history_reload_required is True
        assert idempotency.calls[0]["message_id"] == "message-1"
        assert len(broker.messages) == 1
        message = broker.messages[0]
        assert isinstance(message, SessionWakeUp)
        assert message.session_id == "0123456789abcdef0123456789abcdef"

    async def test_edit_message_retry_does_not_enqueue_broker_message(self) -> None:
        """REST edit retry returns existing record and skips broker enqueue."""
        broker = _MemoryBroker()
        chat_service = _RestWriteChatService()
        idempotency = _RestWriteIdempotencyService(created=False)

        response = await _write_edit_message_via_rest(
            chat_service,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
            idempotency,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
            _exchange_file_service(),
            _model_file_service(),
            broker,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
            InMemoryLiveEventStore(),
            ChatEditMessageWriteRequest(
                agent_id="agent-1",
                client_request_id="edit-1",
                message_id="message-1",
                message="edited",
                inference_profile=RequestedInferenceProfile(
                    model_target_label="Primary",
                    reasoning_effort=None,
                ),
            ),
            session_id="0123456789abcdef0123456789abcdef",
            user_id="user-1",
            tz=ZoneInfo("UTC"),
        )

        assert response.client_request_id == "edit-1"
        assert broker.messages == []

    async def test_command_stores_pending_command_and_wakes_once(self) -> None:
        """New command request creates a pending command and sends wake-up."""
        broker = _MemoryBroker()
        chat_service = _RestWriteChatService()
        idempotency = _RestWriteIdempotencyService(created=True)

        response = await _write_command_via_rest(
            chat_service,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
            idempotency,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
            broker,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
            InMemoryLiveEventStore(),
            ChatCommandWriteRequest(
                agent_id="agent-1",
                client_request_id="command-1",
                command="compact",
            ),
            session_id="0123456789abcdef0123456789abcdef",
            user_id="user-1",
        )

        assert response.accepted.type == "command"
        assert response.accepted.id == "command-request-1"
        assert response.history_reload_required is True
        assert idempotency.calls[0]["command_name"] == "compact"
        assert len(broker.messages) == 1
        message = broker.messages[0]
        assert isinstance(message, SessionWakeUp)
        assert message.session_id == "0123456789abcdef0123456789abcdef"

    async def test_command_retry_does_not_enqueue_broker_message(self) -> None:
        """REST command retry skips broker enqueue."""
        broker = _MemoryBroker()
        chat_service = _RestWriteChatService()
        idempotency = _RestWriteIdempotencyService(created=False)

        response = await _write_command_via_rest(
            chat_service,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
            idempotency,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
            broker,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
            InMemoryLiveEventStore(),
            ChatCommandWriteRequest(
                agent_id="agent-1",
                client_request_id="command-1",
                command="compact",
            ),
            session_id="0123456789abcdef0123456789abcdef",
            user_id="user-1",
        )

        assert response.client_request_id == "command-1"
        assert broker.messages == []


class TestChatInferenceProfileRequestContract:
    """Composer request inference-profile validation tests."""

    def test_run_producing_input_requires_profile(self) -> None:
        """Reject a null profile for a normal model-producing message."""
        try:
            ChatInputWriteRequest(
                agent_id="agent-1",
                client_request_id="message-1",
                message="hello",
                action=None,
                inference_profile=None,
            )
        except ValidationError as exc:
            assert "Run-producing input requires an inference profile" in str(exc)
        else:
            raise AssertionError("Expected profile validation failure")

    def test_command_requires_null_profile(self) -> None:
        """Reject a model profile for a non-model command."""
        try:
            ChatInputWriteRequest(
                agent_id="agent-1",
                client_request_id="command-1",
                message="",
                action=CommandAction(name="compact"),
                inference_profile=RequestedInferenceProfile(
                    model_target_label="Primary",
                    reasoning_effort=None,
                ),
            )
        except ValidationError as exc:
            assert "Non-model commands require a null inference profile" in str(exc)
        else:
            raise AssertionError("Expected profile validation failure")


class TestChatInputBufferContract:
    """Chat input buffer route contract tests."""

    async def test_delete_input_buffer_publishes_deleted_notification(self) -> None:
        """DELETE endpoint returns idempotent 204 and publishes delete notification."""
        broadcast = _MemoryBroadcast()

        await delete_input_buffer(
            "0123456789abcdef0123456789abcdef",
            "1123456789abcdef0123456789abcdef",
            CurrentUser(user_id="user-1", session_id="auth-session"),
            _DeleteInputBufferService(),  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
            broadcast,  # pyright: ignore[reportArgumentType]  # Test double implements only the required methods.
        )

        assert broadcast.events == [
            (
                "0123456789abcdef0123456789abcdef",
                {
                    "type": "live_event_removed",
                    "session_id": "0123456789abcdef0123456789abcdef",
                    "event_id": "1123456789abcdef0123456789abcdef",
                },
            ),
        ]
