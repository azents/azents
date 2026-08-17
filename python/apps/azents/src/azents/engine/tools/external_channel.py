"""Root-only External Channel Action toolkit."""

import json
import logging
import textwrap
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from azents.core.enums import (
    ExternalChannelActionMode,
    ExternalChannelWorkTaskStatus,
)
from azents.core.external_channel_file import (
    MAX_EXTERNAL_CHANNEL_FILES,
    ExternalChannelFileLocator,
)
from azents.core.external_channel_progress import (
    MAX_EXTERNAL_CHANNEL_TASK_SOURCES,
    MAX_EXTERNAL_CHANNEL_TASK_TEXT_LENGTH,
    MAX_EXTERNAL_CHANNEL_WORK_TASKS,
    MAX_EXTERNAL_CHANNEL_WORK_TITLE_LENGTH,
)
from azents.core.external_channel_progress import (
    ExternalChannelWorkSource as ChannelWorkSource,
)
from azents.core.tools import (
    ResolveContext,
    Toolkit,
    ToolkitProvider,
    ToolkitState,
    ToolkitStatus,
    TurnContext,
)
from azents.engine.hooks.types import (
    CompactionSummaryHookContext,
    CompactionSummaryReplace,
    ExternalChannelSessionContinuationInput,
    RuntimeHooks,
    SessionIdleHookContext,
    SessionIdleResult,
)
from azents.engine.run.types import FunctionTool, FunctionToolError
from azents.engine.tooling.execution_context import (
    get_client_tool_execution_context,
)
from azents.engine.tooling.make_tool import make_tool
from azents.engine.tools.runtime_instruction_context import (
    RuntimeInstructionContextStore,
)
from azents.repos.external_channel.work_data import (
    ChannelActionResult,
    ChannelWorkSnapshot,
    ChannelWorkTask,
)
from azents.runtime.transfer.server_to_runtime import ServerToRuntimeTarget
from azents.services.external_channel.channel_action import (
    ExternalChannelActionService,
)
from azents.services.external_channel.file_transfer import (
    ExternalChannelFileTransferError,
    ExternalChannelFileTransferExecutionError,
    ExternalChannelFileTransferService,
)
from azents.services.external_channel.slack_events import (
    SLACK_MARKDOWN_TEXT_MAX_LENGTH,
)
from azents.services.runtime_storage_error import RuntimeStorageError
from azents.services.session_resource_authority import SessionResourceAuthority

EXTERNAL_CHANNEL_TOOLKIT_SLUG = "external_channel"
_LOGGER = logging.getLogger(__name__)
_COMPACTION_HEADING = "## Channel Work Snapshot"
_STATIC_PROMPT = textwrap.dedent(
    """\
    Ordinary assistant output is not delivered to the external channel, so use
    `channel_action` to publish, continue, or silently complete Channel Work.
    """
).strip()
_CHANNEL_ACTION_DESCRIPTION = textwrap.dedent(
    """\
    Act on one active External Channel binding. Use only for the current External
    Channel turn or continuation, or when an ordinary user explicitly requests
    external publication. An active binding or prior External Channel history alone
    does not make ordinary input external; otherwise, answer the user normally. Use
    `finish` for the final reply. Use `continue` while work remains; it may send
    progress and replace the complete ordered Channel Work task list. Use `ignore` to
    finish active Work silently with no message, title, task update, files, or provider
    effect. Ignored Work does not schedule another continuation.
    """
).strip()
_DOWNLOAD_EXTERNAL_FILE_DESCRIPTION = (
    "Materialize one External Channel file into the Runtime. File entries contain "
    "metadata and an opaque locator, not local content."
)


class ChannelActionSourceInput(BaseModel):
    """One labeled URL source supplied by the Agent."""

    model_config = ConfigDict(str_strip_whitespace=True)

    url: str = Field(min_length=1, max_length=2_048)
    label: str = Field(min_length=1, max_length=500)


class ChannelActionTaskInput(BaseModel):
    """One ordered task supplied by the Agent."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=500)
    status: ExternalChannelWorkTaskStatus
    details: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_EXTERNAL_CHANNEL_TASK_TEXT_LENGTH,
    )
    output: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_EXTERNAL_CHANNEL_TASK_TEXT_LENGTH,
    )
    sources: list[ChannelActionSourceInput] = Field(
        default_factory=list,
        max_length=MAX_EXTERNAL_CHANNEL_TASK_SOURCES,
    )


class ChannelActionInput(BaseModel):
    """Act on one active External Channel binding."""

    model_config = ConfigDict(str_strip_whitespace=True)

    mode: Literal["finish", "continue", "ignore"] = Field(
        description=(
            "`finish`: final reply. `continue`: work remains. `ignore`: finish "
            "active Work silently with no other fields."
        )
    )
    binding: str = Field(
        min_length=1,
        max_length=80,
        description="Binding handle from context. Pass it unchanged.",
    )
    message: str | None = Field(
        default=None,
        min_length=1,
        max_length=SLACK_MARKDOWN_TEXT_MAX_LENGTH,
        description="Required for `finish` and file publication.",
    )
    title: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_EXTERNAL_CHANNEL_WORK_TITLE_LENGTH,
        description=(
            "Current activity in the participant's language; use progressive "
            "wording ending in an ellipsis."
        ),
    )
    todo_update: list[ChannelActionTaskInput] | None = Field(
        default=None,
        max_length=MAX_EXTERNAL_CHANNEL_WORK_TASKS,
        description=(
            "Complete ordered task list. Channel Work is independent from the "
            "session-scoped update_todo list."
        ),
    )
    files: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_EXTERNAL_CHANNEL_FILES,
        description=(
            "File source paths. Each item must be either an absolute POSIX Runtime "
            "path beginning with `/` or an authorized `exchange://{object_key}` URI. "
            "Relative paths and other URI schemes, including `artifact://` and "
            "`azents://`, are unsupported."
        ),
    )

    @model_validator(mode="after")
    def validate_action(self) -> "ChannelActionInput":
        """Validate the fields that apply to the selected action mode."""
        if self.mode == "ignore":
            if any(
                value is not None
                for value in (
                    self.message,
                    self.title,
                    self.todo_update,
                    self.files,
                )
            ):
                raise ValueError(
                    "Ignore does not accept a message, title, task update, or files."
                )
            return self
        if self.mode == "finish":
            if self.message is None:
                raise ValueError("Finish requires a message.")
            return self
        if (
            self.message is None
            and self.title is None
            and self.todo_update is None
            and self.files is None
        ):
            raise ValueError(
                "Continue requires a message, title, task update, or a combination."
            )
        if self.todo_update is not None and self.title is None:
            raise ValueError("A Channel Work task update requires a work title.")
        if self.files is not None and self.message is None:
            raise ValueError("Channel file publication requires a message.")
        if self.title is not None and not self.title.endswith(("…", "...")):
            raise ValueError("Channel Work titles must end with an ellipsis.")
        if self.todo_update is not None and not any(
            task.status
            not in {
                ExternalChannelWorkTaskStatus.COMPLETED,
                ExternalChannelWorkTaskStatus.FAILED,
            }
            for task in self.todo_update
        ):
            raise ValueError("Continue must leave at least one unfinished task.")
        if self.todo_update is not None:
            task_ids = [task.id for task in self.todo_update]
            if len(task_ids) != len(set(task_ids)):
                raise ValueError("Channel Work task IDs must be unique.")
        return self


class DownloadExternalFileInput(BaseModel):
    """Materialize one selected External Channel file in the Runtime."""

    model_config = ConfigDict(str_strip_whitespace=True)

    file: str = Field(
        min_length=1,
        max_length=2_048,
        description="Opaque locator from External Channel Files. Pass it unchanged.",
    )
    path: str = Field(
        min_length=1,
        max_length=4_096,
        description="Absolute Runtime destination path for the selected file.",
    )
    overwrite: bool = Field(
        default=False,
        description="Replace an existing destination file.",
    )


class ExternalChannelToolkitConfig(BaseModel):
    """External Channel auto-bound Toolkit settings."""


class ExternalChannelToolkit(Toolkit[ExternalChannelToolkitConfig]):
    """Expose current binding work and one explicit publication tool."""

    def __init__(
        self,
        *,
        service: ExternalChannelActionService,
        file_transfer_service: ExternalChannelFileTransferService,
        agent_id: str,
        session_id: str,
        run_id: str,
    ) -> None:
        """Create one Session-bound toolkit."""
        self.service = service
        self.file_transfer_service = file_transfer_service
        self.agent_id = agent_id
        self.session_id = session_id
        self.run_id = run_id
        self.runtime_context_store: RuntimeInstructionContextStore | None = None
        self.resource_authority: SessionResourceAuthority | None = None

    def set_runtime_context_store(
        self,
        store: RuntimeInstructionContextStore,
    ) -> None:
        """Register current run-scoped Runtime file storage."""
        self.runtime_context_store = store

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Expose Channel Action only while an active binding exists."""
        self.run_id = context.run_id
        self.resource_authority = context.resource_authority
        enabled = await self.service.has_active_binding(
            session_id=self.session_id,
            agent_id=self.agent_id,
        )
        return ToolkitState(
            status=ToolkitStatus.ENABLED if enabled else ToolkitStatus.DISABLED,
            tools=(
                [
                    self._make_channel_action_tool(),
                    *(
                        [self._make_download_external_file_tool()]
                        if self.runtime_context_store is not None
                        else []
                    ),
                ]
                if enabled
                else []
            ),
        )

    async def get_static_prompt(self, context: TurnContext) -> str:
        """Return the direct external publication boundary."""
        del context
        return _STATIC_PROMPT

    def hooks(self) -> RuntimeHooks:
        """Return compaction enrichment and generic idle continuation hooks."""
        return {
            "on_compaction_summary": self._on_compaction_summary,
            "on_session_idle": self._on_session_idle,
        }

    async def _on_compaction_summary(
        self,
        context: CompactionSummaryHookContext,
    ) -> CompactionSummaryReplace | None:
        works = await self.service.snapshot(
            session_id=self.session_id,
            agent_id=self.agent_id,
        )
        snapshot = render_channel_work_compaction_snapshot(works)
        if snapshot is None:
            return None
        base = context.summary.split(f"\n\n{_COMPACTION_HEADING}", 1)[0].rstrip()
        return CompactionSummaryReplace(summary=f"{base}\n\n{snapshot}")

    async def _on_session_idle(
        self,
        context: SessionIdleHookContext,
    ) -> SessionIdleResult | None:
        del context
        works = await self.service.snapshot(
            session_id=self.session_id,
            agent_id=self.agent_id,
        )
        if not works:
            return None
        handles = [work.binding_id for work in works]
        return SessionIdleResult(
            continuations=[
                ExternalChannelSessionContinuationInput(
                    content="",
                    metadata={
                        "source": "external_channel",
                        "active_bindings": ",".join(handles),
                    },
                )
            ]
        )

    def _make_channel_action_tool(self) -> FunctionTool:
        async def channel_action(args: ChannelActionInput) -> str:
            """Commit Channel Work and explicitly publish to one external binding."""
            execution = get_client_tool_execution_context()
            value = args
            tasks = (
                None
                if value.mode == "finish" or value.todo_update is None
                else [
                    ChannelWorkTask(
                        id=task.id,
                        title=task.title,
                        status=task.status,
                        details=task.details,
                        output=task.output,
                        sources=[
                            ChannelWorkSource(
                                url=source.url,
                                label=source.label,
                            )
                            for source in task.sources
                        ],
                    )
                    for task in value.todo_update
                ]
            )
            try:
                runtime_context = (
                    None
                    if self.runtime_context_store is None
                    else self.runtime_context_store.get()
                )
                manifests = ()
                if value.files is not None:
                    manifests = await self.file_transfer_service.prepare_outbound(
                        session_id=self.session_id,
                        agent_id=self.agent_id,
                        binding_id=value.binding,
                        paths=value.files,
                        file_storage=(
                            None
                            if runtime_context is None
                            else runtime_context.file_storage
                        ),
                        authority=self.resource_authority,
                    )
                result = await self.service.execute(
                    session_id=self.session_id,
                    agent_id=self.agent_id,
                    run_id=self.run_id,
                    client_tool_call_id=execution.call_id,
                    binding_id=value.binding,
                    mode=ExternalChannelActionMode(value.mode),
                    message=value.message,
                    title=None if value.mode == "finish" else value.title,
                    tasks=tasks,
                    files=manifests,
                    file_storage=(
                        None
                        if runtime_context is None
                        else runtime_context.file_storage
                    ),
                    authority=self.resource_authority,
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
            except ValueError as error:
                raise FunctionToolError(str(error)) from None
            return json.dumps(
                _result_payload(result),
                ensure_ascii=False,
                sort_keys=True,
            )

        return make_tool(
            channel_action,
            description=_CHANNEL_ACTION_DESCRIPTION,
            input_model=ChannelActionInput,
        )

    def _make_download_external_file_tool(self) -> FunctionTool:
        async def download_external_file(args: DownloadExternalFileInput) -> str:
            """Download one selected provider file to an absolute Runtime path."""
            context = (
                None
                if self.runtime_context_store is None
                else self.runtime_context_store.get()
            )
            if context is None:
                raise FunctionToolError(
                    "Runtime file storage is unavailable for this run."
                )
            transfer_target = None
            try:
                transfer_target = await context.resolve_runtime_target()
                result = await self.file_transfer_service.download(
                    session_id=self.session_id,
                    agent_id=self.agent_id,
                    operation_id=self.run_id,
                    file=args.file,
                    path=args.path,
                    overwrite=args.overwrite,
                    file_storage=context.file_storage,
                    transfer_service=context.transfer_service,
                    transfer_target=transfer_target,
                )
            except ExternalChannelFileTransferError as error:
                _LOGGER.warning(
                    "External Channel file download failed",
                    exc_info=True,
                    extra=_external_file_download_failure_log_fields(
                        file=args.file,
                        path=args.path,
                        overwrite=args.overwrite,
                        session_id=self.session_id,
                        agent_id=self.agent_id,
                        operation_id=self.run_id,
                        transfer_target=transfer_target,
                        error=error,
                    ),
                )
                raise FunctionToolError(str(error)) from None
            except RuntimeStorageError as error:
                _LOGGER.warning(
                    "External Channel Runtime storage operation failed",
                    exc_info=True,
                    extra=_external_file_download_failure_log_fields(
                        file=args.file,
                        path=args.path,
                        overwrite=args.overwrite,
                        session_id=self.session_id,
                        agent_id=self.agent_id,
                        operation_id=self.run_id,
                        transfer_target=transfer_target,
                        error=error,
                    ),
                )
                raise FunctionToolError(error.detail) from None
            return json.dumps(
                {
                    "path": result.path,
                    "filename": result.filename,
                    "media_type": result.media_type,
                    "bytes": result.bytes_written,
                },
                ensure_ascii=False,
                sort_keys=True,
            )

        return make_tool(
            download_external_file,
            description=_DOWNLOAD_EXTERNAL_FILE_DESCRIPTION,
            input_model=DownloadExternalFileInput,
        )


def _external_file_download_failure_log_fields(
    *,
    file: str,
    path: str,
    overwrite: bool,
    session_id: str,
    agent_id: str,
    operation_id: str,
    transfer_target: ServerToRuntimeTarget | None,
    error: ExternalChannelFileTransferError | RuntimeStorageError,
) -> dict[str, object]:
    """Return secret-free correlation fields for one handled download failure."""
    try:
        locator = ExternalChannelFileLocator.parse(file)
    except ValueError:
        locator = None
    if isinstance(error, ExternalChannelFileTransferExecutionError):
        failure_stage = error.failure.stage
        failure_cause = error.failure.cause
        failure_detail = error.failure.detail
        coordinator_failure = (
            None
            if error.failure.coordinator_failure is None
            else error.failure.coordinator_failure.value
        )
    elif isinstance(error, RuntimeStorageError):
        failure_stage = "runtime_storage"
        failure_cause = type(error).__name__
        failure_detail = error.detail
        coordinator_failure = None
    else:
        failure_stage = "validation_or_authorization"
        failure_cause = type(error).__name__
        failure_detail = str(error)
        coordinator_failure = None
    return {
        "session_id": session_id,
        "agent_id": agent_id,
        "operation_id": operation_id,
        "runtime_id": None if transfer_target is None else transfer_target.runtime_id,
        "runtime_generation": (
            None if transfer_target is None else transfer_target.desired_generation
        ),
        "external_channel_provider": (
            None if locator is None else locator.provider.value
        ),
        "external_channel_binding_id": (
            None if locator is None else locator.binding_id
        ),
        "external_channel_provider_file_id": (
            None if locator is None else locator.provider_file_id
        ),
        "external_channel_provider_channel_id": (
            None if locator is None else locator.provider_channel_id
        ),
        "external_channel_provider_message_id": (
            None if locator is None else locator.provider_message_id
        ),
        "destination_path": path,
        "overwrite": overwrite,
        "failure_stage": failure_stage,
        "failure_cause": failure_cause,
        "failure_detail": failure_detail,
        "coordinator_failure": coordinator_failure,
    }


class ExternalChannelToolkitProvider(ToolkitProvider[ExternalChannelToolkitConfig]):
    """Auto-bound root Toolkit provider for active External Channel bindings."""

    slug = EXTERNAL_CHANNEL_TOOLKIT_SLUG
    name = "External Channel"
    description = "Manage external conversation work and explicit delivery"
    system_prompt = ""
    config_model = ExternalChannelToolkitConfig

    def __init__(
        self,
        *,
        service: ExternalChannelActionService,
        file_transfer_service: ExternalChannelFileTransferService,
    ) -> None:
        """Create the provider."""
        self.service = service
        self.file_transfer_service = file_transfer_service

    async def resolve(
        self,
        config: ExternalChannelToolkitConfig,
        context: ResolveContext,
    ) -> Toolkit[ExternalChannelToolkitConfig]:
        """Create one Session-bound External Channel toolkit."""
        del config
        return ExternalChannelToolkit(
            service=self.service,
            file_transfer_service=self.file_transfer_service,
            agent_id=context.agent_id,
            session_id=context.session_id,
            run_id="",
        )


def render_channel_work_compaction_snapshot(
    works: list[ChannelWorkSnapshot],
) -> str | None:
    """Render unfinished Channel Work continuity for compaction."""
    if not works:
        return None
    lines = [_COMPACTION_HEADING, ""]
    for work in works:
        lines.extend(
            [
                f"### Binding `{work.binding_id}`",
                f"- Provider: {work.provider.value}",
                f"- Resource: {work.resource_label}",
                f"- Current work title: {work.title or 'Not declared yet'}",
                "- Tasks:",
            ]
        )
        if work.tasks:
            for task in work.tasks:
                lines.append(f"  - [{task.status.value}] `{task.id}`: {task.title}")
                if task.details is not None:
                    lines.append(f"    - Details: {task.details}")
                if task.output is not None:
                    lines.append(f"    - Output: {task.output}")
                if task.sources:
                    lines.append("    - Sources:")
                    for source in task.sources:
                        lines.append(f"      - {source.label}: {source.url}")
        else:
            lines.append("  - No tasks recorded.")
        lines.append("")
    return "\n".join(lines).rstrip()


def _result_payload(result: ChannelActionResult) -> dict[str, object]:
    return {
        "binding": result.binding_id,
        "state": result.work_status.value,
        "state_revision": result.state_revision,
        "outcomes": [
            {
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
            for outcome in result.outcomes
        ],
    }
