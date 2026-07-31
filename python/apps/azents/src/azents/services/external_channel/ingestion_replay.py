"""Typed access and selector replay for synchronous conversation ingestion."""

import asyncio
import dataclasses
import datetime
from collections.abc import AsyncIterator
from typing import Annotated

import httpx
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelAccessRequestStatus,
    ExternalChannelConnectionStatus,
    ExternalChannelInteractionStatus,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import (
    ExternalChannelAccessRequest,
    ExternalChannelConnection,
    ExternalChannelConnectionConfiguration,
    ExternalChannelConversationPosition,
    ExternalChannelPrincipal,
    ExternalChannelResource,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.external_channel.work import ExternalChannelWorkRepository
from azents.services.external_channel.connection import (
    get_external_channel_credentials_codec,
)
from azents.services.external_channel.conversation import (
    ExternalChannelConversationScope,
    ExternalChannelOperationDeadline,
)
from azents.services.external_channel.credentials import ExternalChannelCredentialsCodec
from azents.services.external_channel.data import DiscordConnectionCredentials
from azents.services.external_channel.discord_delivery import DiscordDeliveryClient
from azents.services.external_channel.ingestion import (
    ExternalChannelConversationIngestionService,
    ExternalChannelIngestionOperation,
    ExternalChannelIngestionOutcome,
    ExternalChannelIngestionOutcomeKind,
    ExternalChannelIngestionReason,
    ExternalChannelIngestionRequest,
    ExternalChannelIngressAuthority,
    ExternalChannelIngressAuthorityKind,
    ExternalChannelReplayBoundary,
    ExternalChannelTriggerLocator,
)
from azents.services.external_channel.ingestion_deps import (
    get_external_channel_conversation_ingestion_service,
)
from azents.services.external_channel.selector_state import (
    selector_state_from_interaction,
)

_REPLAY_OPERATION_BUDGET = datetime.timedelta(seconds=30)


async def get_replay_discord_http_client() -> AsyncIterator[httpx.AsyncClient]:
    """Provide bounded Discord transport for replay thread provisioning."""
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
        yield client


def get_replay_discord_delivery_client(
    http_client: Annotated[
        httpx.AsyncClient,
        Depends(get_replay_discord_http_client),
    ],
) -> DiscordDeliveryClient:
    """Provide the Discord replay thread-provisioning adapter."""
    return DiscordDeliveryClient(http_client)


class ExternalChannelIngestionReplayUnavailable(ValueError):
    """A retained selector or access boundary cannot be replayed safely."""


def external_channel_replay_deadline(
    *,
    now: datetime.datetime,
) -> ExternalChannelOperationDeadline:
    """Build one bounded absolute deadline for an authenticated replay."""
    return ExternalChannelOperationDeadline(now + _REPLAY_OPERATION_BUDGET)


def access_request_uses_typed_replay(
    request: ExternalChannelAccessRequest,
) -> bool:
    """Return whether an access request carries any typed replay identity."""
    return (
        request.conversation_position_id is not None
        or request.trigger_position is not None
    )


@dataclasses.dataclass(frozen=True)
class _ReplaySource:
    """Content-free durable owners needed to reconstruct one replay."""

    configuration: ExternalChannelConnectionConfiguration
    position: ExternalChannelConversationPosition
    resource: ExternalChannelResource
    principal: ExternalChannelPrincipal
    route_id: str
    trigger_provider_message_key: str
    range_start_position: str | None
    trigger_position: str


@dataclasses.dataclass
class ExternalChannelIngestionReplayService:
    """Reconstruct immutable access and selector replay without provider content."""

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    repository: Annotated[
        ExternalChannelRepository,
        Depends(ExternalChannelRepository),
    ]
    work_repository: Annotated[
        ExternalChannelWorkRepository,
        Depends(ExternalChannelWorkRepository),
    ]
    credentials_codec: Annotated[
        ExternalChannelCredentialsCodec,
        Depends(get_external_channel_credentials_codec),
    ]
    discord_client: Annotated[
        DiscordDeliveryClient,
        Depends(get_replay_discord_delivery_client),
    ]
    ingestion_service: Annotated[
        ExternalChannelConversationIngestionService,
        Depends(get_external_channel_conversation_ingestion_service),
    ]

    async def replay_access_allow(
        self,
        *,
        access_request_id: str,
        deadline: ExternalChannelOperationDeadline,
    ) -> ExternalChannelIngestionOutcome:
        """Replay one committed Allow through its retained original boundary."""
        async with self.session_manager() as session:
            request = await self.repository.get_access_request(
                session,
                access_request_id=access_request_id,
            )
            if (
                request is None
                or request.status is not ExternalChannelAccessRequestStatus.ALLOWED
                or request.connection_id is None
                or request.conversation_position_id is None
                or request.trigger_position is None
            ):
                raise ExternalChannelIngestionReplayUnavailable(
                    "External Channel access replay boundary is unavailable."
                )
            source = await self._load_source(
                session,
                connection_id=request.connection_id,
                conversation_position_id=request.conversation_position_id,
                resource_id=request.resource_id,
                principal_id=request.principal_id,
                route_id=request.route_id,
                trigger_provider_message_key=(request.trigger_provider_message_key),
                range_start_position=request.range_start_position,
                trigger_position=request.trigger_position,
            )
        return await self._ingest_source(
            source,
            operation=ExternalChannelIngestionOperation.ACCESS_ALLOW,
            deadline=deadline,
            provider_user_id=source.principal.provider_user_id,
        )

    async def replay_selected_interaction(
        self,
        *,
        selector_interaction_id: str,
        principal_id: str,
        deadline: ExternalChannelOperationDeadline,
    ) -> ExternalChannelIngestionOutcome:
        """Replay one immutable selected route through interaction-owned state."""
        async with self.session_manager() as session:
            interaction = await self.repository.lock_interaction(
                session,
                interaction_id=selector_interaction_id,
            )
            if (
                interaction is None
                or interaction.principal_id != principal_id
                or interaction.status
                in {
                    ExternalChannelInteractionStatus.EXPIRED,
                    ExternalChannelInteractionStatus.REJECTED,
                    ExternalChannelInteractionStatus.FAILED,
                }
            ):
                raise ExternalChannelIngestionReplayUnavailable(
                    "External Channel selector replay boundary is unavailable."
                )
            state = selector_state_from_interaction(interaction)
            if state.principal_id != principal_id or state.selected_route_id is None:
                raise ExternalChannelIngestionReplayUnavailable(
                    "External Channel selector replay boundary is unavailable."
                )
            source = await self._load_source(
                session,
                connection_id=state.connection_id,
                conversation_position_id=state.conversation_position_id,
                resource_id=state.resource_id,
                principal_id=state.principal_id,
                route_id=state.selected_route_id,
                trigger_provider_message_key=state.trigger_provider_message_key,
                range_start_position=state.range_start_position,
                trigger_position=state.trigger_position,
            )
        return await self._ingest_source(
            source,
            operation=ExternalChannelIngestionOperation.SELECTOR_CONTINUATION,
            deadline=deadline,
            provider_user_id=None,
        )

    async def _ingest_source(
        self,
        source: _ReplaySource,
        *,
        operation: ExternalChannelIngestionOperation,
        deadline: ExternalChannelOperationDeadline,
        provider_user_id: str | None,
    ) -> ExternalChannelIngestionOutcome:
        delivery_thread_key = await self._resolve_delivery_thread_key(
            source,
            deadline=deadline,
        )
        if (
            source.configuration.provider is ExternalChannelProvider.DISCORD
            and delivery_thread_key is None
        ):
            return _retryable_failure()
        return await self.ingestion_service.ingest(
            _build_request(
                source,
                operation=operation,
                deadline=deadline,
                provider_user_id=provider_user_id,
                delivery_thread_key=delivery_thread_key,
            )
        )

    async def _resolve_delivery_thread_key(
        self,
        source: _ReplaySource,
        *,
        deadline: ExternalChannelOperationDeadline,
    ) -> str | None:
        configuration = source.configuration
        initial = _delivery_thread_key(
            provider=configuration.provider,
            labels=source.resource.labels or {},
            position=source.position,
        )
        if configuration.provider is not ExternalChannelProvider.DISCORD or initial:
            return initial
        async with self.session_manager() as session:
            resource = await self._lock_discord_provisioning_authority(
                session,
                source=source,
            )
            await session.commit()
        if resource is None:
            return None
        labels = resource.labels or {}
        current = _delivery_thread_key(
            provider=configuration.provider,
            labels=labels,
            position=source.position,
        )
        if current:
            return current
        tenant_id = configuration.provider_tenant_id
        if tenant_id is None:
            raise ExternalChannelIngestionReplayUnavailable(
                "External Channel replay tenant is unavailable."
            )
        parent_channel_id = _provider_parent_channel_id(
            provider=configuration.provider,
            labels=labels,
        )
        root_message_id = _provider_message_id(
            provider=configuration.provider,
            tenant_id=tenant_id,
            provider_message_key=source.trigger_provider_message_key,
        )
        encrypted_credentials = configuration.encrypted_credentials
        if parent_channel_id is None or encrypted_credentials is None:
            return None
        credentials = self.credentials_codec.decrypt(encrypted_credentials)
        if not isinstance(credentials, DiscordConnectionCredentials):
            return None
        try:
            async with asyncio.timeout(deadline.remaining_seconds()):
                result = await self.discord_client.ensure_thread(
                    bot_token=credentials.bot_token,
                    parent_channel_id=parent_channel_id,
                    root_message_id=root_message_id,
                )
        except TimeoutError:
            return None
        if result.status != "delivered":
            return None
        resolved = _discord_thread_channel_id(result.provider_message_key)
        if resolved is None:
            return None
        async with self.session_manager() as session:
            resource = await self._lock_discord_provisioning_authority(
                session,
                source=source,
            )
            if resource is None:
                await session.rollback()
                return None
            concurrent = _delivery_thread_key(
                provider=configuration.provider,
                labels=resource.labels or {},
                position=source.position,
            )
            if concurrent:
                await session.commit()
                return concurrent
            retained = await self.work_repository.record_discord_delivery_channel(
                session,
                resource_id=source.resource.id,
                delivery_channel_id=resolved,
            )
            await session.commit()
        return retained

    async def _lock_discord_provisioning_authority(
        self,
        session: AsyncSession,
        *,
        source: _ReplaySource,
    ) -> ExternalChannelResource | None:
        configuration = source.configuration
        connection = await self.repository.lock_connection_for_routing(
            session,
            connection_id=configuration.id,
        )
        resource = await self.repository.lock_resource(
            session,
            resource_id=source.resource.id,
        )
        if (
            connection is None
            or not _connection_matches_replay(configuration, connection)
            or resource is None
            or resource.connection_id != connection.id
            or resource.status is not ExternalChannelResourceStatus.ACTIVE
            or resource.provider_resource_key != source.resource.provider_resource_key
        ):
            return None
        return resource

    async def _load_source(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        conversation_position_id: str,
        resource_id: str,
        principal_id: str,
        route_id: str,
        trigger_provider_message_key: str,
        range_start_position: str | None,
        trigger_position: str,
    ) -> _ReplaySource:
        configuration = await self.repository.get_connection_configuration(
            session,
            connection_id=connection_id,
        )
        position = await self.repository.get_conversation_position(
            session,
            position_id=conversation_position_id,
        )
        resource = await self.repository.get_resource(
            session,
            resource_id=resource_id,
        )
        principal = await self.repository.get_principal(
            session,
            principal_id=principal_id,
        )
        route = await self.repository.get_agent_route(session, route_id=route_id)
        if (
            configuration is None
            or configuration.provider_tenant_id is None
            or configuration.status
            not in {
                ExternalChannelConnectionStatus.ACTIVE,
                ExternalChannelConnectionStatus.DEGRADED,
            }
            or position is None
            or position.connection_id != connection_id
            or resource is None
            or resource.connection_id != connection_id
            or resource.status is not ExternalChannelResourceStatus.ACTIVE
            or principal is None
            or principal.provider is not configuration.provider
            or principal.provider_tenant_id != configuration.provider_tenant_id
            or principal.author_type is not ExternalChannelPrincipalAuthorType.HUMAN
            or route is None
            or route.connection_id != connection_id
        ):
            raise ExternalChannelIngestionReplayUnavailable(
                "External Channel replay owners are unavailable."
            )
        return _ReplaySource(
            configuration=configuration,
            position=position,
            resource=resource,
            principal=principal,
            route_id=route_id,
            trigger_provider_message_key=trigger_provider_message_key,
            range_start_position=range_start_position,
            trigger_position=trigger_position,
        )


def _build_request(
    source: _ReplaySource,
    *,
    operation: ExternalChannelIngestionOperation,
    deadline: ExternalChannelOperationDeadline,
    provider_user_id: str | None,
    delivery_thread_key: str | None,
) -> ExternalChannelIngestionRequest:
    configuration = source.configuration
    tenant_id = configuration.provider_tenant_id
    if tenant_id is None:
        raise ExternalChannelIngestionReplayUnavailable(
            "External Channel replay tenant is unavailable."
        )
    labels = source.resource.labels or {}
    locator = ExternalChannelTriggerLocator(
        connection_id=configuration.id,
        provider=configuration.provider,
        provider_tenant_id=tenant_id,
        provider_channel_id=source.position.provider_channel_id,
        provider_parent_channel_id=_provider_parent_channel_id(
            provider=configuration.provider,
            labels=labels,
        ),
        provider_thread_key=source.position.provider_thread_key,
        delivery_thread_key=delivery_thread_key,
        provider_resource_key=source.resource.provider_resource_key,
        trigger_provider_message_key=source.trigger_provider_message_key,
        trigger_provider_message_id=_provider_message_id(
            provider=configuration.provider,
            tenant_id=tenant_id,
            provider_message_key=source.trigger_provider_message_key,
        ),
        trigger_position=source.trigger_position,
        provider_user_id=provider_user_id,
        invocation=True,
    )
    return ExternalChannelIngestionRequest(
        locator=locator,
        scope=ExternalChannelConversationScope(
            connection_id=configuration.id,
            kind=source.position.scope_kind,
            provider_channel_id=source.position.provider_channel_id,
            provider_thread_key=source.position.provider_thread_key,
        ),
        authority=ExternalChannelIngressAuthority(
            kind=ExternalChannelIngressAuthorityKind.DURABLE_REPLAY,
            ingress_profile=configuration.ingress_profile,
            configuration_generation=configuration.configuration_generation,
            lease_owner=None,
            lease_generation=None,
        ),
        deadline=deadline,
        operation=operation,
        selected_route_id=source.route_id,
        replay_boundary=ExternalChannelReplayBoundary(
            connection_id=configuration.id,
            resource_id=source.resource.id,
            principal_id=source.principal.id,
            trigger_provider_message_key=source.trigger_provider_message_key,
            conversation_position_id=source.position.id,
            range_start_position=source.range_start_position,
            trigger_position=source.trigger_position,
        ),
    )


def _provider_message_id(
    *,
    provider: ExternalChannelProvider,
    tenant_id: str,
    provider_message_key: str,
) -> str:
    prefix = f"{provider.value}:{tenant_id}:"
    if not provider_message_key.startswith(prefix):
        raise ExternalChannelIngestionReplayUnavailable(
            "External Channel replay message identity is invalid."
        )
    remainder = provider_message_key.removeprefix(prefix)
    if provider is ExternalChannelProvider.SLACK:
        parts = remainder.split(":", 1)
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise ExternalChannelIngestionReplayUnavailable(
                "External Channel Slack replay identity is invalid."
            )
        return parts[1]
    if not remainder or ":" in remainder:
        raise ExternalChannelIngestionReplayUnavailable(
            "External Channel Discord replay identity is invalid."
        )
    return remainder


def _delivery_thread_key(
    *,
    provider: ExternalChannelProvider,
    labels: dict[str, object],
    position: ExternalChannelConversationPosition,
) -> str | None:
    if provider is ExternalChannelProvider.SLACK:
        value = labels.get("thread_ts")
    else:
        value = labels.get("delivery_channel_id") or labels.get("thread_channel_id")
        if value is None:
            thread_id = labels.get("thread_id")
            root_message_id = labels.get("root_message_id")
            if root_message_id is None or root_message_id != thread_id:
                value = thread_id
    if isinstance(value, str) and value:
        return value
    return position.provider_thread_key


def _provider_parent_channel_id(
    *,
    provider: ExternalChannelProvider,
    labels: dict[str, object],
) -> str | None:
    if provider is ExternalChannelProvider.SLACK:
        return None
    value = labels.get("parent_channel_id") or labels.get("channel_id")
    return value if isinstance(value, str) and value else None


def _connection_matches_replay(
    configuration: ExternalChannelConnectionConfiguration,
    connection: ExternalChannelConnection,
) -> bool:
    capabilities = connection.capabilities or {}
    return (
        connection.provider is ExternalChannelProvider.DISCORD
        and connection.provider is configuration.provider
        and connection.status
        in {
            ExternalChannelConnectionStatus.ACTIVE,
            ExternalChannelConnectionStatus.DEGRADED,
        }
        and connection.provider_tenant_id == configuration.provider_tenant_id
        and connection.configuration_generation
        == configuration.configuration_generation
        and capabilities.get("post_messages") is True
    )


def _discord_thread_channel_id(provider_message_key: str | None) -> str | None:
    if provider_message_key is None:
        return None
    prefix = "discord-thread:"
    if not provider_message_key.startswith(prefix):
        return None
    thread_id = provider_message_key.removeprefix(prefix)
    return thread_id if thread_id.isdigit() else None


def _retryable_failure() -> ExternalChannelIngestionOutcome:
    return ExternalChannelIngestionOutcome(
        kind=ExternalChannelIngestionOutcomeKind.RETRYABLE_FAILURE,
        reason=ExternalChannelIngestionReason.HISTORY_UNAVAILABLE,
        mailbox_item_id=None,
        control_delivery_attempt_id=None,
        connection_id=None,
    )
