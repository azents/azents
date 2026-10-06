"""Real canonical Memory dialogue, explicit submit and same-execution correction."""

import dataclasses
import datetime
import json
from collections.abc import Sequence

import pytest
import sqlalchemy as sa

from azents.core.agent import AgentModelSelection, SelectableModelCandidate
from azents.core.enums import AgentRunStatus, AgentSessionRunState, EventKind
from azents.core.historical_memory_budget import ConsolidationTurnLimitExceeded
from azents.core.historical_memory_consolidation import (
    FreshMemoryAdmission,
    MemoryAcceptedOutcome,
    MemoryExecutionPrincipal,
    MemorySubmissionUncertainError,
)
from azents.core.historical_memory_system_setting import HistoricalMemoryExecutionConfig
from azents.core.llm_catalog import ModelCapabilities, ModelToolCallingCapabilities
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.engine.context.compaction import SummaryModelCall
from azents.engine.events.model_messages import (
    TransientModelMessage,
    transient_model_message,
)
from azents.engine.events.protocols import NormalizedAdapterOutput
from azents.engine.events.tools import ToolCatalog
from azents.engine.events.types import (
    AssistantMessagePayload,
    ClientToolCallPayload,
    ClientToolResultPayload,
    NativeArtifact,
    build_native_compat_key,
)
from azents.engine.model_stream import (
    ModelDispatchAdmissionError,
    ModelStreamCallContext,
)
from azents.engine.provider_model_operation import (
    PreparedModelOperation,
    prepare_model_operation_request,
)
from azents.engine.run.model_transport import (
    InMemoryModelTransportState,
    ModelTransportState,
)
from azents.rdb.models.agent_run import RDBAgentRun
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.event import RDBEvent
from azents.rdb.models.session_execution_file import RDBSessionExecutionFile
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.compaction_operation import CompactionOperationRepository
from azents.repos.historical_memory_consolidation.execution import (
    MemoryExecutionRepository,
)
from azents.repos.memory_execution_events import MemoryExecutionEventsRepository
from azents.repos.model_candidate_health import ModelCandidateHealthRepository
from azents.repos.model_operation_completion import ModelOperationCompletionRepository
from azents.repos.session_execution_file import SessionExecutionFileRepository
from azents.repos.session_execution_record import SessionExecutionRecordRepository
from azents.repos.toolkit_state.engine import ToolWorkingSetStore
from azents.services.historical_memory.consolidation_host import (
    ConsolidationIterationHost,
)
from azents.services.historical_memory.consolidation_tools import (
    ConsolidationToolBindings,
)
from azents.services.historical_memory.execution_context import (
    MemoryExecutionContextService,
)
from azents.testing.consolidation import (
    memory_execution_repository,
    seed_consolidation_corpus,
)
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_model_settings,
)


def _native() -> NativeArtifact:
    return NativeArtifact(
        compat_key=build_native_compat_key(
            adapter="synthetic",
            native_format="test_output",
            provider="openai",
            model="gpt-4o",
            schema_version="1",
        ),
        adapter="synthetic",
        native_format="test_output",
        provider="openai",
        model="gpt-4o",
        schema_version="1",
        item={"type": "synthetic"},
    )


def _call(
    name: str, call_id: str, arguments: dict[str, object]
) -> TransientModelMessage:
    return transient_model_message(
        EventKind.CLIENT_TOOL_CALL,
        ClientToolCallPayload(
            call_id=call_id,
            name=name,
            arguments=json.dumps(arguments),
            wire_dialect="json_function",
            native_artifact=_native(),
        ),
    )


def _final() -> TransientModelMessage:
    return transient_model_message(
        EventKind.ASSISTANT_MESSAGE,
        AssistantMessagePayload(
            content="I have finished the memory.", native_artifact=_native()
        ),
    )


def _selection() -> AgentModelSelection:
    return make_test_model_selection().model_copy(
        update={
            "normalized_capabilities": ModelCapabilities(
                tool_calling=ModelToolCallingCapabilities(supported=True)
            )
        }
    )


@dataclasses.dataclass
class _ScriptedModel:
    script: list[list[TransientModelMessage]]
    close_failure: bool
    selection: AgentModelSelection = dataclasses.field(default_factory=_selection)
    effective_input_tokens: int = 128_000
    max_output_tokens: int | None = None
    prompts: list[str] = dataclasses.field(default_factory=list)
    prepared_inputs: list[str] = dataclasses.field(default_factory=list)
    contexts: list[ModelStreamCallContext] = dataclasses.field(default_factory=list)
    closed: bool = False
    credential_kwargs: dict[str, object] = dataclasses.field(
        default_factory=lambda: {"api_key": "synthetic"}
    )
    transport_state: ModelTransportState = dataclasses.field(
        default_factory=lambda: InMemoryModelTransportState(websocket_enabled=False)
    )

    @property
    def candidate(self) -> SelectableModelCandidate:
        return SelectableModelCandidate(
            model_selection=self.selection, settings=make_test_model_settings()
        )

    @property
    def summary_call(self) -> SummaryModelCall:
        async def summarize(
            *,
            candidate: SelectableModelCandidate,
            credential_kwargs: dict[str, object],
            effective_input_tokens: int,
            transport_state: ModelTransportState,
            system_prompt: str,
            user_prompt: str,
            conversation_text: str,
            session_id: str | None = None,
        ) -> str:
            raise AssertionError(
                "This ordinary-sized execution does not need compaction."
            )

        return summarize

    def prepare(
        self,
        messages: Sequence[TransientModelMessage],
        catalog: ToolCatalog | None,
        *,
        system_prompt: str,
        output_tokens: int | None,
    ) -> PreparedModelOperation:
        self.prompts.append(system_prompt)
        prepared = prepare_model_operation_request(
            selection=self.selection,
            messages=messages,
            catalog=catalog,
            system_prompt=system_prompt,
            output_tokens=output_tokens,
        )
        self.prepared_inputs.append(str(prepared.request))
        return prepared

    async def invoke(
        self,
        prepared: PreparedModelOperation,
        *,
        context: ModelStreamCallContext,
    ) -> NormalizedAdapterOutput[TransientModelMessage]:
        self.contexts.append(context)
        assert self.script, "Accepted submit must not request another model turn."
        return NormalizedAdapterOutput[TransientModelMessage](
            events=self.script.pop(0), needs_follow_up=False
        )

    async def close(self) -> None:
        self.closed = True
        if self.close_failure:
            raise RuntimeError("Synthetic close fault after durable acceptance")


async def _never_stop() -> bool:
    return False


async def _host(
    manager: SessionManager[WriteSession],
    model: _ScriptedModel,
    *,
    max_turns: int | None,
) -> ConsolidationIterationHost:
    corpus = await seed_consolidation_corpus(manager)
    executions = memory_execution_repository(manager)
    binding = await executions.ensure_execution(
        corpus.team,
        admission=FreshMemoryAdmission(
            deadline_at=datetime.datetime.now(datetime.UTC)
            + datetime.timedelta(minutes=5),
            execution_policy=HistoricalMemoryExecutionConfig(max_turns=max_turns),
        ),
    )
    assert binding is not None
    records = SessionExecutionRecordRepository()
    async with manager() as session:
        generation = await records.claim_owner_generation(session, binding.session_id)
    principal = await executions.open_run(
        binding, SessionExecutionOwner(binding.session_id, generation)
    )
    await executions.provision_inputs(principal)
    transcript = EventTranscriptRepository()
    runs = AgentRunRepository()
    completion = ModelOperationCompletionRepository(
        AgentSessionRepository(), runs, ModelCandidateHealthRepository(manager)
    )
    context = MemoryExecutionContextService(
        MemoryExecutionEventsRepository(
            manager, manager, executions, transcript, records, runs
        ),
        CompactionOperationRepository(
            manager, transcript, records, completion, ToolWorkingSetStore(manager), None
        ),
    )
    return ConsolidationIterationHost(
        principal,
        model,
        ConsolidationToolBindings(
            principal, SessionExecutionFileRepository(manager), executions
        ),
        executions,
        context,
        _never_stop,
    )


async def _stored_events(
    manager: SessionManager[WriteSession],
    principal: MemoryExecutionPrincipal,
) -> list[RDBEvent]:
    async with manager() as session:
        return list(
            await session.read_session.scalars(
                sa.select(RDBEvent)
                .where(RDBEvent.session_id == principal.owner.session_id)
                .order_by(RDBEvent.id)
            )
        )


async def test_final_prose_feedback_and_sibling_submit_keep_one_durable_execution(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    model = _ScriptedModel(
        [
            [_final()],
            [
                _call(
                    "submit_memory", "wrong", {"path": "azents://execution/missing.md"}
                )
            ],
            [
                _call(
                    "submit_memory",
                    "accepted",
                    {"path": "azents://execution/memory.md"},
                ),
                _call(
                    "write",
                    "author",
                    {
                        "path": "azents://execution/memory.md",
                        "content": (
                            "# Useful context\nVerified task remains in progress.\n"
                        ),
                        "overwrite": False,
                    },
                ),
            ],
        ],
        close_failure=False,
    )
    host = await _host(rdb_session_manager, model, max_turns=5)
    outcome = await host.run()
    assert outcome.tool_call_id == "accepted"
    assert host.started_turns == 3 and len(model.contexts) == 3
    assert model.closed and not model.script
    assert all(
        context.session_id == host.principal.owner.session_id
        for context in model.contexts
    )
    assert all(context.run_id == host.principal.run_id for context in model.contexts)
    rows = await _stored_events(rdb_session_manager, host.principal)
    assert sum(row.kind is EventKind.USER_MESSAGE for row in rows) >= 3
    results = [
        ClientToolResultPayload.model_validate(row.payload)
        for row in rows
        if row.kind is EventKind.CLIENT_TOOL_RESULT
    ]
    assert [result.call_id for result in results] == ["wrong", "author", "accepted"]
    assert results[0].status == "failed"
    assert results[0].metadata["kind"] == "memory_submission_feedback"
    assert results[-1].status == "completed"
    assert "no explicit submission has been accepted" in model.prepared_inputs[1]
    assert "Submit a writable authored Markdown file." in model.prepared_inputs[2]
    for prompt in model.prompts:
        assert "coverage.json" not in prompt
        assert "## Historical Context" not in prompt
        assert "previous integrated" not in prompt
    async with rdb_session_manager() as session:
        run = await session.read_session.get(RDBAgentRun, host.principal.run_id)
        record = await session.read_session.get(
            RDBAgentSession, host.principal.owner.session_id
        )
        assert run is not None and run.status is AgentRunStatus.COMPLETED
        assert record is not None and record.run_state is AgentSessionRunState.IDLE
        files = list(
            await session.read_session.scalars(
                sa.select(RDBSessionExecutionFile).where(
                    RDBSessionExecutionFile.session_id
                    == host.principal.owner.session_id
                )
            )
        )
        assert any(
            file.path.startswith("inputs/") and not file.writable for file in files
        )
        assert any(file.path == "memory.md" and file.writable for file in files)
    result = await host.execution_repository.current_result(host.principal.binding.unit)
    assert result is not None and "Verified task" in result.markdown


async def test_accepted_submit_survives_model_close_failure(
    rdb_session_manager: SessionManager[WriteSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    model = _ScriptedModel(
        [
            [
                _call(
                    "write",
                    "write",
                    {
                        "path": "azents://execution/result.md",
                        "content": "",
                        "overwrite": False,
                    },
                ),
                _call(
                    "submit_memory", "empty", {"path": "azents://execution/result.md"}
                ),
            ]
        ],
        close_failure=True,
    )
    host = await _host(rdb_session_manager, model, max_turns=2)
    outcome = await host.run()
    assert outcome.tool_call_id == "empty"
    assert model.closed and host.closed
    assert "transport cleanup failed" in caplog.text
    observed = await host.execution_repository.inspect_accepted(
        host.principal.owner.session_id, tool_call_id="empty"
    )
    assert observed == outcome


async def test_unsubmitted_turn_limit_retains_files_dialogue_and_pending_truth(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    model = _ScriptedModel([[_final()], [_final()]], close_failure=False)
    host = await _host(rdb_session_manager, model, max_turns=2)
    with pytest.raises(ConsolidationTurnLimitExceeded):
        await host.run()
    assert len(model.contexts) == 2 and model.closed
    binding = await host.execution_repository.load_binding(
        host.principal.owner.session_id
    )
    assert (
        binding is not None and binding.started_turns == 2 and binding.accepted is None
    )
    assert await host.execution_repository.current_result(binding.unit) is None
    rows = await _stored_events(rdb_session_manager, host.principal)
    assert sum(row.kind is EventKind.ASSISTANT_MESSAGE for row in rows) == 2


async def test_owner_loss_at_physical_dispatch_preserves_admission_rejection(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """Rejected I/O cannot settle stale usage and replace its safe admission error."""

    class LostOwnerModel(_ScriptedModel):
        async def invoke(
            self,
            prepared: PreparedModelOperation,
            *,
            context: ModelStreamCallContext,
        ) -> NormalizedAdapterOutput[TransientModelMessage]:
            assert context.session_id is not None and context.check_stop is not None
            async with rdb_session_manager() as session:
                await SessionExecutionRecordRepository().claim_owner_generation(
                    session, context.session_id
                )
            await context.check_stop()
            raise AssertionError("The stale owner must not reach provider I/O.")

    model = LostOwnerModel([], close_failure=False)
    host = await _host(rdb_session_manager, model, max_turns=2)
    with pytest.raises(ModelDispatchAdmissionError) as failure:
        await host.run()
    assert failure.value.reason == "ownership"
    assert model.closed
    rows = await _stored_events(rdb_session_manager, host.principal)
    assert not any(row.kind is EventKind.ASSISTANT_MESSAGE for row in rows)


@dataclasses.dataclass(frozen=True)
class _LostAcknowledgement(MemoryExecutionRepository):
    calls: list[str]

    async def submit(
        self,
        principal: MemoryExecutionPrincipal,
        *,
        tool_call_id: str,
        authored_path: str,
    ) -> MemoryAcceptedOutcome:
        self.calls.append(tool_call_id)
        await super().submit(
            principal, tool_call_id=tool_call_id, authored_path=authored_path
        )
        raise MemorySubmissionUncertainError("Synthetic accepted acknowledgement loss")


async def test_uncertain_submit_resolves_original_outcome_without_repeating_model(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    model = _ScriptedModel(
        [
            [
                _call(
                    "write",
                    "write",
                    {
                        "path": "azents://execution/result.md",
                        "content": "# Exactly one accepted result",
                        "overwrite": False,
                    },
                ),
                _call(
                    "submit_memory",
                    "original",
                    {
                        "path": "azents://execution/result.md",
                    },
                ),
            ]
        ],
        close_failure=False,
    )
    host = await _host(rdb_session_manager, model, max_turns=3)
    calls: list[str] = []
    uncertain = _LostAcknowledgement(
        rdb_session_manager,
        rdb_session_manager,
        host.execution_repository.model_operation_completion_repository,
        calls,
    )
    host.execution_repository = uncertain
    host.tools.executions = uncertain
    outcome = await host.run()
    assert outcome.tool_call_id == "original" and calls == ["original"]
    assert len(model.contexts) == 1 and not model.script
    rows = await _stored_events(rdb_session_manager, host.principal)
    results = [
        ClientToolResultPayload.model_validate(row.payload)
        for row in rows
        if row.kind is EventKind.CLIENT_TOOL_RESULT
    ]
    assert results[-1].call_id == "original"
    assert results[-1].status == "completed"


@dataclasses.dataclass(frozen=True)
class _AcceptedAuditFault(MemoryExecutionContextService):
    async def append(
        self,
        principal: MemoryExecutionPrincipal,
        messages: Sequence[TransientModelMessage],
        *,
        accepted: MemoryAcceptedOutcome | None,
    ) -> None:
        if accepted is not None:
            raise RuntimeError("Synthetic accepted audit append fault")
        await super().append(principal, messages, accepted=None)


async def test_accepted_tool_result_audit_fault_is_secondary_health(
    rdb_session_manager: SessionManager[WriteSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    model = _ScriptedModel(
        [
            [
                _call(
                    "write",
                    "write",
                    {
                        "path": "azents://execution/result.md",
                        "content": "",
                        "overwrite": False,
                    },
                ),
                _call(
                    "submit_memory",
                    "accepted",
                    {
                        "path": "azents://execution/result.md",
                    },
                ),
            ]
        ],
        close_failure=False,
    )
    host = await _host(rdb_session_manager, model, max_turns=3)
    context = host.context_port
    assert isinstance(context, MemoryExecutionContextService)
    host.context_port = _AcceptedAuditFault(
        context.repository, context.compaction_operations
    )
    outcome = await host.run()
    assert outcome.tool_call_id == "accepted" and len(model.contexts) == 1
    assert "audit follow-up failed" in caplog.text
    assert (
        await host.execution_repository.inspect_accepted(
            outcome.session_id, tool_call_id=outcome.tool_call_id
        )
        == outcome
    )
