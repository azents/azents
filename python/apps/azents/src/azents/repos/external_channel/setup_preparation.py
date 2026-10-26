"""Completed setup-claim receipt, execution ownership and recovery operations."""

import dataclasses
import datetime
from typing import Annotated

import sqlalchemy as sa
from fastapi import Depends

from azents.core.enums import (
    ExternalChannelAccessRequestStatus,
    ExternalChannelAppMode,
    ExternalChannelConversationScopeKind,
    ExternalChannelIngressAuthorityKind,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
    ExternalChannelSetupClaimStatus,
    ExternalChannelSetupPreparationStatus,
    ExternalChannelWorkProjectionStatus,
)
from azents.core.external_channel_conversation_data import (
    ExternalChannelConversationScope,
    ExternalChannelOperationDeadline,
)
from azents.core.external_channel_ingestion import (
    ExternalChannelIngestionOperation,
    ExternalChannelIngestionRequest,
    ExternalChannelIngressAuthority,
    ExternalChannelSetupPreparationBoundary,
    ExternalChannelTriggerLocator,
)
from azents.core.external_channel_participation_state import (
    ExternalChannelSetupSourceProjection,
    projection_with_setup_source,
    setup_source_from_projection,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.models.external_channel import (
    RDBExternalChannelAccessRequest,
    RDBExternalChannelSetupClaim,
)
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.external_channel.data import (
    ExternalChannelConversationPositionCreate,
    ExternalChannelPrincipalCreate,
    ExternalChannelResourceCreate,
    ExternalChannelSetupClaimCreate,
)
from azents.repos.external_channel.ingress_drain import _authority_current
from azents.repos.external_channel.repository import ExternalChannelRepository

_PENDING = (
    ExternalChannelSetupClaimStatus.PENDING_AGENT,
    ExternalChannelSetupClaimStatus.PENDING_LOCATION,
)
_PREPARATION_AGE = datetime.timedelta(minutes=15)
_PREPARATION_LEASE = datetime.timedelta(minutes=3)
_MAX_ATTEMPTS = 5


@dataclasses.dataclass(frozen=True)
class SetupPreparationAttempt:
    """A detached claim-owned request or an observable terminal outcome."""

    request: ExternalChannelIngestionRequest | None
    failure_code: str | None


def preparation_owned(
    claim: RDBExternalChannelSetupClaim,
    boundary: ExternalChannelSetupPreparationBoundary,
    *,
    now: datetime.datetime,
) -> bool:
    """Require current source, selection, execution ownership and expiry."""
    return (
        claim.status in _PENDING
        and claim.claim_generation == boundary.claim_generation
        and claim.source_revision == boundary.source_revision
        and claim.preparation_lease_owner == boundary.preparation_owner
        and claim.preparation_lease_until is not None
        and claim.preparation_lease_until > now
        and claim.expires_at > now
    )


async def setup_preparation_current(
    session: WriteSession,
    *,
    boundary: ExternalChannelSetupPreparationBoundary,
    configuration_generation: int,
    now: datetime.datetime,
) -> bool:
    """Validate claim-owned preparation inside the caller's connection lock."""
    row = await session.write_session.scalar(
        sa.select(RDBExternalChannelSetupClaim)
        .where(RDBExternalChannelSetupClaim.id == boundary.claim_id)
        .with_for_update()
    )
    return (
        row is not None
        and preparation_owned(row, boundary, now=now)
        and row.preparation_status is ExternalChannelSetupPreparationStatus.RUNNING
        and row.preparation_configuration_generation == configuration_generation
        and row.connection_id == boundary.connection_id
        and row.source_resource_id == boundary.source_resource_id
        and row.principal_id == boundary.principal_id
        and row.conversation_position_id == boundary.conversation_position_id
    )


async def mark_setup_preparation_dispatch(
    session: WriteSession,
    *,
    boundary: ExternalChannelSetupPreparationBoundary,
    now: datetime.datetime,
) -> None:
    """Commit control reservation and dispatch intent atomically in one scope."""
    row = await session.write_session.get(
        RDBExternalChannelSetupClaim, boundary.claim_id
    )
    if row is None or not preparation_owned(row, boundary, now=now):
        raise ValueError("Setup preparation changed before control preparation.")
    row.preparation_status = ExternalChannelSetupPreparationStatus.DISPATCHING


def _clear_preparation(claim: RDBExternalChannelSetupClaim) -> None:
    claim.preparation_status = None
    claim.preparation_lease_owner = None
    claim.preparation_lease_until = None
    claim.preparation_next_attempt_at = None


@dataclasses.dataclass
class ExternalChannelSetupPreparationRepository:
    """Use the existing channel claim as the only durable preparation owner."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    repository: Annotated[
        ExternalChannelRepository, Depends(ExternalChannelRepository.create)
    ]

    async def admit(
        self,
        *,
        request: ExternalChannelIngestionRequest,
        now: datetime.datetime,
    ) -> str | None:
        """Commit eligible unconfigured setup without provider or broker I/O."""
        locator = request.locator
        if (
            locator.provider is not ExternalChannelProvider.DISCORD
            or request.scope.kind
            is not ExternalChannelConversationScopeKind.PARENT_CHANNEL
            or not locator.invocation
            or locator.provider_user_id is None
        ):
            return None
        parent = locator.provider_parent_channel_id or locator.provider_channel_id
        async with self.session_manager() as session:
            connection = await self.repository.lock_connection_for_routing(
                session, connection_id=locator.connection_id
            )
            if (
                connection is None
                or connection.provider is not locator.provider
                or connection.provider_tenant_id != locator.provider_tenant_id
                or connection.ingress_profile is not request.authority.ingress_profile
                or connection.configuration_generation
                != request.authority.configuration_generation
                or not await _authority_current(
                    repository=self.repository,
                    session=session,
                    connection=connection,
                    authority_kind=request.authority.kind,
                    ingress_profile=request.authority.ingress_profile,
                    lease_owner=request.authority.lease_owner,
                    lease_generation=request.authority.lease_generation,
                    now=now,
                )
            ):
                return None
            route = (
                await self.repository.lock_routable_single_route(
                    session, connection_id=connection.id
                )
                if connection.app_mode is ExternalChannelAppMode.SINGLE
                else await self.repository.lock_routable_channel_default(
                    session, connection_id=connection.id, provider_channel_id=parent
                )
            )
            setting = await self.repository.lock_active_participation_setting(
                session, connection_id=connection.id, provider_parent_channel_id=parent
            )
            if setting is not None:
                return None
            source_resource = await self.repository.create_resource_idempotent(
                session,
                ExternalChannelResourceCreate(
                    connection_id=connection.id,
                    resource_type=ExternalChannelResourceType.THREAD,
                    provider_resource_key=locator.provider_resource_key,
                    labels={
                        "provider": "discord",
                        "guild_id": locator.provider_tenant_id,
                        "parent_channel_id": parent,
                        "source_channel_id": parent,
                        "root_message_id": locator.trigger_provider_message_id,
                        "thread_id": locator.trigger_provider_message_id,
                        "delivery_channel_id": None,
                        "provider_event_type": locator.provider_event_type,
                    },
                    status=ExternalChannelResourceStatus.ACTIVE,
                    latest_activity_at=now,
                    unavailable_at=None,
                    deleted_at=None,
                ),
            )
            principal = await self.repository.create_principal_idempotent(
                session,
                ExternalChannelPrincipalCreate(
                    provider=locator.provider,
                    provider_tenant_id=locator.provider_tenant_id,
                    provider_user_id=locator.provider_user_id,
                    author_type=ExternalChannelPrincipalAuthorType.HUMAN,
                    display_name=None,
                    avatar_url=None,
                    profile=None,
                ),
            )
            if (
                route is not None
                and await self.repository.get_active_block(
                    session,
                    agent_id=route.require_active_agent_id(),
                    principal_id=principal.id,
                )
                is not None
            ):
                await session.write_session.rollback()
                return None
            position = await self.repository.create_conversation_position_idempotent(
                session,
                ExternalChannelConversationPositionCreate(
                    connection_id=connection.id,
                    scope_kind=request.scope.kind,
                    provider_channel_id=request.scope.provider_channel_id,
                    provider_thread_key=request.scope.provider_thread_key,
                    read_through_position=None,
                ),
            )
            source = ExternalChannelSetupSourceProjection(
                schema_version=1,
                provider=locator.provider,
                provider_event_type=locator.provider_event_type,
                provider_tenant_id=locator.provider_tenant_id,
                provider_channel_id=locator.provider_channel_id,
                provider_parent_channel_id=parent,
                scope_kind=request.scope.kind,
                provider_thread_key=locator.provider_thread_key,
                delivery_thread_key=locator.delivery_thread_key,
                provider_resource_key=locator.provider_resource_key,
                trigger_provider_message_key=locator.trigger_provider_message_key,
                trigger_provider_message_id=locator.trigger_provider_message_id,
                trigger_position=locator.trigger_position,
                range_start_position=position.read_through_position,
            )
            claim = await self.repository.lock_nonterminal_setup_claim(
                session, connection_id=connection.id, provider_parent_channel_id=parent
            )
            if claim is not None and claim.expires_at <= now:
                await self.repository.terminate_setup_claim(
                    session,
                    claim_id=claim.id,
                    expected_claim_generation=claim.claim_generation,
                    status=ExternalChannelSetupClaimStatus.EXPIRED,
                )
                claim = None
            if claim is not None:
                if claim.status is ExternalChannelSetupClaimStatus.SELECTED:
                    return None
                previous = setup_source_from_projection(claim.source_projection)
                if previous.trigger_position >= source.trigger_position:
                    await session.write_session.commit()
                    return claim.id
                claim = await self.repository.replace_setup_claim_source(
                    session,
                    claim_id=claim.id,
                    expected_claim_generation=claim.claim_generation,
                    expected_source_revision=claim.source_revision,
                    conversation_position_id=position.id,
                    source_resource_id=source_resource.id,
                    principal_id=principal.id,
                    source_projection=projection_with_setup_source(source),
                    expires_at=now + _PREPARATION_AGE,
                )
            else:
                claim = await self.repository.create_setup_claim(
                    session,
                    ExternalChannelSetupClaimCreate(
                        connection_id=connection.id,
                        provider_parent_channel_id=parent,
                        route_id=None if route is None else route.id,
                        conversation_position_id=position.id,
                        source_resource_id=source_resource.id,
                        principal_id=principal.id,
                        source_projection=projection_with_setup_source(source),
                        source_revision=1,
                        claim_generation=1,
                        status=ExternalChannelSetupClaimStatus.PENDING_AGENT
                        if route is None
                        else ExternalChannelSetupClaimStatus.PENDING_LOCATION,
                        selected_setting_id=None,
                        selected_resource_id=None,
                        selected_source_revision=None,
                        expires_at=now + _PREPARATION_AGE,
                        selected_at=None,
                        completed_at=None,
                    ),
                )
            if claim is None:
                return None
            row = await session.write_session.get(
                RDBExternalChannelSetupClaim, claim.id
            )
            assert row is not None
            row.preparation_status = ExternalChannelSetupPreparationStatus.PENDING
            row.preparation_configuration_generation = (
                connection.configuration_generation
            )
            row.preparation_attempt_count = 0
            row.preparation_next_attempt_at = now
            row.preparation_lease_owner = None
            row.preparation_lease_until = None
            await session.write_session.commit()
            return claim.id

    async def claim(
        self,
        *,
        claim_id: str,
        owner: str,
        now: datetime.datetime,
        deadline: ExternalChannelOperationDeadline,
    ) -> SetupPreparationAttempt:
        """Acquire one due source; expired dispatch is uncertain, never blind replay."""
        async with self.session_manager() as session:
            connection_id = await session.read_session.scalar(
                sa.select(RDBExternalChannelSetupClaim.connection_id).where(
                    RDBExternalChannelSetupClaim.id == claim_id
                )
            )
            if connection_id is None:
                return SetupPreparationAttempt(None, None)
            connection = await self.repository.lock_connection_for_routing(
                session, connection_id=connection_id
            )
            row = await session.write_session.scalar(
                sa.select(RDBExternalChannelSetupClaim)
                .where(RDBExternalChannelSetupClaim.id == claim_id)
                .with_for_update()
            )
            if row is None or row.preparation_status is None:
                return SetupPreparationAttempt(None, None)
            if (
                row.preparation_lease_until is not None
                and row.preparation_lease_until > now
            ):
                return SetupPreparationAttempt(None, None)
            failure = None
            if (
                row.preparation_status
                is ExternalChannelSetupPreparationStatus.DISPATCHING
            ):
                failure = "setup_dispatch_uncertain"
            elif (
                connection is None
                or connection.configuration_generation
                != row.preparation_configuration_generation
                or row.status not in _PENDING
            ):
                failure = "setup_authority_changed"
            elif (
                row.expires_at <= now or row.preparation_attempt_count >= _MAX_ATTEMPTS
            ):
                failure = "setup_retry_exhausted"
            if failure is not None:
                _clear_preparation(row)
                await session.write_session.commit()
                return SetupPreparationAttempt(None, failure)
            if (
                row.preparation_next_attempt_at is not None
                and row.preparation_next_attempt_at > now
            ):
                return SetupPreparationAttempt(None, None)
            assert connection is not None
            row.preparation_status = ExternalChannelSetupPreparationStatus.RUNNING
            row.preparation_lease_owner = owner
            row.preparation_lease_until = now + _PREPARATION_LEASE
            row.preparation_attempt_count += 1
            source = setup_source_from_projection(row.source_projection)
            await session.write_session.execute(
                sa.update(RDBExternalChannelAccessRequest)
                .where(
                    RDBExternalChannelAccessRequest.setup_claim_id == row.id,
                    RDBExternalChannelAccessRequest.connection_id == row.connection_id,
                    RDBExternalChannelAccessRequest.trigger_provider_message_key
                    == source.trigger_provider_message_key,
                    RDBExternalChannelAccessRequest.status
                    == ExternalChannelAccessRequestStatus.PENDING,
                    RDBExternalChannelAccessRequest.control_provider_message_key.is_(
                        None
                    ),
                    RDBExternalChannelAccessRequest.control_projection_status
                    == ExternalChannelWorkProjectionStatus.FAILED,
                )
                .values(control_projection_status=None)
            )
            principal = await self.repository.get_principal(
                session, principal_id=row.principal_id
            )
            if principal is None:
                _clear_preparation(row)
                await session.write_session.commit()
                return SetupPreparationAttempt(None, "setup_principal_missing")
            boundary = ExternalChannelSetupPreparationBoundary(
                connection_id=connection.id,
                source_resource_id=row.source_resource_id,
                target_resource_id=row.source_resource_id,
                principal_id=row.principal_id,
                trigger_provider_message_key=source.trigger_provider_message_key,
                conversation_position_id=row.conversation_position_id,
                range_start_position=source.range_start_position,
                trigger_position=source.trigger_position,
                claim_id=row.id,
                claim_generation=row.claim_generation,
                source_revision=row.source_revision,
                preparation_owner=owner,
            )
            request = ExternalChannelIngestionRequest(
                locator=ExternalChannelTriggerLocator(
                    connection_id=connection.id,
                    provider=source.provider,
                    provider_event_type=source.provider_event_type,
                    provider_tenant_id=source.provider_tenant_id,
                    provider_channel_id=source.provider_channel_id,
                    provider_parent_channel_id=source.provider_parent_channel_id,
                    provider_thread_key=source.provider_thread_key,
                    delivery_thread_key=source.delivery_thread_key,
                    provider_resource_key=source.provider_resource_key,
                    trigger_provider_message_key=source.trigger_provider_message_key,
                    trigger_provider_message_id=source.trigger_provider_message_id,
                    trigger_position=source.trigger_position,
                    provider_user_id=principal.provider_user_id,
                    invocation=True,
                    expected_file_count=None,
                ),
                scope=ExternalChannelConversationScope(
                    connection_id=connection.id,
                    kind=source.scope_kind,
                    provider_channel_id=source.provider_channel_id,
                    provider_thread_key=source.provider_thread_key,
                ),
                authority=ExternalChannelIngressAuthority(
                    kind=ExternalChannelIngressAuthorityKind.DURABLE_REPLAY,
                    ingress_profile=connection.ingress_profile,
                    configuration_generation=connection.configuration_generation,
                    lease_owner=None,
                    lease_generation=None,
                ),
                deadline=deadline,
                operation=ExternalChannelIngestionOperation.SETUP_PREPARATION,
                selected_route_id=None,
                replay_boundary=boundary,
                initial_title_eligible=False,
            )
            await session.write_session.commit()
            return SetupPreparationAttempt(request, None)

    async def transition(
        self,
        *,
        boundary: ExternalChannelSetupPreparationBoundary,
        dispatch: bool,
        retry: bool,
        now: datetime.datetime,
    ) -> bool:
        """Fence dispatch/completion/retry against the exact prepared source."""
        async with self.session_manager() as session:
            connection = await self.repository.lock_connection_for_routing(
                session, connection_id=boundary.connection_id
            )
            row = await session.write_session.scalar(
                sa.select(RDBExternalChannelSetupClaim)
                .where(RDBExternalChannelSetupClaim.id == boundary.claim_id)
                .with_for_update()
            )
            if row is None or not preparation_owned(row, boundary, now=now):
                return False
            if (
                connection is None
                or connection.configuration_generation
                != row.preparation_configuration_generation
            ):
                _clear_preparation(row)
                await session.write_session.commit()
                return False
            if dispatch:
                row.preparation_status = (
                    ExternalChannelSetupPreparationStatus.DISPATCHING
                )
            elif retry:
                row.preparation_status = ExternalChannelSetupPreparationStatus.PENDING
                row.preparation_next_attempt_at = now + datetime.timedelta(
                    seconds=min(60, 2**row.preparation_attempt_count)
                )
                row.preparation_lease_owner = None
                row.preparation_lease_until = None
            else:
                _clear_preparation(row)
            await session.write_session.commit()
            return True

    async def recoverable_ids(self, *, now: datetime.datetime, limit: int) -> list[str]:
        """Observe due or expired-owned preparation; execution claims separately."""
        async with self.session_manager() as session:
            ids = await session.read_session.scalars(
                sa.select(RDBExternalChannelSetupClaim.id)
                .where(
                    RDBExternalChannelSetupClaim.preparation_status.is_not(None),
                    sa.or_(
                        RDBExternalChannelSetupClaim.preparation_lease_until.is_(None),
                        RDBExternalChannelSetupClaim.preparation_lease_until <= now,
                    ),
                    sa.or_(
                        RDBExternalChannelSetupClaim.preparation_next_attempt_at.is_(
                            None
                        ),
                        RDBExternalChannelSetupClaim.preparation_next_attempt_at <= now,
                    ),
                )
                .order_by(RDBExternalChannelSetupClaim.created_at)
                .limit(limit)
            )
            return list(ids)
