"""Completed interaction admission and durable provider-mutation claims."""

import dataclasses
import datetime
from typing import Annotated

from fastapi import Depends

from azents.core.enums import ExternalChannelInteractionStatus
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.external_channel.data import (
    ExternalChannelInteraction,
    ExternalChannelInteractionAdmission,
    ExternalChannelInteractionCreate,
    ExternalChannelPrincipalCreate,
)
from azents.repos.external_channel.repository import ExternalChannelRepository


@dataclasses.dataclass(frozen=True)
class ExternalChannelInteractionMutationClaim:
    """Result of one durable accepted-to-processing interaction claim."""

    interaction: ExternalChannelInteraction
    claimed: bool


@dataclasses.dataclass
class ExternalChannelAdmissionOperations:
    """Finish principal/admission and fenced interaction mutations before effects."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    repository: Annotated[
        ExternalChannelRepository, Depends(ExternalChannelRepository.create)
    ]

    async def admit_interaction(
        self,
        *,
        create: ExternalChannelInteractionCreate,
        principal: ExternalChannelPrincipalCreate,
    ) -> ExternalChannelInteractionAdmission:
        """Commit one interaction and its authenticated provider actor together."""
        async with self.session_manager() as session:
            await self.repository.lock_connection_for_interaction_admission(
                session,
                connection_id=create.connection_id,
            )
            persisted_principal = await self.repository.create_principal_idempotent(
                session,
                principal,
            )
            admission = await self.repository.admit_interaction(
                session,
                create.model_copy(update={"principal_id": persisted_principal.id}),
            )
            await session.write_session.commit()
            return admission

    async def begin_interaction_provider_mutation(
        self,
        *,
        interaction_id: str,
        now: datetime.datetime,
        processing_lease: datetime.timedelta,
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
                await session.write_session.commit()
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
                    and interaction.updated_at <= now - processing_lease
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
                    await session.write_session.commit()
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
            await session.write_session.commit()
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
            await session.write_session.commit()
