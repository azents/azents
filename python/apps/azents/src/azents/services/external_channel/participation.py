"""Provider-neutral External Channel participation setup mutations."""

import datetime
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentLifecycleStatus,
    ExternalChannelAppMode,
    ExternalChannelConnectionStatus,
    ExternalChannelConversationLocation,
    ExternalChannelConversationScopeKind,
    ExternalChannelParticipationSettingStatus,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
    ExternalChannelResponseMode,
    ExternalChannelSetupClaimStatus,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.external_channel.data import (
    ExternalChannelAgentRoute,
    ExternalChannelBinding,
    ExternalChannelParticipationSetting,
    ExternalChannelParticipationSettingCreate,
    ExternalChannelResource,
    ExternalChannelResourceCreate,
    ExternalChannelSetupClaim,
)
from azents.repos.external_channel.management import (
    ExternalChannelManagementRepository,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.conversation import (
    ExternalChannelConversationLock,
    ExternalChannelConversationScope,
    ExternalChannelOperationDeadline,
    ExternalChannelParticipationLock,
    ExternalChannelParticipationScope,
)
from azents.services.external_channel.deps import (
    get_external_channel_conversation_lock,
    get_external_channel_participation_lock,
)
from azents.services.external_channel.ingestion import (
    ExternalChannelIngestionOutcome,
    ExternalChannelIngestionOutcomeKind,
)
from azents.services.external_channel.ingestion_replay import (
    ExternalChannelIngestionReplayService,
)
from azents.services.external_channel.participation_state import (
    ExternalChannelSetupSourceProjection,
    setup_source_from_projection,
)
from azents.services.external_channel.provider_effect import ProviderEffectPlan


class ExternalChannelParticipationError(ValueError):
    """A participation mutation is stale, unauthorized, or unavailable."""


@dataclass(frozen=True)
class ExternalChannelLocationSelection:
    """Committed location selection and its independent replay result."""

    status: Literal["selected", "already_selected", "pending_recovery"]
    setting: ExternalChannelParticipationSetting
    claim: ExternalChannelSetupClaim
    replay_outcome: ExternalChannelIngestionOutcome | None


@dataclass(frozen=True)
class ExternalChannelParticipationSettings:
    """Authorized canonical setup, parent, or connected-thread settings."""

    target: Literal["setup", "parent", "thread"]
    agent_name: str
    setting: ExternalChannelParticipationSetting | None
    claim: ExternalChannelSetupClaim | None
    resource: ExternalChannelResource | None
    binding: ExternalChannelBinding | None


@dataclass(frozen=True)
class ExternalChannelParticipationSettingsMutation:
    """Committed settings state and independent provider cleanup intents."""

    settings: ExternalChannelParticipationSettings
    cleanup_plans: tuple[ProviderEffectPlan, ...]


@dataclass(frozen=True)
class _CommittedLocation:
    """Setting and claim committed before independent replay begins."""

    setting: ExternalChannelParticipationSetting
    claim: ExternalChannelSetupClaim
    created: bool


@dataclass
class ExternalChannelParticipationService:
    """Authorize and commit provider-neutral participation settings."""

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    repository: Annotated[
        ExternalChannelRepository,
        Depends(ExternalChannelRepository.create),
    ]
    management_repository: Annotated[
        ExternalChannelManagementRepository,
        Depends(ExternalChannelManagementRepository.create),
    ]
    agent_repository: Annotated[
        AgentRepository,
        Depends(AgentRepository),
    ]
    ingestion_replay_service: Annotated[
        ExternalChannelIngestionReplayService,
        Depends(ExternalChannelIngestionReplayService),
    ]
    conversation_lock: Annotated[
        ExternalChannelConversationLock,
        Depends(get_external_channel_conversation_lock),
    ]
    participation_lock: Annotated[
        ExternalChannelParticipationLock,
        Depends(get_external_channel_participation_lock),
    ]

    async def resolve_settings(
        self,
        *,
        connection_id: str,
        provider_parent_channel_id: str,
        provider_thread_resource_key: str | None,
        principal_id: str,
    ) -> ExternalChannelParticipationSettings:
        """Resolve one authorized settings surface without mutating provider state."""
        async with self.session_manager() as session:
            connection = await self.repository.get_connection_configuration(
                session,
                connection_id=connection_id,
            )
            if connection is None or connection.status not in {
                ExternalChannelConnectionStatus.ACTIVE,
                ExternalChannelConnectionStatus.DEGRADED,
            }:
                raise ExternalChannelParticipationError(
                    "External Channel settings are unavailable."
                )
            if provider_thread_resource_key is not None:
                resource = await self.repository.get_resource_by_provider_key(
                    session,
                    connection_id=connection.id,
                    resource_type=ExternalChannelResourceType.THREAD,
                    provider_resource_key=provider_thread_resource_key,
                )
                binding = (
                    None
                    if resource is None
                    else await self.repository.get_connected_binding_by_resource(
                        session,
                        resource_id=resource.id,
                    )
                )
                if resource is not None and binding is not None:
                    route, agent_name = await self._authorize_settings_actor(
                        session,
                        connection_id=connection.id,
                        route_id=binding.route_id,
                        principal_id=principal_id,
                        agent_session_id=binding.agent_session_id,
                    )
                    del route
                    return ExternalChannelParticipationSettings(
                        target="thread",
                        agent_name=agent_name,
                        setting=None,
                        claim=None,
                        resource=resource,
                        binding=binding,
                    )
                raise ExternalChannelParticipationError(
                    "External Channel thread settings are unavailable."
                )
            setting = await self.repository.get_active_participation_setting(
                session,
                connection_id=connection.id,
                provider_parent_channel_id=provider_parent_channel_id,
            )
            if setting is not None:
                _, agent_name = await self._authorize_settings_actor(
                    session,
                    connection_id=connection.id,
                    route_id=setting.route_id,
                    principal_id=principal_id,
                    agent_session_id=None,
                )
                resource = await self.repository.get_resource_by_provider_key(
                    session,
                    connection_id=connection.id,
                    resource_type=ExternalChannelResourceType.PARENT_CHANNEL,
                    provider_resource_key=provider_parent_channel_id,
                )
                binding = (
                    None
                    if resource is None
                    else await self.repository.get_connected_binding_by_resource(
                        session,
                        resource_id=resource.id,
                    )
                )
                return ExternalChannelParticipationSettings(
                    target="parent",
                    agent_name=agent_name,
                    setting=setting,
                    claim=None,
                    resource=resource,
                    binding=binding,
                )
            claim = await self.repository.get_nonterminal_setup_claim(
                session,
                connection_id=connection.id,
                provider_parent_channel_id=provider_parent_channel_id,
            )
            if (
                claim is None
                or claim.route_id is None
                or claim.status is not ExternalChannelSetupClaimStatus.PENDING_LOCATION
            ):
                raise ExternalChannelParticipationError(
                    "Mention the App in this channel to begin conversation setup."
                )
            _, agent_name = await self._authorize_settings_actor(
                session,
                connection_id=connection.id,
                route_id=claim.route_id,
                principal_id=principal_id,
                agent_session_id=None,
            )
            return ExternalChannelParticipationSettings(
                target="setup",
                agent_name=agent_name,
                setting=None,
                claim=claim,
                resource=None,
                binding=None,
            )

    async def mutate_parent_settings(
        self,
        *,
        connection_id: str,
        provider_parent_channel_id: str,
        principal_id: str,
        expected_setting_id: str,
        expected_settings_generation: int,
        location: ExternalChannelConversationLocation,
        response_mode: ExternalChannelResponseMode,
        now: datetime.datetime,
        deadline: ExternalChannelOperationDeadline,
    ) -> ExternalChannelParticipationSettingsMutation:
        """Atomically mutate a parent setting and its concrete Channel binding."""
        conversation_scope = ExternalChannelConversationScope(
            connection_id=connection_id,
            kind=ExternalChannelConversationScopeKind.PARENT_CHANNEL,
            provider_channel_id=provider_parent_channel_id,
            provider_thread_key=None,
        )
        participation_scope = ExternalChannelParticipationScope(
            connection_id=connection_id,
            provider_parent_channel_id=provider_parent_channel_id,
        )
        cleanup_plans: tuple[ProviderEffectPlan, ...] = ()
        async with self.conversation_lock.acquire(
            scope=conversation_scope,
            deadline=deadline,
        ) as conversation_lease:
            await conversation_lease.assert_owned()
            async with self.participation_lock.acquire(
                scope=participation_scope,
                deadline=deadline,
            ) as participation_lease:
                await participation_lease.assert_owned()
                await conversation_lease.assert_owned()
                async with self.session_manager() as session:
                    connection = await self.repository.lock_connection_for_routing(
                        session,
                        connection_id=connection_id,
                    )
                    setting = await self.repository.lock_active_participation_setting(
                        session,
                        connection_id=connection_id,
                        provider_parent_channel_id=provider_parent_channel_id,
                    )
                    if (
                        connection is None
                        or setting is None
                        or setting.id != expected_setting_id
                        or setting.settings_generation != expected_settings_generation
                    ):
                        raise ExternalChannelParticipationError(
                            "External Channel settings changed before submission."
                        )
                    _, agent_name = await self._authorize_settings_actor(
                        session,
                        connection_id=connection.id,
                        route_id=setting.route_id,
                        principal_id=principal_id,
                        agent_session_id=None,
                    )
                    resource = await self.repository.lock_resource_by_provider_key(
                        session,
                        connection_id=connection.id,
                        resource_type=ExternalChannelResourceType.PARENT_CHANNEL,
                        provider_resource_key=provider_parent_channel_id,
                    )
                    binding = (
                        None
                        if resource is None
                        else await self.repository.lock_connected_binding_by_resource(
                            session,
                            resource_id=resource.id,
                        )
                    )
                    if (
                        setting.location is ExternalChannelConversationLocation.CHANNEL
                        and location is ExternalChannelConversationLocation.THREADS
                        and resource is not None
                        and binding is not None
                    ):
                        disconnected = await (
                            self.management_repository
                        ).disconnect_parent_binding_for_participation(
                            session,
                            connection_id=connection.id,
                            route_id=setting.route_id,
                            resource_id=resource.id,
                            binding_id=binding.id,
                            now=now,
                        )
                        if disconnected is None:
                            raise ExternalChannelParticipationError(
                                "External Channel parent conversation changed."
                            )
                        cleanup_plans = disconnected
                        binding = None
                    updated = await self.repository.update_participation_setting(
                        session,
                        setting_id=setting.id,
                        expected_settings_generation=setting.settings_generation,
                        location=location,
                        response_mode=response_mode,
                        configured_by_principal_id=principal_id,
                    )
                    if updated is None:
                        raise ExternalChannelParticipationError(
                            "External Channel settings changed before submission."
                        )
                    if (
                        location is ExternalChannelConversationLocation.CHANNEL
                        and binding is not None
                        and binding.response_mode is not response_mode
                    ):
                        binding = await (
                            self.repository.update_connected_binding_response_mode(
                                session,
                                binding_id=binding.id,
                                expected_response_mode=binding.response_mode,
                                expected_updated_at=binding.updated_at,
                                response_mode=response_mode,
                            )
                        )
                        if binding is None:
                            raise ExternalChannelParticipationError(
                                "External Channel parent conversation changed."
                            )
                    await session.commit()
        return ExternalChannelParticipationSettingsMutation(
            settings=ExternalChannelParticipationSettings(
                target="parent",
                agent_name=agent_name,
                setting=updated,
                claim=None,
                resource=resource,
                binding=binding,
            ),
            cleanup_plans=cleanup_plans,
        )

    async def mutate_thread_settings(
        self,
        *,
        connection_id: str,
        provider_parent_channel_id: str,
        resource_id: str,
        binding_id: str,
        principal_id: str,
        expected_response_mode: ExternalChannelResponseMode,
        expected_binding_updated_at: datetime.datetime,
        response_mode: ExternalChannelResponseMode,
        now: datetime.datetime,
        deadline: ExternalChannelOperationDeadline,
    ) -> ExternalChannelParticipationSettingsMutation:
        """Mutate only one exact connected thread binding."""
        del now
        async with self.session_manager() as session:
            resource_snapshot = await self.repository.get_resource(
                session,
                resource_id=resource_id,
            )
        if (
            resource_snapshot is None
            or resource_snapshot.connection_id != connection_id
            or resource_snapshot.resource_type is not ExternalChannelResourceType.THREAD
        ):
            raise ExternalChannelParticipationError(
                "External Channel thread settings are unavailable."
            )
        labels = resource_snapshot.labels or {}
        provider_thread_key = labels.get("thread_ts")
        if not isinstance(provider_thread_key, str) or not provider_thread_key:
            raise ExternalChannelParticipationError(
                "External Channel thread settings are unavailable."
            )
        conversation_scope = ExternalChannelConversationScope(
            connection_id=connection_id,
            kind=ExternalChannelConversationScopeKind.THREAD,
            provider_channel_id=provider_parent_channel_id,
            provider_thread_key=provider_thread_key,
        )
        async with self.conversation_lock.acquire(
            scope=conversation_scope,
            deadline=deadline,
        ) as conversation_lease:
            await conversation_lease.assert_owned()
            async with self.session_manager() as session:
                connection = await self.repository.lock_connection_for_routing(
                    session,
                    connection_id=connection_id,
                )
                resource = await self.repository.lock_resource(
                    session,
                    resource_id=resource_id,
                )
                binding = await self.repository.lock_binding(
                    session,
                    binding_id=binding_id,
                )
                if (
                    connection is None
                    or resource is None
                    or resource.connection_id != connection.id
                    or resource.resource_type is not ExternalChannelResourceType.THREAD
                    or binding is None
                    or binding.resource_id != resource.id
                    or binding.disconnected_at is not None
                    or binding.response_mode is not expected_response_mode
                    or binding.updated_at != expected_binding_updated_at
                ):
                    raise ExternalChannelParticipationError(
                        "External Channel thread settings changed before submission."
                    )
                _, agent_name = await self._authorize_settings_actor(
                    session,
                    connection_id=connection.id,
                    route_id=binding.route_id,
                    principal_id=principal_id,
                    agent_session_id=binding.agent_session_id,
                )
                updated_binding = (
                    await self.repository.update_connected_binding_response_mode(
                        session,
                        binding_id=binding.id,
                        expected_response_mode=binding.response_mode,
                        expected_updated_at=binding.updated_at,
                        response_mode=response_mode,
                    )
                )
                if updated_binding is None:
                    raise ExternalChannelParticipationError(
                        "External Channel thread settings changed before submission."
                    )
                await session.commit()
        return ExternalChannelParticipationSettingsMutation(
            settings=ExternalChannelParticipationSettings(
                target="thread",
                agent_name=agent_name,
                setting=None,
                claim=None,
                resource=resource,
                binding=updated_binding,
            ),
            cleanup_plans=(),
        )

    async def _authorize_settings_actor(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        route_id: str,
        principal_id: str,
        agent_session_id: str | None,
    ) -> tuple[ExternalChannelAgentRoute, str]:
        """Revalidate one human provider actor against the selected route."""
        connection = await self.repository.get_connection_configuration(
            session,
            connection_id=connection_id,
        )
        route = await self.repository.get_routable_route_by_id(
            session,
            route_id=route_id,
        )
        principal = await self.repository.get_principal(
            session,
            principal_id=principal_id,
        )
        if (
            connection is None
            or route is None
            or route.connection_id != connection_id
            or principal is None
            or principal.provider is not connection.provider
            or principal.provider_tenant_id != connection.provider_tenant_id
            or principal.author_type is not ExternalChannelPrincipalAuthorType.HUMAN
        ):
            raise ExternalChannelParticipationError(
                "External Channel settings actor is unavailable."
            )
        agent_id = route.require_active_agent_id()
        if (
            await self.repository.get_active_block(
                session,
                agent_id=agent_id,
                principal_id=principal.id,
            )
            is not None
        ):
            raise ExternalChannelParticipationError(
                "External Channel settings actor is blocked."
            )
        grant = await self.repository.get_active_access_grant(
            session,
            agent_id=agent_id,
            principal_id=principal.id,
            agent_session_id=agent_session_id,
        )
        if grant is None and not route.open_access_enabled:
            raise ExternalChannelParticipationError(
                "External Channel settings actor is not authorized."
            )
        agent = await self.agent_repository.get_by_id(session, agent_id)
        if agent is None or agent.lifecycle_status is not AgentLifecycleStatus.ACTIVE:
            raise ExternalChannelParticipationError(
                "External Channel settings Agent is unavailable."
            )
        return route, agent.name

    async def select_location(
        self,
        *,
        setup_claim_id: str,
        expected_claim_generation: int,
        expected_source_revision: int,
        location: ExternalChannelConversationLocation,
        configured_by_principal_id: str,
        now: datetime.datetime,
        deadline: ExternalChannelOperationDeadline,
    ) -> ExternalChannelLocationSelection:
        """Commit one first valid location selection and recover its source."""
        async with self.session_manager() as session:
            snapshot = await self.repository.get_setup_claim(
                session,
                claim_id=setup_claim_id,
            )
            if snapshot is None:
                raise ExternalChannelParticipationError(
                    "External Channel setup is unavailable."
                )
            source = setup_source_from_projection(snapshot.source_projection)
        conversation_scope = ExternalChannelConversationScope(
            connection_id=snapshot.connection_id,
            kind=source.scope_kind,
            provider_channel_id=source.provider_channel_id,
            provider_thread_key=source.provider_thread_key,
        )
        participation_scope = ExternalChannelParticipationScope(
            connection_id=snapshot.connection_id,
            provider_parent_channel_id=snapshot.provider_parent_channel_id,
        )
        async with self.conversation_lock.acquire(
            scope=conversation_scope,
            deadline=deadline,
        ) as conversation_lease:
            await conversation_lease.assert_owned()
            async with self.participation_lock.acquire(
                scope=participation_scope,
                deadline=deadline,
            ) as participation_lease:
                await participation_lease.assert_owned()
                await conversation_lease.assert_owned()
                committed = await self._commit_location(
                    setup_claim_id=setup_claim_id,
                    expected_claim_generation=expected_claim_generation,
                    expected_source_revision=expected_source_revision,
                    location=location,
                    configured_by_principal_id=configured_by_principal_id,
                    source=source,
                    now=now,
                )
        setting = committed.setting
        claim = committed.claim
        created = committed.created
        if claim.status is ExternalChannelSetupClaimStatus.COMPLETED:
            return ExternalChannelLocationSelection(
                status="already_selected",
                setting=setting,
                claim=claim,
                replay_outcome=None,
            )
        outcome = await self.ingestion_replay_service.replay_setup_claim(
            setup_claim_id=claim.id,
            deadline=deadline,
        )
        if outcome.kind in {
            ExternalChannelIngestionOutcomeKind.ACCEPTED,
            ExternalChannelIngestionOutcomeKind.DUPLICATE,
        }:
            async with self.session_manager() as session:
                completed = await self.repository.get_setup_claim(
                    session,
                    claim_id=claim.id,
                )
            if completed is not None:
                claim = completed
            return ExternalChannelLocationSelection(
                status="selected" if created else "already_selected",
                setting=setting,
                claim=claim,
                replay_outcome=outcome,
            )
        return ExternalChannelLocationSelection(
            status="pending_recovery",
            setting=setting,
            claim=claim,
            replay_outcome=outcome,
        )

    async def _commit_location(
        self,
        *,
        setup_claim_id: str,
        expected_claim_generation: int,
        expected_source_revision: int,
        location: ExternalChannelConversationLocation,
        configured_by_principal_id: str,
        source: ExternalChannelSetupSourceProjection,
        now: datetime.datetime,
    ) -> _CommittedLocation:
        """Commit the setting and frozen selected claim without provider I/O."""
        async with self.session_manager() as session:
            snapshot = await self.repository.get_setup_claim(
                session,
                claim_id=setup_claim_id,
            )
            if snapshot is None or snapshot.route_id is None:
                raise ExternalChannelParticipationError(
                    "External Channel setup has no selected Agent."
                )
            connection = await self.repository.lock_connection_for_routing(
                session,
                connection_id=snapshot.connection_id,
            )
            route = await self.repository.get_routable_route_by_id(
                session,
                route_id=snapshot.route_id,
            )
            if (
                connection is not None
                and connection.app_mode is ExternalChannelAppMode.MULTI
            ):
                current_route = await self.repository.lock_routable_channel_default(
                    session,
                    connection_id=connection.id,
                    provider_channel_id=snapshot.provider_parent_channel_id,
                )
                if current_route is None or current_route.id != snapshot.route_id:
                    raise ExternalChannelParticipationError(
                        "External Channel selected Agent is no longer current."
                    )
            existing = (
                None
                if connection is None
                else await self.repository.lock_active_participation_setting(
                    session,
                    connection_id=connection.id,
                    provider_parent_channel_id=snapshot.provider_parent_channel_id,
                )
            )
            principal = await self.repository.get_principal(
                session,
                principal_id=configured_by_principal_id,
            )
            if (
                connection is None
                or route is None
                or route.connection_id != connection.id
                or principal is None
                or principal.provider is not connection.provider
                or principal.provider_tenant_id != connection.provider_tenant_id
                or principal.author_type is not ExternalChannelPrincipalAuthorType.HUMAN
            ):
                raise ExternalChannelParticipationError(
                    "External Channel setup actor or route is unavailable."
                )
            agent_id = route.require_active_agent_id()
            if (
                await self.repository.get_active_block(
                    session,
                    agent_id=agent_id,
                    principal_id=principal.id,
                )
                is not None
            ):
                raise ExternalChannelParticipationError(
                    "External Channel setup actor is blocked."
                )
            grant = await self.repository.get_active_access_grant(
                session,
                agent_id=agent_id,
                principal_id=principal.id,
                agent_session_id=None,
            )
            if grant is None and not route.open_access_enabled:
                raise ExternalChannelParticipationError(
                    "External Channel setup actor is not authorized."
                )
            agent = await self.agent_repository.get_by_id(session, agent_id)
            if (
                agent is None
                or agent.lifecycle_status is not AgentLifecycleStatus.ACTIVE
            ):
                raise ExternalChannelParticipationError(
                    "External Channel setup Agent is unavailable."
                )
            setting = existing
            created = False
            if setting is None:
                setting = await self.repository.create_participation_setting(
                    session,
                    ExternalChannelParticipationSettingCreate(
                        connection_id=connection.id,
                        provider_parent_channel_id=(
                            snapshot.provider_parent_channel_id
                        ),
                        route_id=route.id,
                        location=location,
                        response_mode=agent.external_channel_default_response_mode,
                        settings_generation=1,
                        configured_by_user_id=None,
                        configured_by_principal_id=principal.id,
                        status=ExternalChannelParticipationSettingStatus.ACTIVE,
                        invalidated_at=None,
                        invalidation_reason=None,
                    ),
                )
                created = True
            claim = await self.repository.lock_setup_claim(
                session,
                claim_id=setup_claim_id,
            )
            if claim is None:
                raise ExternalChannelParticipationError(
                    "External Channel setup is unavailable."
                )
            if (
                claim.status is ExternalChannelSetupClaimStatus.SELECTED
                or claim.status is ExternalChannelSetupClaimStatus.COMPLETED
            ):
                if (
                    setting.id != claim.selected_setting_id
                    or setting.location is not location
                ):
                    raise ExternalChannelParticipationError(
                        "External Channel setup was already selected differently."
                    )
                await session.commit()
                return _CommittedLocation(
                    setting=setting,
                    claim=claim,
                    created=False,
                )
            if (
                not created
                or claim.status is not ExternalChannelSetupClaimStatus.PENDING_LOCATION
                or claim.claim_generation != expected_claim_generation
                or claim.source_revision != expected_source_revision
            ):
                raise ExternalChannelParticipationError(
                    "External Channel setup selection is stale."
                )
            position = await self.repository.lock_conversation_position(
                session,
                position_id=claim.conversation_position_id,
            )
            if position is None or position.connection_id != connection.id:
                raise ExternalChannelParticipationError(
                    "External Channel setup position is unavailable."
                )
            target_resource = await self._resolve_selected_resource(
                session,
                claim=claim,
                source=source,
                location=location,
                now=now,
            )
            selected = await self.repository.select_setup_claim(
                session,
                claim_id=claim.id,
                expected_claim_generation=claim.claim_generation,
                expected_source_revision=claim.source_revision,
                selected_setting_id=setting.id,
                selected_resource_id=target_resource.id,
                selected_at=now,
            )
            if selected is None:
                raise ExternalChannelParticipationError(
                    "External Channel setup selection lost its current revision."
                )
            await session.commit()
            return _CommittedLocation(
                setting=setting,
                claim=selected,
                created=created,
            )

    async def _resolve_selected_resource(
        self,
        session: AsyncSession,
        *,
        claim: ExternalChannelSetupClaim,
        source: ExternalChannelSetupSourceProjection,
        location: ExternalChannelConversationLocation,
        now: datetime.datetime,
    ) -> ExternalChannelResource:
        """Resolve the selected target without creating a Binding or Session."""
        if location is ExternalChannelConversationLocation.THREADS:
            resource = await self.repository.lock_resource(
                session,
                resource_id=claim.source_resource_id,
            )
            if (
                resource is None
                or resource.connection_id != claim.connection_id
                or resource.resource_type is not ExternalChannelResourceType.THREAD
                or resource.status is not ExternalChannelResourceStatus.ACTIVE
            ):
                raise ExternalChannelParticipationError(
                    "External Channel setup source is unavailable."
                )
            return resource
        return await self.repository.create_resource_idempotent(
            session,
            ExternalChannelResourceCreate(
                connection_id=claim.connection_id,
                resource_type=ExternalChannelResourceType.PARENT_CHANNEL,
                provider_resource_key=claim.provider_parent_channel_id,
                labels=_parent_resource_labels(source),
                status=ExternalChannelResourceStatus.ACTIVE,
                latest_activity_at=now,
                unavailable_at=None,
                deleted_at=None,
            ),
        )


def _parent_resource_labels(
    source: ExternalChannelSetupSourceProjection,
) -> dict[str, object]:
    """Build explicit provider labels for a selected parent Resource."""
    if source.provider.value == "slack":
        return {
            "provider": "slack",
            "provider_event_type": source.provider_event_type,
            "tenant_id": source.provider_tenant_id,
            "channel_id": source.provider_parent_channel_id,
            "conversation_scope": ExternalChannelResourceType.PARENT_CHANNEL.value,
        }
    return {
        "provider": "discord",
        "provider_event_type": source.provider_event_type,
        "guild_id": source.provider_tenant_id,
        "parent_channel_id": source.provider_parent_channel_id,
        "source_channel_id": source.provider_parent_channel_id,
        "conversation_scope": ExternalChannelResourceType.PARENT_CHANNEL.value,
    }
