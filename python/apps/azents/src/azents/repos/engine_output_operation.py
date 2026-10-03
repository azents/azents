"""Completed atomic database operations for Engine output admission."""

import dataclasses
import datetime
from collections.abc import Sequence
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentRunPhase
from azents.core.inference_profile import SessionInferenceState
from azents.engine.events.types import (
    ActiveToolCall,
    ClientToolCallPayload,
    ClientToolResultPayload,
    Event,
    SystemPromptAnalysisPayload,
    TokenUsagePayload,
)
from azents.rdb.session import SessionManager
from azents.repos.engine_event_contracts import (
    AgentRunCreateRepository,
    RunStateRepository,
)
from azents.repos.engine_event_mutation import EngineEventMutationRepository
from azents.repos.engine_tool_result_operation import (
    EngineToolResultOperationRepository,
)
from azents.repos.file_metadata_authority import FileResourceAuthority
from azents.repos.provider_output_operation import (
    ProviderOutputFileMetadata,
    ProviderOutputMetadataAdmission,
)


class EngineRunRepository(AgentRunCreateRepository, RunStateRepository, Protocol):
    """Combined narrow Run primitives required by Engine repository assembly."""


class OutputMetadataRepository(Protocol):
    """Narrow database-only generated-file admission dependency."""

    async def persist_in_session(
        self,
        session: AsyncSession,
        *,
        authority: FileResourceAuthority,
        generated_images: Sequence[ProviderOutputFileMetadata],
    ) -> None:
        """Admit generated metadata in the composing output transaction."""
        ...


class OutputSystemPromptRepository(Protocol):
    """Narrow Session prompt snapshot mutations."""

    async def replace(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        system_prompt: SystemPromptAnalysisPayload,
    ) -> None:
        """Replace the Session snapshot in the output transaction."""
        ...

    async def delete(self, session: AsyncSession, *, session_id: str) -> None:
        """Remove the Session snapshot when this turn has no prompt analysis."""
        ...


@dataclasses.dataclass(frozen=True)
class ModelOutputAdmission:
    """Detached model turn data used for atomic durable output admission."""

    session_id: str
    run_id: str
    owner_generation: int
    events: Sequence[Event]
    usage: TokenUsagePayload | None
    inference_state: SessionInferenceState | None
    system_prompt_analysis: SystemPromptAnalysisPayload | None
    metadata_admission: ProviderOutputMetadataAdmission | None


@dataclasses.dataclass(frozen=True)
class AdmittedModelOutput:
    """Committed Events and phase timestamp detached from the database."""

    events: list[Event]
    turn_marker: Event | None
    model_call_started_at: datetime.datetime | None


@dataclasses.dataclass(frozen=True)
class EngineOutputOperationRepository:
    """Own model output and generated client-result admission transactions."""

    session_manager: SessionManager[AsyncSession]
    run_repository: RunStateRepository
    event_mutation_repository: EngineEventMutationRepository
    metadata_repository: OutputMetadataRepository
    tool_result_repository: EngineToolResultOperationRepository
    system_prompt_repository: OutputSystemPromptRepository | None

    async def admit_model_output(
        self, admission: ModelOutputAdmission
    ) -> AdmittedModelOutput:
        """Commit metadata, Events, provenance, snapshot, retry and Tool state."""
        async with self.session_manager() as session:
            if admission.metadata_admission is not None:
                await self._admit_metadata(session, admission.metadata_admission)
            events = await self.event_mutation_repository.append_events(
                session, admission.events, tool_call_run_id=admission.run_id
            )
            turn_marker = await self.event_mutation_repository.append_turn_marker(
                session,
                session_id=admission.session_id,
                run_id=admission.run_id,
                usage=admission.usage,
                inference_state=admission.inference_state,
            )
            if self.system_prompt_repository is not None:
                if admission.system_prompt_analysis is None:
                    await self.system_prompt_repository.delete(
                        session, session_id=admission.session_id
                    )
                else:
                    await self.system_prompt_repository.replace(
                        session,
                        session_id=admission.session_id,
                        system_prompt=admission.system_prompt_analysis,
                    )
            await self.run_repository.update_retry_state(
                session, admission.run_id, None
            )
            calls = [
                event.payload
                for event in admission.events
                if isinstance(event.payload, ClientToolCallPayload)
            ]
            model_call_started_at: datetime.datetime | None = None
            if calls:
                run = await self.run_repository.update_phase(
                    session,
                    admission.run_id,
                    AgentRunPhase.EXECUTING_TOOLS,
                    active_tool_calls=[
                        ActiveToolCall(
                            call_id=call.call_id,
                            name=call.name,
                            arguments=call.arguments,
                            wire_dialect=call.wire_dialect,
                            toolkit_source=call.toolkit_source,
                            started_at=datetime.datetime.now(datetime.UTC),
                            owner_generation=admission.owner_generation,
                        )
                        for call in calls
                    ],
                )
                model_call_started_at = run.model_call_started_at
            return AdmittedModelOutput(
                events=events,
                turn_marker=turn_marker,
                model_call_started_at=model_call_started_at,
            )

    async def admit_client_tool_result(
        self,
        *,
        run_id: str,
        session_id: str,
        call: ClientToolCallPayload,
        result: ClientToolResultPayload,
        metadata_admission: ProviderOutputMetadataAdmission,
    ) -> Event:
        """Commit generated metadata and the sole terminal Tool result together."""
        async with self.session_manager() as session:
            await self._admit_metadata(session, metadata_admission)
            return await self.tool_result_repository.finalize_in_session(
                session, run_id=run_id, session_id=session_id, call=call, result=result
            )

    async def _admit_metadata(
        self, session: AsyncSession, admission: ProviderOutputMetadataAdmission
    ) -> None:
        """Compose typed metadata with no transient upload or service dependency."""
        await self.metadata_repository.persist_in_session(
            session,
            authority=admission.authority,
            generated_images=admission.generated_images,
        )
