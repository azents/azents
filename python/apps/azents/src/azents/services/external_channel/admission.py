"""Transactional External Channel provider-event admission."""

import asyncio
import dataclasses
import datetime
import logging
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import ExternalChannelInteractionStatus
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import (
    ExternalChannelInteraction,
    ExternalChannelInteractionAdmission,
    ExternalChannelInteractionCreate,
    ExternalChannelPrincipalCreate,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.interaction import (
    ExternalChannelInteractionHandoff,
    SlackInteractionTriggerExpired,
)

logger = logging.getLogger(__name__)

_INTERACTION_PROVIDER_MUTATION_TIMEOUT = datetime.timedelta(minutes=5)
_INTERACTION_PROCESSING_LEASE = datetime.timedelta(minutes=6)

type ExternalChannelInteractionMutationCallback = Callable[
    [ExternalChannelInteractionHandoff],
    Awaitable[None],
]


@dataclasses.dataclass(frozen=True)
class ExternalChannelInteractionMutationClaim:
    """Result of one durable accepted-to-processing interaction claim."""

    interaction: ExternalChannelInteraction
    claimed: bool


@dataclasses.dataclass
class ExternalChannelAdmissionService:
    """Commit durable provider-event admission before acknowledging the provider."""

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    repository: Annotated[
        ExternalChannelRepository,
        Depends(ExternalChannelRepository.create),
    ]
    provider_mutation_timeout: datetime.timedelta = (
        _INTERACTION_PROVIDER_MUTATION_TIMEOUT
    )
    processing_lease: datetime.timedelta = _INTERACTION_PROCESSING_LEASE

    def __post_init__(self) -> None:
        """Require stale-claim handling to start after provider I/O is cancelled."""
        if (
            self.provider_mutation_timeout <= datetime.timedelta()
            or self.processing_lease <= self.provider_mutation_timeout
        ):
            raise ValueError(
                "External Channel interaction lease must exceed its mutation timeout."
            )

    async def admit_interaction(
        self,
        *,
        create: ExternalChannelInteractionCreate,
        principal: ExternalChannelPrincipalCreate,
    ) -> ExternalChannelInteractionAdmission:
        """Commit one interaction and its authenticated provider actor together."""
        async with self.session_manager() as session:
            persisted_principal = await self.repository.create_principal_idempotent(
                session,
                principal,
            )
            admission = await self.repository.admit_interaction(
                session,
                create.model_copy(update={"principal_id": persisted_principal.id}),
            )
            await session.commit()
            return admission

    async def begin_interaction_provider_mutation(
        self,
        *,
        interaction_id: str,
        now: datetime.datetime,
    ) -> ExternalChannelInteractionMutationClaim | None:
        """Fence one trigger-bearing provider mutation behind a committed state."""
        async with self.session_manager() as session:
            interaction = await self.repository.lock_interaction(
                session,
                interaction_id=interaction_id,
            )
            if interaction is None:
                return None
            if interaction.expires_at <= now:
                expired = await self.repository.transition_interaction(
                    session,
                    interaction_id=interaction.id,
                    status=ExternalChannelInteractionStatus.EXPIRED,
                    error_kind="interaction_expired",
                    error_summary="Slack interaction expired before processing.",
                )
                await session.commit()
                return (
                    None
                    if expired is None
                    else ExternalChannelInteractionMutationClaim(
                        interaction=expired,
                        claimed=False,
                    )
                )
            if interaction.status is not ExternalChannelInteractionStatus.ACCEPTED:
                if (
                    interaction.status is ExternalChannelInteractionStatus.PROCESSING
                    and interaction.updated_at <= now - self.processing_lease
                ):
                    abandoned = await self.repository.transition_interaction(
                        session,
                        interaction_id=interaction.id,
                        status=ExternalChannelInteractionStatus.FAILED,
                        error_kind="processing_abandoned",
                        error_summary=(
                            "Slack interaction processing did not reach a terminal "
                            "state."
                        ),
                        transitioned_at=now,
                    )
                    await session.commit()
                    return (
                        None
                        if abandoned is None
                        else ExternalChannelInteractionMutationClaim(
                            interaction=abandoned,
                            claimed=False,
                        )
                    )
                return ExternalChannelInteractionMutationClaim(
                    interaction=interaction,
                    claimed=False,
                )
            processing = await self.repository.transition_interaction(
                session,
                interaction_id=interaction.id,
                status=ExternalChannelInteractionStatus.PROCESSING,
                error_kind=None,
                error_summary=None,
                transitioned_at=now,
            )
            await session.commit()
            return (
                None
                if processing is None
                else ExternalChannelInteractionMutationClaim(
                    interaction=processing,
                    claimed=True,
                )
            )

    async def finish_interaction_provider_mutation(
        self,
        *,
        interaction_id: str,
        status: ExternalChannelInteractionStatus,
        error_kind: str | None,
        error_summary: str | None,
    ) -> None:
        """Record the terminal result without replaying an ephemeral trigger."""
        async with self.session_manager() as session:
            await self.repository.transition_interaction(
                session,
                interaction_id=interaction_id,
                status=status,
                error_kind=error_kind,
                error_summary=error_summary,
            )
            await session.commit()

    async def run_interaction_provider_mutation(
        self,
        *,
        handoff: ExternalChannelInteractionHandoff,
        callback: ExternalChannelInteractionMutationCallback,
    ) -> None:
        """Run one post-claim provider mutation and durably terminalize it once."""
        try:
            async with asyncio.timeout(self.provider_mutation_timeout.total_seconds()):
                await callback(handoff)
        except SlackInteractionTriggerExpired:
            await self.finish_interaction_provider_mutation(
                interaction_id=handoff.interaction_id,
                status=ExternalChannelInteractionStatus.EXPIRED,
                error_kind="trigger_expired",
                error_summary="Slack interaction trigger expired.",
            )
        except TimeoutError:
            await self.finish_interaction_provider_mutation(
                interaction_id=handoff.interaction_id,
                status=ExternalChannelInteractionStatus.FAILED,
                error_kind="processor_timeout",
                error_summary="Slack interaction processing timed out.",
            )
        except asyncio.CancelledError:
            await asyncio.shield(
                self.finish_interaction_provider_mutation(
                    interaction_id=handoff.interaction_id,
                    status=ExternalChannelInteractionStatus.FAILED,
                    error_kind="processor_cancelled",
                    error_summary="Slack interaction processing was cancelled.",
                )
            )
            raise
        except Exception:
            logger.exception(
                "Slack interaction provider mutation failed",
                extra={"interaction_id": handoff.interaction_id},
            )
            await self.finish_interaction_provider_mutation(
                interaction_id=handoff.interaction_id,
                status=ExternalChannelInteractionStatus.FAILED,
                error_kind="provider_mutation_failed",
                error_summary="Slack interaction provider mutation failed.",
            )
        else:
            await self.finish_interaction_provider_mutation(
                interaction_id=handoff.interaction_id,
                status=ExternalChannelInteractionStatus.COMPLETED,
                error_kind=None,
                error_summary=None,
            )
