"""Subagent collaboration Toolkit."""

# ruff: noqa: E501

import asyncio
import dataclasses
import json
import time
from textwrap import dedent
from typing import Literal

from pydantic import BaseModel, Field, TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.types import SessionBroker, SessionStopSignal, SessionWakeUp
from azents.core.agent import SubagentSettings
from azents.core.enums import (
    AgentRunStatus,
    AgentSessionRunState,
    EventKind,
    InputBufferKind,
    SessionAgentKind,
)
from azents.core.tools import (
    PublishEventFn,
    ResolveContext,
    Toolkit,
    ToolkitProvider,
    ToolkitState,
    ToolkitStatus,
    TurnContext,
)
from azents.engine.events.engine_events import SubagentTreeChanged
from azents.engine.events.fork_context import (
    ForkTurnsSelection,
    InvalidForkTurns,
    degrade_file_parts_for_fork,
    parse_fork_turns,
    select_fork_events,
)
from azents.engine.events.types import AgentRunState, Event, SystemReminderPayload
from azents.engine.run.types import FunctionTool, FunctionToolError
from azents.engine.tooling.make_tool import make_tool
from azents.rdb.models.event import JSONValue
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSession, SessionAgent
from azents.services.input_buffer import InputBufferEnqueue, InputBufferService

_ROOT_AGENT_USAGE_HINT_TEXT = """You are `/root`, the primary agent in a team of agents collaborating to fulfill the user's goals.

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

_SUBAGENT_USAGE_HINT_TEXT = """You are an agent in a team of agents collaborating to complete a task.

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

_SHARED_USAGE_HINT_TEXT = """Note that collaboration tools cannot be called from inside `exec_command`. Call `spawn_agent`, `send_message`, `followup_task`, `wait_agent`, `interrupt_agent`, and `list_agents` only as direct tool calls using the recipient shown in their tool definitions, since they are intentionally absent from `exec_command`.

All agents share the same directory. In detail:
- All agents have access to the same container and filesystem as you.
- All agents use the same current working directory.
- As a result, edits made by one agent are immediately visible to all other agents."""

_EXPLICIT_REQUEST_ONLY_MODE_TEXT = "Do not spawn sub-agents unless the user or applicable AGENTS.md/skill instructions explicitly ask for sub-agents, delegation, or parallel agent work."


class SubagentToolkitConfig(BaseModel):
    """Subagent collaboration Toolkit configuration."""


class SpawnAgentInput(BaseModel):
    """spawn_agent tool input."""

    name: str = Field(description="Child agent name within the current agent")
    task: str = Field(description="Initial task for the child agent")
    agent_type: Literal["default"] = Field(
        default="default",
        description="Agent type. Only the default type is supported.",
    )
    fork_turns: str = Field(
        default="all",
        description=(
            "Context fork selection: 'none', 'all', or a positive integer string. "
            "Defaults to 'all'."
        ),
    )


class SendMessageInput(BaseModel):
    """send_message tool input."""

    agent_name: str = Field(description="Target agent path or name")
    message: str = Field(description="Message to queue for the target agent")


class FollowupTaskInput(BaseModel):
    """followup_task tool input."""

    agent_name: str = Field(description="Target agent path or name")
    task: str = Field(description="Follow-up task to assign and wake")


class WaitAgentInput(BaseModel):
    """wait_agent tool input."""

    agent_name: str | None = Field(
        default=None,
        description=(
            "Optional target agent path or child name. "
            "Omit to wait for all descendants."
        ),
    )
    timeout_seconds: int | None = Field(
        default=None,
        ge=0,
        le=600,
        description=(
            "Optional maximum wait time. Blocking wait is completed in a later phase."
        ),
    )


class InterruptAgentInput(BaseModel):
    """interrupt_agent tool input."""

    agent_name: str = Field(description="Target agent path or name")


_JSON_OBJECT_ADAPTER = TypeAdapter[dict[str, JSONValue]](dict[str, JSONValue])

_TERMINAL_STATUSES = {
    AgentRunStatus.COMPLETED,
    AgentRunStatus.FAILED,
    AgentRunStatus.STOPPED,
    AgentRunStatus.INTERRUPTED,
    AgentRunStatus.CANCELLED,
}
_WAIT_AGENT_POLL_INTERVAL_SECONDS = 0.1


@dataclasses.dataclass(frozen=True)
class _TargetResolution:
    current: SessionAgent
    target: SessionAgent | None


class SubagentToolkit(Toolkit[SubagentToolkitConfig]):
    """Model-visible subagent collaboration tools."""

    def __init__(
        self,
        *,
        session_manager: SessionManager[AsyncSession],
        agent_session_repository: AgentSessionRepository,
        agent_run_repository: AgentRunRepository,
        event_transcript_repository: EventTranscriptRepository,
        input_buffer_service: InputBufferService,
        broker: SessionBroker,
        subagent_settings: SubagentSettings,
    ) -> None:
        self.session_manager = session_manager
        self.agent_session_repository = agent_session_repository
        self.agent_run_repository = agent_run_repository
        self.event_transcript_repository = event_transcript_repository
        self.input_buffer_service = input_buffer_service
        self.broker = broker
        self.subagent_settings = subagent_settings
        self.session_id: str | None = None
        self.user_id: str | None = None
        self.publish_event: PublishEventFn | None = None

    def set_session_id(self, session_id: str) -> None:
        """Inject current AgentSession ID."""
        self.session_id = session_id

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Return subagent collaboration tools."""
        self.session_id = context.session_id or self.session_id
        self.user_id = context.user_id
        self.publish_event = context.publish_event
        return ToolkitState(
            status=ToolkitStatus.ENABLED,
            tools=[
                self._spawn_agent_tool(),
                self._send_message_tool(),
                self._followup_task_tool(),
                self._wait_agent_tool(),
                self._interrupt_agent_tool(),
                self._list_agents_tool(),
            ],
        )

    async def get_static_prompt(self, context: TurnContext) -> str:
        """Return role-specific Codex V2 collaboration guidance."""
        self.session_id = context.session_id or self.session_id
        async with self.session_manager() as session:
            current = await self._current_session_agent(session)
        usage_hint = (
            _ROOT_AGENT_USAGE_HINT_TEXT
            if current.kind == SessionAgentKind.ROOT
            else _SUBAGENT_USAGE_HINT_TEXT
        )
        max_concurrency = self.subagent_settings.max_subagents + 1
        concurrency_hint = (
            f"There are {max_concurrency} available concurrency slots, meaning that "
            f"up to {max_concurrency} agents can be active at once, including you."
        )
        return "\n\n".join(
            [
                usage_hint,
                _SHARED_USAGE_HINT_TEXT,
                concurrency_hint,
                _EXPLICIT_REQUEST_ONLY_MODE_TEXT,
            ]
        )

    def _spawn_agent_tool(self) -> FunctionTool:
        async def spawn_agent(input: SpawnAgentInput) -> str:
            """Create a child subagent and return its identity."""
            if input.agent_type != "default":
                raise FunctionToolError("Only the default agent_type is supported")
            try:
                fork_selection = parse_fork_turns(input.fork_turns)
            except InvalidForkTurns as exc:
                raise FunctionToolError(str(exc)) from None
            if not input.task.strip():
                raise FunctionToolError("task is required")

            async with self.session_manager() as session:
                current = await self._current_session_agent(session)
                await self._enforce_spawn_limits(session, current)
                try:
                    child = (
                        await self.agent_session_repository.create_child_session_agent(
                            session,
                            parent_session_agent_id=current.id,
                            name=input.name,
                            agent_type=input.agent_type,
                            title=input.name,
                            last_task_message=input.task,
                        )
                    )
                except ValueError as exc:
                    raise FunctionToolError(str(exc)) from None
                child_session = await self._session_or_error(
                    session, child.agent_session_id
                )
                forked = await self._fork_events(
                    session,
                    parent_session_id=current.agent_session_id,
                    head_event_id=(
                        await self._session_or_error(session, current.agent_session_id)
                    ).model_input_head_event_id,
                    selection=fork_selection,
                )
                for event in forked:
                    await self.event_transcript_repository.append(
                        session,
                        EventCreate(
                            session_id=child.agent_session_id,
                            kind=event.kind,
                            payload=_payload_json(event),
                            model_order=event.model_order,
                        ),
                    )
                if forked:
                    await self._append_forked_history_boundary_reminder(
                        session,
                        child,
                    )
                await self._enqueue_agent_message(
                    session,
                    source=current,
                    target=child,
                    message_kind="spawn_agent",
                    content=input.task,
                    wake=True,
                )

            await self._wake_session(child_session)
            await self._publish_tree_changed(child)
            return _json(
                {
                    "agent_name": child.name,
                    "agent_path": child.path,
                    "status": "spawned",
                }
            )

        return make_tool(spawn_agent, name="spawn_agent")

    def _send_message_tool(self) -> FunctionTool:
        async def send_message(input: SendMessageInput) -> str:
            """Queue a message for a target agent without waking it."""
            if not input.message.strip():
                raise FunctionToolError("message is required")
            async with self.session_manager() as session:
                resolution = await self._resolve_target(session, input.agent_name)
                if resolution.target is None:
                    return _json(
                        {"status": "not_found", "agent_name": input.agent_name}
                    )
                await self._enqueue_agent_message(
                    session,
                    source=resolution.current,
                    target=resolution.target,
                    message_kind="send_message",
                    content=input.message,
                    wake=False,
                )
                session_agent_repo = self.agent_session_repository
                await session_agent_repo.update_session_agent_last_task_message(
                    session,
                    session_agent_id=resolution.target.id,
                    last_task_message=input.message,
                )
            await self._publish_tree_changed(resolution.target)
            return _json(
                {
                    "status": "queued",
                    "agent_name": resolution.target.name,
                    "agent_path": resolution.target.path,
                }
            )

        return make_tool(send_message, name="send_message")

    def _followup_task_tool(self) -> FunctionTool:
        async def followup_task(input: FollowupTaskInput) -> str:
            """Assign a follow-up task to an existing agent and wake it."""
            if not input.task.strip():
                raise FunctionToolError("task is required")
            async with self.session_manager() as session:
                resolution = await self._resolve_target(session, input.agent_name)
                if resolution.target is None:
                    return _json(
                        {"status": "not_found", "agent_name": input.agent_name}
                    )
                if resolution.target.kind == SessionAgentKind.ROOT:
                    raise FunctionToolError(
                        "Follow-up tasks can't target the root agent"
                    )
                target_session = await self._session_or_error(
                    session,
                    resolution.target.agent_session_id,
                )
                await self._enqueue_agent_message(
                    session,
                    source=resolution.current,
                    target=resolution.target,
                    message_kind="followup_task",
                    content=input.task,
                    wake=True,
                )
                session_agent_repo = self.agent_session_repository
                await session_agent_repo.update_session_agent_last_task_message(
                    session,
                    session_agent_id=resolution.target.id,
                    last_task_message=input.task,
                )
            await self._wake_session(target_session)
            await self._publish_tree_changed(resolution.target)
            return _json(
                {
                    "status": "assigned",
                    "agent_name": resolution.target.name,
                    "agent_path": resolution.target.path,
                }
            )

        return make_tool(followup_task, name="followup_task")

    def _wait_agent_tool(self) -> FunctionTool:
        async def wait_agent(input: WaitAgentInput) -> str:
            """Observe unread terminal child results."""
            deadline = (
                None
                if input.timeout_seconds is None
                else time.monotonic() + input.timeout_seconds
            )
            while True:
                changed_targets: list[SessionAgent] = []
                async with self.session_manager() as session:
                    current = await self._current_session_agent(session)
                    targets = await self._wait_targets(
                        session, current, input.agent_name
                    )
                    if not targets:
                        message = (
                            "not_found"
                            if input.agent_name is not None
                            else "No descendant agents to wait for."
                        )
                        return _json({"message": message, "timed_out": False})
                    latest_runs = (
                        await self.agent_run_repository.list_latest_by_session_ids(
                            session,
                            session_ids=[target.agent_session_id for target in targets],
                        )
                    )
                    messages: list[str] = []
                    running: list[str] = []
                    for target in targets:
                        run = latest_runs.get(target.agent_session_id)
                        target_session = await self.agent_session_repository.get_by_id(
                            session,
                            target.agent_session_id,
                        )
                        session_running = (
                            target_session is not None
                            and target_session.run_state == AgentSessionRunState.RUNNING
                        )
                        if run is None:
                            if session_running:
                                running.append(target.path)
                            continue
                        terminal_unread = run.status in _TERMINAL_STATUSES and (
                            target.parent_observed_run_index is None
                            or run.run_index > target.parent_observed_run_index
                        )
                        if terminal_unread:
                            text = (
                                run.terminal_result_message
                                or f"{target.path}: {run.status.value}"
                            )
                            messages.append(text)
                            repo = self.agent_session_repository
                            update_cursor = repo.update_session_agent_observation_cursor
                            updated = await update_cursor(
                                session,
                                session_agent_id=target.id,
                                parent_observed_run_index=run.run_index,
                                parent_observed_event_id=run.terminal_result_event_id,
                            )
                            changed_targets.append(updated or target)
                            continue
                        if run.status == AgentRunStatus.RUNNING or session_running:
                            running.append(target.path)
                for target in changed_targets:
                    await self._publish_tree_changed(target)
                if messages:
                    return _json({"message": "\n\n".join(messages), "timed_out": False})
                if not running:
                    return _json(
                        {"message": "No unread terminal result.", "timed_out": False}
                    )
                if deadline is None:
                    return _json(
                        {"message": "No unread terminal result.", "timed_out": False}
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return _json(
                        {
                            "message": "Still running: " + ", ".join(running),
                            "timed_out": True,
                        }
                    )
                await asyncio.sleep(min(_WAIT_AGENT_POLL_INTERVAL_SECONDS, remaining))

        return make_tool(wait_agent, name="wait_agent")

    def _interrupt_agent_tool(self) -> FunctionTool:
        async def interrupt_agent(input: InterruptAgentInput) -> str:
            """Interrupt the target agent's current run without deleting it."""
            async with self.session_manager() as session:
                resolution = await self._resolve_target(session, input.agent_name)
                if resolution.target is None:
                    return _json({"previous_status": "not_found"})
                if resolution.target.kind == SessionAgentKind.ROOT:
                    raise FunctionToolError("root is not a spawned agent")
                if resolution.target.id == resolution.current.id:
                    raise FunctionToolError(
                        "an agent cannot interrupt itself; return your result and let "
                        "the parent interrupt you if needed"
                    )
                target_session = await self._session_or_error(
                    session,
                    resolution.target.agent_session_id,
                )
                previous_status = await self._project_agent_status(
                    session, resolution.target
                )
                if target_session.run_state == AgentSessionRunState.RUNNING:
                    await self.agent_session_repository.request_stop(
                        session,
                        session_id=target_session.id,
                        stop_request_id="subagent_interrupt",
                        user_id=self.user_id,
                    )
            if target_session.run_state == AgentSessionRunState.RUNNING:
                await self.broker.send_message(
                    SessionStopSignal(
                        session_id=target_session.id, user_id=self.user_id
                    )
                )
            await self._publish_tree_changed(resolution.target)
            return _json({"previous_status": previous_status})

        return make_tool(interrupt_agent, name="interrupt_agent")

    def _list_agents_tool(self) -> FunctionTool:
        async def list_agents() -> str:
            """List agents in the current root SessionAgent tree."""
            async with self.session_manager() as session:
                current = await self._current_session_agent(session)
                tree = await self.agent_session_repository.list_session_agent_tree(
                    session,
                    root_session_agent_id=current.root_session_agent_id,
                )
                rows = []
                for agent in tree:
                    rows.append(
                        {
                            "agent_name": agent.name,
                            "agent_path": agent.path,
                            "agent_status": await self._project_agent_status(
                                session, agent
                            ),
                            "last_task_message": agent.last_task_message,
                        }
                    )
            return _json({"agents": rows})

        return make_tool(list_agents, name="list_agents")

    def _current_session_id(self) -> str:
        """Return current AgentSession ID or raise a tool-level error."""
        if self.session_id is None:
            raise FunctionToolError("Current AgentSession ID was not provided")
        return self.session_id

    async def _current_session_agent(self, session: AsyncSession) -> SessionAgent:
        current = await self.agent_session_repository.get_session_agent_by_session_id(
            session,
            self._current_session_id(),
        )
        if current is None:
            raise FunctionToolError("Current SessionAgent was not found")
        return current

    async def _resolve_target(
        self,
        session: AsyncSession,
        agent_name: str,
    ) -> _TargetResolution:
        current = await self._current_session_agent(session)
        try:
            target = await self.agent_session_repository.resolve_session_agent_path(
                session,
                current_session_agent_id=current.id,
                path=agent_name,
            )
        except ValueError:
            target = None
        return _TargetResolution(current=current, target=target)

    async def _wait_targets(
        self,
        session: AsyncSession,
        current: SessionAgent,
        agent_name: str | None,
    ) -> list[SessionAgent]:
        if agent_name is not None:
            try:
                resolved = (
                    await self.agent_session_repository.resolve_session_agent_path(
                        session,
                        current_session_agent_id=current.id,
                        path=agent_name,
                    )
                )
            except ValueError:
                return []
            if resolved is None and agent_name != current.name:
                return []
            if resolved is None or resolved.id == current.id:
                raise FunctionToolError(
                    "an agent cannot wait for itself; wait_agent only observes "
                    "descendants"
                )
            return [resolved]
        descendants = (
            await self.agent_session_repository.list_descendant_session_agents(
                session,
                session_agent_id=current.id,
                include_self=False,
            )
        )
        return descendants

    async def _enforce_spawn_limits(
        self,
        session: AsyncSession,
        current: SessionAgent,
    ) -> None:
        """Raise a tool error when spawning would exceed configured limits."""
        locked_root = await self.agent_session_repository.lock_session_agent_by_id(
            session,
            current.root_session_agent_id,
        )
        if locked_root is None:
            raise FunctionToolError("Root SessionAgent was not found")
        next_depth = _session_agent_depth(current) + 1
        max_depth = self.subagent_settings.max_depth
        if next_depth > max_depth:
            raise FunctionToolError(
                "Cannot spawn subagent: max_depth "
                f"{max_depth} would be exceeded by child depth {next_depth}."
            )

        max_subagents = self.subagent_settings.max_subagents
        tree = await self.agent_session_repository.list_session_agent_tree(
            session,
            root_session_agent_id=current.root_session_agent_id,
        )
        subagents = [
            agent for agent in tree if agent.id != current.root_session_agent_id
        ]
        sessions = await self.agent_session_repository.list_by_ids(
            session,
            agent_session_ids=[agent.agent_session_id for agent in subagents],
        )
        latest_runs = await self.agent_run_repository.list_latest_by_session_ids(
            session,
            session_ids=[agent.agent_session_id for agent in subagents],
        )
        active_count = sum(
            1
            for agent in subagents
            if _session_agent_active(
                sessions.get(agent.agent_session_id),
                latest_runs.get(agent.agent_session_id),
            )
        )
        if active_count >= max_subagents:
            raise FunctionToolError(
                "Cannot spawn subagent: max_subagents "
                f"{max_subagents} is already reached for this root session."
            )

    async def _append_forked_history_boundary_reminder(
        self,
        session: AsyncSession,
        child: SessionAgent,
    ) -> None:
        """Append the model-visible boundary after copied parent history."""
        text = dedent(
            f"""\
            The messages above are inherited conversation history from the parent
            agent. They reflect the parent agent's earlier perspective and are
            background context only.

            You are the subagent named "{child.name}".
            Your full agent path is "{child.path}".
            The next message is your current direct assignment.

            Do not treat agent identities or tool calls in the inherited history as
            your own actions. Never call wait_agent on yourself. wait_agent is only
            for observing your descendants.
            """
        )
        payload = SystemReminderPayload(text=text)
        await self.event_transcript_repository.append(
            session,
            EventCreate(
                session_id=child.agent_session_id,
                kind=EventKind.SYSTEM_REMINDER,
                payload=_JSON_OBJECT_ADAPTER.validate_python(
                    payload.model_dump(mode="json")
                ),
            ),
        )

    async def _enqueue_agent_message(
        self,
        session: AsyncSession,
        *,
        source: SessionAgent,
        target: SessionAgent,
        message_kind: Literal["spawn_agent", "send_message", "followup_task"],
        content: str,
        wake: bool,
    ) -> None:
        await self.input_buffer_service.enqueue(
            session,
            InputBufferEnqueue(
                session_id=target.agent_session_id,
                kind=InputBufferKind.AGENT_MESSAGE,
                actor_user_id=self.user_id,
                content=content,
                idempotency_key=None,
                metadata={
                    "source": "agent_mailbox",
                    "message_kind": message_kind,
                    "source_session_agent_id": source.id,
                    "source_path": source.path,
                    "target_session_agent_id": target.id,
                    "target_path": target.path,
                },
                action=None,
                attachments=[],
                file_parts=[],
            ),
        )
        mark_message_activity = (
            self.agent_session_repository.mark_session_agent_message_activity
        )
        await mark_message_activity(session, session_agent_id=source.id)
        if target.id != source.id:
            await mark_message_activity(session, session_agent_id=target.id)
        if wake:
            await self.agent_session_repository.mark_running_for_input_wakeup(
                session,
                target.agent_session_id,
            )

    async def _publish_tree_changed(self, changed: SessionAgent) -> None:
        """Publish a non-durable Subagent Tree invalidation event."""
        if self.publish_event is None:
            return
        await self.publish_event(
            SubagentTreeChanged(
                root_session_agent_id=changed.root_session_agent_id,
                changed_session_agent_id=changed.id,
            )
        )

    async def _wake_session(self, session: AgentSession) -> None:
        await self.broker.send_message(
            SessionWakeUp(
                agent_id=session.agent_id,
                session_id=session.id,
                user_id=self.user_id,
                additional_system_prompt=None,
                interface=None,
                workspace_id=session.workspace_id,
                workspace_handle=None,
            )
        )

    async def _session_or_error(
        self,
        session: AsyncSession,
        agent_session_id: str,
    ) -> AgentSession:
        agent_session = await self.agent_session_repository.get_by_id(
            session,
            agent_session_id,
        )
        if agent_session is None:
            raise FunctionToolError("AgentSession was not found")
        return agent_session

    async def _fork_events(
        self,
        session: AsyncSession,
        *,
        parent_session_id: str,
        head_event_id: str | None,
        selection: ForkTurnsSelection,
    ) -> list[Event]:
        events = await self.event_transcript_repository.list_for_model_input(
            session,
            parent_session_id,
            head_event_id=head_event_id,
        )
        selected = select_fork_events(
            events,
            selection,
            head_event_id=head_event_id,
        )
        return degrade_file_parts_for_fork(selected)

    async def _project_agent_status(
        self,
        session: AsyncSession,
        agent: SessionAgent,
    ) -> str:
        agent_session = await self.agent_session_repository.get_by_id(
            session,
            agent.agent_session_id,
        )
        if agent_session is None:
            return "not_found"
        if agent_session.run_state == AgentSessionRunState.RUNNING:
            return "running"
        latest = await self.agent_run_repository.list_latest_by_session_ids(
            session,
            session_ids=[agent.agent_session_id],
        )
        run = latest.get(agent.agent_session_id)
        if run is None:
            return "idle"
        if run.status == AgentRunStatus.COMPLETED:
            return "completed"
        if run.status == AgentRunStatus.FAILED:
            return "errored"
        if run.status in {
            AgentRunStatus.STOPPED,
            AgentRunStatus.INTERRUPTED,
            AgentRunStatus.CANCELLED,
        }:
            return "interrupted"
        return run.status.value


class SubagentToolkitProvider(ToolkitProvider[SubagentToolkitConfig]):
    """Resolve the subagent collaboration Toolkit."""

    slug = "subagent"
    name = "Subagent"
    description = "Coordinate child and nested subagents."
    system_prompt = "Use subagent tools to coordinate child agents."
    config_model = SubagentToolkitConfig

    def __init__(
        self,
        *,
        session_manager: SessionManager[AsyncSession],
        broker: SessionBroker,
        input_buffer_service: InputBufferService,
    ) -> None:
        self.session_manager = session_manager
        self.broker = broker
        self.input_buffer_service = input_buffer_service

    async def resolve(
        self,
        config: SubagentToolkitConfig,
        context: ResolveContext,
    ) -> SubagentToolkit:
        """Resolve per-session subagent collaboration tools."""
        del config
        agent = await AgentRepository().get_by_id(context.session, context.agent_id)
        subagent_settings = (
            agent.subagent_settings if agent is not None else SubagentSettings()
        )
        toolkit = SubagentToolkit(
            session_manager=self.session_manager,
            agent_session_repository=AgentSessionRepository(),
            agent_run_repository=AgentRunRepository(),
            event_transcript_repository=EventTranscriptRepository(),
            input_buffer_service=self.input_buffer_service,
            broker=self.broker,
            subagent_settings=subagent_settings,
        )
        toolkit.set_session_id(context.session_id)
        return toolkit


def _session_agent_depth(agent: SessionAgent) -> int:
    """Return depth below /root for a SessionAgent path."""
    if agent.path == "/root":
        return 0
    return len([segment for segment in agent.path.split("/") if segment]) - 1


def _session_agent_active(
    session: AgentSession | None,
    latest_run: AgentRunState | None,
) -> bool:
    """Return whether a SessionAgent should count against active capacity."""
    if session is None:
        return False
    return session.run_state == AgentSessionRunState.RUNNING or (
        latest_run is not None and latest_run.status == AgentRunStatus.RUNNING
    )


def _json(value: dict[str, object]) -> str:
    return json.dumps(value, ensure_ascii=False)


def _payload_json(event: Event) -> dict[str, JSONValue]:
    return event.payload.model_dump(mode="json", exclude_none=True)
