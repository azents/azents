"""Completed database operations for Engine execution lifecycle state."""

import dataclasses
import datetime
from collections.abc import Sequence
from typing import Protocol

from azents.core.enums import AgentRunPhase, AgentRunStatus
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.engine.events.types import ActiveToolCall
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.session_execution.ownership import fence_owned_session_mutation


class ExecutionRunState(Protocol):
    """Detached Run state required by lifecycle operations."""

    @property
    def status(self) -> AgentRunStatus:
        """Return the current Run status."""
        ...

    @property
    def model_call_started_at(self) -> datetime.datetime | None:
        """Return the current model-call start timestamp."""
        ...


class ExecutionRunRepository(Protocol):
    """AgentRun operations required by completed execution lifecycle methods."""

    async def get_by_id(
        self,
        session: ReadSession,
        run_id: str,
    ) -> ExecutionRunState | None:
        """Return one AgentRun state."""
        ...

    async def update_phase(
        self,
        session: WriteSession,
        run_id: str,
        phase: AgentRunPhase,
        *,
        active_tool_calls: list[ActiveToolCall] | None = None,
    ) -> ExecutionRunState:
        """Update phase and active model/tool projections."""
        ...


class ExecutionModelFilePinRepository(Protocol):
    """ModelFile pin mutation required before model dispatch."""

    async def pin_many(
        self,
        session: WriteSession,
        *,
        session_id: str,
        run_id: str,
        model_file_ids: Sequence[str],
    ) -> None:
        """Pin model-visible files for the active Run."""
        ...


@dataclasses.dataclass(frozen=True)
class ConditionalPhaseUpdate:
    """Result of a phase update guarded by current Run status."""

    updated: bool
    model_call_started_at: datetime.datetime | None


@dataclasses.dataclass(frozen=True)
class EngineExecutionOperationRepository:
    """Own completed phase and ModelFile pin transactions."""

    session_manager: SessionManager[WriteSession]
    run_repository: ExecutionRunRepository
    model_file_pin_repository: ExecutionModelFilePinRepository | None
    owner: SessionExecutionOwner | None

    async def update_phase(
        self,
        *,
        run_id: str,
        phase: AgentRunPhase,
        active_tool_calls: list[ActiveToolCall] | None = None,
    ) -> datetime.datetime | None:
        """Update one Run phase in a completed transaction."""
        async with self.session_manager() as session:
            if active_tool_calls is not None and self.owner is not None:
                await fence_owned_session_mutation(session, self.owner)
            run = await self.run_repository.update_phase(
                session,
                run_id,
                phase,
                active_tool_calls=active_tool_calls,
            )
            return run.model_call_started_at

    async def update_phase_if_running(
        self,
        *,
        run_id: str,
        phase: AgentRunPhase,
        active_tool_calls: list[ActiveToolCall] | None = None,
    ) -> ConditionalPhaseUpdate:
        """Update phase only while the current Run remains running."""
        async with self.session_manager() as session:
            if active_tool_calls is not None and self.owner is not None:
                await fence_owned_session_mutation(session, self.owner)
            run = await self.run_repository.get_by_id(session, run_id)
            if run is None or run.status is not AgentRunStatus.RUNNING:
                return ConditionalPhaseUpdate(
                    updated=False,
                    model_call_started_at=None,
                )
            updated = await self.run_repository.update_phase(
                session,
                run_id,
                phase,
                active_tool_calls=active_tool_calls,
            )
            return ConditionalPhaseUpdate(
                updated=True,
                model_call_started_at=updated.model_call_started_at,
            )

    async def pin_model_files(
        self,
        *,
        session_id: str,
        run_id: str,
        model_file_ids: Sequence[str],
    ) -> None:
        """Pin model-visible files in a completed transaction."""
        repository = self.model_file_pin_repository
        if repository is None:
            return
        async with self.session_manager() as session:
            await repository.pin_many(
                session,
                session_id=session_id,
                run_id=run_id,
                model_file_ids=model_file_ids,
            )
