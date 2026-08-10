"""DB-only admission for conversation-bound External Channel triggers."""

import dataclasses
import datetime
import logging
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentSessionStatus,
    ExternalChannelAppMode,
    ExternalChannelConversationLocation,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
    ExternalChannelResponseMode,
)
from azents.job_runtime.deps import get_job_runtime
from azents.job_runtime.local import JobRuntimeClosedError
from azents.job_runtime.types import JobRuntime
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.external_channel.data import (
    ExternalChannelAgentRoute,
    ExternalChannelBinding,
    ExternalChannelConnection,
    ExternalChannelConversationPositionCreate,
    ExternalChannelParticipationSetting,
    ExternalChannelPrincipalCreate,
    ExternalChannelResource,
    ExternalChannelResourceCreate,
)
from azents.repos.external_channel.ingress_queue import (
    ExternalChannelIngressQueueRepository,
)
from azents.repos.external_channel.ingress_queue_data import (
    ExternalChannelIngressItemCreate,
    ExternalChannelIngressOwnerCreate,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.ingestion import (
    ExternalChannelIngestionOutcome,
    ExternalChannelIngestionOutcomeKind,
    ExternalChannelIngestionReason,
    ExternalChannelIngestionRequest,
)
from azents.services.external_channel.ingress_queue import (
    _authority_current,
    _invocation_id,
    _outcome,
    build_external_channel_ingress_job_request,
)

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class _EffectiveTarget:
    """DB-resolved target Resource, route, setting, and optional ready Binding."""

    resource: ExternalChannelResource
    route: ExternalChannelAgentRoute
    setting: ExternalChannelParticipationSetting | None
    binding: ExternalChannelBinding | None
    response_mode: ExternalChannelResponseMode


@dataclasses.dataclass
class ExternalChannelIngressAdmissionService:
    """Persist eligible effective-conversation triggers before provider I/O."""

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    repository: Annotated[
        ExternalChannelRepository,
        Depends(ExternalChannelRepository.create),
    ]
    queue_repository: Annotated[
        ExternalChannelIngressQueueRepository,
        Depends(ExternalChannelIngressQueueRepository),
    ]
    agent_session_repository: Annotated[
        AgentSessionRepository,
        Depends(AgentSessionRepository),
    ]
    job_runtime: Annotated[JobRuntime, Depends(get_job_runtime)]

    async def admit_current_trigger(
        self,
        *,
        provider_event_id: str,
        request: ExternalChannelIngestionRequest,
    ) -> ExternalChannelIngestionOutcome | None:
        """Queue one configured trigger by its effective target conversation."""
        now = datetime.datetime.now(datetime.UTC)
        async with self.session_manager() as session:
            connection = await self._lock_authority(session, request=request, now=now)
            if connection is None:
                return None
            source_resource = await self._ensure_source_resource(
                session,
                request=request,
                now=now,
            )
            if source_resource is None:
                return None
            target = await self._resolve_target(
                session,
                request=request,
                connection=connection,
                source_resource=source_resource,
                now=now,
            )
            if target is None:
                return None
            if (
                not request.locator.invocation
                and target.response_mode is ExternalChannelResponseMode.MENTION_ONLY
            ):
                await session.commit()
                return _outcome(
                    ExternalChannelIngestionOutcomeKind.IGNORED,
                    ExternalChannelIngestionReason.RESPONSE_MODE_NOT_TRIGGERED,
                )
            provider_user_id = request.locator.provider_user_id
            if provider_user_id is None:
                await session.commit()
                return _outcome(
                    ExternalChannelIngestionOutcomeKind.TERMINAL_REJECTION,
                    ExternalChannelIngestionReason.AUTHOR_NOT_ELIGIBLE,
                )
            principal = await self.repository.create_principal_idempotent(
                session,
                ExternalChannelPrincipalCreate(
                    provider=request.locator.provider,
                    provider_tenant_id=request.locator.provider_tenant_id,
                    provider_user_id=provider_user_id,
                    author_type=ExternalChannelPrincipalAuthorType.HUMAN,
                    display_name=None,
                    avatar_url=None,
                    profile=None,
                ),
            )
            agent_id = target.route.require_active_agent_id()
            if (
                await self.repository.get_active_block(
                    session,
                    agent_id=agent_id,
                    principal_id=principal.id,
                )
                is not None
            ):
                await session.commit()
                return _outcome(
                    ExternalChannelIngestionOutcomeKind.IGNORED,
                    ExternalChannelIngestionReason.AUTHOR_NOT_ELIGIBLE,
                )
            target_session_id = (
                None if target.binding is None else target.binding.agent_session_id
            )
            grant = await self.repository.get_active_access_grant(
                session,
                agent_id=agent_id,
                principal_id=principal.id,
                agent_session_id=target_session_id,
            )
            if grant is None and not target.route.open_access_enabled:
                return None
            if target.binding is not None:
                target_session = await self.agent_session_repository.lock_by_id(
                    session,
                    target.binding.agent_session_id,
                )
                if (
                    target_session is None
                    or target_session.status is not AgentSessionStatus.ACTIVE
                    or target_session.stop_requested_at is not None
                ):
                    await session.commit()
                    return _outcome(
                        ExternalChannelIngestionOutcomeKind.TERMINAL_REJECTION,
                        ExternalChannelIngestionReason.CONVERSATION_UNAVAILABLE,
                    )
            position = await self.repository.create_conversation_position_idempotent(
                session,
                ExternalChannelConversationPositionCreate(
                    connection_id=request.scope.connection_id,
                    scope_kind=request.scope.kind,
                    provider_channel_id=request.scope.provider_channel_id,
                    provider_thread_key=request.scope.provider_thread_key,
                    read_through_position=None,
                ),
            )
            invocation_id = _invocation_id(
                connection_id=request.locator.connection_id,
                position_id=position.id,
                provider_message_key=request.locator.trigger_provider_message_key,
                trigger_position=request.locator.trigger_position,
            )
            binding_id = None if target.binding is None else target.binding.id
            session_id = (
                None if target.binding is None else target.binding.agent_session_id
            )
            admission = await self.queue_repository.admit(
                session,
                owner_create=ExternalChannelIngressOwnerCreate(
                    connection_id=connection.id,
                    target_resource_id=target.resource.id,
                    route_id=target.route.id,
                    participation_setting_id=(
                        None if target.setting is None else target.setting.id
                    ),
                    participation_settings_generation=(
                        None
                        if target.setting is None
                        else target.setting.settings_generation
                    ),
                    response_mode=target.response_mode,
                    binding_id=binding_id,
                    session_id=session_id,
                ),
                item_create=ExternalChannelIngressItemCreate(
                    deduplication_key=request.locator.digest,
                    provider_event_id=provider_event_id,
                    connection_id=connection.id,
                    provider=request.locator.provider,
                    ingress_profile=request.authority.ingress_profile,
                    configuration_generation=request.authority.configuration_generation,
                    authority_kind=request.authority.kind,
                    authority_lease_owner=request.authority.lease_owner,
                    authority_lease_generation=request.authority.lease_generation,
                    provider_event_type=request.locator.provider_event_type,
                    provider_tenant_id=request.locator.provider_tenant_id,
                    scope_kind=request.scope.kind,
                    provider_channel_id=request.locator.provider_channel_id,
                    provider_parent_channel_id=(
                        request.locator.provider_parent_channel_id
                    ),
                    provider_thread_key=request.locator.provider_thread_key,
                    delivery_thread_key=request.locator.delivery_thread_key,
                    provider_resource_key=request.locator.provider_resource_key,
                    source_resource_id=source_resource.id,
                    conversation_position_id=position.id,
                    principal_id=principal.id,
                    trigger_provider_message_key=(
                        request.locator.trigger_provider_message_key
                    ),
                    trigger_provider_message_id=(
                        request.locator.trigger_provider_message_id
                    ),
                    trigger_position=request.locator.trigger_position,
                    provider_user_id=provider_user_id,
                    invocation=request.locator.invocation,
                    invocation_id=invocation_id,
                    initial_title_eligible=request.initial_title_eligible,
                ),
            )
            await session.commit()
        if admission.replaced_stale_owner:
            logger.warning(
                "External Channel ingress stale provisioning owner was replaced",
                extra={
                    "external_channel_ingress_owner_id": admission.owner.id,
                    "external_channel_connection_id": connection.id,
                },
            )
        await self._submit(
            admission.owner.id,
            drain_created_at=admission.owner.created_at,
            now=now,
        )
        return _outcome(
            (
                ExternalChannelIngestionOutcomeKind.ACCEPTED
                if admission.created
                else ExternalChannelIngestionOutcomeKind.DUPLICATE
            ),
            (
                ExternalChannelIngestionReason.ACCEPTED
                if admission.created
                else ExternalChannelIngestionReason.DUPLICATE
            ),
        )

    async def _resolve_target(
        self,
        session: AsyncSession,
        *,
        request: ExternalChannelIngestionRequest,
        connection: ExternalChannelConnection,
        source_resource: ExternalChannelResource,
        now: datetime.datetime,
    ) -> _EffectiveTarget | None:
        exact_binding = await self.repository.lock_connected_binding_by_resource(
            session,
            resource_id=source_resource.id,
        )
        if exact_binding is not None:
            route = await self.repository.get_routable_route_by_id(
                session,
                route_id=exact_binding.route_id,
            )
            if route is None or route.connection_id != connection.id:
                return None
            return _EffectiveTarget(
                resource=source_resource,
                route=route,
                setting=None,
                binding=exact_binding,
                response_mode=exact_binding.response_mode,
            )
        route = await self._resolve_route(
            session,
            request=request,
            connection=connection,
        )
        if route is None:
            return None
        parent_channel_id = _provider_parent_channel_id(request)
        setting = await self.repository.lock_active_participation_setting(
            session,
            connection_id=connection.id,
            provider_parent_channel_id=parent_channel_id,
        )
        if setting is None or setting.route_id != route.id:
            return None
        resource = source_resource
        if setting.location is ExternalChannelConversationLocation.CHANNEL:
            resource = await self.repository.lock_resource_by_provider_key(
                session,
                connection_id=connection.id,
                resource_type=ExternalChannelResourceType.PARENT_CHANNEL,
                provider_resource_key=parent_channel_id,
            )
            if resource is None:
                await self.repository.create_resource_idempotent(
                    session,
                    ExternalChannelResourceCreate(
                        connection_id=connection.id,
                        resource_type=ExternalChannelResourceType.PARENT_CHANNEL,
                        provider_resource_key=parent_channel_id,
                        labels=_parent_resource_labels(request),
                        status=ExternalChannelResourceStatus.ACTIVE,
                        latest_activity_at=now,
                        unavailable_at=None,
                        deleted_at=None,
                    ),
                )
                resource = await self.repository.lock_resource_by_provider_key(
                    session,
                    connection_id=connection.id,
                    resource_type=ExternalChannelResourceType.PARENT_CHANNEL,
                    provider_resource_key=parent_channel_id,
                )
            if (
                resource is None
                or resource.status is not ExternalChannelResourceStatus.ACTIVE
            ):
                return None
        binding = await self.repository.lock_connected_binding_by_resource(
            session,
            resource_id=resource.id,
        )
        return _EffectiveTarget(
            resource=resource,
            route=route,
            setting=setting,
            binding=binding,
            response_mode=(
                setting.response_mode if binding is None else binding.response_mode
            ),
        )

    async def _resolve_route(
        self,
        session: AsyncSession,
        *,
        request: ExternalChannelIngestionRequest,
        connection: ExternalChannelConnection,
    ) -> ExternalChannelAgentRoute | None:
        if connection.app_mode is ExternalChannelAppMode.SINGLE:
            return await self.repository.lock_routable_single_route(
                session,
                connection_id=connection.id,
            )
        return await self.repository.lock_routable_channel_default(
            session,
            connection_id=connection.id,
            provider_channel_id=_provider_parent_channel_id(request),
        )

    async def _ensure_source_resource(
        self,
        session: AsyncSession,
        *,
        request: ExternalChannelIngestionRequest,
        now: datetime.datetime,
    ) -> ExternalChannelResource | None:
        resource = await self.repository.lock_resource_by_provider_key(
            session,
            connection_id=request.locator.connection_id,
            resource_type=ExternalChannelResourceType.THREAD,
            provider_resource_key=request.locator.provider_resource_key,
        )
        if resource is not None:
            if resource.status is not ExternalChannelResourceStatus.ACTIVE:
                return None
            return resource
        await self.repository.create_resource_idempotent(
            session,
            ExternalChannelResourceCreate(
                connection_id=request.locator.connection_id,
                resource_type=ExternalChannelResourceType.THREAD,
                provider_resource_key=request.locator.provider_resource_key,
                labels=_resource_labels(request),
                status=ExternalChannelResourceStatus.ACTIVE,
                latest_activity_at=now,
                unavailable_at=None,
                deleted_at=None,
            ),
        )
        resource = await self.repository.lock_resource_by_provider_key(
            session,
            connection_id=request.locator.connection_id,
            resource_type=ExternalChannelResourceType.THREAD,
            provider_resource_key=request.locator.provider_resource_key,
        )
        if (
            resource is None
            or resource.status is not ExternalChannelResourceStatus.ACTIVE
        ):
            return None
        return resource

    async def _submit(
        self,
        owner_id: str,
        *,
        drain_created_at: datetime.datetime,
        now: datetime.datetime,
    ) -> None:
        """Best-effort submit one coalesced owner execution key."""
        try:
            await self.job_runtime.submit(
                build_external_channel_ingress_job_request(
                    owner_id=owner_id,
                    drain_created_at=drain_created_at,
                    now=now,
                )
            )
        except JobRuntimeClosedError:
            logger.warning(
                "External Channel ingress Runtime submission is unavailable",
                extra={"external_channel_ingress_owner_id": owner_id},
            )

    async def _lock_authority(
        self,
        session: AsyncSession,
        *,
        request: ExternalChannelIngestionRequest,
        now: datetime.datetime,
    ) -> ExternalChannelConnection | None:
        connection = await self.repository.lock_connection_for_routing(
            session,
            connection_id=request.locator.connection_id,
        )
        if (
            connection is None
            or connection.provider is not request.locator.provider
            or connection.provider_tenant_id != request.locator.provider_tenant_id
            or connection.ingress_profile is not request.authority.ingress_profile
            or connection.configuration_generation
            != request.authority.configuration_generation
        ):
            return None
        return (
            connection
            if await _authority_current(
                repository=self.repository,
                session=session,
                connection=connection,
                authority_kind=request.authority.kind,
                ingress_profile=request.authority.ingress_profile,
                lease_owner=request.authority.lease_owner,
                lease_generation=request.authority.lease_generation,
                now=now,
            )
            else None
        )


def _provider_parent_channel_id(request: ExternalChannelIngestionRequest) -> str:
    value = request.locator.provider_parent_channel_id
    if value:
        return value
    if request.locator.provider is ExternalChannelProvider.SLACK:
        return request.locator.provider_channel_id
    return request.scope.provider_channel_id


def _resource_labels(request: ExternalChannelIngestionRequest) -> dict[str, object]:
    locator = request.locator
    if locator.provider is ExternalChannelProvider.SLACK:
        return {
            "provider": "slack",
            "provider_event_type": locator.provider_event_type,
            "tenant_id": locator.provider_tenant_id,
            "channel_id": locator.provider_channel_id,
            "thread_ts": locator.delivery_thread_key,
        }
    delivery_thread_key = locator.delivery_thread_key
    delivery_channel_id = (
        delivery_thread_key
        if locator.provider_thread_key is not None
        or delivery_thread_key != locator.trigger_provider_message_id
        else None
    )
    return {
        "provider": "discord",
        "provider_event_type": locator.provider_event_type,
        "guild_id": locator.provider_tenant_id,
        "source_channel_id": locator.provider_channel_id,
        "parent_channel_id": locator.provider_parent_channel_id,
        "root_message_id": locator.trigger_provider_message_id,
        "thread_id": delivery_thread_key,
        "delivery_channel_id": delivery_channel_id,
    }


def _parent_resource_labels(
    request: ExternalChannelIngestionRequest,
) -> dict[str, object]:
    parent_channel_id = _provider_parent_channel_id(request)
    if request.locator.provider is ExternalChannelProvider.SLACK:
        return {
            "provider": "slack",
            "provider_event_type": request.locator.provider_event_type,
            "tenant_id": request.locator.provider_tenant_id,
            "channel_id": parent_channel_id,
            "conversation_scope": ExternalChannelResourceType.PARENT_CHANNEL.value,
        }
    return {
        "provider": "discord",
        "provider_event_type": request.locator.provider_event_type,
        "guild_id": request.locator.provider_tenant_id,
        "parent_channel_id": parent_channel_id,
        "source_channel_id": parent_channel_id,
        "conversation_scope": ExternalChannelResourceType.PARENT_CHANNEL.value,
    }
