"""Typed access and selector replay for synchronous conversation ingestion."""

import dataclasses
import datetime
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelAccessRequestStatus,
    ExternalChannelConnectionStatus,
    ExternalChannelInteractionStatus,
    ExternalChannelParticipationSettingStatus,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelSetupClaimStatus,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import (
    ExternalChannelAccessRequest,
    ExternalChannelConnectionConfiguration,
    ExternalChannelConversationPosition,
    ExternalChannelPrincipal,
    ExternalChannelResource,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.conversation import (
    ExternalChannelConversationScope,
    ExternalChannelOperationDeadline,
)
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
from azents.services.external_channel.participation_state import (
    build_setup_continuation_request,
    setup_source_from_projection,
)
from azents.services.external_channel.selector_state import (
    selector_state_from_interaction,
)

_REPLAY_OPERATION_BUDGET = datetime.timedelta(seconds=30)


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
    """Reconstruct immutable access, selector, and setup replay."""

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    repository: Annotated[
        ExternalChannelRepository,
        Depends(ExternalChannelRepository),
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
            access_request_id=access_request_id,
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
            access_request_id=None,
        )

    async def replay_setup_claim(
        self,
        *,
        setup_claim_id: str,
        deadline: ExternalChannelOperationDeadline,
    ) -> ExternalChannelIngestionOutcome:
        """Replay one selected setup claim through its frozen source."""
        async with self.session_manager() as session:
            request = await self._load_setup_request(
                session,
                setup_claim_id=setup_claim_id,
                deadline=deadline,
            )
        return await self.ingestion_service.ingest(request)

    async def recover_selected_setup_claims(
        self,
        *,
        limit: int,
        now: datetime.datetime,
    ) -> tuple[ExternalChannelIngestionOutcome, ...]:
        """Attempt a bounded oldest-first selected-setup recovery pass."""
        async with self.session_manager() as session:
            claims = await self.repository.list_selected_setup_claims(
                session,
                limit=limit,
            )
        outcomes: list[ExternalChannelIngestionOutcome] = []
        for claim in claims:
            outcomes.append(
                await self.replay_setup_claim(
                    setup_claim_id=claim.id,
                    deadline=external_channel_replay_deadline(now=now),
                )
            )
        return tuple(outcomes)

    async def _load_setup_request(
        self,
        session: AsyncSession,
        *,
        setup_claim_id: str,
        deadline: ExternalChannelOperationDeadline,
    ) -> ExternalChannelIngestionRequest:
        claim = await self.repository.get_setup_claim(
            session,
            claim_id=setup_claim_id,
        )
        if (
            claim is None
            or claim.status is not ExternalChannelSetupClaimStatus.SELECTED
            or claim.route_id is None
            or claim.selected_setting_id is None
            or claim.selected_resource_id is None
            or claim.selected_source_revision is None
        ):
            raise ExternalChannelIngestionReplayUnavailable(
                "External Channel setup replay boundary is unavailable."
            )
        configuration = await self.repository.get_connection_configuration(
            session,
            connection_id=claim.connection_id,
        )
        setting = await self.repository.get_active_participation_setting(
            session,
            connection_id=claim.connection_id,
            provider_parent_channel_id=claim.provider_parent_channel_id,
        )
        source_resource = await self.repository.get_resource(
            session,
            resource_id=claim.source_resource_id,
        )
        target_resource = await self.repository.get_resource(
            session,
            resource_id=claim.selected_resource_id,
        )
        principal = await self.repository.get_principal(
            session,
            principal_id=claim.principal_id,
        )
        if (
            configuration is None
            or configuration.provider_tenant_id is None
            or configuration.status
            not in {
                ExternalChannelConnectionStatus.ACTIVE,
                ExternalChannelConnectionStatus.DEGRADED,
                ExternalChannelConnectionStatus.RECONNECT_REQUIRED,
            }
            or setting is None
            or setting.id != claim.selected_setting_id
            or setting.route_id != claim.route_id
            or setting.status is not ExternalChannelParticipationSettingStatus.ACTIVE
            or source_resource is None
            or source_resource.connection_id != claim.connection_id
            or source_resource.status is not ExternalChannelResourceStatus.ACTIVE
            or target_resource is None
            or target_resource.connection_id != claim.connection_id
            or target_resource.status is not ExternalChannelResourceStatus.ACTIVE
            or principal is None
            or principal.provider is not configuration.provider
            or principal.provider_tenant_id != configuration.provider_tenant_id
            or principal.author_type is not ExternalChannelPrincipalAuthorType.HUMAN
        ):
            raise ExternalChannelIngestionReplayUnavailable(
                "External Channel setup replay owners are unavailable."
            )
        return build_setup_continuation_request(
            configuration=configuration,
            claim=claim,
            setting=setting,
            source_resource=source_resource,
            principal=principal,
            source=setup_source_from_projection(claim.source_projection),
            deadline=deadline,
        )

    async def _ingest_source(
        self,
        source: _ReplaySource,
        *,
        operation: ExternalChannelIngestionOperation,
        deadline: ExternalChannelOperationDeadline,
        provider_user_id: str | None,
        access_request_id: str | None,
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
                access_request_id=access_request_id,
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
        del deadline
        labels = source.resource.labels or {}
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
        if parent_channel_id is None:
            return None
        return root_message_id

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
                ExternalChannelConnectionStatus.RECONNECT_REQUIRED,
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
    access_request_id: str | None,
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
        provider_event_type=_provider_event_type(
            provider=configuration.provider,
            labels=labels,
        ),
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
        access_request_id=access_request_id,
    )


def _provider_event_type(
    *,
    provider: ExternalChannelProvider,
    labels: dict[str, object],
) -> str:
    value = labels.get("provider_event_type")
    expected = {
        ExternalChannelProvider.SLACK: {"app_mention", "message"},
        ExternalChannelProvider.DISCORD: {"discord_message_create"},
    }
    return (
        value if isinstance(value, str) and value in expected[provider] else "unknown"
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


def _retryable_failure() -> ExternalChannelIngestionOutcome:
    return ExternalChannelIngestionOutcome(
        kind=ExternalChannelIngestionOutcomeKind.RETRYABLE_FAILURE,
        reason=ExternalChannelIngestionReason.HISTORY_UNAVAILABLE,
        mailbox_item_id=None,
        control_delivery_attempt_id=None,
        connection_id=None,
    )
