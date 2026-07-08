"""Subagent collaboration Toolkit tests."""

import datetime
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.types import BrokerMessage, SessionBroker, SessionWakeUp
from azents.core.enums import (
    AgentRunPhase,
    AgentRunStatus,
    AgentSessionKind,
    AgentSessionRunState,
    AgentSessionStartReason,
    AgentSessionStatus,
    InputBufferKind,
    SessionAgentKind,
)
from azents.core.tools import ToolkitStatus, TurnContext
from azents.engine.events.types import AgentRunState
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSession, SessionAgent
from azents.services.input_buffer import InputBufferEnqueue, InputBufferService

from .subagent import SubagentToolkit

_NOW = datetime.datetime.now(datetime.UTC)


@asynccontextmanager
async def _session_manager() -> AsyncGenerator[AsyncSession, None]:
    """Yield a placeholder DB session for Toolkit tests."""
    yield cast(AsyncSession, object())


def _session_agent(
    *,
    id: str,
    path: str,
    agent_session_id: str,
    name: str,
    kind: SessionAgentKind = SessionAgentKind.SUBAGENT,
) -> SessionAgent:
    """Create SessionAgent fixture."""
    return SessionAgent(
        id=id,
        context_id="context-1",
        root_session_agent_id="root-agent",
        agent_session_id=agent_session_id,
        kind=kind,
        name=name,
        path=path,
        agent_type="default",
        parent_session_agent_id="root-agent"
        if kind is SessionAgentKind.SUBAGENT
        else None,
        last_task_message=None,
        parent_observed_run_index=None,
        parent_observed_event_id=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _agent_session(
    *,
    id: str,
    run_state: AgentSessionRunState = AgentSessionRunState.IDLE,
) -> AgentSession:
    """Create AgentSession fixture."""
    return AgentSession(
        id=id,
        workspace_id="workspace-1",
        agent_id="agent-1",
        handle="session-handle",
        session_kind=AgentSessionKind.SUBAGENT,
        status=AgentSessionStatus.ACTIVE,
        primary_kind=None,
        start_reason=AgentSessionStartReason.INITIAL,
        title=None,
        title_source=None,
        title_generated_at=None,
        title_generation_event_id=None,
        last_user_input_at=_NOW,
        end_reason=None,
        model_input_head_event_id=None,
        model_input_head_model_order=None,
        model_file_gc_cursor_event_id=None,
        model_file_gc_cursor_model_order=0,
        started_at=_NOW,
        lifecycle_started_at=None,
        run_state=run_state,
        run_heartbeat_at=_NOW,
        pending_command_id=None,
        pending_command_name=None,
        pending_command_payload=None,
        pending_command_user_id=None,
        pending_command_created_at=None,
        stop_requested_at=None,
        stop_requested_by=None,
        stop_request_id=None,
        ended_at=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


class _AgentSessionRepository:
    """AgentSessionRepository fake for subagent tool tests."""

    def __init__(self) -> None:
        """Initialize fake state."""
        self.current = _session_agent(
            id="root-agent",
            path="/root",
            agent_session_id="root-session",
            name="root",
            kind=SessionAgentKind.ROOT,
        )
        self.target = _session_agent(
            id="child-agent",
            path="/root/child",
            agent_session_id="child-session",
            name="child",
        )
        self.sessions = {"child-session": _agent_session(id="child-session")}
        self.marked_running: list[str] = []
        self.last_task_updates: list[tuple[str, str | None]] = []
        self.observation_updates: list[tuple[str, int | None, str | None]] = []

    async def get_session_agent_by_session_id(
        self,
        session: AsyncSession,
        agent_session_id: str,
    ) -> SessionAgent | None:
        """Return the current agent for the root session."""
        del session
        if agent_session_id == "root-session":
            return self.current
        if agent_session_id == "child-session":
            return self.target
        return None

    async def resolve_session_agent_path(
        self,
        session: AsyncSession,
        *,
        current_session_agent_id: str,
        path: str,
    ) -> SessionAgent | None:
        """Resolve the child fixture by name or path."""
        del session, current_session_agent_id
        if path in {"child", "/root/child"}:
            return self.target
        return None

    async def update_session_agent_last_task_message(
        self,
        session: AsyncSession,
        *,
        session_agent_id: str,
        last_task_message: str | None,
    ) -> SessionAgent | None:
        """Record last task/message preview updates."""
        del session
        self.last_task_updates.append((session_agent_id, last_task_message))
        return self.target

    async def list_descendant_session_agents(
        self,
        session: AsyncSession,
        *,
        session_agent_id: str,
        include_self: bool,
    ) -> list[SessionAgent]:
        """Return the child fixture as the only descendant."""
        del session, session_agent_id, include_self
        return [self.target]

    async def update_session_agent_observation_cursor(
        self,
        session: AsyncSession,
        *,
        session_agent_id: str,
        parent_observed_run_index: int | None,
        parent_observed_event_id: str | None,
    ) -> SessionAgent | None:
        """Record terminal result observation cursor updates."""
        del session
        self.observation_updates.append(
            (
                session_agent_id,
                parent_observed_run_index,
                parent_observed_event_id,
            )
        )
        self.target.parent_observed_run_index = parent_observed_run_index
        self.target.parent_observed_event_id = parent_observed_event_id
        return self.target

    async def mark_running_for_input_wakeup(
        self,
        session: AsyncSession,
        agent_session_id: str,
    ) -> None:
        """Record wake-producing run state transition requests."""
        del session
        self.marked_running.append(agent_session_id)

    async def get_by_id(
        self,
        session: AsyncSession,
        agent_session_id: str,
    ) -> AgentSession | None:
        """Return linked child AgentSession fixture."""
        del session
        return self.sessions.get(agent_session_id)


class _AgentRunRepository:
    """AgentRunRepository fake for subagent tool tests."""

    def __init__(self) -> None:
        """Initialize latest child run fixture."""
        self.latest_by_session_id = {
            "child-session": AgentRunState(
                id="run".rjust(32, "0"),
                session_id="child-session",
                run_index=1,
                phase=AgentRunPhase.IDLE,
                status=AgentRunStatus.COMPLETED,
                terminal_result_event_id="event".rjust(32, "0"),
                terminal_result_message="child result",
                started_at=_NOW,
                ended_at=_NOW,
                updated_at=_NOW,
            )
        }

    async def list_latest_by_session_ids(
        self,
        session: AsyncSession,
        *,
        session_ids: list[str],
    ) -> dict[str, AgentRunState]:
        """Return latest runs for requested sessions."""
        del session
        return {
            session_id: self.latest_by_session_id[session_id]
            for session_id in session_ids
            if session_id in self.latest_by_session_id
        }


class _InputBufferService:
    """InputBufferService fake for subagent tool tests."""

    def __init__(self) -> None:
        """Initialize fake state."""
        self.enqueued: list[InputBufferEnqueue] = []

    async def enqueue(
        self,
        session: AsyncSession,
        input: InputBufferEnqueue,
    ) -> object:
        """Record enqueued mailbox input."""
        del session
        self.enqueued.append(input)
        return object()


class _Broker:
    """SessionBroker fake for subagent tool tests."""

    def __init__(self) -> None:
        """Initialize fake state."""
        self.messages: list[BrokerMessage] = []

    async def send_message(self, message: BrokerMessage) -> None:
        """Record broker messages."""
        self.messages.append(message)


async def _make_toolkit() -> tuple[
    SubagentToolkit,
    _AgentSessionRepository,
    _InputBufferService,
    _Broker,
]:
    """Create an initialized SubagentToolkit fixture."""
    agent_session_repository = _AgentSessionRepository()
    input_buffer_service = _InputBufferService()
    broker = _Broker()
    toolkit = SubagentToolkit(
        session_manager=_session_manager,
        agent_session_repository=cast(AgentSessionRepository, agent_session_repository),
        agent_run_repository=cast(AgentRunRepository, _AgentRunRepository()),
        event_transcript_repository=cast(EventTranscriptRepository, object()),
        input_buffer_service=cast(InputBufferService, input_buffer_service),
        broker=cast(SessionBroker, broker),
    )
    state = await toolkit.update_context(
        TurnContext(
            user_id="user-1",
            workspace_id="workspace-1",
            model="gpt-5.1",
            run_id="run-1",
            publish_event=cast(Any, object()),
            session_id="root-session",
        )
    )
    assert state.status == ToolkitStatus.ENABLED
    return toolkit, agent_session_repository, input_buffer_service, broker


async def test_send_message_is_queue_only() -> None:
    """send_message writes mailbox input without waking the target child."""
    toolkit, repo, input_service, broker = await _make_toolkit()
    state = await toolkit.update_context(
        TurnContext(
            user_id="user-1",
            workspace_id="workspace-1",
            model="gpt-5.1",
            run_id="run-1",
            publish_event=cast(Any, object()),
            session_id="root-session",
        )
    )
    tool = next(tool for tool in state.tools if tool.spec.name == "send_message")

    result = await tool.handler(json.dumps({"agent_name": "child", "message": "note"}))

    assert json.loads(cast(str, result)) == {
        "status": "queued",
        "agent_name": "child",
        "agent_path": "/root/child",
    }
    assert input_service.enqueued[0].kind == InputBufferKind.AGENT_MESSAGE
    assert input_service.enqueued[0].metadata["message_kind"] == "send_message"
    assert input_service.enqueued[0].content == "note"
    assert repo.last_task_updates == [("child-agent", "note")]
    assert repo.marked_running == []
    assert broker.messages == []


async def test_followup_task_wakes_target_child() -> None:
    """followup_task writes mailbox input and wakes the target child."""
    toolkit, repo, input_service, broker = await _make_toolkit()
    state = await toolkit.update_context(
        TurnContext(
            user_id="user-1",
            workspace_id="workspace-1",
            model="gpt-5.1",
            run_id="run-1",
            publish_event=cast(Any, object()),
            session_id="root-session",
        )
    )
    tool = next(tool for tool in state.tools if tool.spec.name == "followup_task")

    result = await tool.handler(json.dumps({"agent_name": "child", "task": "work"}))

    assert json.loads(cast(str, result)) == {
        "status": "assigned",
        "agent_name": "child",
        "agent_path": "/root/child",
    }
    assert input_service.enqueued[0].kind == InputBufferKind.AGENT_MESSAGE
    assert input_service.enqueued[0].metadata["message_kind"] == "followup_task"
    assert input_service.enqueued[0].content == "work"
    assert repo.last_task_updates == [("child-agent", "work")]
    assert repo.marked_running == ["child-session"]
    assert len(broker.messages) == 1
    wake = broker.messages[0]
    assert isinstance(wake, SessionWakeUp)
    assert wake.session_id == "child-session"


async def test_wait_agent_returns_terminal_result_and_advances_cursor() -> None:
    """wait_agent observes unread child terminal results once."""
    toolkit, repo, _input_service, _broker = await _make_toolkit()
    state = await toolkit.update_context(
        TurnContext(
            user_id="user-1",
            workspace_id="workspace-1",
            model="gpt-5.1",
            run_id="run-1",
            publish_event=cast(Any, object()),
            session_id="root-session",
        )
    )
    tool = next(tool for tool in state.tools if tool.spec.name == "wait_agent")

    result = await tool.handler(json.dumps({"agent_name": "child"}))

    assert json.loads(cast(str, result)) == {
        "message": "child result",
        "timed_out": False,
    }
    assert repo.observation_updates == [("child-agent", 1, "event".rjust(32, "0"))]

    second_result = await tool.handler(json.dumps({"agent_name": "child"}))

    assert json.loads(cast(str, second_result)) == {
        "message": "No unread terminal result.",
        "timed_out": False,
    }
    assert repo.observation_updates == [("child-agent", 1, "event".rjust(32, "0"))]
