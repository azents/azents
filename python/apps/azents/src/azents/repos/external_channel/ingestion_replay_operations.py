"""Completed immutable replay snapshots and selected-interaction row locking."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from azents.core.enums import (
    ExternalChannelAccessRequestStatus,
    ExternalChannelConnectionStatus,
    ExternalChannelInteractionStatus,
    ExternalChannelParticipationSettingStatus,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelResourceStatus,
    ExternalChannelSetupClaimStatus,
)
from azents.core.external_channel_replay import (
    ExternalChannelIngestionReplayUnavailable,
    ExternalChannelReplaySource,
    ExternalChannelSetupReplaySource,
)
from azents.core.external_channel_selector_state import selector_state_from_interaction
from azents.rdb.deps import get_read_only_session_manager, get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.external_channel.repository import ExternalChannelRepository


@dataclass(frozen=True, kw_only=True)
class ExternalChannelReplayOperations:
    """Return detached validated replay facts after repository scope completion."""

    read_session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]
    write_session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    repository: Annotated[
        ExternalChannelRepository, Depends(ExternalChannelRepository.create)
    ]

    async def read_access_allow(
        self,
        *,
        access_request_id: str,
    ) -> ExternalChannelReplaySource:
        """Replay one committed Allow through its retained original boundary."""
        async with self.read_session_manager() as session:
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
                resource_id=request.source_resource_id,
                target_resource_id=request.resource_id,
                principal_id=request.principal_id,
                route_id=request.route_id,
                trigger_provider_message_key=(request.trigger_provider_message_key),
                range_start_position=request.range_start_position,
                trigger_position=request.trigger_position,
            )
        return source

    async def read_selected_interaction(
        self,
        *,
        selector_interaction_id: str,
        principal_id: str,
    ) -> ExternalChannelReplaySource:
        """Replay one immutable selected route through interaction-owned state."""
        async with self.write_session_manager() as session:
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
                target_resource_id=state.resource_id,
                principal_id=state.principal_id,
                route_id=state.selected_route_id,
                trigger_provider_message_key=state.trigger_provider_message_key,
                range_start_position=state.range_start_position,
                trigger_position=state.trigger_position,
            )
        return source

    async def read_setup_claim(
        self,
        *,
        setup_claim_id: str,
    ) -> ExternalChannelSetupReplaySource:
        async with self.read_session_manager() as session:
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
                or setting.status
                is not ExternalChannelParticipationSettingStatus.ACTIVE
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
        return ExternalChannelSetupReplaySource(
            configuration=configuration,
            claim=claim,
            setting=setting,
            source_resource=source_resource,
            principal=principal,
        )

    async def _load_source(
        self,
        session: ReadSession,
        *,
        connection_id: str,
        conversation_position_id: str,
        resource_id: str,
        target_resource_id: str,
        principal_id: str,
        route_id: str,
        trigger_provider_message_key: str,
        range_start_position: str | None,
        trigger_position: str,
    ) -> ExternalChannelReplaySource:
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
        return ExternalChannelReplaySource(
            configuration=configuration,
            position=position,
            resource=resource,
            target_resource_id=target_resource_id,
            principal=principal,
            route_id=route_id,
            trigger_provider_message_key=trigger_provider_message_key,
            range_start_position=range_start_position,
            trigger_position=trigger_position,
        )

    async def list_selected_setup_claim_ids(self, *, limit: int) -> tuple[str, ...]:
        """Finish the bounded oldest-selection recovery read before replay work."""
        async with self.read_session_manager() as session:
            claims = await self.repository.list_selected_setup_claims(
                session, limit=limit
            )
            ids = tuple(claim.id for claim in claims)
        return ids
