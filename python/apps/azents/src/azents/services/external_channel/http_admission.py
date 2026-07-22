"""Slack HTTP callback orchestration with durable event admission."""

import datetime
from dataclasses import dataclass
from typing import Annotated, assert_never

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelConnectionStatus,
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
from azents.services.external_channel.credentials import ExternalChannelCredentialsCodec
from azents.services.external_channel.data import SlackConnectionCredentials
from azents.services.external_channel.slack_http import (
    SlackEventCallback,
    SlackEventRouteIdentity,
    SlackHTTPUnauthorized,
    SlackURLVerification,
    parse_slack_callback,
    parse_slack_callback_route,
    verify_slack_signature,
)


@dataclass(frozen=True)
class SlackHTTPAdmissionResult:
    """Provider acknowledgement payload after verification and optional commit."""

    challenge: str | None
    event_id: str | None
    created: bool | None


@dataclass
class SlackHTTPAdmissionService:
    """Verify a Slack callback and durably admit ordinary events before return."""

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    repository: Annotated[
        ExternalChannelRepository,
        Depends(ExternalChannelRepository),
    ]
    credentials_codec: Annotated[
        ExternalChannelCredentialsCodec,
        Depends(get_external_channel_credentials_codec),
    ]
    admission_service: Annotated[
        ExternalChannelAdmissionService,
        Depends(ExternalChannelAdmissionService),
    ]

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
                created=None,
            )
        if not isinstance(route, SlackEventRouteIdentity):
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
                admission = await self.admission_service.admit(event)
                return SlackHTTPAdmissionResult(
                    challenge=None,
                    event_id=admission.event.id,
                    created=admission.created,
                )
            case _ as unreachable:
                assert_never(unreachable)
