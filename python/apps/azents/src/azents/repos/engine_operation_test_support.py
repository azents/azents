"""Recording persistence fixtures for composed Engine operation regressions."""

import copy
import datetime
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentRunParentResultDeliveryState,
    AgentRunPhase,
    AgentRunStatus,
    EventKind,
)
from azents.engine.events.types import (
    ActiveToolCall,
    AgentRunState,
    AssistantMessagePayload,
    ClientToolCallPayload,
    Event,
    NativeArtifact,
    OutputTextPart,
    SystemPromptAnalysisPayload,
    TokenUsagePayload,
    build_native_compat_key,
    validate_event_payload,
)
from azents.engine.run.failure import FailedRunRetryState
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.engine_event_mutation import EngineEventMutationRepository
from azents.repos.engine_output_operation import EngineOutputOperationRepository
from azents.repos.engine_run_finalization_operation import (
    EngineRunFinalizationOperationRepository,
)
from azents.repos.engine_tool_result_operation import (
    EngineToolResultOperationRepository,
)
from azents.repos.file_metadata_authority import FileResourceAuthority
from azents.repos.model_operation_completion import ModelOperationCompletion
from azents.repos.provider_output_operation import (
    ProviderOutputFileMetadata,
    ProviderOutputMetadataAdmission,
)
from azents.repos.terminal_finalization import TerminalRunFinalizationRepository
from azents.repos.terminal_finalization_data import (
    TerminalDeliveryDisposition,
    TerminalFinalizationOutcome,
)

NOW = datetime.datetime(2026, 10, 2, tzinfo=datetime.UTC)
RUN_ID = "1" * 32
SESSION_ID = "2" * 32
FailurePoint = Literal[
    "metadata",
    "events",
    "turn_marker",
    "snapshot",
    "retry",
    "phase",
    "commit",
    "marker",
    "completion",
    "prelock",
    "terminal",
    "delivery",
    "pins",
]


@dataclass
class PersistenceState:
    """Authoritative test state committed or restored as one database group."""

    run: AgentRunState | None
    events: list[Event]
    metadata: list[ProviderOutputMetadataAdmission]
    prompt: SystemPromptAnalysisPayload | None
    completions: list[ModelOperationCompletion]
    deliveries: list[str]
    released_pins: list[str]


class RecordingSessionManager:
    """Require one active session and restore all persistence on failure."""

    def __init__(
        self,
        state: PersistenceState,
        *,
        failure_point: FailurePoint | None,
        failure: BaseException | None,
    ) -> None:
        self.state = state
        self.failure_point = failure_point
        self.failure = failure
        self.active = False
        self.sessions: list[AsyncSession] = []
        self.commits = 0
        self.rollbacks = 0
        self.order: list[str] = []

    def check(self, session: AsyncSession, operation: str) -> None:
        """Record a narrow DB operation in its caller's one active session."""
        assert self.active
        assert session is self.sessions[-1]
        self.order.append(operation)

    def fail(self, point: FailurePoint) -> None:
        """Raise at a named persisted mutation, never at an external callback."""
        if point == self.failure_point:
            assert self.failure is not None
            raise self.failure

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[AsyncSession]:
        """Commit on clean exit and abort every member on late failure."""
        assert not self.active
        before = copy.deepcopy(self.state)
        session = AsyncSession()
        self.sessions.append(session)
        self.active = True
        try:
            yield session
            self.fail("commit")
            self.commits += 1
            self.order.append("commit")
        except BaseException:
            self.state.run = before.run
            self.state.events = before.events
            self.state.metadata = before.metadata
            self.state.prompt = before.prompt
            self.state.completions = before.completions
            self.state.deliveries = before.deliveries
            self.state.released_pins = before.released_pins
            self.rollbacks += 1
            raise
        finally:
            self.active = False
            await session.close()


class RecordingRunRepository(AgentRunRepository):
    """Apply Run mutations to shared state in the composed session."""

    def __init__(self, manager: RecordingSessionManager) -> None:
        self.manager = manager

    async def get_by_id(
        self, session: AsyncSession, run_id: str
    ) -> AgentRunState | None:
        """Read current authoritative Run state."""
        assert run_id == RUN_ID
        self.manager.check(session, "read_run")
        return self.manager.state.run

    async def lock_by_id(
        self, session: AsyncSession, run_id: str
    ) -> AgentRunState | None:
        """Record the existing result-append-before-Run-lock order."""
        self.manager.check(session, "lock_run")
        return await self.get_by_id(session, run_id)

    async def update_retry_state(
        self,
        session: AsyncSession,
        run_id: str,
        retry_state: FailedRunRetryState | None,
    ) -> AgentRunState:
        """Clear retry state in the model output admission atomic group."""
        assert run_id == RUN_ID
        self.manager.check(session, "retry")
        run = self.manager.state.run
        assert run is not None
        updated = run.model_copy(update={"retry_state": retry_state})
        self.manager.state.run = updated
        self.manager.fail("retry")
        return updated

    async def update_phase(
        self,
        session: AsyncSession,
        run_id: str,
        phase: AgentRunPhase,
        *,
        active_tool_calls: list[ActiveToolCall] | None = None,
    ) -> AgentRunState:
        """Admit the complete active Tool set with the output Events."""
        assert run_id == RUN_ID
        self.manager.check(session, "phase")
        run = self.manager.state.run
        assert run is not None
        updated = run.model_copy(
            update={
                "phase": phase,
                "model_call_started_at": None,
                "active_tool_calls": run.active_tool_calls
                if active_tool_calls is None
                else active_tool_calls,
            }
        )
        self.manager.state.run = updated
        self.manager.fail("phase")
        return updated

    async def mark_terminal(
        self,
        session: AsyncSession,
        run_id: str,
        status: AgentRunStatus,
        *,
        ended_at: datetime.datetime,
        last_completed_event_id: str | None = None,
        terminal_result_event_id: str | None = None,
        terminal_result_message: str | None = None,
    ) -> AgentRunState:
        """Record terminal fields before parent finalization and pin release."""
        assert run_id == RUN_ID
        self.manager.check(session, "terminal")
        run = self.manager.state.run
        assert run is not None
        updated = run.model_copy(
            update={
                "status": status,
                "ended_at": ended_at,
                "last_completed_event_id": last_completed_event_id,
                "terminal_result_event_id": terminal_result_event_id,
                "terminal_result_message": terminal_result_message,
            }
        )
        self.manager.state.run = updated
        self.manager.fail("terminal")
        return updated

    async def mark_parent_result_suppressed(
        self,
        session: AsyncSession,
        *,
        run_id: str,
        finalized_at: datetime.datetime,
    ) -> AgentRunState:
        """Keep bridge suppression distinct from actual parent delivery."""
        assert run_id == RUN_ID
        self.manager.check(session, "suppress_parent")
        run = self.manager.state.run
        assert run is not None
        updated = run.model_copy(
            update={
                "parent_result_delivery_state": (
                    AgentRunParentResultDeliveryState.SUPPRESSED
                ),
                "parent_result_enqueued_at": finalized_at,
            }
        )
        self.manager.state.run = updated
        self.manager.fail("delivery")
        return updated


class RecordingTranscriptRepository(EventTranscriptRepository):
    """Serialize immutable typed Events and deterministic identities."""

    def __init__(self, manager: RecordingSessionManager) -> None:
        self.manager = manager

    async def append(self, session: AsyncSession, create: EventCreate) -> Event:
        """Append inside one atomic group and support deterministic duplicates."""
        self.manager.check(session, f"append:{create.kind.value}")
        if create.external_id is not None:
            for event in self.manager.state.events:
                if event.external_id == create.external_id:
                    return event
        next_id = (
            max((int(event.id) for event in self.manager.state.events), default=0) + 1
        )
        event = Event(
            id=f"{next_id:032d}",
            session_id=create.session_id,
            kind=create.kind,
            payload=validate_event_payload(create.kind, create.payload),
            external_id=create.external_id,
            adapter=create.adapter,
            provider=create.provider,
            model=create.model,
            native_format=create.native_format,
            schema_version=create.schema_version,
            created_at=NOW,
        )
        self.manager.state.events.append(event)
        if create.kind is EventKind.TURN_MARKER:
            self.manager.fail("turn_marker")
        elif create.kind is EventKind.RUN_MARKER:
            self.manager.fail("marker")
        else:
            self.manager.fail("events")
        return event

    async def get_by_external_id(
        self,
        session: AsyncSession,
        session_id: str,
        external_id: str,
    ) -> Event | None:
        """Observe marker identity lookup before idempotent append."""
        assert session_id == SESSION_ID
        self.manager.check(session, "find_marker")
        return next(
            (
                event
                for event in self.manager.state.events
                if event.external_id == external_id
            ),
            None,
        )


class RecordingMetadataRepository:
    """Admit detached file metadata without any prepared output object."""

    def __init__(self, manager: RecordingSessionManager) -> None:
        self.manager = manager

    async def persist_in_session(
        self,
        session: AsyncSession,
        *,
        authority: FileResourceAuthority,
        generated_images: Sequence[ProviderOutputFileMetadata],
    ) -> None:
        """Record metadata before Events in the composing output session."""
        self.manager.check(session, "metadata")
        self.manager.state.metadata.append(
            ProviderOutputMetadataAdmission(
                authority=authority,
                generated_images=tuple(generated_images),
            )
        )
        self.manager.fail("metadata")


class RecordingPromptRepository:
    """Replace or delete the current Session snapshot atomically with output."""

    def __init__(self, manager: RecordingSessionManager) -> None:
        self.manager = manager

    async def replace(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        system_prompt: SystemPromptAnalysisPayload,
    ) -> None:
        """Record the exact immutable prompt analysis supplied for this turn."""
        assert session_id == SESSION_ID
        self.manager.check(session, "snapshot_replace")
        self.manager.state.prompt = system_prompt
        self.manager.fail("snapshot")

    async def delete(self, session: AsyncSession, *, session_id: str) -> None:
        """Delete stale analysis when the prepared model call has none."""
        assert session_id == SESSION_ID
        self.manager.check(session, "snapshot_delete")
        self.manager.state.prompt = None
        self.manager.fail("snapshot")


class RecordingCompletionRepository:
    """Settle typed model-operation authority in the terminal transaction."""

    def __init__(self, manager: RecordingSessionManager) -> None:
        self.manager = manager

    async def complete_success_in_session(
        self,
        session: AsyncSession,
        completion: ModelOperationCompletion,
    ) -> None:
        """Record foreground completion without an injected application callback."""
        self.manager.check(session, "completion")
        self.manager.state.completions.append(completion)
        self.manager.fail("completion")


class RecordingTerminalRepository(TerminalRunFinalizationRepository):
    """Record the unchanged Phase 27 prelock and parent delivery interface."""

    def __init__(self, manager: RecordingSessionManager) -> None:
        self.manager = manager

    async def lock_run_finalization(
        self,
        session: AsyncSession,
        *,
        run_id: str,
    ) -> None:
        """Preserve branch-specific terminal prelock position."""
        assert run_id == RUN_ID
        self.manager.check(session, "prelock")
        self.manager.fail("prelock")

    async def finalize_run_in_session(
        self,
        session: AsyncSession,
        *,
        run_id: str,
    ) -> TerminalFinalizationOutcome:
        """Record direct-parent finalization in the same terminal transaction."""
        self.manager.check(session, "delivery")
        self.manager.state.deliveries.append(run_id)
        self.manager.fail("delivery")
        return TerminalFinalizationOutcome(
            run_id=run_id,
            disposition=TerminalDeliveryDisposition.ENQUEUED,
            mailbox_item_id="3" * 32,
        )


class RecordingPinRepository:
    """Record ModelFile pin release last in terminal database work."""

    def __init__(self, manager: RecordingSessionManager) -> None:
        self.manager = manager

    async def release_run(self, session: AsyncSession, *, run_id: str) -> None:
        """Release only this Run's pins inside the terminal atomic group."""
        self.manager.check(session, "pins")
        self.manager.state.released_pins.append(run_id)
        self.manager.fail("pins")


@dataclass(frozen=True)
class EngineOperationFixture:
    """Completed operation repositories and their observable persistence."""

    manager: RecordingSessionManager
    output: EngineOutputOperationRepository
    finalization: EngineRunFinalizationOperationRepository


def operation_fixture(
    *,
    run: AgentRunState | None,
    events: list[Event],
    prompt: SystemPromptAnalysisPayload | None,
    failure_point: FailurePoint | None,
    failure: BaseException | None,
) -> EngineOperationFixture:
    """Compose the real output and terminal repositories around recording queries."""
    state = PersistenceState(
        run=run,
        events=list(events),
        metadata=[],
        prompt=prompt,
        completions=[],
        deliveries=[],
        released_pins=[],
    )
    manager = RecordingSessionManager(
        state,
        failure_point=failure_point,
        failure=failure,
    )
    runs = RecordingRunRepository(manager)
    transcript = RecordingTranscriptRepository(manager)
    mutations = EngineEventMutationRepository(transcript_repository=transcript)
    return EngineOperationFixture(
        manager=manager,
        output=EngineOutputOperationRepository(
            session_manager=manager,
            run_repository=runs,
            event_mutation_repository=mutations,
            metadata_repository=RecordingMetadataRepository(manager),
            tool_result_repository=EngineToolResultOperationRepository(
                session_manager=manager,
                run_repository=runs,
                transcript_repository=transcript,
            ),
            system_prompt_repository=RecordingPromptRepository(manager),
        ),
        finalization=EngineRunFinalizationOperationRepository(
            session_manager=manager,
            run_repository=runs,
            event_mutation_repository=mutations,
            model_operation_repository=RecordingCompletionRepository(manager),
            terminal_finalization_repository=RecordingTerminalRepository(manager),
            model_file_pin_repository=RecordingPinRepository(manager),
        ),
    )


def running_run() -> AgentRunState:
    """Build one current Run snapshot for atomicity and branch tests."""
    return AgentRunState(
        id=RUN_ID,
        session_id=SESSION_ID,
        scheduled_task_cycle_id=None,
        run_index=1,
        phase=AgentRunPhase.APPENDING_EVENTS,
        status=AgentRunStatus.RUNNING,
        parent_agent_run_id=None,
        requested_model_target_label=None,
        requested_reasoning_effort=None,
        requested_enabled_execution_options=[],
        active_tool_calls=[],
        parent_result_delivery_state=None,
        parent_result_mailbox_item_id=None,
        parent_result_enqueued_at=None,
        created_at=NOW,
        started_at=NOW,
        model_call_started_at=NOW,
        updated_at=NOW,
    )


def native_artifact() -> NativeArtifact:
    """Create immutable provider metadata used by Event serialization tests."""
    return NativeArtifact(
        compat_key=build_native_compat_key(
            adapter="test",
            native_format="responses",
            provider="test",
            model="test",
            schema_version="1",
        ),
        adapter="test",
        native_format="responses",
        provider="test",
        model="test",
        schema_version="1",
        item={"type": "message"},
    )


def assistant_event() -> Event:
    """Create text with exact terminal whitespace normalization expectations."""
    return Event(
        id=f"{8:032d}",
        session_id=SESSION_ID,
        kind=EventKind.ASSISTANT_MESSAGE,
        payload=AssistantMessagePayload(
            content=[OutputTextPart(text=" final response ")],
            native_artifact=native_artifact(),
        ),
        adapter="test",
        provider="test",
        model="test",
        native_format="responses",
        schema_version="1",
        created_at=NOW,
    )


def tool_call_event() -> Event:
    """Create one durable foreground call with a deterministic admission identity."""
    return Event(
        id=f"{9:032d}",
        session_id=SESSION_ID,
        kind=EventKind.CLIENT_TOOL_CALL,
        payload=ClientToolCallPayload(
            call_id="call-1",
            name="read",
            arguments="{}",
            wire_dialect="json_function",
            native_artifact=native_artifact(),
        ),
        created_at=NOW,
    )


def token_usage() -> TokenUsagePayload:
    """Create one immutable usage record for the output marker atomic group."""
    return TokenUsagePayload(
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        raw={},
    )


def metadata_admission() -> ProviderOutputMetadataAdmission:
    """Provide typed metadata admission identity with no transient upload handle."""
    return ProviderOutputMetadataAdmission(
        authority=FileResourceAuthority(
            workspace_id="workspace-1",
            agent_id="agent-1",
            session_id=SESSION_ID,
            root_session_id=SESSION_ID,
            run_id=RUN_ID,
            run_index=1,
            owner_generation=1,
        ),
        generated_images=(),
    )
