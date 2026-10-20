"""Root-owned Session Routine management and independent occurrence results."""

import datetime
import json
from dataclasses import asdict

from pydantic import BaseModel, ConfigDict, Field, model_validator

from azents.core.external_channel_file import MAX_EXTERNAL_CHANNEL_FILES
from azents.core.routine import (
    RoutineChanges,
    RoutineContent,
    RoutineScope,
    RoutineWorkResult,
)
from azents.core.routine_presentation import (
    ordered_incomplete_routines,
    render_routine_execution_input,
    replace_routine_compaction_snapshot,
    routine_execution_ref,
)
from azents.core.session_resource_authority import (
    SessionExecutionOwner,
    SessionResourceAuthority,
    accepts_execution_owner,
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
    RoutineSessionContinuationInput,
    RuntimeHooks,
    SessionIdleHookContext,
    SessionIdleResult,
)
from azents.engine.run.types import FunctionTool, FunctionToolError
from azents.engine.tooling.make_tool import make_tool
from azents.engine.tools.runtime_instruction_context import (
    RuntimeInstructionContextStore,
)
from azents.repos.routine.completion import RoutineCompletionRepository
from azents.repos.routine.operations import RoutineOperations
from azents.services.routine.files import RoutineFileService
from azents.services.routine.notification import RoutineNotificationService


class RoutineToolkitConfig(BaseModel):
    """Code-owned auto-bound Toolkit configuration."""

    model_config = ConfigDict(extra="forbid")


class CreateRoutineInput(RoutineContent):
    """Create exact Routine content; creation does not immediately run a check."""


class RoutineIdentityInput(BaseModel):
    """Identify a definition in this Session, never an arbitrary Session."""

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(min_length=1)


class InspectRoutineInput(RoutineIdentityInput):
    """Read exact current content and a bounded recent result page."""

    record_limit: int = Field(ge=1, le=100)


class UpdateRoutineInput(RoutineIdentityInput):
    """Compare complete existing content before applying separate changes."""

    expected: RoutineContent
    changes: RoutineChanges


class RoutineExecutionInput(RoutineIdentityInput):
    """Read or settle one immutable admitted occurrence."""

    execution_id: str = Field(min_length=1)


class RecordRoutineResultInput(RoutineExecutionInput, RoutineWorkResult):
    """Record objective outcome, continuity, and independently chosen notification."""

    files: list[str] | None = Field(
        min_length=1,
        max_length=MAX_EXTERNAL_CHANNEL_FILES,
        description=(
            "Absolute Runtime paths or authorized exchange:// URIs to attach. "
            "Null when no files. Requires notify=true."
        ),
    )

    @model_validator(mode="after")
    def validate_files(self) -> "RecordRoutineResultInput":
        """Silent results cannot publish files."""
        if self.files is not None and not self.notify:
            raise ValueError("Silent Routine results cannot include files.")
        return self


class RoutineToolkit(Toolkit[RoutineToolkitConfig]):
    """Manage definitions and finish one item without ending its ordinary Run."""

    def __init__(
        self,
        *,
        operations: RoutineOperations,
        completion: RoutineCompletionRepository,
        notifications: RoutineNotificationService,
        scope: RoutineScope,
        files: RoutineFileService,
    ) -> None:
        self.operations = operations
        self.completion = completion
        self.notifications = notifications
        self.scope = scope
        self.files = files
        self.turn_context: TurnContext | None = None
        self.execution_owner: SessionExecutionOwner | None = None
        self.runtime_context_store: RuntimeInstructionContextStore | None = None

    def bind_execution_owner(self, owner: SessionExecutionOwner) -> None:
        """Bind to the existing ordinary Session owner, never a Routine owner."""
        if accepts_execution_owner(
            self.execution_owner, owner, session_id=self.scope.session_id
        ):
            self.execution_owner = owner

    def set_runtime_context_store(self, store: RuntimeInstructionContextStore) -> None:
        """Use existing provider delivery dependencies for immediate publication."""
        self.runtime_context_store = store

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Expose the root-only tool group with current ordinary Run authority."""
        self.turn_context = context
        return ToolkitState(status=ToolkitStatus.ENABLED, tools=self._tools())

    async def _authority(self) -> SessionResourceAuthority:
        context = self.turn_context
        authority = None if context is None else context.resource_authority
        if (
            authority is None
            or self.execution_owner is None
            or authority.execution_owner != self.execution_owner
            or context is None
            or context.run_id != authority.run_id
            or context.run_index != authority.run_index
        ):
            raise FunctionToolError(
                "Routine execution authority is missing or changed."
            )
        try:
            await self.completion.authorize(scope=self.scope, authority=authority)
        except ValueError as exc:
            raise FunctionToolError(str(exc)) from None
        return authority

    def hooks(self) -> RuntimeHooks:
        """Contribute unfinished work only to the ordinary idle boundary."""
        return {
            "on_session_idle": self._on_session_idle,
            "on_compaction_summary": self._on_compaction_summary,
        }

    async def _on_compaction_summary(
        self, context: CompactionSummaryHookContext
    ) -> CompactionSummaryReplace | None:
        """Keep immutable obligation context across ordinary history compaction."""
        if self.turn_context is None:
            return None
        authority = await self._authority()
        if (
            context.session_id != self.scope.session_id
            or context.workspace_id != self.scope.workspace_id
            or context.agent_id != self.scope.agent_id
            or context.run_id != authority.run_id
        ):
            return None
        states = await self.completion.list_for_compaction(
            scope=self.scope, authority=authority
        )
        summary = replace_routine_compaction_snapshot(context.summary, states)
        return (
            None
            if summary == context.summary
            else CompactionSummaryReplace(summary=summary)
        )

    async def _on_session_idle(
        self, context: SessionIdleHookContext
    ) -> SessionIdleResult | None:
        if (
            self.execution_owner is None
            or context.reason != "completed"
            or context.session_id != self.scope.session_id
            or context.workspace_id != self.scope.workspace_id
            or context.agent_id != self.scope.agent_id
        ):
            return None
        states = ordered_incomplete_routines(
            await self.completion.list_for_idle(
                scope=self.scope,
                owner=self.execution_owner,
                run_id=context.run_id,
            )
        )
        if not states:
            return None
        return SessionIdleResult(
            continuations=[
                RoutineSessionContinuationInput(
                    content=render_routine_execution_input(states, continuation=True),
                    executions=tuple(routine_execution_ref(state) for state in states),
                    metadata={"source": "routine"},
                )
            ]
        )

    def _tools(self) -> list[FunctionTool]:
        async def create_routine(args: CreateRoutineInput) -> str:
            authority = await self._authority()
            try:
                definition = await self.operations.create(
                    scope=self.scope,
                    content=RoutineContent.model_validate(args.model_dump()),
                    owner=authority.execution_owner,
                )
            except ValueError as exc:
                raise FunctionToolError(str(exc)) from None
            return _json(asdict(definition))

        async def list_routines() -> str:
            await self._authority()
            return _json(
                {
                    "routines": [
                        asdict(item)
                        for item in await self.operations.list_routines(
                            scope=self.scope
                        )
                    ]
                }
            )

        async def inspect_routine(args: InspectRoutineInput) -> str:
            await self._authority()
            result = await self.operations.inspect(
                scope=self.scope, slug=args.slug, record_limit=args.record_limit
            )
            return _json({"routine": None if result is None else asdict(result)})

        async def update_routine(args: UpdateRoutineInput) -> str:
            authority = await self._authority()
            try:
                definition = await self.operations.update(
                    scope=self.scope,
                    slug=args.slug,
                    expected=args.expected,
                    changes=args.changes,
                    owner=authority.execution_owner,
                )
            except ValueError as exc:
                raise FunctionToolError(str(exc)) from None
            return _json(asdict(definition))

        async def delete_routine(args: RoutineIdentityInput) -> str:
            authority = await self._authority()
            try:
                definition = await self.operations.delete(
                    scope=self.scope, slug=args.slug, owner=authority.execution_owner
                )
            except ValueError as exc:
                raise FunctionToolError(str(exc)) from None
            return _json({"deleted": True, "routine": asdict(definition)})

        async def read_routine_context(args: RoutineExecutionInput) -> str:
            authority = await self._authority()
            try:
                state = await self.completion.context(
                    scope=self.scope,
                    authority=authority,
                    slug=args.slug,
                    execution_id=args.execution_id,
                )
            except ValueError as exc:
                raise FunctionToolError(str(exc)) from None
            return state.context.model_dump_json()

        async def record_routine_result(args: RecordRoutineResultInput) -> str:
            authority = await self._authority()
            runtime = (
                None
                if self.runtime_context_store is None
                else self.runtime_context_store.get()
            )
            try:
                prepared_files = None
                if args.files is not None:
                    current = await self.completion.context(
                        scope=self.scope,
                        authority=authority,
                        slug=args.slug,
                        execution_id=args.execution_id,
                    )
                    if current.phase != "completed":
                        binding_id = (
                            await self.notifications.operations.current_primary(
                                scope=self.scope, authority=authority
                            )
                        )
                        prepared_files = await self.files.prepare(
                            paths=args.files,
                            binding_id=binding_id,
                            execution_id=args.execution_id,
                            authority=authority,
                            runtime=runtime,
                        )
                recording = await self.completion.complete(
                    scope=self.scope,
                    authority=authority,
                    slug=args.slug,
                    execution_id=args.execution_id,
                    work=RoutineWorkResult(
                        objective_outcome=args.objective_outcome,
                        result=args.result,
                        next_hint=args.next_hint,
                        notify=args.notify,
                        message=args.message,
                    ),
                    now=datetime.datetime.now(datetime.UTC),
                )
            except ValueError as exc:
                raise FunctionToolError(str(exc)) from None
            state = await self.notifications.deliver(
                scope=self.scope,
                authority=authority,
                recording=recording,
                runtime=runtime,
                publish_event=None
                if self.turn_context is None
                else self.turn_context.publish_event,
                files=prepared_files,
            )
            return _json(
                {
                    "created": recording.created,
                    "execution": state.model_dump(mode="json"),
                }
            )

        return [
            make_tool(
                create_routine,
                input_model=CreateRoutineInput,
                description=(
                    "Create one Session Routine with exact content and supported "
                    "manual sources. Checking happens at normal eligible ticks, "
                    "not immediately. Empty sources never make a candidate."
                ),
            ),
            make_tool(
                list_routines,
                description="List Session Routine definitions and exact content.",
            ),
            make_tool(
                inspect_routine,
                input_model=InspectRoutineInput,
                description=(
                    "Read one Routine's current definition and bounded recent "
                    "results before editing."
                ),
            ),
            make_tool(
                update_routine,
                input_model=UpdateRoutineInput,
                description=(
                    "Update a Routine by comparing its entire exact prior content "
                    "in expected and applying separate changes. Omit unchanged "
                    "fields; null does not mean omission. Reread after conflict."
                ),
            ),
            make_tool(
                delete_routine,
                input_model=RoutineIdentityInput,
                description=(
                    "Delete one Routine definition and retained records. "
                    "Admitted work can finish from its stored context; "
                    "deletion prevents future selection."
                ),
            ),
            make_tool(
                read_routine_context,
                input_model=RoutineExecutionInput,
                description=(
                    "Read the immutable full context of an admitted occurrence "
                    "owned by this Run, including deleted or edited definitions."
                ),
            ),
            make_tool(
                record_routine_result,
                input_model=RecordRoutineResultInput,
                description=(
                    "Record one admitted occurrence's objective outcome, concise "
                    "result and required future next_hint. Record honest failed "
                    "investigations too. Choose notify independently: true requires "
                    "message; false forbids message. Notify only when the user "
                    "needs to know. Attach files with absolute Runtime paths or "
                    "authorized exchange:// URIs; silent results forbid files. "
                    "Delivery uses current Session Primary or "
                    "Session chat when absent, with no automatic resend. "
                    "Closes only this occurrence, never the Run, other Routines, "
                    "ordinary work or Channel Work."
                ),
            ),
        ]


class RoutineToolkitProvider(ToolkitProvider[RoutineToolkitConfig]):
    """Auto-bind the independent Routines group only to root execution modes."""

    slug = "routine"
    name = "Routines"
    description = "Manage Session Routines and record independent work results"
    system_prompt = ""
    config_model = RoutineToolkitConfig
    vfs_resource_root = "resources/vfs/toolkits/routine"

    def __init__(
        self,
        *,
        operations: RoutineOperations,
        completion: RoutineCompletionRepository,
        notifications: RoutineNotificationService,
        files: RoutineFileService,
    ) -> None:
        self.operations = operations
        self.completion = completion
        self.notifications = notifications
        self.files = files

    async def resolve(
        self, config: RoutineToolkitConfig, context: ResolveContext
    ) -> Toolkit[RoutineToolkitConfig]:
        """Capture exact Session identity and revalidate authority at tool calls."""
        del config
        return RoutineToolkit(
            operations=self.operations,
            completion=self.completion,
            notifications=self.notifications,
            files=self.files,
            scope=RoutineScope(
                workspace_id=context.workspace_id,
                agent_id=context.agent_id,
                session_id=context.session_id,
            ),
        )


def _json(value: object) -> str:
    """Serialize detached typed contracts without coercing unsupported objects."""

    def encode(item: object) -> object:
        if isinstance(item, BaseModel):
            return item.model_dump(mode="json")
        if isinstance(item, datetime.datetime):
            return item.isoformat()
        raise TypeError(f"Unsupported Routine output type: {type(item).__name__}")

    return json.dumps(value, default=encode, ensure_ascii=False, sort_keys=True)
