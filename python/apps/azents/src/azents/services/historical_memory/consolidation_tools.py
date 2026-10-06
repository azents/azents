"""Closed current-execution file catalog and path-only explicit submission."""

import dataclasses
from collections.abc import Sequence
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, Field

from azents.core.agent import AgentModelSelection
from azents.core.historical_memory_consolidation import (
    MemoryAcceptedOutcome,
    MemoryExecutionAuthorityError,
    MemoryExecutionPrincipal,
)
from azents.core.historical_memory_publication import MemorySubmissionError
from azents.core.vfs import VfsUriError, parse_vfs_exact_uri
from azents.engine.events.output_parts import (
    enforce_tool_output_text_hard_cap,
    iter_output_parts,
)
from azents.engine.events.tool_invocation import PreparedClientToolInvocation
from azents.engine.events.tools import (
    ToolCatalog,
    ToolCatalogClientToolInvoker,
    project_tool_catalog_for_client_compatibility,
)
from azents.engine.events.types import (
    ClientToolCallPayload,
    ClientToolResultPayload,
    OutputTextPart,
)
from azents.engine.run.client_tool_compatibility import (
    ClientToolRoute,
    resolve_client_tool_adapter_profile,
    resolve_client_tool_model_profiles,
)
from azents.engine.run.types import FunctionTool, FunctionToolError
from azents.engine.tooling.execution_context import get_client_tool_execution_context
from azents.engine.tooling.make_tool import make_tool
from azents.engine.tooling.tool_search import (
    CatalogTool,
    ToolCatalogSource,
    ToolExposure,
)
from azents.engine.tools.glob import make_glob_tool
from azents.engine.tools.grep import make_grep_tool
from azents.engine.tools.mutable_storage import RoutedMutationTools
from azents.engine.tools.read_text import make_read_text_tool
from azents.engine.tools.readable_storage import RoutedReadableStorage
from azents.repos.historical_memory_consolidation.execution import (
    MemoryExecutionRepository,
)
from azents.repos.session_execution_file import SessionExecutionFileRepository
from azents.services.session_execution_files import (
    ExecutionFileObservations,
    SessionExecutionFileBackend,
)
from azents.services.vfs_mutation import (
    VfsBackendRegistration,
    VfsMutationCapabilities,
    VfsMutationRegistry,
    VfsMutationRouter,
)
from azents.services.vfs_read import VfsReadBackendRegistry, VfsReadError, VfsReadRouter


class SubmitMemoryInput(BaseModel):
    """The model selects an authored file, not work settlement or scope."""

    model_config = ConfigDict(extra="forbid")
    path: str = Field(
        description="Canonical authored Markdown file in azents://execution."
    )


@dataclasses.dataclass(frozen=True)
class MemoryFileAuthority:
    repository: MemoryExecutionRepository

    async def validate(self, context: MemoryExecutionPrincipal) -> None:
        try:
            await self.repository.authorize_execution(context)
        except MemoryExecutionAuthorityError:
            raise VfsReadError(
                "not_found", "Execution files are unavailable."
            ) from None


@dataclasses.dataclass
class ConsolidationAdmittedTool:
    """One canonical call with a sibling-frozen writable file buffer."""

    call: ClientToolCallPayload
    before: ExecutionFileObservations
    writer_observations: ExecutionFileObservations
    bindings: "ConsolidationToolBindings"
    selection: AgentModelSelection
    accepted: MemoryAcceptedOutcome | None = dataclasses.field(init=False, default=None)

    @property
    def call_id(self) -> str:
        return self.call.call_id

    async def execute(self) -> ClientToolResultPayload:
        async def submit(input: SubmitMemoryInput) -> str:
            try:
                location = parse_vfs_exact_uri(input.path)
            except VfsUriError:
                raise FunctionToolError(
                    "Submit a canonical authored file in azents://execution."
                ) from None
            if location.mount != "execution":
                raise FunctionToolError(
                    "Only this execution's authored files can be submitted."
                )
            call_id = get_client_tool_execution_context().call_id
            if call_id != self.call_id:
                raise RuntimeError("Submission call identity does not match admission.")
            try:
                self.accepted = await self.bindings.executions.submit(
                    self.bindings.principal,
                    tool_call_id=call_id,
                    authored_path=location.path.removeprefix("/"),
                )
            except MemorySubmissionError as error:
                raise FunctionToolError(
                    str(error),
                    metadata={
                        "kind": "memory_submission_feedback",
                        "rendered_bytes": error.rendered_bytes,
                        "allowance_bytes": 10_000,
                    },
                ) from None
            return "Memory submission accepted. No further model work is needed."

        catalog = self.bindings._catalog(
            self.selection,
            writer=self.writer_observations,
            submit_tool=make_tool(
                submit,
                name="submit_memory",
                description=(
                    "Submit one authored Markdown file from this execution. "
                    "Correctable artifact or size feedback keeps this execution open. "
                    "Only accepted submission completes the task."
                ),
            ),
        )
        result = await ToolCatalogClientToolInvoker(catalog).invoke(
            PreparedClientToolInvocation(
                self.call.call_id,
                self.call.name,
                self.call.arguments,
                self.call.wire_dialect,
            )
        )
        if result.pending_generated_files or result.terminal_run:
            raise RuntimeError(
                "Execution file tools cannot create external terminal actions."
            )
        texts = []
        for part in iter_output_parts(result.output):
            if not isinstance(part, OutputTextPart):
                raise RuntimeError("Execution file tools return bounded text only.")
            texts.append(part.text)
        return ClientToolResultPayload(
            call_id=result.call_id,
            name=result.name,
            wire_dialect=result.wire_dialect,
            status=result.status,
            output=enforce_tool_output_text_hard_cap(
                [OutputTextPart(text="\n".join(texts))]
            ),
            metadata=dict(result.metadata),
        )


@dataclasses.dataclass
class ConsolidationToolBindings:
    """No ordinary Memory, Runtime, Saved, source or attached Toolkit backend."""

    principal: MemoryExecutionPrincipal
    files: SessionExecutionFileRepository
    executions: MemoryExecutionRepository
    observations: ExecutionFileObservations = dataclasses.field(init=False)

    def __post_init__(self) -> None:
        self.observations = ExecutionFileObservations(self.principal.owner)

    def _catalog(
        self,
        selection: AgentModelSelection,
        *,
        writer: ExecutionFileObservations,
        submit_tool: FunctionTool,
    ) -> ToolCatalog:
        authority = MemoryFileAuthority(self.executions)
        backend = SessionExecutionFileBackend(self.files, self.observations)
        storage = RoutedReadableStorage(
            self.principal.binding.unit.agent_id,
            VfsReadRouter(VfsReadBackendRegistry([backend]), authority),
            self.principal,
            None,
            None,
        )
        frozen = SessionExecutionFileBackend(self.files, writer)
        router = VfsMutationRouter(
            VfsMutationRegistry(
                [
                    VfsBackendRegistration(
                        frozen, frozen, frozen, VfsMutationCapabilities(True, True)
                    ),
                ]
            ),
            authority,
        )
        return _catalog(
            [
                make_read_text_tool(
                    session_storage=storage,
                    agent_id=self.principal.binding.unit.agent_id,
                ),
                make_grep_tool(
                    session_storage=storage,
                    agent_id=self.principal.binding.unit.agent_id,
                ),
                make_glob_tool(
                    session_storage=storage,
                    agent_id=self.principal.binding.unit.agent_id,
                ),
                *RoutedMutationTools(
                    self.principal, router, {}, get_client_tool_execution_context
                ).tools(),
                submit_tool,
            ],
            selection,
        )

    def catalog(
        self, selection: AgentModelSelection, *, writer: ExecutionFileObservations
    ) -> ToolCatalog:
        async def submit(input: SubmitMemoryInput) -> str:
            raise RuntimeError("Submission must use an admitted canonical tool call.")

        return self._catalog(
            selection,
            writer=writer,
            submit_tool=make_tool(
                submit,
                name="submit_memory",
                description=(
                    "Submit an authored Markdown file in azents://execution. "
                    "The complete framed result must fit 10,000 UTF-8 bytes. "
                    "Format or size feedback is correctable; "
                    "acceptance completes the task."
                ),
            ),
        )

    def admit(
        self, calls: Sequence[ClientToolCallPayload], selection: AgentModelSelection
    ) -> tuple[ConsolidationAdmittedTool, ...]:
        before = self.observations.snapshot()
        return tuple(
            ConsolidationAdmittedTool(call, before, before.snapshot(), self, selection)
            for call in calls
        )

    def merge(self, admitted: ConsolidationAdmittedTool) -> None:
        self.observations.merge_mutations(admitted.before, admitted.writer_observations)


def _catalog(
    tools: Sequence[FunctionTool], selection: AgentModelSelection
) -> ToolCatalog:
    source = ToolCatalogSource(
        slug="consolidation",
        namespace="consolidation",
        toolkit_type=None,
        toolkit_class="ConsolidationFiles",
        display_name="Scoped consolidation files",
        use_prefix=False,
    )
    by_name = {tool.spec.name: tool for tool in tools}
    if len(by_name) != len(tools):
        raise ValueError("Duplicate internal tool name.")
    candidate = ToolCatalog(
        native_replay_context=None,
        tools=MappingProxyType(by_name),
        wire_dialects=MappingProxyType({}),
        entries=MappingProxyType(
            {
                name: CatalogTool(tool, source, ToolExposure.DIRECT)
                for name, tool in by_name.items()
            }
        ),
        static_prompt_fragment_inputs=[],
        dynamic_prompt_fragment_inputs=[],
        active_toolkit_bindings=[],
    )
    native = selection.provider.value in {"openai", "chatgpt_oauth"}
    return project_tool_catalog_for_client_compatibility(
        candidate,
        resolve_client_tool_model_profiles(
            model_identifier=selection.model_identifier,
            model_developer=selection.model_developer,
            model_family=selection.model_family,
        ),
        resolve_client_tool_adapter_profile(
            route=ClientToolRoute(
                provider=selection.provider,
                adapter="openai" if native else "pydantic_ai",
                native_format="responses" if native else "model_messages",
            )
        ),
    )
