"""Historical Memory Lightweight candidate preparation state operations."""

import dataclasses
import datetime
from typing import Annotated

from azcommon.uuid import uuid7
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.historical_memory import (
    HistoricalMemoryDueSource,
    HistoricalMemoryFailure,
)
from azents.core.inference_profile import RequestedInferenceProfile
from azents.core.model_operation import (
    ModelOperationCandidateOutcomeStatus,
    ModelOperationChainExhaustedError,
    ModelOperationKind,
    ModelOperationSnapshot,
    build_model_operation,
    mark_current_candidate_quota_and_advance,
)
from azents.engine.run.provider_failure import ModelProviderFailure
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.historical_memory import HistoricalMemoryRepository
from azents.repos.model_candidate_health import ModelCandidateHealthRepository
from azents.repos.model_candidate_health.data import ModelCandidateIdentity
from azents.services.model_candidate_selection import select_model_operation_candidate

_RETRY_MIN_SECONDS = 60
_RETRY_MAX_SECONDS = 6 * 60 * 60


@dataclasses.dataclass
class HistoricalMemoryPreparationRepository:
    """Freeze, advance, and persist source-owned Lightweight model operations."""

    historical_repository: Annotated[
        HistoricalMemoryRepository,
        Depends(HistoricalMemoryRepository),
    ]
    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    health_repository: Annotated[
        ModelCandidateHealthRepository,
        Depends(ModelCandidateHealthRepository),
    ]
    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]

    async def begin_next(
        self,
        *,
        agent_id: str,
        attempted_at: datetime.datetime,
        inactive_before: datetime.datetime,
    ) -> HistoricalMemoryDueSource | None:
        """Select and persist one due source's current Lightweight candidate."""
        async with self.session_manager() as session:
            due = await self.historical_repository.list_due_for_agent_in_session(
                session,
                agent_id=agent_id,
                now=attempted_at,
                inactive_before=inactive_before,
                limit=1,
            )
            if not due:
                return None
            source = due[0]
            admission = (
                await self.historical_repository.lock_preparation_admission_in_session(
                    session,
                    source_session_id=source.source_session_id,
                    attempted_at=attempted_at,
                    inactive_before=inactive_before,
                )
            )
            if admission is None:
                return None
            source = admission.source
            agent = await self.agent_repository.lock_by_id(session, source.agent_id)
            if (
                agent is None
                or agent.id != agent_id
                or agent.workspace_id != source.workspace_id
                or not agent.memory_enabled
            ):
                return None
            lock_membership = (
                self.historical_repository.lock_preparation_membership_in_session
            )
            membership_current = await lock_membership(session, admission)
            if not membership_current:
                return None
            option = next(
                (
                    item
                    for item in agent.selectable_model_options
                    if item.label == agent.lightweight_model_label
                ),
                None,
            )
            if option is None:
                await self._record_failure_in_session(
                    session,
                    source_session_id=source.source_session_id,
                    failure_count=source.failure_count,
                    attempted_at=attempted_at,
                    failure_code="lightweight_option_unavailable",
                    operation=source.model_operation_state,
                )
                await session.commit()
                return None
            operation = source.model_operation_state
            if (
                operation is None
                or operation.kind is not ModelOperationKind.HISTORICAL_MEMORY
                or operation.semantic_label != option.label
                or operation.terminal_reason is not None
            ):
                operation = build_model_operation(
                    option=option,
                    profile=RequestedInferenceProfile(
                        model_target_label=option.label,
                        reasoning_effort=None,
                        enabled_execution_options=[],
                    ),
                    kind=ModelOperationKind.HISTORICAL_MEMORY,
                    operation_id=uuid7().hex,
                    recorded_at=attempted_at,
                )
            try:
                selected = await select_model_operation_candidate(
                    session,
                    operation=operation,
                    workspace_id=agent.workspace_id,
                    health_repository=self.health_repository,
                    recorded_at=attempted_at,
                    session_id=None,
                    reservation=None,
                )
            except ModelOperationChainExhaustedError as exc:
                await self._record_failure_in_session(
                    session,
                    source_session_id=source.source_session_id,
                    failure_count=source.failure_count,
                    attempted_at=attempted_at,
                    failure_code="candidate_chain_exhausted",
                    operation=exc.operation,
                )
                await session.commit()
                return None
            persist_operation = (
                self.historical_repository.persist_preparation_operation_in_session
            )
            prepared = await persist_operation(
                session,
                admission,
                attempted_at=attempted_at,
                operation=selected.operation,
            )
            await session.commit()
            return prepared

    async def advance_after_quota(
        self,
        *,
        source_session_id: str,
        failure: ModelProviderFailure,
        attempted_at: datetime.datetime,
        inactive_before: datetime.datetime,
    ) -> HistoricalMemoryDueSource | None:
        """Record shared quota health and move to the next candidate."""
        async with self.session_manager() as session:
            admission = (
                await self.historical_repository.lock_preparation_admission_in_session(
                    session,
                    source_session_id=source_session_id,
                    attempted_at=attempted_at,
                    inactive_before=inactive_before,
                )
            )
            if admission is None:
                return None
            source = admission.source
            operation = source.model_operation_state
            if operation is None:
                return None
            agent = await self.agent_repository.lock_by_id(session, source.agent_id)
            if (
                agent is None
                or agent.workspace_id != source.workspace_id
                or not agent.memory_enabled
            ):
                return None
            lock_membership = (
                self.historical_repository.lock_preparation_membership_in_session
            )
            membership_current = await lock_membership(session, admission)
            if not membership_current:
                return None
            outcome = operation.outcomes[operation.cursor]
            if outcome.status is not ModelOperationCandidateOutcomeStatus.ACTIVE:
                return None
            candidate = operation.current_candidate
            selection = candidate.model_selection
            if (
                failure.route_integration != selection.llm_provider_integration_id
                or failure.route_provider != selection.provider.value
                or failure.route_model != selection.model_identifier
            ):
                return None
            observation = await self.health_repository.renew_quota_in_session(
                session,
                ModelCandidateIdentity(
                    workspace_id=agent.workspace_id,
                    llm_provider_integration_id=(selection.llm_provider_integration_id),
                    model_identifier=selection.model_identifier,
                ),
            )
            try:
                advanced = mark_current_candidate_quota_and_advance(
                    operation,
                    recorded_at=observation.server_time,
                )
                selected = await select_model_operation_candidate(
                    session,
                    operation=advanced,
                    workspace_id=agent.workspace_id,
                    health_repository=self.health_repository,
                    recorded_at=observation.server_time,
                    session_id=None,
                    reservation=None,
                )
            except ModelOperationChainExhaustedError as exc:
                await self._record_failure_in_session(
                    session,
                    source_session_id=source.source_session_id,
                    failure_count=source.failure_count,
                    attempted_at=attempted_at,
                    failure_code="candidate_chain_exhausted",
                    operation=exc.operation,
                )
                await session.commit()
                return None
            persist_operation = (
                self.historical_repository.persist_preparation_operation_in_session
            )
            prepared = await persist_operation(
                session,
                admission,
                attempted_at=attempted_at,
                operation=selected.operation,
            )
            await session.commit()
            return prepared

    async def record_failure(
        self,
        *,
        source: HistoricalMemoryDueSource,
        attempted_at: datetime.datetime,
        failure_code: str,
    ) -> None:
        """Persist one safe bounded retry after an attempt failure."""
        async with self.session_manager() as session:
            await self._record_failure_in_session(
                session,
                source_session_id=source.source_session_id,
                failure_count=source.failure_count,
                attempted_at=attempted_at,
                failure_code=failure_code,
                operation=source.model_operation_state,
            )
            await session.commit()

    async def _record_failure_in_session(
        self,
        session: AsyncSession,
        *,
        source_session_id: str,
        failure_count: int,
        attempted_at: datetime.datetime,
        failure_code: str,
        operation: ModelOperationSnapshot | None,
    ) -> None:
        failure_number = failure_count + 1
        exponent = min(failure_number - 1, 9)
        delay_seconds = min(
            _RETRY_MIN_SECONDS * (2**exponent),
            _RETRY_MAX_SECONDS,
        )
        await self.historical_repository.record_failure_in_session(
            session,
            source_session_id=source_session_id,
            failure=HistoricalMemoryFailure(
                attempted_at=attempted_at,
                next_retry_at=attempted_at + datetime.timedelta(seconds=delay_seconds),
                failure_code=failure_code,
                model_operation_state=operation,
            ),
        )
