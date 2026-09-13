"""Authoritative Session model availability and Primary reservation service."""

import dataclasses
from typing import Annotated

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.agent import AgentModelSelection, SelectableModelCandidate
from azents.core.enums import (
    ModelCandidateClaimKind,
)
from azents.core.model_availability import (
    ModelCandidateIdentity as PublicModelCandidateIdentity,
)
from azents.core.model_availability import (
    PrimaryModelReservation,
    SessionModelAvailability,
)
from azents.core.model_execution_options import validate_execution_options
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSession
from azents.repos.model_candidate_health import ModelCandidateHealthRepository
from azents.repos.model_candidate_health.data import (
    CandidateHealthSettlement,
    ModelCandidateHealthObservation,
    ModelCandidateHealthStatus,
    ModelCandidateIdentity,
    ReservationClaimOutcome,
)
from azents.repos.session_model_profile.repository import (
    SessionModelProfileRepository,
)


@dataclasses.dataclass(frozen=True)
class SessionModelAvailabilityNotFound:
    """The Session is absent or unavailable to the requester."""


@dataclasses.dataclass(frozen=True)
class SessionModelReservationConflict:
    """The optimistic reservation request no longer matches authority."""

    availability: SessionModelAvailability


SessionModelAvailabilityError = SessionModelAvailabilityNotFound
SessionModelReservationError = (
    SessionModelAvailabilityNotFound | SessionModelReservationConflict
)


@dataclasses.dataclass(frozen=True)
class _AuthorizedAvailabilityContext:
    """Current root Session, Agent, label, and Primary candidate."""

    session: AgentSession
    agent: Agent
    semantic_label: str
    primary: SelectableModelCandidate


@dataclasses.dataclass
class SessionModelAvailabilityService:
    """Project model recovery state from PostgreSQL and mutate reservations."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    session_model_profile_repository: Annotated[
        SessionModelProfileRepository, Depends(SessionModelProfileRepository)
    ]
    health_repository: Annotated[
        ModelCandidateHealthRepository, Depends(ModelCandidateHealthRepository)
    ]

    async def get(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
    ) -> Result[SessionModelAvailability, SessionModelAvailabilityError]:
        """Return the current DB-derived availability projection."""
        async with self.session_manager() as db:
            context = await self._authorize(
                db,
                agent_id=agent_id,
                session_id=session_id,
                user_id=user_id,
                lock=False,
            )
        if context is None:
            return Failure(SessionModelAvailabilityNotFound())
        return Success(await self._project(context))

    async def reserve(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
        semantic_label: str,
        primary: PublicModelCandidateIdentity,
    ) -> Result[SessionModelAvailability, SessionModelReservationError]:
        """Reserve the exact current Primary recovery opportunity once."""
        conflict = False
        async with self.session_manager() as db:
            context = await self._authorize(
                db,
                agent_id=agent_id,
                session_id=session_id,
                user_id=user_id,
                lock=True,
            )
            if context is None:
                return Failure(SessionModelAvailabilityNotFound())
            expected = self._public_identity(context.primary.model_selection)
            if context.semantic_label != semantic_label or expected != primary:
                conflict = True
            else:
                identity = self._health_identity(context)
                claim = await self.health_repository.claim_reservation_in_session(
                    db,
                    identity,
                    session_id=session_id,
                )
                if claim.outcome is ReservationClaimOutcome.HEALTHY:
                    conflict = True
                elif claim.outcome is ReservationClaimOutcome.BUSY:
                    conflict = True
                else:
                    health = claim.observation.health
                    if (
                        health is None
                        or health.claim_kind is not ModelCandidateClaimKind.RESERVATION
                        or health.claim_owner_id != session_id
                        or health.claim_token is None
                        or health.claim_until is None
                    ):
                        raise RuntimeError(
                            "Reservation claim returned incomplete authority"
                        )
                    current = context.session.primary_model_reservation
                    if claim.outcome is ReservationClaimOutcome.IDEMPOTENT:
                        if not self._reservation_matches_health(
                            current,
                            context=context,
                            observation=claim.observation,
                        ):
                            conflict = True
                    else:
                        reservation = PrimaryModelReservation(
                            semantic_label=context.semantic_label,
                            candidate=expected,
                            health_generation=health.generation,
                            reservation_generation=(
                                context.session.primary_model_reservation_generation + 1
                            ),
                            claim_token=health.claim_token,
                            created_at=claim.observation.server_time,
                            expires_at=health.claim_until,
                        )
                        update_reservation = (
                            self.agent_session_repository.set_primary_model_reservation
                        )
                        updated = await update_reservation(
                            db,
                            session_id=session_id,
                            reservation=reservation,
                            expected_reservation_generation=None,
                        )
                        if updated is None:
                            raise RuntimeError(
                                "Active root Session reservation disappeared"
                            )
                        context = dataclasses.replace(context, session=updated)
        availability = await self._project(context)
        if conflict:
            return Failure(SessionModelReservationConflict(availability))
        return Success(availability)

    async def cancel(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
        reservation_generation: int,
    ) -> Result[SessionModelAvailability, SessionModelReservationError]:
        """Cancel only the exact current Session reservation generation."""
        conflict = False
        async with self.session_manager() as db:
            context = await self._authorize(
                db,
                agent_id=agent_id,
                session_id=session_id,
                user_id=user_id,
                lock=True,
            )
            if context is None:
                return Failure(SessionModelAvailabilityNotFound())
            reservation = context.session.primary_model_reservation
            if (
                reservation is None
                or reservation.reservation_generation != reservation_generation
            ):
                conflict = True
            else:
                settlement = await self.health_repository.cancel_reservation_in_session(
                    db,
                    self._health_identity(context),
                    expected_generation=reservation.health_generation,
                    expected_session_id=session_id,
                    expected_claim_token=reservation.claim_token,
                )
                if settlement is CandidateHealthSettlement.STALE:
                    conflict = True
                updated = (
                    await self.agent_session_repository.set_primary_model_reservation(
                        db,
                        session_id=session_id,
                        reservation=None,
                        expected_reservation_generation=reservation_generation,
                    )
                )
                if updated is None:
                    conflict = True
                else:
                    context = dataclasses.replace(context, session=updated)
        availability = await self._project(context)
        if conflict:
            return Failure(SessionModelReservationConflict(availability))
        return Success(availability)

    async def _authorize(
        self,
        db: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
        lock: bool,
    ) -> _AuthorizedAvailabilityContext | None:
        try:
            session = (
                await self.session_model_profile_repository.lock_writable_root(
                    db,
                    agent_id=agent_id,
                    session_id=session_id,
                    user_id=user_id,
                    nowait=False,
                )
                if lock
                else await self.session_model_profile_repository.get_readable_root(
                    db,
                    agent_id=agent_id,
                    session_id=session_id,
                    user_id=user_id,
                )
            )
        except ValueError:
            return None
        agent = await self.agent_repository.get_by_id(db, agent_id)
        if agent is None:
            return None
        semantic_label = (
            session.applied_inference_profile.model_target_label
            if session.applied_inference_profile is not None
            else agent.main_model_label
        )
        option = next(
            (
                item
                for item in agent.selectable_model_options
                if item.label == semantic_label
            ),
            None,
        )
        if option is None:
            return None
        return _AuthorizedAvailabilityContext(
            session=session,
            agent=agent,
            semantic_label=semantic_label,
            primary=option.candidates[0],
        )

    async def _project(
        self,
        context: _AuthorizedAvailabilityContext,
    ) -> SessionModelAvailability:
        primary_observation = await self.health_repository.snapshot(
            self._health_identity(context)
        )
        reservation = context.session.primary_model_reservation
        reservation_active = self._reservation_matches_health(
            reservation,
            context=context,
            observation=primary_observation,
        )
        if reservation_active:
            state = "primary_next"
            deadline = reservation.expires_at if reservation is not None else None
        elif primary_observation.status is ModelCandidateHealthStatus.AVAILABLE:
            state = "available"
            deadline = None
        elif primary_observation.status is ModelCandidateHealthStatus.COOLDOWN:
            state = "cooldown"
            deadline = (
                primary_observation.health.cooldown_until
                if primary_observation.health is not None
                else None
            )
        elif primary_observation.status is ModelCandidateHealthStatus.CLAIMED:
            state = "probing"
            deadline = (
                primary_observation.health.claim_until
                if primary_observation.health is not None
                else None
            )
        else:
            state = "probing"
            deadline = None
        fallback_display = await self._first_usable_fallback_display(context)
        selection = context.primary.model_selection
        return SessionModelAvailability(
            semantic_label=context.semantic_label,
            primary=self._public_identity(selection),
            primary_display_name=selection.model_display_name,
            state=state,
            deadline=deadline,
            server_time=primary_observation.server_time,
            first_usable_fallback_display_name=fallback_display,
            reservation=reservation if reservation_active else None,
        )

    async def _first_usable_fallback_display(
        self,
        context: _AuthorizedAvailabilityContext,
    ) -> str | None:
        option = next(
            item
            for item in context.agent.selectable_model_options
            if item.label == context.semantic_label
        )
        profile = context.session.applied_inference_profile
        reasoning_effort = profile.reasoning_effort if profile is not None else None
        execution_options = (
            profile.enabled_execution_options if profile is not None else []
        )
        for candidate in option.candidates[1:]:
            selection = candidate.model_selection
            if reasoning_effort is not None and reasoning_effort not in (
                selection.normalized_capabilities.reasoning.effort_levels
            ):
                continue
            try:
                validate_execution_options(
                    provider=selection.provider,
                    supported=selection.supported_execution_options,
                    enabled=execution_options,
                )
            except ValueError:
                continue
            observation = await self.health_repository.snapshot_for_background(
                ModelCandidateIdentity(
                    workspace_id=context.agent.workspace_id,
                    llm_provider_integration_id=(selection.llm_provider_integration_id),
                    model_identifier=selection.model_identifier,
                )
            )
            if observation.status is ModelCandidateHealthStatus.AVAILABLE:
                return selection.model_display_name
        return None

    def _reservation_matches_health(
        self,
        reservation: PrimaryModelReservation | None,
        *,
        context: _AuthorizedAvailabilityContext,
        observation: ModelCandidateHealthObservation,
    ) -> bool:
        health = observation.health
        return (
            reservation is not None
            and reservation.semantic_label == context.semantic_label
            and reservation.candidate
            == self._public_identity(context.primary.model_selection)
            and health is not None
            and health.generation == reservation.health_generation
            and health.claim_kind is ModelCandidateClaimKind.RESERVATION
            and health.claim_owner_id == context.session.id
            and health.claim_token == reservation.claim_token
            and health.claim_until == reservation.expires_at
            and health.claim_until is not None
            and health.claim_until > observation.server_time
        )

    def _health_identity(
        self,
        context: _AuthorizedAvailabilityContext,
    ) -> ModelCandidateIdentity:
        selection = context.primary.model_selection
        return ModelCandidateIdentity(
            workspace_id=context.agent.workspace_id,
            llm_provider_integration_id=selection.llm_provider_integration_id,
            model_identifier=selection.model_identifier,
        )

    def _public_identity(
        self,
        selection: AgentModelSelection,
    ) -> PublicModelCandidateIdentity:
        return PublicModelCandidateIdentity(
            llm_provider_integration_id=selection.llm_provider_integration_id,
            model_identifier=selection.model_identifier,
        )
