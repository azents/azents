"""Subagent collaboration Toolkit."""

# ruff: noqa: E501

import dataclasses
import datetime
import json
import logging
from textwrap import dedent
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from azents.broker.types import SessionBroker, SessionStopSignal, SessionWakeUp
from azents.core.agent import SelectableModelOption, SubagentSettings
from azents.core.agent_session_data import AgentSession, SessionAgent
from azents.core.enums import AgentRunStatus, AgentSessionRunState, SessionAgentKind
from azents.core.inference_profile import (
    SessionInferenceState,
    normalize_inherited_reasoning_effort,
)
from azents.core.llm_catalog import ModelReasoningEffort
from azents.core.model_execution_options import validate_execution_options
from azents.core.session_resource_authority import (
    SessionExecutionOwner,
    accepts_execution_owner,
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
from azents.engine.context.window import (
    compute_auto_compaction_threshold_tokens,
    compute_effective_context_window_tokens,
    resolve_model_input_tokens,
)
from azents.engine.events.engine_events import SubagentTreeChanged
from azents.engine.events.fork_context import (
    ForkTurnsSelection,
    InvalidForkTurns,
    degrade_file_parts_for_fork,
    parse_fork_turns,
    select_fork_events,
)
from azents.engine.run.types import FunctionTool, FunctionToolError
from azents.engine.tooling.make_tool import make_tool
from azents.repos.agent.data import Agent
from azents.repos.subagent_tool_operations import (
    SubagentToolOperationError,
    SubagentToolOperationRepository,
)
from azents.services.model_metadata import ModelMetadataService

logger = logging.getLogger(__name__)

_ROOT_AGENT_USAGE_HINT_TEXT = """You are `/root`, the primary agent in a team of agents collaborating to fulfill the user's goals.

At the start of your turn, you are the active agent.
You can spawn sub-agents to handle subtasks, and those sub-agents can spawn their own sub-agents.
All agents in the team, including the agents that you can assign tasks to, are equally intelligent and capable, and have access to almost the same set of tools, except for Azents root/user-facing capabilities that are not available in subagent mode.

You can use `spawn_agent` to create a new agent, `followup_task` to give an existing agent a new task and trigger a turn, and `send_message` to pass a message to a running agent without triggering a turn.
Child agents can also spawn their own sub-agents.
You can decide how much context you want to propagate to your sub-agents with the `fork_turns` parameter.
Use `wait` to pause until your mailbox changes or all descendants become idle.

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

_SHARED_USAGE_HINT_TEXT = """Note that collaboration tools cannot be called from inside `exec_command`. Call `spawn_agent`, `send_message`, `followup_task`, `wait`, `interrupt_agent`, and `list_agents` only as direct tool calls using the recipient shown in their tool definitions, since they are intentionally absent from `exec_command`.

All agents share the same directory. In detail:
- All agents have access to the same container and filesystem as you.
- All agents use the same current working directory.
- As a result, edits made by one agent are immediately visible to all other agents."""

_EXPLICIT_REQUEST_ONLY_MODE_TEXT = "Do not spawn sub-agents unless the user or applicable AGENTS.md/skill instructions explicitly ask for sub-agents, delegation, or parallel agent work."


class SubagentToolkitConfig(BaseModel):
    """Subagent collaboration Toolkit configuration."""


class SpawnAgentInput(BaseModel):
    """spawn_agent tool input."""

    model_config = ConfigDict(extra="forbid")

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

    model_config = ConfigDict(extra="forbid")

    agent_name: str = Field(description="Target agent path or name")
    message: str = Field(description="Message to queue for the target agent")


class FollowupTaskInput(BaseModel):
    """followup_task tool input."""

    model_config = ConfigDict(extra="forbid")

    agent_name: str = Field(description="Target agent path or name")
    task: str = Field(description="Follow-up task to assign and wake")


class InterruptAgentInput(BaseModel):
    """interrupt_agent tool input."""

    model_config = ConfigDict(extra="forbid")

    agent_name: str = Field(description="Target agent path or name")


@dataclasses.dataclass(frozen=True)
class _SpawnInferenceProfile:
    state: SessionInferenceState


class SubagentToolkit(Toolkit[SubagentToolkitConfig]):
    """Model-visible subagent collaboration tools."""

    def __init__(
        self,
        *,
        operations: SubagentToolOperationRepository,
        broker: SessionBroker,
        agent: Agent,
        subagent_settings: SubagentSettings,
    ) -> None:
        self.operations = operations
        self.broker = broker
        self.agent = agent
        self.subagent_settings = subagent_settings
        self.session_id: str | None = None
        self.publish_event: PublishEventFn | None = None
        self._execution_owner: SessionExecutionOwner | None = None

    def bind_execution_owner(self, owner: SessionExecutionOwner) -> None:
        """Bind this resolved Toolkit to one immutable Session owner."""
        session_id = self.session_id
        if session_id is None:
            raise ValueError("Subagent Toolkit Session was not initialized")
        if accepts_execution_owner(
            self._execution_owner,
            owner,
            session_id=session_id,
        ):
            self.operations = dataclasses.replace(
                self.operations,
                owner=owner,
            )
            self._execution_owner = owner

    def set_session_id(self, session_id: str) -> None:
        """Inject current AgentSession ID."""
        self.session_id = session_id

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Return subagent collaboration tools."""
        self.session_id = context.session_id or self.session_id
        self.publish_event = context.publish_event
        agent = await self.operations.get_agent(self.agent.id)
        if agent is None:
            raise FunctionToolError("Agent was not found")
        self.agent = agent
        self.subagent_settings = agent.subagent_settings
        return ToolkitState(
            status=ToolkitStatus.ENABLED,
            tools=[
                self._spawn_agent_tool(parent_run_id=context.run_id),
                self._send_message_tool(),
                self._followup_task_tool(),
                self._interrupt_agent_tool(),
                self._list_agents_tool(),
            ],
        )

    async def get_static_prompt(self, context: TurnContext) -> str:
        """Return role-specific Codex V2 collaboration guidance."""
        self.session_id = context.session_id or self.session_id
        current = await self.operations.get_current_session_agent(
            self._current_session_id()
        )
        if current is None:
            raise FunctionToolError("Current SessionAgent was not found")
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

    @staticmethod
    def _subagent_override_options(agent: Agent) -> list[SelectableModelOption]:
        """Return Agent options eligible for explicit subagent selection."""
        return [
            option
            for option in agent.selectable_model_options
            if option.subagent_enabled
        ]

    def _spawn_agent_description(self) -> str:
        """Build label-only spawn guidance from the current Agent snapshot."""
        target_lines: list[str] = []
        for option in self._subagent_override_options(self.agent):
            levels = option.candidates[
                0
            ].model_selection.normalized_capabilities.configurable_reasoning_efforts()
            efforts = ", ".join(level.value for level in levels)
            effort_text = efforts if efforts else "none"
            target_line = f"- `{option.label}` Reasoning efforts: {effort_text}."
            if option.subagent_guidance is not None:
                guidance_lines = "\n  ".join(option.subagent_guidance.splitlines())
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

            try:
                preparation = await self.operations.prepare_spawn(
                    session_id=self._current_session_id(),
                    agent_id=self.agent.id,
                    parent_run_id=parent_run_id,
                    settings=self.subagent_settings,
                )
            except SubagentToolOperationError as exc:
                raise FunctionToolError(str(exc)) from None
            parent_state = preparation.parent_session.inference_state
            if parent_state is None:
                raise FunctionToolError(
                    "Current Session has no prepared inference state"
                )
            self.agent = preparation.agent
            self.subagent_settings = preparation.agent.subagent_settings
            profile = await self._derive_spawn_inference_profile(
                agent=preparation.agent,
                parent_state=parent_state,
                fork_selection=fork_selection,
                model_target_label=input.model_target_label,
                reasoning_effort=input.reasoning_effort,
            )
            selected = select_fork_events(
                preparation.events,
                fork_selection,
                head_event_id=preparation.parent_session.model_input_head_event_id,
            )
            forked = degrade_file_parts_for_fork(selected)
            try:
                result = await self.operations.spawn(
                    session_id=self._current_session_id(),
                    parent_run_id=parent_run_id,
                    settings=self.subagent_settings,
                    name=input.name,
                    agent_type=input.agent_type,
                    task=input.task,
                    profile=profile.state,
                    forked_events=forked,
                )
            except SubagentToolOperationError as exc:
                raise FunctionToolError(str(exc)) from None

            await self._wake_session(result.child_session)
            await self._publish_tree_changed(result.child)
            return _json(
                {
                    "agent_name": result.child.name,
                    "agent_path": result.child.path,
                    "status": "spawned",
                }
            )

        return make_tool(
            spawn_agent,
            name="spawn_agent",
            description=self._spawn_agent_description(),
        )

    async def _derive_spawn_inference_profile(
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
            selection = option.candidates[0].model_selection
            settings = option.candidates[0].settings

        supported_efforts = (
            selection.normalized_capabilities.configurable_reasoning_efforts()
        )
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

        enabled_execution_options = (
            parent_state.enabled_execution_options
            if model_target_label is None
            else validate_execution_options(
                provider=selection.provider,
                supported=selection.supported_execution_options,
                enabled=[
                    option
                    for option in parent_state.enabled_execution_options
                    if option in selection.supported_execution_options
                ],
            )
        )

        if model_target_label is None:
            effective_context_window_tokens = (
                parent_state.effective_context_window_tokens
            )
            effective_auto_compaction_threshold_tokens = (
                parent_state.effective_auto_compaction_threshold_tokens
            )
        else:
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
            lightweight = lightweight_option.candidates[0].model_selection
            requests = ModelMetadataService.context_requests([selection, lightweight])
            source_snapshot = (
                None
                if not requests
                else await self.operations.load_model_context(requests=requests)
            )
            compaction_input_tokens = resolve_model_input_tokens(
                lightweight.normalized_capabilities.context_window.default_input_tokens,
                lightweight.normalized_capabilities.context_window.max_input_tokens,
                ModelMetadataService.maximum_input_tokens(
                    source_snapshot,
                    provider=lightweight.provider,
                    model_identifier=lightweight.model_identifier,
                ),
                lightweight_option.candidates[0].settings.context_window_tokens,
            )
            main_input_tokens = resolve_model_input_tokens(
                selection.normalized_capabilities.context_window.default_input_tokens,
                selection.normalized_capabilities.context_window.max_input_tokens,
                ModelMetadataService.maximum_input_tokens(
                    source_snapshot,
                    provider=selection.provider,
                    model_identifier=selection.model_identifier,
                ),
                settings.context_window_tokens,
            )
            context_window = compute_effective_context_window_tokens(
                main_max_input_tokens=main_input_tokens.effective_input_tokens,
                compaction_max_input_tokens=(
                    compaction_input_tokens.effective_input_tokens
                ),
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
                enabled_execution_options=enabled_execution_options,
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
            try:
                result = await self.operations.send_message(
                    session_id=self._current_session_id(),
                    agent_name=input.agent_name,
                    content=input.message,
                )
            except SubagentToolOperationError as exc:
                raise FunctionToolError(str(exc)) from None
            target = result.target
            if target is None:
                return _json({"status": "not_found", "agent_name": input.agent_name})
            await self.broker.notify_mailbox_activity(target.agent_session_id)
            await self._publish_tree_changed(target)
            return _json(
                {
                    "status": "queued",
                    "agent_name": target.name,
                    "agent_path": target.path,
                }
            )

        return make_tool(send_message, name="send_message")

    def _followup_task_tool(self) -> FunctionTool:
        async def followup_task(input: FollowupTaskInput) -> str:
            """Assign a follow-up task to an existing agent and wake it."""
            if not input.task.strip():
                raise FunctionToolError("task is required")
            try:
                result = await self.operations.followup_task(
                    session_id=self._current_session_id(),
                    agent_name=input.agent_name,
                    content=input.task,
                    max_subagents=self.subagent_settings.max_subagents,
                )
            except SubagentToolOperationError as exc:
                raise FunctionToolError(str(exc)) from None
            target = result.target
            if target is None:
                return _json({"status": "not_found", "agent_name": input.agent_name})
            target_session = result.target_session
            if target_session is None:
                raise RuntimeError("Follow-up target Session is missing.")
            await self._wake_session(target_session)
            await self._publish_tree_changed(target)
            return _json(
                {
                    "status": "assigned",
                    "agent_name": target.name,
                    "agent_path": target.path,
                }
            )

        return make_tool(followup_task, name="followup_task")

    def _interrupt_agent_tool(self) -> FunctionTool:
        async def interrupt_agent(input: InterruptAgentInput) -> str:
            """Interrupt the target agent's current run without deleting it."""
            try:
                result = await self.operations.interrupt(
                    session_id=self._current_session_id(),
                    agent_name=input.agent_name,
                )
            except SubagentToolOperationError as exc:
                raise FunctionToolError(str(exc)) from None
            target = result.target
            if target is None:
                return _json({"previous_status": "not_found"})
            target_session = result.target_session
            if target_session is None or result.previous_status is None:
                raise RuntimeError("Interrupt target projection is incomplete.")
            if result.signal_stop:
                await self.broker.send_message(
                    SessionStopSignal(session_id=target_session.id)
                )
            await self._publish_tree_changed(target)
            return _json({"previous_status": result.previous_status})

        return make_tool(interrupt_agent, name="interrupt_agent")

    def _list_agents_tool(self) -> FunctionTool:
        async def list_agents() -> str:
            """List bounded agents in the current root SessionAgent tree."""
            projection = await self.operations.list_agents(
                session_id=self._current_session_id(),
                configured_capacity=self.subagent_settings.max_subagents,
            )
            if projection is None:
                raise FunctionToolError("Current SessionAgent was not found")
            logger.debug(
                "Projected bounded subagent coordination list",
                extra={
                    "configured_capacity": projection.configured_capacity,
                    "required_count": projection.required_count,
                    "selected_inactive_count": projection.selected_inactive_count,
                    "omitted_inactive_count": projection.omitted_inactive_count,
                    "emitted_count": len(projection.rows),
                    "capacity_converging": (
                        projection.required_count > projection.configured_capacity
                    ),
                },
            )
            return _json(
                {
                    "agents": [
                        {
                            "agent_name": row.path,
                            "agent_status": _coordination_status(
                                row.session_run_state,
                                row.latest_run_status,
                            ),
                        }
                        for row in projection.rows
                    ]
                }
            )

        return make_tool(list_agents, name="list_agents")

    def _current_session_id(self) -> str:
        """Return current AgentSession ID or raise a tool-level error."""
        if self.session_id is None:
            raise FunctionToolError("Current AgentSession ID was not provided")
        return self.session_id

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
        await self.broker.send_message(SessionWakeUp(session_id=session.id))


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
        operations: SubagentToolOperationRepository,
        broker: SessionBroker,
    ) -> None:
        self.operations = operations
        self.broker = broker

    async def resolve(
        self,
        config: SubagentToolkitConfig,
        context: ResolveContext,
    ) -> SubagentToolkit:
        """Resolve per-session subagent collaboration tools."""
        del config
        agent = await self.operations.get_agent(context.agent_id)
        if agent is None:
            raise ValueError("Agent not found while resolving subagent Toolkit")
        subagent_settings = agent.subagent_settings
        toolkit = SubagentToolkit(
            operations=self.operations,
            broker=self.broker,
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
    return normalize_inherited_reasoning_effort(baseline, supported)


def _coordination_status(
    session_run_state: AgentSessionRunState,
    latest_run_status: AgentRunStatus | None,
) -> str:
    """Project one bounded model-facing coordination status."""
    if session_run_state == AgentSessionRunState.RUNNING:
        return "running"
    if latest_run_status is None:
        return "idle"
    if latest_run_status == AgentRunStatus.COMPLETED:
        return "completed"
    if latest_run_status == AgentRunStatus.FAILED:
        return "errored"
    if latest_run_status in {
        AgentRunStatus.STOPPED,
        AgentRunStatus.INTERRUPTED,
        AgentRunStatus.CANCELLED,
    }:
        return "interrupted"
    return latest_run_status.value


def _json(value: dict[str, object]) -> str:
    return json.dumps(value, ensure_ascii=False)
