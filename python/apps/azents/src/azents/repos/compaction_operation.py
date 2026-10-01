"""Completed database operations for append-only context compaction."""

import dataclasses
from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import EventKind
from azents.core.model_operation import ModelOperationKind
from azents.engine.events.types import (
    CompactionMarkerPayload,
    CompactionSummaryPayload,
    Event,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.model_operation_completion import (
    ModelOperationCompletion,
    ModelOperationCompletionRepository,
)
from azents.repos.toolkit_state.engine import ToolWorkingSetStore


class CompactionTranscriptRepository(Protocol):
    """Transcript mutations required by compaction finalization."""

    async def append(
        self,
        session: AsyncSession,
        create: EventCreate,
    ) -> Event:
        """Append one durable Event."""
        ...


class CompactionSessionState(Protocol):
    """Detached Session state required by compaction planning."""

    @property
    def model_input_head_event_id(self) -> str | None:
        """Return the current model-input head."""
        ...


class CompactionSessionRepository(Protocol):
    """Session state operations required by compaction."""

    async def get_by_id(
        self,
        session: AsyncSession,
        agent_session_id: str,
    ) -> CompactionSessionState | None:
        """Return Session state with a model-input head."""
        ...

    async def lock_compaction_plan_if_current(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        expected_head_event_id: str | None,
        expected_tail_event_id: str,
    ) -> bool:
        """Lock and verify captured compaction boundaries."""
        ...

    async def move_model_input_head(
        self,
        session: AsyncSession,
        session_id: str,
        event_id: str,
    ) -> object:
        """Move the durable model-input head."""
        ...


class CompactionModelOperationRepository(Protocol):
    """Model-operation mutation composed into compaction finalization."""

    async def complete_success_in_session(
        self,
        session: AsyncSession,
        completion: ModelOperationCompletion,
    ) -> None:
        """Settle one successful model operation."""
        ...


@dataclasses.dataclass(frozen=True)
class CompactionPlan:
    """Detached database snapshot used to fence compaction finalization."""

    expected_head_event_id: str | None


@dataclasses.dataclass(frozen=True)
class CompactionCommitContext:
    """Run-owned database mutations committed with a compaction summary."""

    workspace_id: str
    agent_id: str
    run_id: str
    owner_generation: int
    settle_model_operation: bool


def _tool_working_set_store(
    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ],
) -> ToolWorkingSetStore:
    """Build the repository-composed Tool Search working-set store."""
    return ToolWorkingSetStore(session_manager=session_manager)


@dataclasses.dataclass(frozen=True)
class CompactionOperationRepository:
    """Own compaction planning and atomic finalization transactions."""

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    transcript_repository: Annotated[
        CompactionTranscriptRepository,
        Depends(EventTranscriptRepository),
    ]
    agent_session_repository: Annotated[
        CompactionSessionRepository,
        Depends(AgentSessionRepository),
    ]
    model_operation_completion_repository: Annotated[
        CompactionModelOperationRepository,
        Depends(ModelOperationCompletionRepository),
    ]
    tool_working_set_store: Annotated[
        ToolWorkingSetStore,
        Depends(_tool_working_set_store),
    ]

    def with_session_manager(
        self,
        session_manager: SessionManager[AsyncSession],
    ) -> "CompactionOperationRepository":
        """Bind completed operations to one execution authority."""
        return dataclasses.replace(
            self,
            session_manager=session_manager,
            tool_working_set_store=self.tool_working_set_store.with_session_manager(
                session_manager
            ),
        )

    async def prepare(self, *, session_id: str) -> CompactionPlan:
        """Capture the current model-input head in a completed transaction."""
        async with self.session_manager() as session:
            session_state = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
            if session_state is None:
                raise ValueError("AgentSession not found")
            return CompactionPlan(
                expected_head_event_id=session_state.model_input_head_event_id
            )

    async def finalize(
        self,
        *,
        session_id: str,
        plan: CompactionPlan,
        expected_tail_event_id: str,
        compaction_id: str,
        content: str,
        reason: str | None,
        commit_context: CompactionCommitContext | None,
    ) -> Event | None:
        """Commit one current compaction plan or return None when stale."""
        async with self.session_manager() as session:
            current = (
                await self.agent_session_repository.lock_compaction_plan_if_current(
                    session,
                    session_id=session_id,
                    expected_head_event_id=plan.expected_head_event_id,
                    expected_tail_event_id=expected_tail_event_id,
                )
            )
            if not current:
                return None
            await self.transcript_repository.append(
                session,
                EventCreate(
                    session_id=session_id,
                    kind=EventKind.COMPACTION_MARKER,
                    payload=CompactionMarkerPayload(
                        compaction_id=compaction_id,
                        status="started",
                        reason=reason,
                    ).model_dump(mode="json", exclude_none=True),
                ),
            )
            summary_event = await self.transcript_repository.append(
                session,
                EventCreate(
                    session_id=session_id,
                    kind=EventKind.COMPACTION_SUMMARY,
                    payload=CompactionSummaryPayload(
                        compaction_id=compaction_id,
                        content=content,
                        covered_until_event_id=expected_tail_event_id,
                        reason=reason,
                    ).model_dump(mode="json", exclude_none=True),
                ),
            )
            await self.agent_session_repository.move_model_input_head(
                session,
                session_id,
                summary_event.id,
            )
            if commit_context is not None:
                if commit_context.settle_model_operation:
                    await (
                        self.model_operation_completion_repository.complete_success_in_session
                    )(
                        session,
                        ModelOperationCompletion(
                            workspace_id=commit_context.workspace_id,
                            session_id=session_id,
                            run_id=commit_context.run_id,
                            owner_generation=commit_context.owner_generation,
                            operation_kind=ModelOperationKind.COMPACTION,
                        ),
                    )
                await self.tool_working_set_store.clear_in_session(
                    session,
                    commit_context.agent_id,
                    session_id,
                )
            return summary_event
