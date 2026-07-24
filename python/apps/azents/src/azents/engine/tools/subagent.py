"""Subagent collaboration Toolkit."""

# ruff: noqa: E501

import asyncio
import dataclasses
import datetime
import json
import time
from textwrap import dedent
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.types import SessionBroker, SessionStopSignal, SessionWakeUp
from azents.core.agent import SelectableModelOption, SubagentSettings
from azents.core.enums import (
    AgentRunStatus,
    AgentSessionRunState,
    EventKind,
    SessionAgentKind,
)
from azents.core.inference_profile import SessionInferenceState
from azents.core.llm_catalog import ModelReasoningEffort
from azents.core.llm_mapping import to_runtime_model
from azents.core.tools import (
    PublishEventFn,
    ResolveContext,
    Toolkit,
    ToolkitProvider,
    ToolkitState,
    ToolkitStatus,
    TurnContext,
)
from azents.engine.context.window import (
    compute_auto_compaction_threshold_tokens,
    compute_effective_context_window_tokens,
    get_max_input_tokens,
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
from azents.repos.agent.data import Agent
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSession, SessionAgent
from azents.services.agent_mailbox import AgentMailboxService
from azents.services.input_buffer import InputBufferService
from azents.services.subagent_terminal_result import SubagentTerminalResultService

_ROOT_AGENT_USAGE_HINT_TEXT = """You are `/root`, the primary agent in a team of agents collaborating to fulfill the user's goals.

At the start of your turn, you are the active agent.
You can spawn sub-agents to handle subtasks, and those sub-agents can spawn their own sub-agents.
All agents in the team, including the agents that you can assign tasks to, are equally intelligent and capable, and have access to almost the same set of tools, except for Azents root/user-facing capabilities that are not available in subagent mode.

You can use `spawn_agent` to create a new agent, `followup_task` to give an existing agent a new task and trigger a turn, and `send_message` to pass a message to a running agent without triggering a turn.
Child agents can also spawn their own sub-agents.
You can decide how much context you want to propagate to your sub-agents with the `fork_turns` parameter.
Use `wait_agent` to pause until your mailbox changes or all descendants become idle.

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

When you provide a final response, that content is queued in your direct parent's mailbox as a terminal result.

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
    model_target_label: str | None = Field(
        default=None,
        description=(
            "Model target label override for the new agent. Omit unless an explicit "
            "override is needed. Full-history forks inherit the parent Run profile."
        ),
    )
    reasoning_effort: ModelReasoningEffort | None = Field(
        default=None,
        description=(
            "Reasoning effort override for the new agent. Omit to inherit or "
            "normalize from the parent Run's effective effort. Full-history forks "
            "inherit the parent Run profile."
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

    model_config = ConfigDict(extra="forbid")

    timeout_seconds: int = Field(
        default=30,
        ge=0,
        le=600,
        description="Maximum mailbox activity wait in seconds. Defaults to 30.",
    )


class InterruptAgentInput(BaseModel):
    """interrupt_agent tool input."""

    agent_name: str = Field(description="Target agent path or name")


_JSON_OBJECT_ADAPTER = TypeAdapter[dict[str, JSONValue]](dict[str, JSONValue])

_WAIT_AGENT_POLL_INTERVAL_SECONDS = 0.1


@dataclasses.dataclass(frozen=True)
class _TargetResolution:
    current: SessionAgent
    target: SessionAgent | None


@dataclasses.dataclass(frozen=True)
class _SpawnInferenceProfile:
    state: SessionInferenceState


@dataclasses.dataclass(frozen=True)
class _WaitObservation:
    mailbox_updated: bool
    descendant_count: int
    active_paths: tuple[str, ...]


class SubagentToolkit(Toolkit[SubagentToolkitConfig]):
    """Model-visible subagent collaboration tools."""

    def __init__(
        self,
        *,
        session_manager: SessionManager[AsyncSession],
        agent_session_repository: AgentSessionRepository,
        agent_run_repository: AgentRunRepository,
        event_transcript_repository: EventTranscriptRepository,
        agent_mailbox_service: AgentMailboxService,
        input_buffer_service: InputBufferService,
        subagent_terminal_result_service: SubagentTerminalResultService,
        broker: SessionBroker,
        agent_repository: AgentRepository,
        agent: Agent,
        subagent_settings: SubagentSettings,
    ) -> None:
        self.session_manager = session_manager
        self.agent_session_repository = agent_session_repository
        self.agent_run_repository = agent_run_repository
        self.event_transcript_repository = event_transcript_repository
        self.agent_mailbox_service = agent_mailbox_service
        self.input_buffer_service = input_buffer_service
        self.subagent_terminal_result_service = subagent_terminal_result_service
        self.broker = broker
        self.agent_repository = agent_repository
        self.agent = agent
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
        async with self.session_manager() as session:
            self.agent = await self._current_agent(session)
        return ToolkitState(
            status=ToolkitStatus.ENABLED,
            tools=[
                self._spawn_agent_tool(parent_run_id=context.run_id),
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

    async def _current_agent(self, session: AsyncSession) -> Agent:
        """Load the current owning Agent policy snapshot."""
        agent = await self.agent_repository.get_by_id(session, self.agent.id)
        if agent is None:
            raise FunctionToolError("Agent was not found")
        return agent

    @staticmethod
    def _subagent_override_options(agent: Agent) -> list[SelectableModelOption]:
        """Return Agent options eligible for explicit subagent selection."""
        return [
            option
            for option in agent.selectable_model_options
            if option.settings.subagent_enabled
        ]

    def _spawn_agent_description(self) -> str:
        """Build label-only spawn guidance from the current Agent snapshot."""
        target_lines: list[str] = []
        for option in self._subagent_override_options(self.agent):
            levels = (
                option.model_selection.normalized_capabilities.reasoning.effort_levels
            )
            efforts = ", ".join(level.value for level in levels)
            effort_text = efforts if efforts else "none"
            target_line = f"- `{option.label}` Reasoning efforts: {effort_text}."
            if option.settings.subagent_guidance is not None:
                guidance_lines = "\n  ".join(
                    option.settings.subagent_guidance.splitlines()
                )
                target_line = f"{target_line}\n  Guidance: {guidance_lines}"
            target_lines.append(target_line)
        if target_lines:
            targets = "\n".join(target_lines)
        else:
            targets = (
                "No explicit model target overrides are available. "
                "Omit `model_target_label` to inherit the parent Run profile."
            )
        guidance = dedent(
            """\
            Create a child subagent for a concrete, bounded task that can run
            independently and return its identity.

            Spawned agents inherit the current parent Run's model target by default.
            Omit `model_target_label` to use that preferred default; set
            `model_target_label` only when an explicit override is needed.

            Available model target overrides
            (optional; inherited parent Run target is preferred):
            """
        )
        return f"{guidance}{targets}"

    def _spawn_agent_tool(self, *, parent_run_id: str) -> FunctionTool:
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
                parent_run = await self._validated_spawn_parent_run(
                    session,
                    current=current,
                    parent_run_id=parent_run_id,
                )
                parent_session = await self._session_or_error(
                    session, current.agent_session_id
                )
                if parent_session.inference_state is None:
                    raise FunctionToolError(
                        "Current Session has no prepared inference state"
                    )
                current_agent = await self._current_agent(session)
                profile = self._derive_spawn_inference_profile(
                    agent=current_agent,
                    parent_state=parent_session.inference_state,
                    fork_selection=fork_selection,
                    model_target_label=input.model_target_label,
                    reasoning_effort=input.reasoning_effort,
                )
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
                await self.agent_run_repository.create_pending(
                    session,
                    session_id=child.agent_session_id,
                    parent_agent_run_id=parent_run.id,
                )
                await self.agent_session_repository.set_inference_state(
                    session,
                    session_id=child.agent_session_id,
                    inference_state=profile.state,
                )
                forked = await self._fork_events(
                    session,
                    parent_session_id=current.agent_session_id,
                    head_event_id=parent_session.model_input_head_event_id,
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
                await self.agent_mailbox_service.enqueue_spawn_assignment(
                    session,
                    source=current,
                    target=child,
                    content=input.task,
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

        return make_tool(
            spawn_agent,
            name="spawn_agent",
            description=self._spawn_agent_description(),
        )

    def _derive_spawn_inference_profile(
        self,
        *,
        agent: Agent,
        parent_state: SessionInferenceState,
        fork_selection: ForkTurnsSelection,
        model_target_label: str | None,
        reasoning_effort: ModelReasoningEffort | None,
    ) -> _SpawnInferenceProfile:
        """Validate and derive the child Session inference state."""
        override_requested = (
            model_target_label is not None or reasoning_effort is not None
        )
        if override_requested and fork_selection.mode == "all":
            raise FunctionToolError(
                "Inference profile overrides require fork_turns='none' or a "
                "positive bounded count; full-history forks inherit the parent "
                "Session inference state"
            )
        if not override_requested:
            return _SpawnInferenceProfile(state=parent_state)

        requested_label = model_target_label or parent_state.model_target_label
        if model_target_label is None:
            selection = parent_state.model_selection
            settings = parent_state.model_settings
        else:
            option = next(
                (
                    option
                    for option in self._subagent_override_options(agent)
                    if option.label == model_target_label
                ),
                None,
            )
            if option is None:
                raise FunctionToolError(
                    f"Model target label '{model_target_label}' is not available "
                    "for explicit subagent override"
                )
            selection = option.model_selection
            settings = option.settings

        supported_efforts = selection.normalized_capabilities.reasoning.effort_levels
        if reasoning_effort is not None:
            if reasoning_effort not in supported_efforts:
                raise FunctionToolError(
                    f"Reasoning effort '{reasoning_effort.value}' is not supported "
                    f"by model target label '{requested_label}'"
                )
            resolved_effort = reasoning_effort
        elif model_target_label is not None:
            resolved_effort = normalize_spawn_reasoning_effort(
                parent_state.reasoning_effort,
                supported_efforts,
            )
        else:
            resolved_effort = parent_state.reasoning_effort

        if model_target_label is None:
            effective_context_window_tokens = (
                parent_state.effective_context_window_tokens
            )
            effective_auto_compaction_threshold_tokens = (
                parent_state.effective_auto_compaction_threshold_tokens
            )
        else:
            main_model = to_runtime_model(
                selection.provider,
                selection.model_identifier,
            )
            lightweight_option = next(
                (
                    option
                    for option in agent.selectable_model_options
                    if option.label == agent.lightweight_model_label
                ),
                None,
            )
            if lightweight_option is None:
                raise FunctionToolError("Agent lightweight model target was not found")
            lightweight = lightweight_option.model_selection
            lightweight_model = to_runtime_model(
                lightweight.provider,
                lightweight.model_identifier,
            )
            compaction_max_input_tokens = get_max_input_tokens(
                lightweight.normalized_capabilities.context_window.max_input_tokens,
                lightweight_model,
            )
            if lightweight_option.settings.context_window_tokens is not None:
                compaction_max_input_tokens = min(
                    compaction_max_input_tokens,
                    lightweight_option.settings.context_window_tokens,
                )
            context_window = compute_effective_context_window_tokens(
                main_max_input_tokens=get_max_input_tokens(
                    selection.normalized_capabilities.context_window.max_input_tokens,
                    main_model,
                ),
                compaction_max_input_tokens=compaction_max_input_tokens,
                context_window_tokens=settings.context_window_tokens,
            )
            effective_context_window_tokens = context_window.effective_max_input_tokens
            effective_auto_compaction_threshold_tokens = (
                compute_auto_compaction_threshold_tokens(
                    effective_context_window_tokens
                )
            )

        return _SpawnInferenceProfile(
            state=SessionInferenceState(
                model_target_label=requested_label,
                model_selection=selection,
                model_settings=settings,
                reasoning_effort=resolved_effort,
                effective_context_window_tokens=effective_context_window_tokens,
                effective_auto_compaction_threshold_tokens=(
                    effective_auto_compaction_threshold_tokens
                ),
                resolved_at=datetime.datetime.now(datetime.UTC),
            )
        )

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
                await self.agent_mailbox_service.enqueue_message(
                    session,
                    source=resolution.current,
                    target=resolution.target,
                    content=input.message,
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
                await self._enforce_followup_limit(
                    session,
                    current=resolution.current,
                    target=resolution.target,
                )
                target_session = await self._session_or_error(
                    session,
                    resolution.target.agent_session_id,
                )
                await self.agent_mailbox_service.enqueue_followup_task(
                    session,
                    source=resolution.current,
                    target=resolution.target,
                    content=input.task,
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
            """Wait for current mailbox activity or descendant idleness."""
            return await self._wait_agent(input.timeout_seconds)

        return make_tool(wait_agent, name="wait_agent")

    async def _wait_agent(self, timeout_seconds: int) -> str:
        """Poll mailbox activity with descendant-idle fallback."""
        current_session_id = self._current_session_id()
        deadline = time.monotonic() + timeout_seconds
        while True:
            await self.subagent_terminal_result_service.deliver_pending_for_parent_children(
                current_session_id,
                repair_source="parent_wait",
            )
            observation = await self._observe_wait_state()
            immediate = self._wait_observation_result(observation)
            if immediate is not None:
                if observation.mailbox_updated or observation.descendant_count == 0:
                    return immediate
                await self.subagent_terminal_result_service.deliver_pending_for_parent_children(
                    current_session_id,
                    repair_source="parent_wait",
                )
                final = await self._observe_wait_state()
                final_result = self._wait_observation_result(final)
                if final_result is not None:
                    return final_result
                observation = final

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                await self.subagent_terminal_result_service.deliver_pending_for_parent_children(
                    current_session_id,
                    repair_source="parent_wait",
                )
                final = await self._observe_wait_state()
                final_result = self._wait_observation_result(final)
                if final_result is not None:
                    return final_result
                return _json(
                    {
                        "message": "Wait timed out; active descendants: "
                        + ", ".join(final.active_paths),
                        "timed_out": True,
                    }
                )
            await asyncio.sleep(min(_WAIT_AGENT_POLL_INTERVAL_SECONDS, remaining))

    async def _observe_wait_state(self) -> _WaitObservation:
        """Read current mailbox state and descendant activity."""
        current_session_id = self._current_session_id()
        mailbox_updated = await self.input_buffer_service.has_pending_agent_messages(
            current_session_id
        )
        async with self.session_manager() as session:
            current = await self._current_session_agent(session)
            descendants = (
                await self.agent_session_repository.list_descendant_session_agents(
                    session,
                    session_agent_id=current.id,
                    include_self=False,
                )
            )
            session_ids = [agent.agent_session_id for agent in descendants]
            sessions = await self.agent_session_repository.list_by_ids(
                session,
                agent_session_ids=session_ids,
            )
            latest_runs = await self.agent_run_repository.list_latest_by_session_ids(
                session,
                session_ids=session_ids,
            )
        active_paths: list[str] = []
        for descendant in descendants:
            session = sessions.get(descendant.agent_session_id)
            latest_run = latest_runs.get(descendant.agent_session_id)
            if _session_agent_active(session, latest_run) or (
                await self.input_buffer_service.has_pending_wake_session_input_buffers(
                    descendant.agent_session_id
                )
            ):
                active_paths.append(descendant.path)
        return _WaitObservation(
            mailbox_updated=mailbox_updated,
            descendant_count=len(descendants),
            active_paths=tuple(active_paths),
        )

    @staticmethod
    def _wait_observation_result(observation: _WaitObservation) -> str | None:
        """Return a completed wait result when observation is terminal."""
        if observation.mailbox_updated:
            return _json({"message": "Mailbox updated.", "timed_out": False})
        if observation.descendant_count == 0:
            return _json(
                {"message": "No descendant agents to wait for.", "timed_out": False}
            )
        if not observation.active_paths:
            return _json(
                {"message": "All descendant agents are idle.", "timed_out": False}
            )
        return None

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
                locked_root = (
                    await self.agent_session_repository.lock_session_agent_by_id(
                        session,
                        resolution.current.root_session_agent_id,
                    )
                )
                if locked_root is None:
                    raise FunctionToolError("Root SessionAgent was not found")
                target_session = await self.agent_session_repository.lock_by_id(
                    session,
                    resolution.target.agent_session_id,
                )
                if target_session is None:
                    raise FunctionToolError("AgentSession was not found")
                previous_status = await self._project_agent_status(
                    session, resolution.target
                )
                if target_session.run_state == AgentSessionRunState.RUNNING:
                    await self.agent_session_repository.request_stop(
                        session,
                        session_id=target_session.id,
                        stop_request_id="subagent_interrupt",
                        stop_requester_user_id=None,
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

    async def _validated_spawn_parent_run(
        self,
        session: AsyncSession,
        *,
        current: SessionAgent,
        parent_run_id: str,
    ) -> AgentRunState:
        """Load and validate the exact run invoking ``spawn_agent``."""
        parent_run = await self.agent_run_repository.get_by_id(
            session,
            parent_run_id,
        )
        if parent_run is None or parent_run.session_id != current.agent_session_id:
            raise FunctionToolError("Current AgentRun was not found")
        if parent_run.status != AgentRunStatus.RUNNING:
            raise FunctionToolError("Current AgentRun is not running")
        return parent_run

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

    async def _enforce_spawn_limits(
        self,
        session: AsyncSession,
        current: SessionAgent,
    ) -> None:
        """Raise a tool error when spawning would exceed configured limits."""
        next_depth = _session_agent_depth(current) + 1
        max_depth = self.subagent_settings.max_depth
        if next_depth > max_depth:
            raise FunctionToolError(
                "Cannot spawn subagent: max_depth "
                f"{max_depth} would be exceeded by child depth {next_depth}."
            )

        active_subagent_ids = await self._lock_and_list_active_subagent_ids(
            session,
            current=current,
        )
        max_subagents = self.subagent_settings.max_subagents
        if len(active_subagent_ids) >= max_subagents:
            raise FunctionToolError(
                "Cannot spawn subagent: max_subagents "
                f"{max_subagents} is already reached for this root session."
            )

    async def _enforce_followup_limit(
        self,
        session: AsyncSession,
        *,
        current: SessionAgent,
        target: SessionAgent,
    ) -> None:
        """Reject a follow-up that would activate a new over-capacity child."""
        active_subagent_ids = await self._lock_and_list_active_subagent_ids(
            session,
            current=current,
        )
        max_subagents = self.subagent_settings.max_subagents
        if (
            target.id not in active_subagent_ids
            and len(active_subagent_ids) >= max_subagents
        ):
            raise FunctionToolError(
                "Cannot assign follow-up task: max_subagents "
                f"{max_subagents} is already reached for this root session."
            )

    async def _lock_and_list_active_subagent_ids(
        self,
        session: AsyncSession,
        *,
        current: SessionAgent,
    ) -> set[str]:
        """Lock the root tree and return active child SessionAgent IDs."""
        locked_root = await self.agent_session_repository.lock_session_agent_by_id(
            session,
            current.root_session_agent_id,
        )
        if locked_root is None:
            raise FunctionToolError("Root SessionAgent was not found")
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
        return {
            agent.id
            for agent in subagents
            if _session_agent_active(
                sessions.get(agent.agent_session_id),
                latest_runs.get(agent.agent_session_id),
            )
        }

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
        agent_repository: AgentRepository,
    ) -> None:
        self.session_manager = session_manager
        self.broker = broker
        self.input_buffer_service = input_buffer_service
        self.agent_repository = agent_repository

    async def resolve(
        self,
        config: SubagentToolkitConfig,
        context: ResolveContext,
    ) -> SubagentToolkit:
        """Resolve per-session subagent collaboration tools."""
        del config
        async with self.session_manager() as session:
            agent = await self.agent_repository.get_by_id(session, context.agent_id)
        if agent is None:
            raise ValueError("Agent not found while resolving subagent Toolkit")
        subagent_settings = agent.subagent_settings
        agent_session_repository = AgentSessionRepository()
        agent_run_repository = AgentRunRepository()
        agent_mailbox_service = AgentMailboxService(
            input_buffer_service=self.input_buffer_service,
            agent_session_repository=agent_session_repository,
        )
        toolkit = SubagentToolkit(
            session_manager=self.session_manager,
            agent_session_repository=agent_session_repository,
            agent_run_repository=agent_run_repository,
            event_transcript_repository=EventTranscriptRepository(),
            agent_mailbox_service=agent_mailbox_service,
            input_buffer_service=self.input_buffer_service,
            subagent_terminal_result_service=SubagentTerminalResultService(
                session_manager=self.session_manager,
                agent_run_repository=agent_run_repository,
                agent_session_repository=agent_session_repository,
                agent_mailbox_service=agent_mailbox_service,
            ),
            broker=self.broker,
            agent_repository=self.agent_repository,
            agent=agent,
            subagent_settings=subagent_settings,
        )
        toolkit.set_session_id(context.session_id)
        return toolkit


def normalize_spawn_reasoning_effort(
    baseline: ModelReasoningEffort | None,
    supported: list[ModelReasoningEffort],
) -> ModelReasoningEffort | None:
    """Normalize an inherited effort against a target's canonical levels."""
    if not supported:
        return None
    effective_baseline = baseline or ModelReasoningEffort.MEDIUM
    if effective_baseline in supported:
        return effective_baseline
    ordering = list(ModelReasoningEffort)
    baseline_index = ordering.index(effective_baseline)
    lower = [level for level in supported if ordering.index(level) < baseline_index]
    if lower:
        return max(lower, key=ordering.index)
    return min(supported, key=ordering.index)


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
        latest_run is not None
        and latest_run.status in {AgentRunStatus.PENDING, AgentRunStatus.RUNNING}
    )


def _json(value: dict[str, object]) -> str:
    return json.dumps(value, ensure_ascii=False)


def _payload_json(event: Event) -> dict[str, JSONValue]:
    return event.payload.model_dump(mode="json", exclude_none=True)
