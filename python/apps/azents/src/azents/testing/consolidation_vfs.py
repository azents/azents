"""Real common Session bindings for current private file and tool tests."""

import dataclasses
import json
from collections.abc import Mapping

import sqlalchemy as sa
from uuid6 import uuid7

from azents.core.enums import AgentRunPhase, AgentRunStatus
from azents.core.historical_memory_consolidation import (
    ConsolidationUnitKey,
    FreshMemoryAdmission,
    MemoryExecutionPrincipal,
)
from azents.core.historical_memory_system_setting import HistoricalMemoryExecutionConfig
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.engine.run.types import FunctionTool, FunctionToolResult
from azents.engine.tooling.execution_context import (
    client_tool_execution_context,
    get_client_tool_execution_context,
)
from azents.engine.tools.mutable_storage import RoutedMutationTools
from azents.rdb.models.agent_run import RDBAgentRun
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.session_execution_file import SessionExecutionFileRepository
from azents.repos.session_execution_record import SessionExecutionRecordRepository
from azents.services.file_storage import TextReadResult
from azents.services.historical_memory.consolidation_tools import (
    ConsolidationToolBindings,
    MemoryFileAuthority,
)
from azents.services.session_execution_files import (
    SessionExecutionFileBackend,
)
from azents.services.vfs_mutation import (
    VfsBackendRegistration,
    VfsMutationCapabilities,
    VfsMutationRegistry,
    VfsMutationRouter,
)
from azents.services.vfs_read import VfsReadBackendRegistry, VfsReadRouter
from azents.testing.consolidation import (
    ConsolidationCorpus,
    consolidation_deadline,
    memory_execution_repository,
    seed_consolidation_corpus,
)


async def create_memory_test_principal(
    manager: SessionManager[WriteSession], key: ConsolidationUnitKey
) -> MemoryExecutionPrincipal:
    repository = memory_execution_repository(manager)
    binding = await repository.ensure_execution(
        key,
        admission=FreshMemoryAdmission(
            consolidation_deadline(),
            HistoricalMemoryExecutionConfig(),
        ),
    )
    assert binding is not None
    async with manager() as session:
        generation = await SessionExecutionRecordRepository().claim_owner_generation(
            session, binding.session_id
        )
        run_id = uuid7().hex
        await session.write_session.execute(
            sa.insert(RDBAgentRun).values(
                id=run_id,
                session_id=binding.session_id,
                run_index=1,
                parent_agent_run_id=None,
                phase=AgentRunPhase.IDLE,
                status=AgentRunStatus.RUNNING,
            )
        )
    return MemoryExecutionPrincipal(
        binding, SessionExecutionOwner(binding.session_id, generation), run_id
    )


@dataclasses.dataclass(frozen=True)
class ConsolidationTestVfsBinding:
    corpus: ConsolidationCorpus
    principal: MemoryExecutionPrincipal
    backend: SessionExecutionFileBackend
    reads: VfsReadRouter[MemoryExecutionPrincipal]
    mutations: VfsMutationRouter[MemoryExecutionPrincipal]
    bindings: ConsolidationToolBindings

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
    manager: SessionManager[WriteSession],
) -> ConsolidationTestVfsBinding:
    corpus = await seed_consolidation_corpus(manager)
    principal = await create_memory_test_principal(manager, corpus.team)
    executions = memory_execution_repository(manager)
    await executions.provision_inputs(principal)
    files = SessionExecutionFileRepository(manager)
    bindings = ConsolidationToolBindings(principal, files, executions)
    backend = SessionExecutionFileBackend(files, bindings.observations)
    authority = MemoryFileAuthority(executions)
    mutations = VfsMutationRouter(
        VfsMutationRegistry(
            [
                VfsBackendRegistration(
                    backend, backend, backend, VfsMutationCapabilities(True, True)
                ),
            ]
        ),
        authority,
    )
    return ConsolidationTestVfsBinding(
        corpus,
        principal,
        backend,
        VfsReadRouter(VfsReadBackendRegistry([backend]), authority),
        mutations,
        bindings,
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
