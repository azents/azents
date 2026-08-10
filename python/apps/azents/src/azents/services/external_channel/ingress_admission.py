"""DB-only admission for Session-bound External Channel triggers."""

import dataclasses
import datetime
import logging
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentSessionStatus,
    ExternalChannelPrincipalAuthorType,
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
    ExternalChannelConnection,
    ExternalChannelConversationPositionCreate,
    ExternalChannelPrincipalCreate,
)
from azents.repos.external_channel.ingress_queue import (
    ExternalChannelIngressQueueRepository,
)
from azents.repos.external_channel.ingress_queue_data import (
    ExternalChannelIngressItemCreate,
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


@dataclasses.dataclass
class ExternalChannelIngressAdmissionService:
    """Persist eligible Session-bound triggers before provider I/O."""

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
        """Queue an established active conversation or defer to legacy replay flow."""
        now = datetime.datetime.now(datetime.UTC)
        async with self.session_manager() as session:
            connection = await self._lock_authority(
                session,
                request=request,
                now=now,
            )
            if connection is None:
                return None
            resource = await self.repository.lock_resource_by_provider_key(
                session,
                connection_id=connection.id,
                resource_type=ExternalChannelResourceType.THREAD,
                provider_resource_key=request.locator.provider_resource_key,
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
            if binding is None:
                return None
            if (
                not request.locator.invocation
                and binding.response_mode is ExternalChannelResponseMode.MENTION_ONLY
            ):
                await session.commit()
                return _outcome(
                    ExternalChannelIngestionOutcomeKind.IGNORED,
                    ExternalChannelIngestionReason.RESPONSE_MODE_NOT_TRIGGERED,
                )
            route = await self.repository.get_routable_route_by_id(
                session,
                route_id=binding.route_id,
            )
            if route is None or route.agent_id is None:
                return None
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
            if (
                await self.repository.get_active_block(
                    session,
                    agent_id=route.agent_id,
                    principal_id=principal.id,
                )
                is not None
            ):
                await session.commit()
                return _outcome(
                    ExternalChannelIngestionOutcomeKind.IGNORED,
                    ExternalChannelIngestionReason.AUTHOR_NOT_ELIGIBLE,
                )
            grant = await self.repository.get_active_access_grant(
                session,
                agent_id=route.agent_id,
                principal_id=principal.id,
                agent_session_id=binding.agent_session_id,
            )
            if grant is None and not route.open_access_enabled:
                return None
            target_session = await self.agent_session_repository.lock_by_id(
                session,
                binding.agent_session_id,
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
            admission = await self.queue_repository.admit(
                session,
                create=ExternalChannelIngressItemCreate(
                    session_id=binding.agent_session_id,
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
                    resource_id=resource.id,
                    binding_id=binding.id,
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
                    invocation=True,
                    invocation_id=invocation_id,
                    initial_title_eligible=request.initial_title_eligible,
                ),
            )
            await session.commit()
        await self._submit(
            binding.agent_session_id,
            drain_created_at=admission.session.created_at,
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

    async def _submit(
        self,
        session_id: str,
        *,
        drain_created_at: datetime.datetime,
        now: datetime.datetime,
    ) -> None:
        """Best-effort submit one coalesced Session execution key."""
        try:
            await self.job_runtime.submit(
                build_external_channel_ingress_job_request(
                    session_id=session_id,
                    drain_created_at=drain_created_at,
                    now=now,
                )
            )
        except JobRuntimeClosedError:
            logger.warning(
                "External Channel ingress Runtime submission is unavailable",
                extra={"external_channel_session_id": session_id},
            )

    async def _lock_authority(
        self,
        session: AsyncSession,
        *,
        request: ExternalChannelIngestionRequest,
        now: datetime.datetime,
    ) -> ExternalChannelConnection | None:
        """Lock and validate callback authority without provider content."""
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
