"""Slack HTTP callback orchestration with durable event admission."""

import datetime
from dataclasses import dataclass, field
from typing import Annotated, assert_never

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelConnectionStatus,
    ExternalChannelIngressProfile,
    ExternalChannelInteractionStatus,
    ExternalChannelProvider,
    ExternalChannelTransport,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.admission import ExternalChannelAdmissionService
from azents.services.external_channel.connection import (
    get_external_channel_credentials_codec,
)
from azents.services.external_channel.connection_revocation import (
    ExternalChannelConnectionRevocationService,
)
from azents.services.external_channel.credentials import ExternalChannelCredentialsCodec
from azents.services.external_channel.data import SlackConnectionCredentials
from azents.services.external_channel.ingestion import (
    ExternalChannelIngestionOutcomeKind,
    ExternalChannelIngressAuthority,
    ExternalChannelIngressAuthorityKind,
)
from azents.services.external_channel.interaction import (
    ExternalChannelInteractionHandoff,
    ExternalChannelInteractionProcessor,
)
from azents.services.external_channel.provider_effect import ProviderEffectPlan
from azents.services.external_channel.shortcut_source import (
    ExternalChannelShortcutSourceService,
)
from azents.services.external_channel.slack_events import SlackConnectionRevocation
from azents.services.external_channel.slack_http import (
    SlackEventCallback,
    SlackEventRouteIdentity,
    SlackHTTPUnauthorized,
    SlackInteractionCallback,
    SlackInteractionRouteIdentity,
    SlackURLVerification,
    parse_slack_callback,
    parse_slack_callback_route,
    project_slack_shortcut_source_event_from_callback_body,
    slack_event_is_normal_message_ingress,
    verify_slack_signature,
)
from azents.services.external_channel.transport_ingestion import (
    ExternalChannelTransportIngestionService,
    external_channel_transport_deadline,
    transport_outcome_acknowledgeable,
)


@dataclass(frozen=True)
class SlackHTTPAdmissionResult:
    """Provider acknowledgement payload after verification and optional commit."""

    challenge: str | None
    event_id: str | None
    interaction_id: str | None
    created: bool | None
    interaction_handoff: ExternalChannelInteractionHandoff | None = field(
        default=None,
        repr=False,
    )
    control_plans: tuple[ProviderEffectPlan, ...] = field(default=(), repr=False)
    control_delivery_connection_id: str | None = field(default=None, repr=False)


class SlackHTTPMessageIngressQuiesced(RuntimeError):
    """Normal Slack message ingress is temporarily quiesced."""


class SlackHTTPRetryableIngestion(RuntimeError):
    """Slack message ingestion did not reach an acknowledgeable outcome."""


@dataclass
class SlackHTTPAdmissionService:
    """Verify a Slack callback and durably admit it before acknowledgement."""

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    repository: Annotated[
        ExternalChannelRepository,
        Depends(ExternalChannelRepository.create),
    ]
    credentials_codec: Annotated[
        ExternalChannelCredentialsCodec,
        Depends(get_external_channel_credentials_codec),
    ]
    admission_service: Annotated[
        ExternalChannelAdmissionService,
        Depends(ExternalChannelAdmissionService),
    ]
    interaction_processor: Annotated[
        ExternalChannelInteractionProcessor,
        Depends(ExternalChannelInteractionProcessor),
    ]
    shortcut_source_service: Annotated[
        ExternalChannelShortcutSourceService,
        Depends(ExternalChannelShortcutSourceService),
    ]
    transport_ingestion_service: Annotated[
        ExternalChannelTransportIngestionService,
        Depends(ExternalChannelTransportIngestionService),
    ]
    revocation_service: Annotated[
        ExternalChannelConnectionRevocationService,
        Depends(ExternalChannelConnectionRevocationService),
    ]
    config: Annotated[Config | None, Depends(get_config)] = None

    async def handle(
        self,
        *,
        raw_body: bytes,
        timestamp_header: str | None,
        signature_header: str | None,
        received_at: datetime.datetime,
    ) -> SlackHTTPAdmissionResult:
        """Authenticate, normalize, and admit one Slack callback."""
        route = parse_slack_callback_route(raw_body)
        if isinstance(route, SlackURLVerification):
            return SlackHTTPAdmissionResult(
                challenge=route.challenge,
                event_id=None,
                interaction_id=None,
                created=None,
            )
        if not isinstance(
            route, SlackEventRouteIdentity | SlackInteractionRouteIdentity
        ):
            raise AssertionError("Slack callback route is not exhaustive.")
        async with self.session_manager() as session:
            configuration = (
                await self.repository.get_slack_http_configuration_by_provider_identity(
                    session,
                    provider_app_id=route.app_id,
                    provider_tenant_id=route.tenant_id,
                )
            )
        if configuration is None:
            raise SlackHTTPUnauthorized("Slack callback could not be authenticated.")
        if (
            configuration.provider is not ExternalChannelProvider.SLACK
            or configuration.transport is not ExternalChannelTransport.HTTP
            or configuration.encrypted_credentials is None
        ):
            raise SlackHTTPUnauthorized("Slack callback could not be authenticated.")
        credentials = self.credentials_codec.decrypt(
            configuration.encrypted_credentials
        )
        if not isinstance(credentials, SlackConnectionCredentials):
            raise SlackHTTPUnauthorized("Slack callback could not be authenticated.")
        verify_slack_signature(
            raw_body=raw_body,
            timestamp_header=timestamp_header,
            signature_header=signature_header,
            signing_secret=credentials.signing_secret,
            now=received_at,
        )
        callback = parse_slack_callback(
            connection_id=configuration.id,
            raw_body=raw_body,
            received_at=received_at,
        )
        match callback:
            case SlackURLVerification():
                raise SlackHTTPUnauthorized(
                    "Slack callback could not be authenticated."
                )
            case SlackEventCallback(app_id=app_id, tenant_id=tenant_id, event=event):
                if configuration.status not in {
                    ExternalChannelConnectionStatus.ACTIVE,
                    ExternalChannelConnectionStatus.DEGRADED,
                }:
                    raise SlackHTTPUnauthorized(
                        "Slack callback could not be authenticated."
                    )
                if (
                    configuration.provider_app_id != app_id
                    or configuration.provider_tenant_id != tenant_id
                ):
                    raise SlackHTTPUnauthorized(
                        "Slack callback could not be authenticated."
                    )
                if (
                    self.config is not None
                    and self.config.external_channel_conversation.quiesce.slack_http
                    and slack_event_is_normal_message_ingress(event)
                ):
                    raise SlackHTTPMessageIngressQuiesced(
                        "Slack message ingress is temporarily quiesced."
                    )
                result = await self.transport_ingestion_service.ingest_slack_event(
                    event=event,
                    connected_bot_user_id=configuration.provider_bot_user_id,
                    authority=ExternalChannelIngressAuthority(
                        kind=ExternalChannelIngressAuthorityKind.CONFIGURATION,
                        ingress_profile=ExternalChannelIngressProfile.SLACK_HTTP,
                        configuration_generation=(
                            configuration.configuration_generation
                        ),
                        lease_owner=None,
                        lease_generation=None,
                    ),
                    deadline=external_channel_transport_deadline(received_at),
                )
                if result is None:
                    return SlackHTTPAdmissionResult(
                        challenge=None,
                        event_id=event.provider_event_id,
                        interaction_id=None,
                        created=False,
                    )
                if isinstance(result, SlackConnectionRevocation):
                    changed = await self.revocation_service.apply(
                        connection_id=configuration.id,
                        revocation=result,
                        required_configuration_generation=(
                            configuration.configuration_generation
                        ),
                        required_socket_lease_owner=None,
                        now=received_at,
                    )
                    if not changed:
                        raise SlackHTTPUnauthorized(
                            "Slack callback could not be authenticated."
                        )
                    return SlackHTTPAdmissionResult(
                        challenge=None,
                        event_id=event.provider_event_id,
                        interaction_id=None,
                        created=False,
                    )
                if not transport_outcome_acknowledgeable(result):
                    raise SlackHTTPRetryableIngestion(
                        "Slack message ingestion is temporarily unavailable."
                    )
                return SlackHTTPAdmissionResult(
                    challenge=None,
                    event_id=event.provider_event_id,
                    interaction_id=None,
                    created=(
                        result.kind is ExternalChannelIngestionOutcomeKind.ACCEPTED
                    ),
                    control_plans=result.control_plans,
                    control_delivery_connection_id=result.connection_id,
                )
            case (
                SlackInteractionCallback(app_id=app_id, tenant_id=tenant_id) as callback
            ):
                if configuration.status not in {
                    ExternalChannelConnectionStatus.ACTIVE,
                    ExternalChannelConnectionStatus.DEGRADED,
                }:
                    raise SlackHTTPUnauthorized(
                        "Slack callback could not be authenticated."
                    )
                if (
                    configuration.provider_app_id != app_id
                    or configuration.provider_tenant_id != tenant_id
                ):
                    raise SlackHTTPUnauthorized(
                        "Slack callback could not be authenticated."
                    )
                shortcut_source_event = (
                    project_slack_shortcut_source_event_from_callback_body(
                        connection_id=configuration.id,
                        raw_body=raw_body,
                        provider_interaction_key=callback.provider_interaction_key,
                        received_at=received_at,
                    )
                    if (
                        configuration.app_mode is ExternalChannelAppMode.MULTI
                        and callback.handler == "selector_open"
                    )
                    else None
                )
                admission = await self.admission_service.admit_interaction(
                    create=callback.interaction_create(
                        connection_id=configuration.id,
                        transport=ExternalChannelTransport.HTTP,
                    ),
                    principal=callback.principal_create(),
                )
                if shortcut_source_event is not None:
                    await self.shortcut_source_service.ensure(
                        shortcut_source_event=shortcut_source_event,
                        interaction_id=admission.interaction.id,
                        now=received_at,
                    )
                interaction_supported = callback.requires_provider_processing(
                    app_mode=configuration.app_mode,
                )
                claim = (
                    await self.admission_service.begin_interaction_provider_mutation(
                        interaction_id=admission.interaction.id,
                        now=received_at,
                    )
                    if interaction_supported
                    else None
                )
                if not interaction_supported:
                    await self.admission_service.finish_interaction_provider_mutation(
                        interaction_id=admission.interaction.id,
                        status=ExternalChannelInteractionStatus.REJECTED,
                        error_kind="interaction_unsupported",
                        error_summary=(
                            "Slack interaction has no supported callback handler."
                        ),
                    )
                return SlackHTTPAdmissionResult(
                    challenge=None,
                    event_id=None,
                    interaction_id=admission.interaction.id,
                    created=admission.created,
                    interaction_handoff=(
                        ExternalChannelInteractionHandoff(
                            interaction_id=claim.interaction.id,
                            handler=callback.handler,
                            provider_parent_channel_id=(
                                callback.provider_parent_channel_id
                            ),
                            provider_thread_key=callback.provider_thread_key,
                            settings_metadata=callback.settings_metadata,
                            settings_location=callback.settings_location,
                            settings_response_mode=callback.settings_response_mode,
                            trigger_id=callback.trigger_id,
                            selector_interaction_id=callback.selector_interaction_id,
                            selector_metadata=callback.selector_metadata,
                            selected_route_id=callback.selected_route_id,
                            selector_navigation=callback.selector_navigation,
                            selector_search=callback.selector_search,
                            selector_view_id=callback.selector_view_id,
                            selector_view_hash=callback.selector_view_hash,
                        )
                        if claim is not None and claim.claimed
                        else None
                    ),
                )
            case _ as unreachable:
                assert_never(unreachable)

    async def run_interaction_handoff(
        self,
        handoff: ExternalChannelInteractionHandoff,
    ) -> None:
        """Invoke the injected processor only after the admission/claim commits."""
        await self.admission_service.run_interaction_provider_mutation(
            handoff=handoff,
            callback=self.interaction_processor.process,
        )

    async def attempt_control_delivery(
        self,
        *,
        connection_id: str,
        plan: ProviderEffectPlan,
    ) -> None:
        """Attempt one approval control after provider acknowledgement."""
        await self.interaction_processor.attempt_control_delivery(
            connection_id=connection_id,
            plan=plan,
        )
