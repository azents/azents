"""Provider-neutral External Channel participation setup mutations."""

import datetime
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.enums import (
    AgentLifecycleStatus,
    ExternalChannelAppMode,
    ExternalChannelConversationLocation,
    ExternalChannelParticipationSettingStatus,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
    ExternalChannelSetupClaimStatus,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.external_channel.data import (
    ExternalChannelParticipationSetting,
    ExternalChannelParticipationSettingCreate,
    ExternalChannelResource,
    ExternalChannelResourceCreate,
    ExternalChannelSetupClaim,
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
        Depends(ExternalChannelRepository),
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
    config: Annotated[Config, Depends(get_config)]

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
        if not self.config.external_channel_participation_enabled:
            raise ExternalChannelParticipationError(
                "External Channel participation is not enabled."
            )
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
