"""Shared synthetic native VFS bindings for storage and tool integration tests."""

import dataclasses
import json
from collections.abc import Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.historical_memory_consolidation import ConsolidationJobPrincipal
from azents.engine.run.types import FunctionTool, FunctionToolResult
from azents.engine.tooling.execution_context import (
    client_tool_execution_context,
    get_client_tool_execution_context,
)
from azents.engine.tools.mutable_storage import RoutedMutationTools
from azents.rdb.session import SessionManager
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
from azents.services.file_storage import TextReadResult
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
from azents.testing.consolidation import seed_consolidation_corpus


@dataclasses.dataclass(frozen=True)
class ConsolidationTestVfsBinding:
    """One real current owner, closed source corpus and private file backend."""

    principal: ConsolidationJobPrincipal
    draft: ConsolidationDraftVfsBackend
    source: ConsolidationSourceVfsBackend
    reads: VfsReadRouter[ConsolidationJobPrincipal]
    mutations: VfsMutationRouter[ConsolidationJobPrincipal]

    def tools(self, runtime_tools: dict[str, FunctionTool]) -> dict[str, FunctionTool]:
        return {
            tool.spec.name: tool
            for tool in RoutedMutationTools(
                self.principal,
                self.mutations,
                runtime_tools,
                get_client_tool_execution_context,
            ).tools()
        }


async def bind_consolidation_test_vfs(
    manager: SessionManager[AsyncSession],
) -> ConsolidationTestVfsBinding:
    corpus = await seed_consolidation_corpus(manager)
    owner_repository = ConsolidationOwnershipRepository(manager)
    claim = await owner_repository.claim(corpus.team)
    assert claim is not None
    ledger = ConsolidationVfsObservations(claim.principal)
    draft = ConsolidationDraftVfsBackend(ConsolidationDraftRepository(manager), ledger)
    source = ConsolidationSourceVfsBackend(
        ConsolidationSourceRepository(manager),
        ledger,
        ConsolidationWorkRepository(manager),
    )
    authority = ConsolidationVfsAuthorityValidator(owner_repository)
    mutations = VfsMutationRouter(
        VfsMutationRegistry(
            [
                VfsBackendRegistration(
                    draft, draft, draft, VfsMutationCapabilities(True, True)
                ),
                VfsBackendRegistration(
                    source, None, None, VfsMutationCapabilities(False, False)
                ),
            ]
        ),
        authority,
    )
    return ConsolidationTestVfsBinding(
        claim.principal,
        draft,
        source,
        VfsReadRouter(
            VfsReadBackendRegistry([draft, source]),
            authority,
        ),
        mutations,
    )


async def invoke_consolidation_test_tool(
    tool: FunctionTool, call_id: str, arguments: Mapping[str, object]
) -> str | FunctionToolResult:
    with client_tool_execution_context(call_id=call_id, name=tool.spec.name):
        return await tool.handler(json.dumps(dict(arguments), ensure_ascii=False))


async def read_consolidation_test_uri(
    binding: ConsolidationTestVfsBinding, uri: str
) -> TextReadResult:
    return await binding.reads.read_text(
        binding.principal, uri, offset=0, limit=10000, encoding="utf-8"
    )
