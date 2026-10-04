"""Closed internal file catalog with admission-frozen sibling mutation evidence."""

import dataclasses
from collections.abc import Sequence
from types import MappingProxyType

from azents.core.agent import AgentModelSelection
from azents.engine.events.output_parts import iter_output_parts
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
from azents.engine.run.types import FunctionTool
from azents.engine.tooling.execution_context import get_client_tool_execution_context
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
from azents.repos.historical_memory_consolidation.drafts import (
    ConsolidationDraftRepository,
)
from azents.repos.historical_memory_consolidation.ownership import (
    ConsolidationOwnershipRepository,
)
from azents.repos.historical_memory_consolidation.sources import (
    ConsolidationSourceRepository,
)
from azents.repos.historical_memory_consolidation.work import (
    ConsolidationWorkRepository,
)
from azents.services.historical_memory.draft_vfs import (
    ConsolidationDraftVfsBackend,
    ConsolidationVfsObservations,
)
from azents.services.historical_memory.source_vfs import (
    ConsolidationSourceVfsBackend,
    ConsolidationVfsAuthorityValidator,
)
from azents.services.vfs_mutation import (
    VfsBackendRegistration,
    VfsMutationCapabilities,
    VfsMutationRegistry,
    VfsMutationRouter,
)
from azents.services.vfs_read import VfsReadBackendRegistry, VfsReadRouter

_RESULT_CAP = 12000
_RESULT_TRUNCATION = (
    "\n[Result truncated; continue with narrower search or the next read/page.]"
)


@dataclasses.dataclass(frozen=True)
class ConsolidationAdmittedTool:
    """One call, frozen writer and unchanged shared read surface."""

    call: ClientToolCallPayload
    catalog: ToolCatalog
    before: ConsolidationVfsObservations
    writer_observations: ConsolidationVfsObservations

    @property
    def call_id(self) -> str:
        return self.call.call_id

    async def execute(self) -> ClientToolResultPayload:
        result = await ToolCatalogClientToolInvoker(self.catalog).invoke(
            PreparedClientToolInvocation(
                self.call.call_id,
                self.call.name,
                self.call.arguments,
                self.call.wire_dialect,
            )
        )
        if result.pending_generated_files or result.terminal_run:
            raise RuntimeError(
                "Internal tools cannot create files or terminal actions "
                "outside the draft."
            )
        texts: list[str] = []
        for part in iter_output_parts(result.output):
            if not isinstance(part, OutputTextPart):
                raise RuntimeError("Internal tools must return bounded text only.")
            texts.append(part.text)
        text = "\n".join(texts)
        encoded = text.encode("utf-8")
        if len(encoded) > _RESULT_CAP:
            note = _RESULT_TRUNCATION.encode()
            text = (
                encoded[: _RESULT_CAP - len(note)].decode("utf-8", errors="ignore")
                + _RESULT_TRUNCATION
            )
        return ClientToolResultPayload(
            call_id=result.call_id,
            name=result.name,
            wire_dialect=result.wire_dialect,
            status=result.status,
            output=[OutputTextPart(text=text)],
            metadata=dict(result.metadata),
        )


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


@dataclasses.dataclass(frozen=True)
class ConsolidationToolBindings:
    """No foreground context, Runtime, Saved, skills, or original-history backend."""

    observations: ConsolidationVfsObservations
    draft_repository: ConsolidationDraftRepository
    source_repository: ConsolidationSourceRepository
    work_repository: ConsolidationWorkRepository
    ownership_repository: ConsolidationOwnershipRepository

    def catalog(
        self,
        selection: AgentModelSelection,
        *,
        writer: ConsolidationVfsObservations,
    ) -> ToolCatalog:
        principal = self.observations.principal
        authority = ConsolidationVfsAuthorityValidator(self.ownership_repository)
        draft = ConsolidationDraftVfsBackend(self.draft_repository, self.observations)
        sources = ConsolidationSourceVfsBackend(
            self.source_repository, self.observations, self.work_repository
        )
        storage = RoutedReadableStorage(
            principal.unit.agent_id,
            VfsReadRouter(VfsReadBackendRegistry([draft, sources]), authority),
            principal,
            None,
            None,
        )
        frozen_draft = ConsolidationDraftVfsBackend(self.draft_repository, writer)
        mutations = VfsMutationRouter(
            VfsMutationRegistry(
                [
                    VfsBackendRegistration(
                        frozen_draft,
                        frozen_draft,
                        frozen_draft,
                        VfsMutationCapabilities(True, True),
                    )
                ]
            ),
            authority,
        )
        tools = [
            make_read_text_tool(
                session_storage=storage, agent_id=principal.unit.agent_id
            ),
            make_grep_tool(session_storage=storage, agent_id=principal.unit.agent_id),
            make_glob_tool(session_storage=storage, agent_id=principal.unit.agent_id),
            *RoutedMutationTools(
                principal, mutations, {}, get_client_tool_execution_context
            ).tools(),
        ]
        return _catalog(tools, selection)

    def admit(
        self,
        calls: Sequence[ClientToolCallPayload],
        selection: AgentModelSelection,
    ) -> tuple[ConsolidationAdmittedTool, ...]:
        """Capture every sibling before the first handler can run or refresh reads."""
        before = self.observations.snapshot()
        return tuple(
            ConsolidationAdmittedTool(
                call, self.catalog(selection, writer=writer), before, writer
            )
            for call in calls
            for writer in [before.snapshot()]
        )

    def merge(self, admitted: ConsolidationAdmittedTool) -> None:
        self.observations.merge_mutations(admitted.before, admitted.writer_observations)
