"""Database operations for automatic Session title generation."""

import dataclasses
import datetime
from typing import Annotated

from azcommon.uuid import uuid7
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentSessionTitleSource
from azents.core.inference_profile import RequestedInferenceProfile
from azents.core.llm_mapping import to_runtime_model
from azents.core.model_operation import (
    ModelOperationCandidateOutcomeStatus,
    ModelOperationChainExhaustedError,
    ModelOperationKind,
    build_model_operation,
    mark_current_candidate_quota_and_advance,
)
from azents.engine.run.provider_failure import ModelProviderFailure
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSession
from azents.repos.model_candidate_health import ModelCandidateHealthRepository
from azents.repos.model_candidate_health.data import ModelCandidateIdentity
from azents.services.model_candidate_selection import select_model_operation_candidate

from .data import SessionTitleGenerationSnapshot


@dataclasses.dataclass
class SessionTitleRepository:
    """Own database-only automatic Session title operations."""

    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    health_repository: Annotated[
        ModelCandidateHealthRepository, Depends(ModelCandidateHealthRepository)
    ]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]

    async def load_generation_snapshot(
        self,
        *,
        session_id: str,
        generation_event_id: str,
    ) -> SessionTitleGenerationSnapshot | None:
        """Freeze and select the current Lightweight title candidate."""
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.lock_by_id(
                session,
                session_id,
            )
            if not self._generation_is_current(
                agent_session,
                generation_event_id=generation_event_id,
            ):
                return None
            if agent_session is None:
                return None
            agent = await self.agent_repository.lock_by_id(
                session,
                agent_session.agent_id,
            )
            if agent is None:
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
                return None
            operation = agent_session.title_model_operation_state
            if (
                operation is None
                or operation.kind is not ModelOperationKind.TITLE
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
                    kind=ModelOperationKind.TITLE,
                    operation_id=uuid7().hex,
                    recorded_at=datetime.datetime.now(datetime.UTC),
                )
            try:
                selected = await select_model_operation_candidate(
                    session,
                    operation=operation,
                    workspace_id=agent.workspace_id,
                    health_repository=self.health_repository,
                    recorded_at=datetime.datetime.now(datetime.UTC),
                    session_id=None,
                    reservation=None,
                )
            except ModelOperationChainExhaustedError as exc:
                await self.agent_session_repository.set_title_model_operation_state(
                    session,
                    session_id=session_id,
                    generation_event_id=generation_event_id,
                    operation=exc.operation,
                )
                return None
            updated = (
                await self.agent_session_repository.set_title_model_operation_state(
                    session,
                    session_id=session_id,
                    generation_event_id=generation_event_id,
                    operation=selected.operation,
                )
            )
            if updated is None:
                return None
            return SessionTitleGenerationSnapshot(
                agent_id=agent.id,
                workspace_id=agent.workspace_id,
                operation=selected.operation,
            )

    async def advance_after_quota(
        self,
        *,
        session_id: str,
        generation_event_id: str,
        failure: ModelProviderFailure,
    ) -> SessionTitleGenerationSnapshot | None:
        """Record title quota and select the next background candidate."""
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.lock_by_id(
                session,
                session_id,
            )
            if not self._generation_is_current(
                agent_session,
                generation_event_id=generation_event_id,
            ):
                return None
            if agent_session is None:
                return None
            operation = agent_session.title_model_operation_state
            if operation is None or operation.kind is not ModelOperationKind.TITLE:
                return None
            outcome = operation.outcomes[operation.cursor]
            if outcome.status is not ModelOperationCandidateOutcomeStatus.ACTIVE:
                return None
            candidate = operation.current_candidate
            selection = candidate.model_selection
            if (
                failure.route_integration != selection.llm_provider_integration_id
                or failure.route_provider != selection.provider.value
                or failure.route_model
                != to_runtime_model(selection.provider, selection.model_identifier)
            ):
                return None
            agent = await self.agent_repository.get_by_id(
                session,
                agent_session.agent_id,
            )
            if agent is None:
                return None
            observation = await self.health_repository.renew_quota_in_session(
                session,
                ModelCandidateIdentity(
                    workspace_id=agent.workspace_id,
                    llm_provider_integration_id=(selection.llm_provider_integration_id),
                    model_identifier=selection.model_identifier,
                ),
            )
            exhausted = False
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
                resulting = selected.operation
            except ModelOperationChainExhaustedError as exc:
                resulting = exc.operation
                exhausted = True
            updated = (
                await self.agent_session_repository.set_title_model_operation_state(
                    session,
                    session_id=session_id,
                    generation_event_id=generation_event_id,
                    operation=resulting,
                )
            )
            if updated is None or exhausted:
                return None
            return SessionTitleGenerationSnapshot(
                agent_id=agent.id,
                workspace_id=agent.workspace_id,
                operation=resulting,
            )

    async def generation_is_current(
        self,
        *,
        session_id: str,
        generation_event_id: str,
    ) -> bool:
        """Return whether the initial automatic title still owns generation."""
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
            return self._generation_is_current(
                agent_session,
                generation_event_id=generation_event_id,
            )

    async def replace_initial_auto_title(
        self,
        *,
        session_id: str,
        title: str,
        event_id: str,
    ) -> AgentSession | None:
        """Atomically replace the current initial automatic title."""
        async with self.session_manager() as session:
            return await self.agent_session_repository.replace_initial_auto_title(
                session,
                session_id=session_id,
                title=title,
                event_id=event_id,
            )

    def _generation_is_current(
        self,
        agent_session: AgentSession | None,
        *,
        generation_event_id: str,
    ) -> bool:
        """Check the durable automatic-title ownership predicate."""
        return (
            agent_session is not None
            and agent_session.title_source == AgentSessionTitleSource.AUTO_INITIAL
            and agent_session.title_generation_event_id == generation_event_id
        )
