"""Root-only Scheduled Task management and execution Toolkit."""

import datetime
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.external_channel_file import (
    MAX_EXTERNAL_CHANNEL_FILES,
    ExternalChannelOutboundFileManifest,
)
from azents.core.tools import (
    ResolveContext,
    Toolkit,
    ToolkitProvider,
    ToolkitState,
    ToolkitStatus,
    TurnContext,
)
from azents.engine.events.types import ScheduledTaskResultPayload
from azents.engine.hooks.types import (
    CompactionSummaryHookContext,
    CompactionSummaryReplace,
    RuntimeHooks,
    ScheduledTaskSessionContinuationInput,
    SessionIdleHookContext,
    SessionIdleResult,
)
from azents.engine.run.types import FunctionTool, FunctionToolError, FunctionToolResult
from azents.engine.tooling.make_tool import make_tool
from azents.engine.tools.runtime_instruction_context import (
    RuntimeInstructionContextStore,
)
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.scheduled_task.data import (
    MAX_SCHEDULED_TASK_OBJECTIVE_LENGTH,
    ScheduledTask,
)
from azents.repos.scheduled_task_cycle import ScheduledTaskCycleRepository
from azents.repos.scheduled_task_cycle.data import (
    ScheduledTaskCycleRecord,
    ScheduledTaskCycleState,
)
from azents.services.external_channel.file_transfer import (
    ExternalChannelFileTransferService,
)
from azents.services.external_channel.provider_effect import ProviderEffectOutcome
from azents.services.scheduled_task.channel import ScheduledTaskChannelService
from azents.services.scheduled_task.rendering import (
    render_scheduled_task_compaction_snapshot,
    render_scheduled_task_cycle_guidance,
    render_scheduled_task_runtime_message,
    replace_scheduled_compaction_snapshot,
)
from azents.services.scheduled_task.service import ScheduledTaskService
from azents.services.scheduled_task.terminal import ScheduledTaskTerminalService

_ADD_DESCRIPTION = "Create one Scheduled Task in the current Session."
_LIST_DESCRIPTION = "List active Scheduled Tasks in the current Session."
_DELETE_DESCRIPTION = "Delete one exact Scheduled Task by task_id."
_SUBMIT_DESCRIPTION = (
    "Commit the finished or failed result of the current Scheduled Task cycle. "
    "For a channel-bound cycle, the result message and files are delivered to the "
    "exact same bound conversation used by channel_action; this does not select or "
    "send to another Slack or Discord channel. Session-only cycles do not publish "
    "externally and do not accept files."
)


class ScheduledToolkitConfig(BaseModel):
    """Code-owned Scheduled Toolkit release configuration."""

    implementation_revision: Literal[1] = 1


class AddScheduledTaskInput(BaseModel):
    """add_scheduled_task tool input."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=120)
    objective: str = Field(
        min_length=1,
        max_length=MAX_SCHEDULED_TASK_OBJECTIVE_LENGTH,
    )
    at: str | None = Field(
        description=(
            "One-time timezone-bearing RFC 3339 timestamp. Set cron and timezone "
            "to null when at is supplied; set at to null for recurring schedules."
        )
    )
    cron: str | None = Field(
        description=(
            "Recurring standard five-field cron expression. Requires an IANA "
            "timezone and requires at to be null."
        )
    )
    timezone: str | None = Field(
        description=(
            "IANA timezone for a recurring cron schedule only. Must be null when "
            "at is supplied."
        )
    )
    channel_id: str | None = Field(min_length=1, max_length=256)


class DeleteScheduledTaskInput(BaseModel):
    """delete_scheduled_task tool input."""

    model_config = ConfigDict(str_strip_whitespace=True)

    task_id: str = Field(min_length=32, max_length=32)


class SubmitScheduledTaskResultInput(BaseModel):
    """submit_scheduled_task_result tool input."""

    model_config = ConfigDict(str_strip_whitespace=True)

    status: Literal["finished", "failed"]
    result: str = Field(min_length=1, max_length=50_000)
    files: list[str] | None = Field(
        min_length=1,
        max_length=MAX_EXTERNAL_CHANNEL_FILES,
        description=(
            "File source paths published with the terminal result to the same bound "
            "conversation used by channel_action. Each item must be either an "
            "absolute POSIX Runtime path beginning with `/` or an authorized "
            "`exchange://{object_key}` URI. Relative paths and other URI schemes, "
            "including `artifact://` and `azents://`, are unsupported. Set null for "
            "Session-only cycles or when no files are needed."
        ),
    )


class ScheduledToolkit(Toolkit[ScheduledToolkitConfig]):
    """Manage Session Tasks and execute current Scheduled work."""

    def __init__(
        self,
        *,
        session_manager: SessionManager[AsyncSession],
        service: ScheduledTaskService,
        terminal_service: ScheduledTaskTerminalService,
        channel_service: ScheduledTaskChannelService,
        file_transfer_service: ExternalChannelFileTransferService,
        cycle_repository: ScheduledTaskCycleRepository,
        run_repository: AgentRunRepository,
        workspace_id: str,
        agent_id: str,
        session_id: str,
    ) -> None:
        self.session_manager = session_manager
        self.service = service
        self.terminal_service = terminal_service
        self.channel_service = channel_service
        self.file_transfer_service = file_transfer_service
        self.cycle_repository = cycle_repository
        self.run_repository = run_repository
        self.workspace_id = workspace_id
        self.agent_id = agent_id
        self.session_id = session_id
        self.turn_context: TurnContext | None = None
        self.runtime_context_store: RuntimeInstructionContextStore | None = None

    def set_runtime_context_store(
        self,
        store: RuntimeInstructionContextStore,
    ) -> None:
        """Register current run-scoped Runtime file storage."""
        self.runtime_context_store = store

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Expose management tools and the run-bound terminal action."""
        self.turn_context = context
        tools = [
            self._make_add_tool(),
            self._make_list_tool(),
            self._make_delete_tool(),
        ]
        if await self._active_cycle(context.run_id) is not None:
            tools.append(self._make_submit_result_tool())
        return ToolkitState(status=ToolkitStatus.ENABLED, tools=tools)

    async def get_dynamic_prompt(self, context: TurnContext) -> str:
        """Return execution guidance only for the current started cycle."""
        cycle = await self._active_cycle(context.run_id)
        if cycle is None:
            return ""
        return render_scheduled_task_cycle_guidance(cycle.state)

    def hooks(self) -> RuntimeHooks:
        """Return Scheduled idle and compaction continuity hooks."""
        return {
            "on_session_idle": self._on_session_idle,
            "on_compaction_summary": self._on_compaction_summary,
        }

    async def _on_session_idle(
        self,
        context: SessionIdleHookContext,
    ) -> SessionIdleResult | None:
        """Continue every current started cycle in deterministic order."""
        del context
        states = await self._started_cycle_states()
        if not states:
            return None
        return SessionIdleResult(
            continuations=[
                ScheduledTaskSessionContinuationInput(
                    cycle_id=state.cycle_id,
                    title=state.title,
                    content=render_scheduled_task_runtime_message(
                        title=state.title,
                        objective=state.objective,
                        schedule_type=state.schedule_type,
                        scheduled_at=state.scheduled_at,
                        cron_expression=state.cron_expression,
                        timezone=state.timezone,
                        scheduled_for=state.scheduled_for,
                    ),
                    metadata={"source": "scheduled_task"},
                )
                for state in states
            ]
        )

    async def _on_compaction_summary(
        self,
        context: CompactionSummaryHookContext,
    ) -> CompactionSummaryReplace | None:
        """Replace the active Scheduled work snapshot without mutating state."""
        states = await self._started_cycle_states()
        snapshot = render_scheduled_task_compaction_snapshot(states)
        replaced = replace_scheduled_compaction_snapshot(context.summary, snapshot)
        if replaced == context.summary:
            return None
        return CompactionSummaryReplace(summary=replaced)

    async def _active_cycle(
        self,
        run_id: str,
    ) -> ScheduledTaskCycleRecord | None:
        """Resolve the current Run's valid started cycle binding."""
        async with self.session_manager() as session:
            run = await self.run_repository.get_by_id(session, run_id)
            if (
                run is None
                or run.session_id != self.session_id
                or run.scheduled_task_cycle_id is None
            ):
                return None
            cycle = await self.cycle_repository.get_started(
                session,
                agent_id=self.agent_id,
                session_id=self.session_id,
                cycle_id=run.scheduled_task_cycle_id,
            )
        if (
            cycle is None
            or cycle.state.workspace_id != self.workspace_id
            or cycle.state.current_run_id != run_id
        ):
            return None
        return cycle

    async def _started_cycle_states(self) -> list[ScheduledTaskCycleState]:
        """Read current started Session cycles without locking."""
        async with self.session_manager() as session:
            records = await self.cycle_repository.list_started(
                session,
                agent_id=self.agent_id,
                session_id=self.session_id,
            )
        return [record.state for record in records]

    def _make_add_tool(self) -> FunctionTool:
        async def add_scheduled_task(args: AddScheduledTaskInput) -> str:
            """Create one exact Scheduled Task definition."""
            try:
                async with self.session_manager() as session:
                    task = await self.service.create(
                        session,
                        workspace_id=self.workspace_id,
                        agent_id=self.agent_id,
                        session_id=self.session_id,
                        title=args.title,
                        objective=args.objective,
                        at=args.at,
                        cron=args.cron,
                        timezone=args.timezone,
                        binding_id=args.channel_id,
                    )
            except ValueError as exc:
                raise FunctionToolError(str(exc)) from None
            registration = await self.channel_service.execute_registration(task)
            return _json(
                {
                    "task": _task_definition(task),
                    "created": True,
                    "registration": (
                        None
                        if registration is None
                        else _provider_outcome_definition(registration)
                    ),
                }
            )

        return make_tool(
            add_scheduled_task,
            description=_ADD_DESCRIPTION,
            input_model=AddScheduledTaskInput,
        )

    def _make_list_tool(self) -> FunctionTool:
        async def list_scheduled_tasks() -> str:
            """List current Session-owned Scheduled Tasks."""
            async with self.session_manager() as session:
                tasks = await self.service.list_tasks(
                    session,
                    session_id=self.session_id,
                )
                projections = [
                    await self._task_projection(session, task) for task in tasks
                ]
            return _json({"tasks": projections})

        return make_tool(
            list_scheduled_tasks,
            description=_LIST_DESCRIPTION,
        )

    def _make_delete_tool(self) -> FunctionTool:
        async def delete_scheduled_task(args: DeleteScheduledTaskInput) -> str:
            """Delete one exact Session-owned Scheduled Task."""
            try:
                async with self.session_manager() as session:
                    deleted = await self.service.delete(
                        session,
                        session_id=self.session_id,
                        task_id=args.task_id,
                    )
            except ValueError as exc:
                raise FunctionToolError(str(exc)) from None
            return _json({"task_id": args.task_id, "deleted": deleted})

        return make_tool(
            delete_scheduled_task,
            description=_DELETE_DESCRIPTION,
            input_model=DeleteScheduledTaskInput,
        )

    def _make_submit_result_tool(self) -> FunctionTool:
        async def submit_scheduled_task_result(
            args: SubmitScheduledTaskResultInput,
        ) -> FunctionToolResult:
            """Commit the terminal result of the current Scheduled Task cycle."""
            context = self.turn_context
            if context is None:
                raise FunctionToolError("Scheduled Task execution context is missing.")
            try:
                cycle = await self._active_cycle(context.run_id)
                runtime_context = (
                    None
                    if self.runtime_context_store is None
                    else self.runtime_context_store.get()
                )
                manifests: tuple[ExternalChannelOutboundFileManifest, ...] = ()
                if args.files is not None and cycle is not None:
                    binding_id = cycle.state.binding_id
                    if binding_id is None:
                        raise ValueError(
                            "Scheduled Task terminal files require a channel-bound "
                            "cycle."
                        )
                    manifests = await self.file_transfer_service.prepare_outbound(
                        session_id=self.session_id,
                        agent_id=self.agent_id,
                        binding_id=binding_id,
                        paths=args.files,
                        file_storage=(
                            None
                            if runtime_context is None
                            else runtime_context.file_storage
                        ),
                        authority=context.resource_authority,
                    )
                outcome = await self.terminal_service.submit(
                    workspace_id=self.workspace_id,
                    agent_id=self.agent_id,
                    session_id=self.session_id,
                    run_id=context.run_id,
                    status=args.status,
                    result=args.result,
                )
            except ValueError as exc:
                raise FunctionToolError(str(exc)) from None
            if outcome.created:
                await context.publish_event(outcome.event)
            provider_outcomes = (
                ()
                if outcome.effect_snapshot is None
                else await self.channel_service.execute_terminal(
                    outcome.effect_snapshot,
                    files=manifests,
                    file_storage=(
                        None
                        if runtime_context is None
                        else runtime_context.file_storage
                    ),
                    authority=context.resource_authority,
                    provider_delivery_service=(
                        None
                        if runtime_context is None
                        else runtime_context.provider_delivery_service
                    ),
                    resolve_runtime_target=(
                        None
                        if runtime_context is None
                        else runtime_context.resolve_runtime_target
                    ),
                )
            )
            payload = outcome.event.payload
            if not isinstance(payload, ScheduledTaskResultPayload):
                raise RuntimeError("Scheduled Task terminal Event payload is invalid.")
            return FunctionToolResult(
                output=_json(
                    {
                        "status": payload.status,
                        "result": payload.result,
                        "recovered": not outcome.created,
                        "outcomes": [
                            {
                                "operation": provider.operation.value,
                                "part": provider.part,
                                "status": provider.status,
                                **(
                                    {
                                        "reason": provider.reason,
                                        "detail": provider.detail,
                                    }
                                    if provider.reason is not None
                                    else {}
                                ),
                            }
                            for provider in provider_outcomes
                        ],
                    }
                ),
                terminal_run=True,
            )

        return make_tool(
            submit_scheduled_task_result,
            description=_SUBMIT_DESCRIPTION,
            input_model=SubmitScheduledTaskResultInput,
        )

    async def _task_projection(
        self,
        session: AsyncSession,
        task: ScheduledTask,
    ) -> dict[str, object]:
        """Build one management response with derived execution state."""
        execution_state: Literal[
            "idle",
            "admitted",
            "running",
            "running_with_pending",
        ] = "idle"
        if task.active_cycle_id is not None:
            cycle = await self.cycle_repository.get(
                session,
                agent_id=self.agent_id,
                session_id=self.session_id,
                cycle_id=task.active_cycle_id,
            )
            if cycle is None:
                raise RuntimeError("Scheduled Task active cycle state is missing.")
            if cycle.state.phase == "admitted":
                execution_state = "admitted"
            elif task.pending_scheduled_for is not None:
                execution_state = "running_with_pending"
            else:
                execution_state = "running"
        return {
            **_task_definition(task),
            "execution_state": execution_state,
        }


class ScheduledToolkitProvider(ToolkitProvider[ScheduledToolkitConfig]):
    """Provide the root-only auto-bound Scheduled Toolkit."""

    slug = "scheduled"
    name = "Scheduled Tasks"
    description = "Manage and complete Session Scheduled Tasks"
    system_prompt = ""
    config_model = ScheduledToolkitConfig
    vfs_resource_root = "resources/vfs/toolkits/scheduled"

    def __init__(
        self,
        *,
        session_manager: SessionManager[AsyncSession],
        service: ScheduledTaskService,
        terminal_service: ScheduledTaskTerminalService,
        channel_service: ScheduledTaskChannelService,
        file_transfer_service: ExternalChannelFileTransferService,
        cycle_repository: ScheduledTaskCycleRepository,
        run_repository: AgentRunRepository,
    ) -> None:
        self.session_manager = session_manager
        self.service = service
        self.terminal_service = terminal_service
        self.channel_service = channel_service
        self.file_transfer_service = file_transfer_service
        self.cycle_repository = cycle_repository
        self.run_repository = run_repository

    async def resolve(
        self,
        config: ScheduledToolkitConfig,
        context: ResolveContext,
    ) -> Toolkit[ScheduledToolkitConfig]:
        """Return one Session-bound Scheduled Toolkit."""
        del config
        return ScheduledToolkit(
            session_manager=self.session_manager,
            service=self.service,
            terminal_service=self.terminal_service,
            channel_service=self.channel_service,
            file_transfer_service=self.file_transfer_service,
            cycle_repository=self.cycle_repository,
            run_repository=self.run_repository,
            workspace_id=context.workspace_id,
            agent_id=context.agent_id,
            session_id=context.session_id,
        )


def _task_definition(task: ScheduledTask) -> dict[str, object]:
    """Return the complete provider-neutral Task definition."""
    return {
        "task_id": task.id,
        "title": task.title,
        "objective": task.objective,
        "at": _datetime_text(task.scheduled_at),
        "cron": task.cron_expression,
        "timezone": task.timezone,
        "channel_id": task.binding_id,
        "next_eligible_at": _datetime_text(task.next_eligible_at),
        "pending_scheduled_for": _datetime_text(task.pending_scheduled_for),
    }


def _provider_outcome_definition(
    outcome: ProviderEffectOutcome,
) -> dict[str, object]:
    """Return one identifier-free immediate provider outcome."""
    return {
        "operation": outcome.operation.value,
        "part": outcome.part,
        "status": outcome.status,
        **(
            {
                "reason": outcome.reason,
                "detail": outcome.detail,
            }
            if outcome.reason is not None
            else {}
        ),
    }


def _datetime_text(value: datetime.datetime | None) -> str | None:
    """Render an optional timezone-aware datetime as canonical UTC text."""
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Scheduled Task datetime must be timezone-aware.")
    return value.astimezone(datetime.UTC).isoformat().replace("+00:00", "Z")


def _json(value: dict[str, object]) -> str:
    """Serialize one stable Tool response."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True)
