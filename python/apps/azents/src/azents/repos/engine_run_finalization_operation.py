"""Completed database operations for the Event Engine terminal branches."""

import dataclasses
import datetime
from collections.abc import Sequence
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentRunStatus
from azents.engine.events.protocols import RunStateRepository
from azents.engine.events.terminal_projection import terminal_result_from_events
from azents.engine.events.types import Event
from azents.rdb.session import SessionManager
from azents.repos.engine_event_mutation import EngineEventMutationRepository
from azents.repos.model_operation_completion import ModelOperationCompletion
from azents.repos.terminal_finalization import TerminalRunFinalizationRepository


class TerminalModelOperationRepository(Protocol):
    """Database-only success settlement composed with terminal Run mutation."""

    async def complete_success_in_session(
        self, session: AsyncSession, completion: ModelOperationCompletion
    ) -> None:
        """Settle the exact frozen model operation in the terminal transaction."""
        ...


class TerminalModelFilePinRepository(Protocol):
    """Database-only pin release performed with terminal Run mutation."""

    async def release_run(self, session: AsyncSession, *, run_id: str) -> None:
        """Release ModelFile pins in the terminal transaction."""
        ...


@dataclasses.dataclass(frozen=True)
class InterruptedModelOutput:
    """Committed partial assistant Events and interrupted marker."""

    events: list[Event]
    run_marker: Event


@dataclasses.dataclass(frozen=True)
class EngineRunFinalizationOperationRepository:
    """Own terminal operations without changing branch-specific atomic groups."""

    session_manager: SessionManager[AsyncSession]
    run_repository: RunStateRepository
    event_mutation_repository: EngineEventMutationRepository
    model_operation_repository: TerminalModelOperationRepository
    terminal_finalization_repository: TerminalRunFinalizationRepository | None
    model_file_pin_repository: TerminalModelFilePinRepository | None

    async def interrupt_before_turn(self, *, run_id: str) -> None:
        """Interrupt the Run before a turn without adding a marker."""
        async with self.session_manager() as session:
            await self._mark_terminal(
                session,
                run_id=run_id,
                status=AgentRunStatus.INTERRUPTED,
                terminal_result_event_id=None,
                terminal_result_message=None,
                suppress_parent_result=False,
            )

    async def complete_polled_run(
        self, *, run_id: str, suppress_parent_result: bool
    ) -> None:
        """Complete a polled Run with its existing parent-result disposition."""
        async with self.session_manager() as session:
            await self._mark_terminal(
                session,
                run_id=run_id,
                status=AgentRunStatus.COMPLETED,
                terminal_result_event_id=None,
                terminal_result_message=None,
                suppress_parent_result=suppress_parent_result,
            )

    async def complete_bridged_run(self, *, run_id: str) -> None:
        """Complete bridge ownership transfer while suppressing parent delivery."""
        await self.complete_polled_run(run_id=run_id, suppress_parent_result=True)

    async def complete_model_run(
        self,
        *,
        session_id: str,
        run_id: str,
        output_events: Sequence[Event],
        completion: ModelOperationCompletion | None,
    ) -> Event:
        """Commit marker, successful operation, terminal delivery and pin release."""
        async with self.session_manager() as session:
            marker = await self.event_mutation_repository.append_run_marker(
                session, session_id=session_id, run_id=run_id, status="completed"
            )
            result = terminal_result_from_events(output_events)
            if completion is not None:
                await self.model_operation_repository.complete_success_in_session(
                    session, completion
                )
            await self._mark_terminal(
                session,
                run_id=run_id,
                status=AgentRunStatus.COMPLETED,
                terminal_result_event_id=result.event_id,
                terminal_result_message=result.message,
                suppress_parent_result=False,
            )
            return marker

    async def interrupt_after_tool_stop_if_running(
        self, *, session_id: str, run_id: str
    ) -> Event | None:
        """Interrupt only a currently running Run after its Tool-stop repair."""
        async with self.session_manager() as session:
            current = await self.run_repository.get_by_id(session, run_id)
            if current is None or current.status is not AgentRunStatus.RUNNING:
                return None
            marker = await self.event_mutation_repository.append_run_marker(
                session, session_id=session_id, run_id=run_id, status="interrupted"
            )
            await self._mark_terminal(
                session,
                run_id=run_id,
                status=AgentRunStatus.INTERRUPTED,
                terminal_result_event_id=None,
                terminal_result_message=None,
                suppress_parent_result=False,
            )
            return marker

    async def interrupt_turn_limit(self, *, session_id: str, run_id: str) -> None:
        """Commit a turn-limit interruption without adding a publication effect."""
        async with self.session_manager() as session:
            await self.event_mutation_repository.append_run_marker(
                session, session_id=session_id, run_id=run_id, status="interrupted"
            )
            await self._mark_terminal(
                session,
                run_id=run_id,
                status=AgentRunStatus.INTERRUPTED,
                terminal_result_event_id=None,
                terminal_result_message=None,
                suppress_parent_result=False,
            )

    async def interrupt_model_stream(
        self, *, session_id: str, run_id: str, assistant_events: Sequence[Event]
    ) -> InterruptedModelOutput:
        """Durabilize partial assistant text and its interrupted terminal marker."""
        async with self.session_manager() as session:
            events = await self.event_mutation_repository.append_events(
                session, assistant_events, tool_call_run_id=None
            )
            marker = await self.event_mutation_repository.append_run_marker(
                session, session_id=session_id, run_id=run_id, status="interrupted"
            )
            result = terminal_result_from_events(events)
            await self._mark_terminal(
                session,
                run_id=run_id,
                status=AgentRunStatus.INTERRUPTED,
                terminal_result_event_id=result.event_id,
                terminal_result_message=result.message,
                suppress_parent_result=False,
            )
            return InterruptedModelOutput(events=events, run_marker=marker)

    async def complete_committed_scheduled_result(
        self,
        *,
        session_id: str,
        run_id: str,
        completion: ModelOperationCompletion | None,
    ) -> Event | None:
        """Recover an eligible durable scheduled result without model replay."""
        async with self.session_manager() as session:
            run = await self.run_repository.get_by_id(session, run_id)
            if (
                run is None
                or run.status is not AgentRunStatus.RUNNING
                or run.scheduled_task_cycle_id is None
                or run.terminal_result_event_id is None
                or run.terminal_result_message is None
            ):
                return None
            marker = await self.event_mutation_repository.append_run_marker(
                session, session_id=session_id, run_id=run_id, status="completed"
            )
            if completion is not None:
                await self.model_operation_repository.complete_success_in_session(
                    session, completion
                )
            await self._mark_terminal(
                session,
                run_id=run_id,
                status=AgentRunStatus.COMPLETED,
                terminal_result_event_id=run.terminal_result_event_id,
                terminal_result_message=run.terminal_result_message,
                suppress_parent_result=False,
            )
            return marker

    async def _mark_terminal(
        self,
        session: AsyncSession,
        *,
        run_id: str,
        status: AgentRunStatus,
        terminal_result_event_id: str | None,
        terminal_result_message: str | None,
        suppress_parent_result: bool,
    ) -> None:
        """Preserve terminal prelock, Run mutation, delivery and pin ordering."""
        if self.terminal_finalization_repository is not None:
            await self.terminal_finalization_repository.lock_run_finalization(
                session, run_id=run_id
            )
        terminal_at = datetime.datetime.now(datetime.UTC)
        await self.run_repository.mark_terminal(
            session,
            run_id,
            status,
            ended_at=terminal_at,
            terminal_result_event_id=terminal_result_event_id,
            terminal_result_message=terminal_result_message,
        )
        if suppress_parent_result:
            await self.run_repository.mark_parent_result_suppressed(
                session, run_id=run_id, finalized_at=terminal_at
            )
        elif self.terminal_finalization_repository is not None:
            await self.terminal_finalization_repository.finalize_run_in_session(
                session, run_id=run_id
            )
        if self.model_file_pin_repository is not None:
            await self.model_file_pin_repository.release_run(session, run_id=run_id)
