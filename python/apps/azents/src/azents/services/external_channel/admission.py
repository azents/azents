"""Transactional External Channel provider-event admission."""

import asyncio
import dataclasses
import datetime
import logging
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends

from azents.core.enums import ExternalChannelInteractionStatus
from azents.repos.external_channel.admission_operations import (
    ExternalChannelAdmissionOperations,
    ExternalChannelInteractionMutationClaim,
)
from azents.repos.external_channel.data import (
    ExternalChannelInteractionAdmission,
    ExternalChannelInteractionCreate,
    ExternalChannelPrincipalCreate,
)
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


@dataclasses.dataclass
class ExternalChannelAdmissionService:
    """Commit durable provider-event admission before acknowledging the provider."""

    operations: Annotated[
        ExternalChannelAdmissionOperations, Depends(ExternalChannelAdmissionOperations)
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
        """Commit one authenticated principal and interaction before acknowledgement."""
        return await self.operations.admit_interaction(
            create=create, principal=principal
        )

    async def begin_interaction_provider_mutation(
        self,
        *,
        interaction_id: str,
        now: datetime.datetime,
    ) -> ExternalChannelInteractionMutationClaim | None:
        """Claim one durable provider mutation before callback I/O."""
        return await self.operations.begin_interaction_provider_mutation(
            interaction_id=interaction_id,
            now=now,
            processing_lease=self.processing_lease,
        )

    async def finish_interaction_provider_mutation(
        self,
        *,
        interaction_id: str,
        status: ExternalChannelInteractionStatus,
        error_kind: str | None,
        error_summary: str | None,
    ) -> None:
        """Complete the terminal database mutation after provider work."""
        await self.operations.finish_interaction_provider_mutation(
            interaction_id=interaction_id,
            status=status,
            error_kind=error_kind,
            error_summary=error_summary,
        )

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
