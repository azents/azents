"""Discord signed HTTP interaction admission boundary."""

import datetime
import hashlib
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelConnectionStatus,
    ExternalChannelInteractionStatus,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import ExternalChannelInteractionAdmission
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.admission import ExternalChannelAdmissionService
from azents.services.external_channel.discord_interaction import (
    DiscordInteractionEnvelope,
    DiscordInteractionUnauthorized,
    discord_interaction_admission_inputs,
    discord_message_command_source_event,
    parse_discord_interaction,
    verify_discord_interaction_signature,
)
from azents.services.external_channel.discord_selector import (
    DiscordSelectorResponseService,
)
from azents.services.external_channel.shortcut_source import (
    ExternalChannelShortcutSourceService,
)


@dataclass(frozen=True)
class DiscordHTTPAdmissionResult:
    """Verified Discord interaction result before canonical routing."""

    envelope: DiscordInteractionEnvelope
    admission: ExternalChannelInteractionAdmission | None
    response: dict[str, object] | None = None
    control_delivery_attempt_id: str | None = None
    control_delivery_connection_id: str | None = None

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
    shortcut_source_service: Annotated[
        ExternalChannelShortcutSourceService,
        Depends(ExternalChannelShortcutSourceService),
    ]
    selector_response_service: Annotated[
        DiscordSelectorResponseService,
        Depends(DiscordSelectorResponseService),
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
                "Discord interaction could not be authenticated.",
                failure_code="discord_callback_configuration_missing",
            )
        public_key = configuration.capabilities.get("interaction_public_key")
        if not isinstance(public_key, str):
            raise DiscordInteractionUnauthorized(
                "Discord interaction could not be authenticated.",
                failure_code="discord_callback_public_key_missing",
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
                "Discord interaction could not be authenticated.",
                failure_code="discord_interaction_application_mismatch",
            )
        if envelope.interaction_type == 1:
            return DiscordHTTPAdmissionResult(envelope=envelope, admission=None)
        if configuration.status not in (
            ExternalChannelConnectionStatus.ACTIVE,
            ExternalChannelConnectionStatus.DEGRADED,
        ):
            raise DiscordInteractionUnauthorized(
                "Discord interaction callback is not active.",
                failure_code="discord_interaction_not_active",
            )
        if envelope.guild_id != configuration.provider_tenant_id:
            raise DiscordInteractionUnauthorized(
                "Discord interaction could not be authenticated.",
                failure_code="discord_interaction_guild_mismatch",
            )
        inputs = discord_interaction_admission_inputs(
            connection_id=configuration.id,
            envelope=envelope,
            received_at=received_at,
        )
        shortcut_source_event = (
            discord_message_command_source_event(
                connection_id=configuration.id,
                envelope=envelope,
                received_at=received_at,
            )
            if configuration.app_mode is ExternalChannelAppMode.MULTI
            else None
        )
        admission = await self.admission_service.admit_interaction(
            create=inputs.create,
            principal=inputs.principal,
        )
        if envelope.selector_custom_id is not None:
            claim = await self.admission_service.begin_interaction_provider_mutation(
                interaction_id=admission.interaction.id,
                now=received_at,
            )
            principal_id = admission.interaction.principal_id
            if (
                claim is None
                or not claim.claimed
                or not isinstance(principal_id, str)
                or not principal_id
            ):
                return DiscordHTTPAdmissionResult(
                    envelope=envelope,
                    admission=admission,
                )
            try:
                component_response = (
                    await self.selector_response_service.component_response(
                        custom_id=envelope.selector_custom_id,
                        selected_route_id=envelope.selected_route_id,
                        principal_id=principal_id,
                        guild_id=envelope.guild_id,
                        channel_id=envelope.channel_id,
                        now=received_at,
                    )
                )
            except Exception:
                await self.admission_service.finish_interaction_provider_mutation(
                    interaction_id=admission.interaction.id,
                    status=ExternalChannelInteractionStatus.FAILED,
                    error_kind="selector_component_failed",
                    error_summary="Discord selector component could not be processed.",
                )
                raise
            await self.admission_service.finish_interaction_provider_mutation(
                interaction_id=admission.interaction.id,
                status=ExternalChannelInteractionStatus.COMPLETED,
                error_kind=None,
                error_summary=None,
            )
            return DiscordHTTPAdmissionResult(
                envelope=envelope,
                admission=admission,
                response=component_response.response,
                control_delivery_attempt_id=(
                    component_response.control_delivery_attempt_id
                ),
                control_delivery_connection_id=component_response.connection_id,
            )
        if shortcut_source_event is not None:
            materialization = await self.shortcut_source_service.ensure(
                shortcut_source_event=shortcut_source_event,
                interaction_id=admission.interaction.id,
                now=received_at,
            )
            claim = await self.admission_service.begin_interaction_provider_mutation(
                interaction_id=admission.interaction.id,
                now=received_at,
            )
            if claim is None or not claim.claimed:
                return DiscordHTTPAdmissionResult(
                    envelope=envelope,
                    admission=admission,
                )
            principal_id = admission.interaction.principal_id
            if not isinstance(principal_id, str) or not principal_id:
                await self.admission_service.finish_interaction_provider_mutation(
                    interaction_id=admission.interaction.id,
                    status=ExternalChannelInteractionStatus.FAILED,
                    error_kind="selector_principal_missing",
                    error_summary="Discord selector principal is unavailable.",
                )
                raise RuntimeError("Discord selector principal is unavailable.")
            try:
                response: dict[str, object]
                if materialization.selector_interaction is None:
                    response = {
                        "type": 4,
                        "data": {
                            "flags": 64,
                            "content": (
                                "This conversation is already linked to an Agent."
                            ),
                            "embeds": [
                                {
                                    "title": "Conversation already linked",
                                    "description": (
                                        "This conversation is already linked to an "
                                        "Agent."
                                    ),
                                    "color": 0xFEE75C,
                                }
                            ],
                        },
                    }
                else:
                    response = await self.selector_response_service.initial_response(
                        selector_interaction_id=materialization.selector_interaction.id,
                        principal_id=principal_id,
                        now=received_at,
                    )
            except Exception:
                await self.admission_service.finish_interaction_provider_mutation(
                    interaction_id=admission.interaction.id,
                    status=ExternalChannelInteractionStatus.FAILED,
                    error_kind="selector_response_failed",
                    error_summary="Discord selector response could not be created.",
                )
                raise
            await self.admission_service.finish_interaction_provider_mutation(
                interaction_id=admission.interaction.id,
                status=ExternalChannelInteractionStatus.COMPLETED,
                error_kind=None,
                error_summary=None,
            )
            return DiscordHTTPAdmissionResult(
                envelope=envelope,
                admission=admission,
                response=response,
            )
        return DiscordHTTPAdmissionResult(envelope=envelope, admission=admission)

    async def attempt_control_delivery(
        self,
        *,
        connection_id: str,
        delivery_attempt_id: str,
    ) -> None:
        """Run one post-response selector control delivery from its durable intent."""
        await self.selector_response_service.attempt_control_delivery(
            connection_id=connection_id,
            delivery_attempt_id=delivery_attempt_id,
        )
