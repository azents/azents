"""Discord signed HTTP interaction admission boundary."""

import datetime
import hashlib
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import ExternalChannelConnectionStatus
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import ExternalChannelInteractionAdmission
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.admission import ExternalChannelAdmissionService
from azents.services.external_channel.discord_interaction import (
    DiscordInteractionEnvelope,
    DiscordInteractionUnauthorized,
    discord_interaction_admission_inputs,
    parse_discord_interaction,
    verify_discord_interaction_signature,
)


@dataclass(frozen=True)
class DiscordHTTPAdmissionResult:
    """Verified Discord interaction result before canonical routing."""

    envelope: DiscordInteractionEnvelope
    admission: ExternalChannelInteractionAdmission | None

    @property
    def ping(self) -> bool:
        """Return whether the interaction is Discord's endpoint verification PING."""
        return self.envelope.interaction_type == 1


@dataclass
class DiscordHTTPAdmissionService:
    """Select and authenticate a bounded Discord interaction before admission."""

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    repository: Annotated[
        ExternalChannelRepository,
        Depends(ExternalChannelRepository),
    ]
    admission_service: Annotated[
        ExternalChannelAdmissionService,
        Depends(ExternalChannelAdmissionService),
    ]

    async def handle(
        self,
        *,
        selector: str,
        raw_body: bytes,
        timestamp: str | None,
        signature: str | None,
        received_at: datetime.datetime,
    ) -> DiscordHTTPAdmissionResult:
        """Verify one selector-scoped Discord interaction."""
        selector_hash = hashlib.sha256(selector.encode()).hexdigest()
        async with self.session_manager() as session:
            configuration = (
                await self.repository.get_discord_http_configuration_by_selector_hash(
                    session,
                    selector_hash=selector_hash,
                )
            )
        if configuration is None or configuration.capabilities is None:
            raise DiscordInteractionUnauthorized(
                "Discord interaction could not be authenticated."
            )
        public_key = configuration.capabilities.get("interaction_public_key")
        if not isinstance(public_key, str):
            raise DiscordInteractionUnauthorized(
                "Discord interaction could not be authenticated."
            )
        verify_discord_interaction_signature(
            raw_body=raw_body,
            timestamp=timestamp,
            signature=signature,
            public_key=public_key,
        )
        envelope = parse_discord_interaction(raw_body)
        if envelope.application_id != configuration.provider_app_id:
            raise DiscordInteractionUnauthorized(
                "Discord interaction could not be authenticated."
            )
        if envelope.interaction_type == 1:
            return DiscordHTTPAdmissionResult(envelope=envelope, admission=None)
        if configuration.status not in (
            ExternalChannelConnectionStatus.ACTIVE,
            ExternalChannelConnectionStatus.DEGRADED,
        ):
            raise DiscordInteractionUnauthorized(
                "Discord interaction callback is not active."
            )
        if envelope.guild_id != configuration.provider_tenant_id:
            raise DiscordInteractionUnauthorized(
                "Discord interaction could not be authenticated."
            )
        inputs = discord_interaction_admission_inputs(
            connection_id=configuration.id,
            envelope=envelope,
            received_at=received_at,
        )
        admission = await self.admission_service.admit_interaction(
            create=inputs.create,
            principal=inputs.principal,
        )
        return DiscordHTTPAdmissionResult(envelope=envelope, admission=admission)
