"""Repository-owned assembly of completed, owner-fenced Engine operations."""

import dataclasses
from typing import Annotated

from fastapi import Depends

from azents.core.session_resource_authority import SessionExecutionOwner
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session_system_prompt_snapshot import (
    AgentSessionSystemPromptSnapshotRepository,
)
from azents.repos.compaction_operation import CompactionOperationRepository
from azents.repos.engine_event_contracts import (
    EventPayloadRepository,
    SessionHeadRepository,
    TranscriptRepository,
)
from azents.repos.engine_event_mutation import EngineEventMutationRepository
from azents.repos.engine_event_operation import EngineEventOperationRepository
from azents.repos.engine_execution_operation import EngineExecutionOperationRepository
from azents.repos.engine_input_projection import EngineInputProjectionRepository
from azents.repos.engine_model_input_operation import (
    EngineModelInputOperationRepository,
)
from azents.repos.engine_output_operation import (
    EngineOutputOperationRepository,
    EngineRunRepository,
)
from azents.repos.engine_run_finalization_operation import (
    EngineRunFinalizationOperationRepository,
)
from azents.repos.engine_tool_result_operation import (
    EngineToolResultOperationRepository,
)
from azents.repos.exchange_file import ExchangeFileRepository
from azents.repos.model_file import ModelFileRepository
from azents.repos.model_file_pin import ModelFilePinRepository
from azents.repos.model_operation_completion import ModelOperationCompletionRepository
from azents.repos.provider_output_operation import ProviderOutputOperationRepository
from azents.repos.session_execution.ownership import (
    OwnerBoundSessionManager,
    SessionExecutionAuthorityRepository,
)
from azents.repos.terminal_finalization import TerminalRunFinalizationRepository
from azents.repos.toolkit_state.engine import ToolWorkingSetStore


def get_engine_tool_working_set_store(
    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ],
) -> ToolWorkingSetStore:
    """Wire the completed deferred-tool store at the repository boundary."""
    return ToolWorkingSetStore(session_manager=session_manager, repository=None)


@dataclasses.dataclass(frozen=True)
class OwnerBoundEngineRepositories:
    """Completed database operations sharing the same durable execution fence."""

    authority: SessionExecutionAuthorityRepository
    events: EngineEventOperationRepository
    tool_working_set: ToolWorkingSetStore
    compaction: CompactionOperationRepository
    execution: EngineExecutionOperationRepository
    model_input: EngineModelInputOperationRepository
    tool_results: EngineToolResultOperationRepository
    output: EngineOutputOperationRepository
    finalization: EngineRunFinalizationOperationRepository


@dataclasses.dataclass(frozen=True)
class EngineEventRepositoryFactory:
    """Build completed repositories without handing Engine a session factory."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    run_repository: Annotated[EngineRunRepository, Depends(AgentRunRepository)]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    session_head_repository: Annotated[
        SessionHeadRepository, Depends(AgentSessionRepository)
    ]
    transcript_repository: Annotated[
        TranscriptRepository, Depends(EventTranscriptRepository)
    ]
    event_payload_repository: Annotated[
        EventPayloadRepository, Depends(EventTranscriptRepository)
    ]
    tool_working_set_repository: Annotated[
        ToolWorkingSetStore, Depends(get_engine_tool_working_set_store)
    ]
    system_prompt_repository: Annotated[
        AgentSessionSystemPromptSnapshotRepository,
        Depends(AgentSessionSystemPromptSnapshotRepository),
    ]
    model_file_pin_repository: Annotated[
        ModelFilePinRepository, Depends(ModelFilePinRepository)
    ]
    model_operation_repository: Annotated[
        ModelOperationCompletionRepository, Depends(ModelOperationCompletionRepository)
    ]
    terminal_repository: Annotated[
        TerminalRunFinalizationRepository, Depends(TerminalRunFinalizationRepository)
    ]
    output_metadata_repository: Annotated[
        ProviderOutputOperationRepository, Depends(ProviderOutputOperationRepository)
    ]
    compaction_repository: Annotated[
        CompactionOperationRepository, Depends(CompactionOperationRepository)
    ]
    exchange_file_repository: Annotated[
        ExchangeFileRepository, Depends(ExchangeFileRepository)
    ]
    model_file_repository: Annotated[ModelFileRepository, Depends(ModelFileRepository)]

    def for_execution(
        self, owner: SessionExecutionOwner
    ) -> OwnerBoundEngineRepositories:
        """Bind all operations before Engine begins external work."""
        manager = OwnerBoundSessionManager(
            session_manager=self.session_manager,
            session_id=owner.session_id,
            owner_generation=owner.owner_generation,
        )
        mutations = EngineEventMutationRepository(
            transcript_repository=self.transcript_repository
        )
        tool_results = EngineToolResultOperationRepository(
            session_manager=manager,
            run_repository=self.run_repository,
            transcript_repository=self.transcript_repository,
        )
        projections = EngineInputProjectionRepository(
            exchange_file_repository=self.exchange_file_repository,
            model_file_repository=self.model_file_repository,
            transcript_repository=self.event_payload_repository,
        )
        return OwnerBoundEngineRepositories(
            authority=SessionExecutionAuthorityRepository(
                session_manager=self.session_manager,
                owner=owner,
            ),
            events=EngineEventOperationRepository(
                session_manager=manager,
                run_repository=self.run_repository,
                agent_session_repository=self.agent_session_repository,
                session_head_repository=self.session_head_repository,
                transcript_repository=self.transcript_repository,
            ),
            tool_working_set=self.tool_working_set_repository.with_session_manager(
                manager
            ),
            compaction=self.compaction_repository.with_session_manager(manager),
            execution=EngineExecutionOperationRepository(
                session_manager=manager,
                run_repository=self.run_repository,
                model_file_pin_repository=self.model_file_pin_repository,
            ),
            model_input=EngineModelInputOperationRepository(
                session_manager=manager,
                run_repository=self.run_repository,
                transcript_repository=self.transcript_repository,
                session_head_repository=self.session_head_repository,
                tool_result_repository=tool_results,
                input_projection_repository=projections,
            ),
            tool_results=tool_results,
            output=EngineOutputOperationRepository(
                session_manager=manager,
                run_repository=self.run_repository,
                event_mutation_repository=mutations,
                metadata_repository=self.output_metadata_repository,
                tool_result_repository=tool_results,
                system_prompt_repository=self.system_prompt_repository,
            ),
            finalization=EngineRunFinalizationOperationRepository(
                session_manager=manager,
                run_repository=self.run_repository,
                event_mutation_repository=mutations,
                model_operation_repository=self.model_operation_repository,
                terminal_finalization_repository=self.terminal_repository,
                model_file_pin_repository=self.model_file_pin_repository,
            ),
        )
