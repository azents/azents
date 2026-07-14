"""Subagent collaboration Toolkit tests."""

# ruff: noqa: E501

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
from azents.core.agent import SelectableModelOption, SubagentSettings
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
from azents.core.inference_profile import SessionInferenceState
from azents.core.llm_catalog import ModelReasoningEffort
from azents.core.tools import ToolkitStatus, TurnContext
from azents.engine.events.engine_events import SubagentTreeChanged
from azents.engine.events.types import AgentRunState, Event, UserMessagePayload
from azents.engine.run.types import FunctionToolError
from azents.repos.agent.data import Agent
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSession, SessionAgent
from azents.services.input_buffer import InputBufferEnqueue, InputBufferService
from azents.testing.model_selection import make_test_model_selection

from .subagent import (
    SpawnAgentInput,
    SubagentToolkit,
    normalize_spawn_reasoning_effort,
)

_NOW = datetime.datetime.now(datetime.UTC)
_PARENT_RUN_ID = "parent-run".rjust(32, "0")


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
        last_message_at=None,
        parent_observed_run_index=None,
        parent_observed_event_id=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _agent() -> Agent:
    """Create the Agent snapshot used by subagent tool tests."""
    selection = make_test_model_selection()
    selection.normalized_capabilities.reasoning.supported = True
    selection.normalized_capabilities.reasoning.effort_levels = [
        ModelReasoningEffort.LOW,
        ModelReasoningEffort.MEDIUM,
        ModelReasoningEffort.HIGH,
    ]
    return Agent.model_construct(
        id="agent-1",
        workspace_id="workspace-1",
        name="Agent",
        model_selection=selection,
        lightweight_model_selection=selection,
        selectable_model_options=[
            SelectableModelOption(label="Quality", model_selection=selection)
        ],
        main_model_label="Quality",
        lightweight_model_label="Quality",
        model_parameters=None,
        enabled=True,
        subagent_settings=SubagentSettings(),
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
        owner_generation=0,
        inference_state=SessionInferenceState(
            model_target_label="Quality",
            model_selection=_agent().model_selection,
            reasoning_effort=ModelReasoningEffort.HIGH,
            effective_context_window_tokens=64_000,
            effective_auto_compaction_threshold_tokens=51_200,
            resolved_at=_NOW,
        ),
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
        self.inference_states: list[tuple[str, SessionInferenceState]] = []
        self.last_task_updates: list[tuple[str, str | None]] = []
        self.message_sent_updates: list[str] = []
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

    async def mark_session_agent_message_activity(
        self,
        session: AsyncSession,
        *,
        session_agent_id: str,
    ) -> SessionAgent | None:
        """Record an agent message activity timestamp update."""
        del session
        self.message_sent_updates.append(session_agent_id)
        return next(agent for agent in self.tree if agent.id == session_agent_id)

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

    async def set_inference_state(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        inference_state: SessionInferenceState,
    ) -> AgentSession:
        """Record the inherited child session inference state."""
        del session
        self.inference_states.append((session_id, inference_state))
        updated = self.sessions[session_id].model_copy(
            update={"inference_state": inference_state}
        )
        self.sessions[session_id] = updated
        return updated

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

    async def lock_by_id(
        self,
        session: AsyncSession,
        agent_session_id: str,
    ) -> AgentSession | None:
        """Return one locked AgentSession fixture."""
        return await self.get_by_id(session, agent_session_id)


class _AgentRunRepository:
    """AgentRunRepository fake for subagent tool tests."""

    def __init__(self) -> None:
        """Initialize parent and latest child run fixtures."""
        self.parent_run = AgentRunState(
            id=_PARENT_RUN_ID,
            session_id="root-session",
            run_index=1,
            phase=AgentRunPhase.EXECUTING_TOOLS,
            status=AgentRunStatus.RUNNING,
            parent_agent_run_id=None,
            terminal_result_event_id=None,
            terminal_result_message=None,
            created_at=_NOW,
            started_at=_NOW,
            model_call_started_at=None,
            ended_at=None,
            updated_at=_NOW,
        )
        self.get_by_id_calls: list[str] = []
        self.pending_creates: list[dict[str, object]] = []
        self.latest_by_session_id = {
            "child-session": AgentRunState(
                id="run".rjust(32, "0"),
                session_id="child-session",
                run_index=1,
                phase=AgentRunPhase.IDLE,
                status=AgentRunStatus.COMPLETED,
                parent_agent_run_id=None,
                terminal_result_event_id="event".rjust(32, "0"),
                terminal_result_message="child result",
                created_at=_NOW,
                started_at=_NOW,
                model_call_started_at=None,
                ended_at=_NOW,
                updated_at=_NOW,
            )
        }

    async def get_by_id(
        self,
        session: AsyncSession,
        run_id: str,
    ) -> AgentRunState | None:
        """Return the exact spawning parent run fixture."""
        del session
        self.get_by_id_calls.append(run_id)
        if run_id != self.parent_run.id:
            return None
        return self.parent_run

    async def create_pending(
        self,
        session: AsyncSession,
        **kwargs: object,
    ) -> AgentRunState:
        """Record inherited pending child run creation."""
        del session
        self.pending_creates.append(kwargs)
        return self.parent_run

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
        agent=_agent(),
        subagent_settings=SubagentSettings(),
    )
    state = await toolkit.update_context(
        TurnContext(
            user_id="user-1",
            workspace_id="workspace-1",
            model="gpt-5.1",
            run_id=_PARENT_RUN_ID,
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


_EXPECTED_ROOT_USAGE_HINT = """You are `/root`, the primary agent in a team of agents collaborating to fulfill the user's goals.

At the start of your turn, you are the active agent.
You can spawn sub-agents to handle subtasks, and those sub-agents can spawn their own sub-agents.
All agents in the team, including the agents that you can assign tasks to, are equally intelligent and capable, and have access to almost the same set of tools, except for Azents root/user-facing capabilities that are not available in subagent mode.

You can use `spawn_agent` to create a new agent, `followup_task` to give an existing agent a new task and trigger a turn, and `send_message` to pass a message to a running agent without triggering a turn.
Child agents can also spawn their own sub-agents.
You can decide how much context you want to propagate to your sub-agents with the `fork_turns` parameter.
Use `wait_agent` to observe unread terminal child results when you need completion output from child agents.

You will receive messages in the model input in the form:
```
Message Type: MESSAGE
Task name: <recipient>
Sender: <author>
Payload:
<payload text>
```
They may be addressed as to=/root"""

_EXPECTED_CHILD_USAGE_HINT = """You are an agent in a team of agents collaborating to complete a task.

You can spawn sub-agents to handle subtasks, and those sub-agents can spawn their own sub-agents. All agents in the team, including the agents that you can assign tasks to, are equally intelligent and capable, and have access to almost the same set of tools, except for Azents root/user-facing capabilities that are not available in subagent mode.

You can use `spawn_agent` to create a new agent, `followup_task` to give an existing agent a new task and trigger a turn, and `send_message` to pass a message to a running agent.
Child agents can also spawn their own sub-agents.

When you provide a final response, that content is stored as a terminal child result for your parent to observe with `wait_agent`.

You will receive messages in the model input in the form:
```
Message Type: NEW_TASK | MESSAGE
Task name: <recipient>
Sender: <author>
Payload:
<payload text>
```
You may also see them addressed as to=/root/..., which indicates your identity is /root/..."""

_EXPECTED_SHARED_USAGE_HINT = """Note that collaboration tools cannot be called from inside `exec_command`. Call `spawn_agent`, `send_message`, `followup_task`, `wait_agent`, `interrupt_agent`, and `list_agents` only as direct tool calls using the recipient shown in their tool definitions, since they are intentionally absent from `exec_command`.

All agents share the same directory. In detail:
- All agents have access to the same container and filesystem as you.
- All agents use the same current working directory.
- As a result, edits made by one agent are immediately visible to all other agents."""

_EXPECTED_CONCURRENCY_HINT = "There are 4 available concurrency slots, meaning that up to 4 agents can be active at once, including you."
_EXPECTED_DELEGATION_POLICY = "Do not spawn sub-agents unless the user or applicable AGENTS.md/skill instructions explicitly ask for sub-agents, delegation, or parallel agent work."


def _expected_static_prompt(usage_hint: str) -> str:
    """Build the exact frozen prompt expected by Toolkit tests."""
    return "\n\n".join(
        [
            usage_hint,
            _EXPECTED_SHARED_USAGE_HINT,
            _EXPECTED_CONCURRENCY_HINT,
            _EXPECTED_DELEGATION_POLICY,
        ]
    )


async def test_subagent_static_prompt_matches_codex_root_prompt() -> None:
    """Render the exact Codex V2 root prompt with Azents terminology."""
    toolkit, _repo, _input_service, _broker, _run_repo, _events = await _make_toolkit()

    prompt = await toolkit.get_static_prompt(
        TurnContext(
            user_id="user-1",
            workspace_id="workspace-1",
            model="gpt-5.1",
            run_id=_PARENT_RUN_ID,
            publish_event=cast(Any, _noop_publish),
            session_id="root-session",
        )
    )

    assert prompt == _expected_static_prompt(_EXPECTED_ROOT_USAGE_HINT)
    assert "immediately delivered back to your parent agent" not in prompt
    assert "maximum subagent depth" not in prompt


async def test_subagent_static_prompt_matches_codex_child_prompt() -> None:
    """Render the exact Codex V2 child prompt with Azents terminology."""
    toolkit, _repo, _input_service, _broker, _run_repo, _events = await _make_toolkit()

    prompt = await toolkit.get_static_prompt(
        TurnContext(
            user_id="user-1",
            workspace_id="workspace-1",
            model="gpt-5.1",
            run_id="run-1",
            publish_event=cast(Any, _noop_publish),
            session_id="child-session",
        )
    )

    assert prompt == _expected_static_prompt(_EXPECTED_CHILD_USAGE_HINT)
    assert "primary agent" not in prompt
    assert "maximum subagent depth" not in prompt


def test_spawn_agent_fork_turns_defaults_to_all() -> None:
    """spawn_agent propagates all context by default."""
    assert SpawnAgentInput.model_fields["fork_turns"].default == "all"


@pytest.mark.parametrize(
    ("baseline", "supported", "expected"),
    [
        (ModelReasoningEffort.HIGH, [], None),
        (
            ModelReasoningEffort.HIGH,
            [ModelReasoningEffort.LOW, ModelReasoningEffort.HIGH],
            ModelReasoningEffort.HIGH,
        ),
        (
            ModelReasoningEffort.HIGH,
            [ModelReasoningEffort.LOW, ModelReasoningEffort.MEDIUM],
            ModelReasoningEffort.MEDIUM,
        ),
        (
            ModelReasoningEffort.LOW,
            [ModelReasoningEffort.HIGH, ModelReasoningEffort.XHIGH],
            ModelReasoningEffort.HIGH,
        ),
        (
            None,
            [ModelReasoningEffort.LOW, ModelReasoningEffort.HIGH],
            ModelReasoningEffort.LOW,
        ),
    ],
)
def test_normalize_reasoning_effort(
    baseline: ModelReasoningEffort | None,
    supported: list[ModelReasoningEffort],
    expected: ModelReasoningEffort | None,
) -> None:
    """Normalize model-only overrides using canonical effort ordering."""
    assert normalize_spawn_reasoning_effort(baseline, supported) == expected


async def test_spawn_agent_schema_lists_labels_without_model_identity() -> None:
    """Expose Agent-owned labels and effort levels without physical metadata."""
    toolkit, _repo, _input_service, _broker, _run_repo, _events = await _make_toolkit()
    selection = make_test_model_selection(
        integration_id="secret-integration",
        model_identifier="secret-physical-model",
    )
    selection.model_display_name = "Secret Display Name"
    selection.model_family = "secret-family"
    selection.normalized_capabilities.reasoning.supported = True
    selection.normalized_capabilities.reasoning.effort_levels = [
        ModelReasoningEffort.MEDIUM,
        ModelReasoningEffort.XHIGH,
    ]
    toolkit.agent.selectable_model_options.append(
        SelectableModelOption(label="Research", model_selection=selection)
    )

    state = await toolkit.update_context(
        TurnContext(
            user_id="user-1",
            workspace_id="workspace-1",
            model="secret-parent-runtime-model",
            run_id=_PARENT_RUN_ID,
            publish_event=cast(Any, _noop_publish),
            session_id="root-session",
        )
    )
    tool = next(tool for tool in state.tools if tool.spec.name == "spawn_agent")
    rendered = json.dumps(
        {"description": tool.spec.description, "schema": tool.spec.input_schema}
    )

    assert "inherited parent Run target is preferred" in rendered
    assert "`Quality` Reasoning efforts: low, medium, high." in rendered
    assert "`Research` Reasoning efforts: medium, xhigh." in rendered
    assert "secret-integration" not in rendered
    assert "secret-physical-model" not in rendered
    assert "Secret Display Name" not in rendered
    assert "secret-family" not in rendered
    assert "secret-parent-runtime-model" not in rendered


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
            run_id=_PARENT_RUN_ID,
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
    assert repo.message_sent_updates == ["root-agent", "child-agent"]
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
            run_id=_PARENT_RUN_ID,
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
            run_id=_PARENT_RUN_ID,
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
            run_id=_PARENT_RUN_ID,
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
            run_id=_PARENT_RUN_ID,
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
            run_id=_PARENT_RUN_ID,
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
            run_id=_PARENT_RUN_ID,
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

    second_result = await tool.handler("{}")

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
            run_id=_PARENT_RUN_ID,
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
            run_id=_PARENT_RUN_ID,
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


async def test_wait_agent_reports_when_no_descendants_exist() -> None:
    """wait_agent distinguishes an empty descendant set from an empty result."""
    toolkit, repo, _input_service, _broker, _run_repo, _events = await _make_toolkit()
    repo.tree = [repo.current]
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

    result = await tool.handler(json.dumps({"timeout_seconds": 120}))

    assert json.loads(cast(str, result)) == {
        "message": "No descendant agents to wait for.",
        "timed_out": False,
    }


async def test_wait_agent_reports_named_missing_target() -> None:
    """wait_agent preserves the named missing-target result."""
    toolkit, _repo, _input_service, _broker, _run_repo, _events = await _make_toolkit()
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

    result = await tool.handler(json.dumps({"agent_name": "missing"}))

    assert json.loads(cast(str, result)) == {
        "message": "not_found",
        "timed_out": False,
    }


async def test_wait_agent_rejects_current_agent_target() -> None:
    """wait_agent rejects the current agent instead of treating it as missing."""
    toolkit, _repo, _input_service, _broker, _run_repo, _events = await _make_toolkit()
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

    with pytest.raises(FunctionToolError, match="cannot wait for itself"):
        await tool.handler(json.dumps({"agent_name": "root"}))


async def test_spawn_agent_creates_and_wakes_child_within_limits() -> None:
    """spawn_agent creates a child when depth and active subagent limits allow it."""
    (
        toolkit,
        repo,
        input_service,
        broker,
        run_repo,
        published_events,
    ) = await _make_toolkit()
    state = await toolkit.update_context(
        TurnContext(
            user_id="user-1",
            workspace_id="workspace-1",
            model="gpt-5.1",
            run_id=_PARENT_RUN_ID,
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
    assert run_repo.get_by_id_calls == [_PARENT_RUN_ID]
    assert run_repo.pending_creates == [
        {
            "session_id": child.agent_session_id,
            "parent_agent_run_id": _PARENT_RUN_ID,
        }
    ]
    assert repo.inference_states == [
        (child.agent_session_id, repo.sessions["root-session"].inference_state)
    ]
    assert input_service.enqueued[0].metadata["message_kind"] == "spawn_agent"
    assert input_service.enqueued[0].content == "Review it"
    assert repo.locked_session_agents == ["root-agent"]
    assert repo.marked_running == [child.agent_session_id]
    assert len(broker.messages) == 1
    assert isinstance(broker.messages[0], SessionWakeUp)
    assert [event.type for event in published_events] == ["subagent_tree_changed"]


async def test_spawn_agent_applies_target_override_and_normalized_effort() -> None:
    """Pre-resolve a bounded target override and persist its child intent."""
    toolkit, repo, _input_service, _broker, run_repo, _events = await _make_toolkit()
    selection = make_test_model_selection(model_identifier="override-model")
    selection.normalized_capabilities.context_window.max_input_tokens = 32_000
    selection.normalized_capabilities.reasoning.supported = True
    selection.normalized_capabilities.reasoning.effort_levels = [
        ModelReasoningEffort.LOW,
        ModelReasoningEffort.MEDIUM,
    ]
    toolkit.agent.selectable_model_options.append(
        SelectableModelOption(label="Research", model_selection=selection)
    )
    state = await toolkit.update_context(
        TurnContext(
            user_id="user-1",
            workspace_id="workspace-1",
            model="gpt-5.1",
            run_id=_PARENT_RUN_ID,
            publish_event=cast(Any, _noop_publish),
            session_id="root-session",
        )
    )
    tool = next(tool for tool in state.tools if tool.spec.name == "spawn_agent")

    await tool.handler(
        json.dumps(
            {
                "name": "researcher",
                "task": "Research it",
                "fork_turns": "none",
                "model_target_label": "Research",
            }
        )
    )

    assert run_repo.pending_creates[0] == {
        "session_id": "researcher-session",
        "parent_agent_run_id": _PARENT_RUN_ID,
    }
    child_state = repo.inference_states[0]
    assert child_state[0] == "researcher-session"
    assert child_state[1].model_target_label == "Research"
    assert child_state[1].model_selection == selection
    assert child_state[1].reasoning_effort == ModelReasoningEffort.MEDIUM
    assert child_state[1].effective_context_window_tokens == 32_000
    assert child_state[1].effective_auto_compaction_threshold_tokens == 28_800


@pytest.mark.parametrize(
    ("arguments", "expected_error"),
    [
        (
            {"fork_turns": "all", "model_target_label": "Quality"},
            "full-history forks inherit",
        ),
        (
            {"fork_turns": "none", "model_target_label": "Missing"},
            "was not found",
        ),
        (
            {"fork_turns": "none", "reasoning_effort": "xhigh"},
            "is not supported",
        ),
    ],
)
async def test_spawn_agent_rejects_invalid_override_without_child_residue(
    arguments: dict[str, str],
    expected_error: str,
) -> None:
    """Reject static override errors before creating or waking a child."""
    toolkit, repo, input_service, broker, run_repo, events = await _make_toolkit()
    state = await toolkit.update_context(
        TurnContext(
            user_id="user-1",
            workspace_id="workspace-1",
            model="gpt-5.1",
            run_id=_PARENT_RUN_ID,
            publish_event=cast(Any, _publish_to(events)),
            session_id="root-session",
        )
    )
    tool = next(tool for tool in state.tools if tool.spec.name == "spawn_agent")

    with pytest.raises(FunctionToolError, match=expected_error):
        await tool.handler(
            json.dumps({"name": "reviewer", "task": "Review it", **arguments})
        )

    assert repo.created_children == []
    assert run_repo.pending_creates == []
    assert repo.inference_states == []
    assert input_service.enqueued == []
    assert broker.messages == []
    assert events == []


@pytest.mark.parametrize(
    ("parent_run_id", "parent_updates", "expected_error"),
    [
        ("arbitrary-run", {}, "Current AgentRun was not found"),
        (
            _PARENT_RUN_ID,
            {"session_id": "other-session"},
            "Current AgentRun was not found",
        ),
        (
            _PARENT_RUN_ID,
            {"status": AgentRunStatus.COMPLETED},
            "Current AgentRun is not running",
        ),
    ],
)
async def test_spawn_agent_rejects_invalid_parent_run(
    parent_run_id: str,
    parent_updates: dict[str, object],
    expected_error: str,
) -> None:
    """spawn_agent accepts only the complete run executing the parent turn."""
    (
        toolkit,
        repo,
        input_service,
        broker,
        run_repo,
        _published_events,
    ) = await _make_toolkit()
    run_repo.parent_run = run_repo.parent_run.model_copy(update=parent_updates)
    state = await toolkit.update_context(
        TurnContext(
            user_id="user-1",
            workspace_id="workspace-1",
            model="gpt-5.1",
            run_id=parent_run_id,
            publish_event=cast(Any, _noop_publish),
            session_id="root-session",
        )
    )
    tool = next(tool for tool in state.tools if tool.spec.name == "spawn_agent")

    with pytest.raises(FunctionToolError, match=expected_error):
        await tool.handler(json.dumps({"name": "reviewer", "task": "Review it"}))

    assert repo.created_children == []
    assert run_repo.pending_creates == []
    assert repo.inference_states == []
    assert input_service.enqueued == []
    assert broker.messages == []


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
            run_id=_PARENT_RUN_ID,
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
    assert 'You are the subagent named "reviewer".' in reminder_text
    assert 'Your full agent path is "/root/reviewer".' in reminder_text
    assert "The next message is your current direct assignment." in reminder_text
    assert "Never call wait_agent on yourself." in reminder_text
    assert "for observing your descendants" in reminder_text
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
            run_id=_PARENT_RUN_ID,
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
            run_id=_PARENT_RUN_ID,
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
        parent_agent_run_id=None,
        terminal_result_event_id=None,
        terminal_result_message=None,
        created_at=_NOW,
        started_at=_NOW,
        model_call_started_at=None,
        ended_at=None,
        updated_at=_NOW,
    )
    state = await toolkit.update_context(
        TurnContext(
            user_id="user-1",
            workspace_id="workspace-1",
            model="gpt-5.1",
            run_id=_PARENT_RUN_ID,
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
            run_id=_PARENT_RUN_ID,
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
