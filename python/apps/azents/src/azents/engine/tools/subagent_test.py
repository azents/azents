"""Subagent collaboration Toolkit tests."""

import asyncio
import datetime
import json
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.types import BrokerMessage, SessionBroker, SessionWakeUp
from azents.core.agent import SubagentSettings
from azents.core.enums import (
    AgentRunPhase,
    AgentRunStatus,
    AgentSessionKind,
    AgentSessionRunState,
    AgentSessionStartReason,
    AgentSessionStatus,
    EventKind,
    InputBufferKind,
    SessionAgentKind,
)
from azents.core.tools import ToolkitStatus, TurnContext
from azents.engine.events.engine_events import SubagentTreeChanged
from azents.engine.events.types import AgentRunState, Event, UserMessagePayload
from azents.engine.run.types import FunctionToolError
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSession, SessionAgent
from azents.services.input_buffer import InputBufferEnqueue, InputBufferService

from .subagent import SpawnAgentInput, SubagentToolkit

_NOW = datetime.datetime.now(datetime.UTC)


async def _noop_publish(event: object) -> None:
    """Ignore published events."""
    del event


def _publish_to(
    events: list[SubagentTreeChanged],
) -> Callable[[SubagentTreeChanged], Awaitable[None]]:
    """Return an async publisher that appends to a list."""

    async def publish(event: SubagentTreeChanged) -> None:
        events.append(event)

    return publish


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


def _event(kind: EventKind, payload: UserMessagePayload, model_order: int) -> Event:
    """Create Event fixture."""
    return Event(
        id=str(model_order).rjust(32, "0"),
        session_id="root-session",
        kind=kind,
        payload=payload,
        model_order=model_order,
        created_at=_NOW,
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
        self.sessions = {
            "root-session": _agent_session(id="root-session"),
            "child-session": _agent_session(id="child-session"),
        }
        self.tree = [self.current, self.target]
        self.created_children: list[SessionAgent] = []
        self.locked_session_agents: list[str] = []
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
        """Resolve absolute or current-agent-relative fixture paths."""
        del session
        current = next(
            (agent for agent in self.tree if agent.id == current_session_agent_id),
            None,
        )
        if current is None:
            raise ValueError("SessionAgent not found")
        if path == ".":
            resolved_path = current.path
        elif path.startswith("/"):
            resolved_path = path
        else:
            resolved_path = f"{current.path}/{path}"
        return next(
            (agent for agent in self.tree if agent.path == resolved_path),
            None,
        )

    async def lock_session_agent_by_id(
        self,
        session: AsyncSession,
        session_agent_id: str,
    ) -> SessionAgent | None:
        """Record root tree lock requests and return the matching SessionAgent."""
        del session
        self.locked_session_agents.append(session_agent_id)
        for agent in self.tree:
            if agent.id == session_agent_id:
                return agent
        return None

    async def list_session_agent_tree(
        self,
        session: AsyncSession,
        *,
        root_session_agent_id: str,
    ) -> list[SessionAgent]:
        """Return the fake root tree."""
        del session, root_session_agent_id
        return list(self.tree)

    async def list_by_ids(
        self,
        session: AsyncSession,
        *,
        agent_session_ids: list[str],
    ) -> dict[str, AgentSession]:
        """Return linked AgentSession fixtures by ID."""
        del session
        return {
            session_id: self.sessions[session_id]
            for session_id in agent_session_ids
            if session_id in self.sessions
        }

    async def create_child_session_agent(
        self,
        session: AsyncSession,
        *,
        parent_session_agent_id: str,
        name: str,
        agent_type: str,
        title: str | None,
        last_task_message: str | None,
    ) -> SessionAgent:
        """Create a child SessionAgent fixture."""
        del session, title
        if parent_session_agent_id != self.current.id:
            raise ValueError("Parent SessionAgent not found")
        child = _session_agent(
            id=f"{name}-agent",
            path=f"{self.current.path}/{name}",
            agent_session_id=f"{name}-session",
            name=name,
        ).model_copy(
            update={
                "agent_type": agent_type,
                "last_task_message": last_task_message,
            }
        )
        self.sessions[child.agent_session_id] = _agent_session(
            id=child.agent_session_id
        )
        self.tree.append(child)
        self.created_children.append(child)
        return child

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
        """Return descendants of the requested fixture agent."""
        del session
        current = next(agent for agent in self.tree if agent.id == session_agent_id)
        descendants = [
            agent for agent in self.tree if agent.path.startswith(f"{current.path}/")
        ]
        if include_self:
            return [current, *descendants]
        return descendants

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


class _EventTranscriptRepository:
    """EventTranscriptRepository fake for subagent tool tests."""

    def __init__(self) -> None:
        """Initialize fake state."""
        self.appended: list[EventCreate] = []
        self.forked_events: list[Event] = []

    async def list_for_model_input(
        self,
        session: AsyncSession,
        session_id: str,
        *,
        head_event_id: str | None,
    ) -> list[Any]:
        """Return no forked events by default."""
        del session, session_id, head_event_id
        return list(self.forked_events)

    async def append(
        self,
        session: AsyncSession,
        event: EventCreate,
    ) -> object:
        """Record appended fork events."""
        del session
        self.appended.append(event)
        return object()


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
    _AgentRunRepository,
    list[SubagentTreeChanged],
]:
    """Create an initialized SubagentToolkit fixture."""
    agent_session_repository = _AgentSessionRepository()
    input_buffer_service = _InputBufferService()
    broker = _Broker()
    run_repository = _AgentRunRepository()
    published_events: list[SubagentTreeChanged] = []

    async def publish_event(event: SubagentTreeChanged) -> None:
        published_events.append(event)

    toolkit = SubagentToolkit(
        session_manager=_session_manager,
        agent_session_repository=cast(AgentSessionRepository, agent_session_repository),
        agent_run_repository=cast(AgentRunRepository, run_repository),
        event_transcript_repository=cast(
            EventTranscriptRepository, _EventTranscriptRepository()
        ),
        input_buffer_service=cast(InputBufferService, input_buffer_service),
        broker=cast(SessionBroker, broker),
        subagent_settings=SubagentSettings(),
    )
    state = await toolkit.update_context(
        TurnContext(
            user_id="user-1",
            workspace_id="workspace-1",
            model="gpt-5.1",
            run_id="run-1",
            publish_event=cast(Any, publish_event),
            session_id="root-session",
        )
    )
    assert state.status == ToolkitStatus.ENABLED
    return (
        toolkit,
        agent_session_repository,
        input_buffer_service,
        broker,
        run_repository,
        published_events,
    )


async def test_subagent_static_prompt_matches_azents_semantics() -> None:
    """Expose Codex-style team guidance with Azents delivery semantics."""
    toolkit, _repo, _input_service, _broker, _run_repo, _events = await _make_toolkit()

    prompt = await toolkit.get_static_prompt(
        TurnContext(
            user_id="user-1",
            workspace_id="workspace-1",
            model="gpt-5.1",
            run_id="run-1",
            publish_event=cast(Any, _noop_publish),
            session_id="root-session",
        )
    )

    assert "There are 4 available concurrency slots" in prompt
    assert "maximum subagent depth below the root agent is" in prompt
    assert "1" in prompt
    assert "almost the same set of tools" in prompt
    assert "fork_turns` parameter, which defaults to" in prompt
    assert "terminal child result" in prompt
    assert "immediately delivered" not in prompt


def test_spawn_agent_fork_turns_defaults_to_all() -> None:
    """spawn_agent propagates all context by default."""
    assert SpawnAgentInput.model_fields["fork_turns"].default == "all"


async def test_send_message_is_queue_only() -> None:
    """send_message writes mailbox input without waking the target child."""
    (
        toolkit,
        repo,
        input_service,
        broker,
        _run_repo,
        published_events,
    ) = await _make_toolkit()

    async def publish_event(event: SubagentTreeChanged) -> None:
        published_events.append(event)

    state = await toolkit.update_context(
        TurnContext(
            user_id="user-1",
            workspace_id="workspace-1",
            model="gpt-5.1",
            run_id="run-1",
            publish_event=cast(Any, publish_event),
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
    assert [event.type for event in published_events] == ["subagent_tree_changed"]


async def test_send_message_from_child_can_target_root() -> None:
    """send_message matches Codex by allowing upward communication."""
    toolkit, repo, input_service, _broker, _run_repo, _events = await _make_toolkit()
    state = await toolkit.update_context(
        TurnContext(
            user_id="user-1",
            workspace_id="workspace-1",
            model="gpt-5.1",
            run_id="run-1",
            publish_event=cast(Any, _noop_publish),
            session_id="child-session",
        )
    )
    tool = next(tool for tool in state.tools if tool.spec.name == "send_message")

    result = await tool.handler(
        json.dumps({"agent_name": "/root", "message": "status update"})
    )

    assert json.loads(cast(str, result)) == {
        "status": "queued",
        "agent_name": "root",
        "agent_path": "/root",
    }
    assert input_service.enqueued[0].metadata["source_path"] == "/root/child"
    assert input_service.enqueued[0].metadata["target_path"] == "/root"
    assert repo.last_task_updates == [("root-agent", "status update")]


async def test_followup_task_wakes_target_child() -> None:
    """followup_task writes mailbox input and wakes the target child."""
    (
        toolkit,
        repo,
        input_service,
        broker,
        _run_repo,
        published_events,
    ) = await _make_toolkit()

    async def publish_event(event: SubagentTreeChanged) -> None:
        published_events.append(event)

    state = await toolkit.update_context(
        TurnContext(
            user_id="user-1",
            workspace_id="workspace-1",
            model="gpt-5.1",
            run_id="run-1",
            publish_event=cast(Any, publish_event),
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
    assert [event.type for event in published_events] == ["subagent_tree_changed"]


async def test_followup_task_from_child_rejects_root() -> None:
    """followup_task matches Codex by rejecting the root agent."""
    toolkit, _repo, input_service, broker, _run_repo, _events = await _make_toolkit()
    state = await toolkit.update_context(
        TurnContext(
            user_id="user-1",
            workspace_id="workspace-1",
            model="gpt-5.1",
            run_id="run-1",
            publish_event=cast(Any, _noop_publish),
            session_id="child-session",
        )
    )
    tool = next(tool for tool in state.tools if tool.spec.name == "followup_task")

    with pytest.raises(
        FunctionToolError,
        match="Follow-up tasks can't target the root agent",
    ):
        await tool.handler(json.dumps({"agent_name": "/root", "task": "work"}))

    assert input_service.enqueued == []
    assert broker.messages == []


async def test_interrupt_agent_rejects_root_and_self() -> None:
    """interrupt_agent matches Codex root and self restrictions."""
    toolkit, _repo, _input_service, _broker, _run_repo, _events = await _make_toolkit()
    state = await toolkit.update_context(
        TurnContext(
            user_id="user-1",
            workspace_id="workspace-1",
            model="gpt-5.1",
            run_id="run-1",
            publish_event=cast(Any, _noop_publish),
            session_id="child-session",
        )
    )
    tool = next(tool for tool in state.tools if tool.spec.name == "interrupt_agent")

    with pytest.raises(FunctionToolError, match="root is not a spawned agent"):
        await tool.handler(json.dumps({"agent_name": "/root"}))
    with pytest.raises(FunctionToolError, match="an agent cannot interrupt itself"):
        await tool.handler(json.dumps({"agent_name": "."}))


async def test_list_agents_from_child_includes_root_tree() -> None:
    """list_agents matches Codex by exposing the root and known agent tree."""
    toolkit, _repo, _input_service, _broker, _run_repo, _events = await _make_toolkit()
    state = await toolkit.update_context(
        TurnContext(
            user_id="user-1",
            workspace_id="workspace-1",
            model="gpt-5.1",
            run_id="run-1",
            publish_event=cast(Any, _noop_publish),
            session_id="child-session",
        )
    )
    tool = next(tool for tool in state.tools if tool.spec.name == "list_agents")

    result = await tool.handler("{}")

    agents = json.loads(cast(str, result))["agents"]
    assert [agent["agent_path"] for agent in agents] == ["/root", "/root/child"]


async def test_wait_agent_returns_terminal_result_and_advances_cursor() -> None:
    """wait_agent observes unread child terminal results once."""
    (
        toolkit,
        repo,
        _input_service,
        _broker,
        _run_repo,
        published_events,
    ) = await _make_toolkit()

    async def publish_event(event: SubagentTreeChanged) -> None:
        published_events.append(event)

    state = await toolkit.update_context(
        TurnContext(
            user_id="user-1",
            workspace_id="workspace-1",
            model="gpt-5.1",
            run_id="run-1",
            publish_event=cast(Any, publish_event),
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
    assert [event.type for event in published_events] == ["subagent_tree_changed"]

    second_result = await tool.handler(json.dumps({"agent_name": "child"}))

    assert json.loads(cast(str, second_result)) == {
        "message": "No unread terminal result.",
        "timed_out": False,
    }
    assert repo.observation_updates == [("child-agent", 1, "event".rjust(32, "0"))]
    assert [event.type for event in published_events] == ["subagent_tree_changed"]


async def test_wait_agent_waits_for_running_child_result() -> None:
    """wait_agent waits for a running child before timing out."""
    (
        toolkit,
        repo,
        _input_service,
        _broker,
        run_repo,
        published_events,
    ) = await _make_toolkit()
    running = run_repo.latest_by_session_id["child-session"].model_copy(
        update={"status": AgentRunStatus.RUNNING, "ended_at": None}
    )
    run_repo.latest_by_session_id["child-session"] = running
    repo.sessions["child-session"] = _agent_session(
        id="child-session",
        run_state=AgentSessionRunState.RUNNING,
    )

    async def publish_event(event: SubagentTreeChanged) -> None:
        published_events.append(event)

    state = await toolkit.update_context(
        TurnContext(
            user_id="user-1",
            workspace_id="workspace-1",
            model="gpt-5.1",
            run_id="run-1",
            publish_event=cast(Any, publish_event),
            session_id="root-session",
        )
    )
    tool = next(tool for tool in state.tools if tool.spec.name == "wait_agent")

    async def complete_child() -> None:
        await asyncio.sleep(0.01)
        run_repo.latest_by_session_id["child-session"] = running.model_copy(
            update={
                "status": AgentRunStatus.COMPLETED,
                "terminal_result_event_id": "done".rjust(32, "0"),
                "terminal_result_message": "child completed after wait",
                "ended_at": _NOW,
            }
        )
        repo.sessions["child-session"] = _agent_session(id="child-session")

    completion = asyncio.create_task(complete_child())
    try:
        result = await tool.handler(
            json.dumps({"agent_name": "child", "timeout_seconds": 1})
        )
    finally:
        await completion

    assert json.loads(cast(str, result)) == {
        "message": "child completed after wait",
        "timed_out": False,
    }
    assert repo.observation_updates == [("child-agent", 1, "done".rjust(32, "0"))]
    assert [event.type for event in published_events] == ["subagent_tree_changed"]


async def test_wait_agent_timeout_waits_until_deadline() -> None:
    """wait_agent reports timeout only after the requested wait window."""
    (
        toolkit,
        repo,
        _input_service,
        _broker,
        run_repo,
        _published_events,
    ) = await _make_toolkit()
    run_repo.latest_by_session_id["child-session"] = run_repo.latest_by_session_id[
        "child-session"
    ].model_copy(update={"status": AgentRunStatus.RUNNING, "ended_at": None})
    repo.sessions["child-session"] = _agent_session(
        id="child-session",
        run_state=AgentSessionRunState.RUNNING,
    )

    state = await toolkit.update_context(
        TurnContext(
            user_id="user-1",
            workspace_id="workspace-1",
            model="gpt-5.1",
            run_id="run-1",
            publish_event=cast(Any, _noop_publish),
            session_id="root-session",
        )
    )
    tool = next(tool for tool in state.tools if tool.spec.name == "wait_agent")

    started = time.monotonic()
    result = await tool.handler(
        json.dumps({"agent_name": "child", "timeout_seconds": 1})
    )

    assert time.monotonic() - started >= 0.9
    assert json.loads(cast(str, result)) == {
        "message": "Still running: /root/child",
        "timed_out": True,
    }
    assert repo.observation_updates == []


async def test_spawn_agent_creates_and_wakes_child_within_limits() -> None:
    """spawn_agent creates a child when depth and active subagent limits allow it."""
    (
        toolkit,
        repo,
        input_service,
        broker,
        _run_repo,
        published_events,
    ) = await _make_toolkit()
    state = await toolkit.update_context(
        TurnContext(
            user_id="user-1",
            workspace_id="workspace-1",
            model="gpt-5.1",
            run_id="run-1",
            publish_event=cast(Any, _publish_to(published_events)),
            session_id="root-session",
        )
    )
    tool = next(tool for tool in state.tools if tool.spec.name == "spawn_agent")

    result = await tool.handler(json.dumps({"name": "reviewer", "task": "Review it"}))

    child = repo.created_children[0]
    assert json.loads(cast(str, result)) == {
        "agent_name": "reviewer",
        "agent_path": "/root/reviewer",
        "status": "spawned",
    }
    assert repo.locked_session_agents == ["root-agent"]
    assert input_service.enqueued[0].metadata["message_kind"] == "spawn_agent"
    assert input_service.enqueued[0].content == "Review it"
    assert repo.locked_session_agents == ["root-agent"]
    assert repo.marked_running == [child.agent_session_id]
    assert len(broker.messages) == 1
    assert isinstance(broker.messages[0], SessionWakeUp)
    assert [event.type for event in published_events] == ["subagent_tree_changed"]


async def test_spawn_agent_inserts_boundary_after_forked_history() -> None:
    """spawn_agent separates copied parent history from the child task."""
    (
        toolkit,
        _repo,
        input_service,
        _broker,
        _run_repo,
        _published_events,
    ) = await _make_toolkit()
    event_repo = cast(_EventTranscriptRepository, toolkit.event_transcript_repository)
    event_repo.forked_events = [
        _event(EventKind.USER_MESSAGE, UserMessagePayload(content="Make the PR"), 1000)
    ]
    state = await toolkit.update_context(
        TurnContext(
            user_id="user-1",
            workspace_id="workspace-1",
            model="gpt-5.1",
            run_id="run-1",
            publish_event=cast(Any, _noop_publish),
            session_id="root-session",
        )
    )
    tool = next(tool for tool in state.tools if tool.spec.name == "spawn_agent")

    await tool.handler(json.dumps({"name": "reviewer", "task": "Review only"}))

    assert [event.kind for event in event_repo.appended] == [
        EventKind.USER_MESSAGE,
        EventKind.SYSTEM_REMINDER,
    ]
    assert event_repo.appended[0].model_order == 1000
    assert event_repo.appended[1].model_order is None
    reminder_text = event_repo.appended[1].payload["text"]
    assert isinstance(reminder_text, str)
    assert "inherited conversation history" in reminder_text
    assert "direct assignment begins after this reminder" in reminder_text
    assert input_service.enqueued[0].content == "Review only"


async def test_spawn_agent_does_not_insert_boundary_without_forked_history() -> None:
    """spawn_agent omits the fork boundary when no parent events are copied."""
    (
        toolkit,
        _repo,
        _input_service,
        _broker,
        _run_repo,
        _published_events,
    ) = await _make_toolkit()
    event_repo = cast(_EventTranscriptRepository, toolkit.event_transcript_repository)
    state = await toolkit.update_context(
        TurnContext(
            user_id="user-1",
            workspace_id="workspace-1",
            model="gpt-5.1",
            run_id="run-1",
            publish_event=cast(Any, _noop_publish),
            session_id="root-session",
        )
    )
    tool = next(tool for tool in state.tools if tool.spec.name == "spawn_agent")

    await tool.handler(json.dumps({"name": "reviewer", "task": "Review only"}))

    assert event_repo.appended == []


async def test_spawn_agent_rejects_when_active_subagent_limit_is_reached() -> None:
    """spawn_agent reports a clear error instead of queueing over capacity."""
    (
        toolkit,
        repo,
        input_service,
        broker,
        _run_repo,
        _published_events,
    ) = await _make_toolkit()
    toolkit.subagent_settings = SubagentSettings(max_subagents=1, max_depth=1)
    repo.sessions["child-session"] = _agent_session(
        id="child-session",
        run_state=AgentSessionRunState.RUNNING,
    )
    state = await toolkit.update_context(
        TurnContext(
            user_id="user-1",
            workspace_id="workspace-1",
            model="gpt-5.1",
            run_id="run-1",
            publish_event=cast(Any, _noop_publish),
            session_id="root-session",
        )
    )
    tool = next(tool for tool in state.tools if tool.spec.name == "spawn_agent")

    with pytest.raises(FunctionToolError, match="max_subagents 1 is already reached"):
        await tool.handler(json.dumps({"name": "extra", "task": "Work"}))

    assert repo.created_children == []
    assert input_service.enqueued == []
    assert broker.messages == []


async def test_spawn_agent_counts_latest_running_run_toward_active_limit() -> None:
    """Count latest running child runs before run_state projection catches up."""
    (
        toolkit,
        repo,
        input_service,
        broker,
        run_repo,
        _published_events,
    ) = await _make_toolkit()
    toolkit.subagent_settings = SubagentSettings(max_subagents=1, max_depth=1)
    repo.sessions["child-session"] = _agent_session(
        id="child-session",
        run_state=AgentSessionRunState.IDLE,
    )
    run_repo.latest_by_session_id["child-session"] = AgentRunState(
        id="running-run".rjust(32, "0"),
        session_id="child-session",
        run_index=2,
        phase=AgentRunPhase.EXECUTING_TOOLS,
        status=AgentRunStatus.RUNNING,
        terminal_result_event_id=None,
        terminal_result_message=None,
        started_at=_NOW,
        ended_at=None,
        updated_at=_NOW,
    )
    state = await toolkit.update_context(
        TurnContext(
            user_id="user-1",
            workspace_id="workspace-1",
            model="gpt-5.1",
            run_id="run-1",
            publish_event=cast(Any, _noop_publish),
            session_id="root-session",
        )
    )
    tool = next(tool for tool in state.tools if tool.spec.name == "spawn_agent")

    with pytest.raises(FunctionToolError, match="max_subagents 1 is already reached"):
        await tool.handler(json.dumps({"name": "extra", "task": "Work"}))

    assert repo.created_children == []
    assert input_service.enqueued == []
    assert broker.messages == []


async def test_spawn_agent_rejects_when_depth_limit_is_reached() -> None:
    """spawn_agent rejects nested children beyond configured max_depth."""
    (
        toolkit,
        repo,
        input_service,
        broker,
        _run_repo,
        _published_events,
    ) = await _make_toolkit()
    toolkit.session_id = "child-session"
    toolkit.subagent_settings = SubagentSettings(max_subagents=3, max_depth=1)
    state = await toolkit.update_context(
        TurnContext(
            user_id="user-1",
            workspace_id="workspace-1",
            model="gpt-5.1",
            run_id="run-1",
            publish_event=cast(Any, _noop_publish),
            session_id="child-session",
        )
    )
    tool = next(tool for tool in state.tools if tool.spec.name == "spawn_agent")

    with pytest.raises(FunctionToolError, match="max_depth 1 would be exceeded"):
        await tool.handler(json.dumps({"name": "nested", "task": "Work"}))

    assert repo.created_children == []
    assert input_service.enqueued == []
    assert broker.messages == []
