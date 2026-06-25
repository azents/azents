"""Chat v1 public endpoint tests."""

import datetime
from collections.abc import Sequence
from typing import cast
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from azcommon.result import Failure, Success
from fastapi import FastAPI
from fastapi.testclient import TestClient

from azents.api.public.chat.v1 import (
    _write_command_via_rest,  # pyright: ignore[reportPrivateUsage]  # Pin the REST write boundary helper directly.
    _write_edit_message_via_rest,  # pyright: ignore[reportPrivateUsage]  # Pin the REST write boundary helper directly.
    _write_message_via_rest,  # pyright: ignore[reportPrivateUsage]  # Pin the REST write boundary helper directly.
    delete_input_buffer,
    list_history_events,
    list_live_events,
    mount,
    stop_session_run,
    update_session_goal_status,
)
from azents.api.public.chat.v1.data import (
    ChatCommandWriteRequest,
    ChatEditMessageWriteRequest,
    ChatMessageWriteRequest,
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
    AgentSessionRunState,
    AgentSessionStartReason,
    AgentSessionStatus,
    EventKind,
    InputBufferKind,
)
from azents.engine.events.types import (
    ActiveToolCall,
    Event,
    UserMessagePayload,
)
from azents.engine.run.input import InputMessage
from azents.engine.tools.goal import GoalStateSnapshot
from azents.rdb.models.chat_write_request import ChatWriteRequestType
from azents.repos.agent_session.data import AgentSession
from azents.repos.chat_write_request.data import ChatWriteRequest
from azents.repos.input_buffer.data import InputBuffer
from azents.services.agent_session_input import BufferedAgentSessionInputResult
from azents.services.chat.data import (
    ChatLiveRunState,
    ChatLiveStateSnapshot,
    EnsureSessionInput,
    PaginatedEvents,
    SessionAccessDenied,
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
from azents.utils.fastapi.route import as_route_mounter


def _make_app() -> FastAPI:
    """Create a test app with Chat public endpoints mounted."""
    app = FastAPI()
    mount(as_route_mounter(app))
    return app


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
        message = cast(InputMessage, kwargs["message"])
        session_id = self.target_session_id or str(kwargs["agent_session_id"])
        input_buffer = InputBuffer(
            id="0123456789abcdef0123456789abcdef",
            session_id=session_id,
            kind=InputBufferKind.USER_MESSAGE,
            actor_user_id=str(kwargs["user_id"]),
            content=str(message.text),
            idempotency_key=(
                str(kwargs["client_request_id"])
                if kwargs.get("client_request_id") is not None
                else None
            ),
            metadata={"source": "chat"},
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


class _RestWriteChatService:
    """ChatSessionService double for REST write tests."""

    def __init__(self, session_id: str = "0123456789abcdef0123456789abcdef") -> None:
        self.session_id = session_id
        self.ensure_inputs: list[EnsureSessionInput] = []
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

    async def ensure_session(
        self, ensure_input: EnsureSessionInput
    ) -> Success[AgentSession]:
        """Return the confirmed AgentSession."""
        self.ensure_inputs.append(ensure_input)
        return Success(
            AgentSession(
                id=self.session_id,
                workspace_id="workspace-1",
                agent_id="agent-1",
                status=AgentSessionStatus.ACTIVE,
                start_reason=AgentSessionStartReason.INITIAL,
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
                id="1123456789abcdef0123456789abcdef",
                workspace_id="workspace-1",
                agent_id="agent-1",
                status=AgentSessionStatus.ACTIVE,
                start_reason=AgentSessionStartReason.INITIAL,
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
                kind=InputBufferKind.EDITED_USER_MESSAGE,
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
                agent_runtime_id="1123456789abcdef0123456789abcdef",
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
                agent_runtime_id="1123456789abcdef0123456789abcdef",
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
            agent_runtime_id="1123456789abcdef0123456789abcdef",
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
                ),
                session_run_state=AgentSessionRunState.RUNNING,
            )
        )


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
            assert getattr(exc, "status_code", None) == 403
        else:
            raise AssertionError("Expected HTTPException")

        assert broker.messages == []
        assert chat_write_service.session_ids == []


class TestListSlashCommands:
    """Tests for GET /chat/v1/commands."""

    def test_returns_server_managed_slash_commands(self) -> None:
        """Return registered slash commands."""
        client = TestClient(_make_app())

        response = client.get("/chat/v1/commands")

        assert response.status_code == 200
        assert response.json() == {
            "items": [
                {
                    "name": "compact",
                    "description": (
                        "Summarize previous conversation and compact "
                        "the context window."
                    ),
                }
            ]
        }


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
        }
        assert dump["session_run_state"] == "running"


class TestRestMessageWriteContract:
    """REST message write contract tests."""

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

    async def test_new_session_message_uses_sessionless_contract(self) -> None:
        """New-session REST write ensures without session_id, then creates a buffer."""
        broker = _MemoryBroker()
        broadcast = _MemoryBroadcast()
        chat_service = _RestWriteChatService(
            session_id="2223456789abcdef0123456789abcdef"
        )
        input_service = _BufferedInputService(
            target_session_id="2223456789abcdef0123456789abcdef"
        )

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
                client_request_id="client-new",
                message="first hello",
            ),
            session_id=None,
            user_id="user-1",
            tz=ZoneInfo("UTC"),
        )

        ensure_input = chat_service.ensure_inputs[0]
        assert ensure_input.session_id is None
        assert response.session_id == "2223456789abcdef0123456789abcdef"
        assert input_service.kwargs[0]["agent_session_id"] == (
            "2223456789abcdef0123456789abcdef"
        )
        assert len(broker.messages) == 1

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
