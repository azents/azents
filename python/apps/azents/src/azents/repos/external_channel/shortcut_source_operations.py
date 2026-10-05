"""Complete atomic content-free shortcut selector admission."""

import datetime
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelConversationScopeKind,
    ExternalChannelInteractionStatus,
    ExternalChannelInteractionType,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
    ExternalChannelSetupClaimStatus,
)
from azents.core.external_channel_participation_state import (
    ExternalChannelSetupSourceProjection,
    projection_with_setup_source,
)
from azents.core.external_channel_selector_state import (
    ExternalChannelSelectorState,
    projection_with_selector_state,
    selector_provider_interaction_key,
    selector_state_from_interaction,
)
from azents.core.external_channel_shortcut_source import (
    ExternalChannelShortcutSourceMaterialization,
    ShortcutSelectionUnavailable,
    ShortcutSourceProjection,
)
from azents.rdb.deps import get_read_only_session_manager, get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.external_channel.data import (
    ExternalChannelConnection,
    ExternalChannelConversationPosition,
    ExternalChannelConversationPositionCreate,
    ExternalChannelInteraction,
    ExternalChannelInteractionCreate,
    ExternalChannelResource,
    ExternalChannelResourceCreate,
    ExternalChannelSetupClaim,
    ExternalChannelSetupClaimCreate,
    ExternalChannelTrigger,
)
from azents.repos.external_channel.repository import ExternalChannelRepository

_SETUP_CLAIM_AGE = datetime.timedelta(days=7)


@dataclass
class ExternalChannelShortcutSourceOperations:
    """Resolve a shortcut source and attach typed selector state to its interaction."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    repository: Annotated[
        ExternalChannelRepository, Depends(ExternalChannelRepository.create)
    ]

    async def _ensure_setup_claim(
        self,
        session: WriteSession,
        *,
        connection: ExternalChannelConnection,
        interaction: ExternalChannelInteraction,
        position: ExternalChannelConversationPosition,
        resource: ExternalChannelResource,
        provider_event_type: str,
        provider_tenant_id: str,
        provider_channel_id: str,
        provider_parent_channel_id: str,
        delivery_thread_key: str,
        provider_resource_key: str,
        trigger_provider_message_key: str,
        trigger_provider_message_id: str,
        trigger_position: str,
        now: datetime.datetime,
    ) -> ExternalChannelSetupClaim:
        """Create or refresh one parent setup claim for a shortcut source."""
        assert interaction.principal_id is not None
        route = await self.repository.lock_routable_channel_default(
            session,
            connection_id=connection.id,
            provider_channel_id=provider_parent_channel_id,
        )
        source_projection = projection_with_setup_source(
            ExternalChannelSetupSourceProjection(
                schema_version=1,
                provider=connection.provider,
                provider_event_type=provider_event_type,
                provider_tenant_id=provider_tenant_id,
                provider_channel_id=provider_channel_id,
                provider_parent_channel_id=provider_parent_channel_id,
                scope_kind=ExternalChannelConversationScopeKind.PARENT_CHANNEL,
                provider_thread_key=None,
                delivery_thread_key=delivery_thread_key,
                provider_resource_key=provider_resource_key,
                trigger_provider_message_key=trigger_provider_message_key,
                trigger_provider_message_id=trigger_provider_message_id,
                trigger_position=trigger_position,
                range_start_position=position.read_through_position,
            )
        )
        claim = await self.repository.lock_nonterminal_setup_claim(
            session,
            connection_id=connection.id,
            provider_parent_channel_id=provider_parent_channel_id,
        )
        if (
            claim is not None
            and claim.status is ExternalChannelSetupClaimStatus.SELECTED
        ):
            raise ValueError("Shortcut setup selection is already in progress.")
        if claim is None:
            return await self.repository.create_setup_claim(
                session,
                ExternalChannelSetupClaimCreate(
                    connection_id=connection.id,
                    provider_parent_channel_id=provider_parent_channel_id,
                    route_id=None if route is None else route.id,
                    conversation_position_id=position.id,
                    source_resource_id=resource.id,
                    principal_id=interaction.principal_id,
                    source_projection=source_projection,
                    source_revision=1,
                    claim_generation=1,
                    status=ExternalChannelSetupClaimStatus.PENDING_AGENT
                    if route is None
                    else ExternalChannelSetupClaimStatus.PENDING_LOCATION,
                    selected_setting_id=None,
                    selected_resource_id=None,
                    selected_source_revision=None,
                    expires_at=now + _SETUP_CLAIM_AGE,
                    selected_at=None,
                    completed_at=None,
                ),
            )
        if (
            claim.status is ExternalChannelSetupClaimStatus.PENDING_AGENT
            and route is not None
        ):
            assigned = await self.repository.assign_setup_claim_route(
                session,
                claim_id=claim.id,
                expected_claim_generation=claim.claim_generation,
                route_id=route.id,
            )
            if assigned is None:
                raise ValueError("Shortcut setup route selection lost its generation.")
            claim = assigned
        if (route is None) != (claim.route_id is None) or (
            route is not None and claim.route_id != route.id
        ):
            raise ValueError("Shortcut setup route is no longer current.")
        if (
            claim.conversation_position_id == position.id
            and claim.source_resource_id == resource.id
            and (claim.principal_id == interaction.principal_id)
            and (claim.source_projection == source_projection)
        ):
            return claim
        replaced = await self.repository.replace_setup_claim_source(
            session,
            claim_id=claim.id,
            expected_claim_generation=claim.claim_generation,
            expected_source_revision=claim.source_revision,
            conversation_position_id=position.id,
            source_resource_id=resource.id,
            principal_id=interaction.principal_id,
            source_projection=source_projection,
            expires_at=now + _SETUP_CLAIM_AGE,
        )
        if replaced is None:
            raise ValueError("Shortcut setup source lost its current generation.")
        return replaced

    async def _ensure_setup_selector(
        self,
        session: WriteSession,
        *,
        connection: ExternalChannelConnection,
        interaction: ExternalChannelInteraction,
        position: ExternalChannelConversationPosition,
        resource: ExternalChannelResource,
        claim: ExternalChannelSetupClaim,
        trigger_provider_message_key: str,
        trigger_position: str,
        now: datetime.datetime,
    ) -> ExternalChannelInteraction:
        """Create a setup-linked selector instead of replaying into a Binding."""
        assert interaction.principal_id is not None
        provider_key = selector_provider_interaction_key(
            connection_id=connection.id,
            trigger_provider_message_key=trigger_provider_message_key,
        )
        expected = ExternalChannelSelectorState(
            connection_id=connection.id,
            resource_id=resource.id,
            principal_id=interaction.principal_id,
            conversation_position_id=position.id,
            trigger_provider_message_key=trigger_provider_message_key,
            range_start_position=position.read_through_position,
            trigger_position=trigger_position,
            selected_route_id=None,
        )
        existing = await self.repository.get_interaction_by_provider_key(
            session, connection_id=connection.id, provider_interaction_key=provider_key
        )
        if existing is not None:
            state = selector_state_from_interaction(existing)
            if (
                state.model_copy(update={"selected_route_id": None}) != expected
                or existing.setup_claim_id != claim.id
            ):
                raise ValueError("Shortcut setup selector retry is incompatible.")
            return existing
        admitted = await self.repository.admit_interaction(
            session,
            ExternalChannelInteractionCreate(
                connection_id=connection.id,
                transport=connection.transport,
                provider_interaction_key=provider_key,
                interaction_type=ExternalChannelInteractionType.MANAGEMENT_ACTION,
                callback_id=None,
                action_id="agent_selector",
                principal_id=interaction.principal_id,
                setup_claim_id=claim.id,
                resource_correlation_key=None,
                projection=projection_with_selector_state({}, expected),
                status=ExternalChannelInteractionStatus.ACCEPTED,
                expires_at=now + _SETUP_CLAIM_AGE,
                error_kind=None,
                error_summary=None,
            ),
        )
        return admitted.interaction

    read_session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]

    async def ensure(
        self,
        *,
        shortcut_source_event: ExternalChannelTrigger,
        interaction_id: str,
        now: datetime.datetime,
        connection_snapshot: ExternalChannelConnection,
        projection: ShortcutSourceProjection,
    ) -> ExternalChannelShortcutSourceMaterialization:
        """Commit one content-free selector boundary before opening the modal."""
        async with self.session_manager() as session:
            interaction = await self.repository.lock_interaction(
                session, interaction_id=interaction_id
            )
            if (
                interaction is None
                or interaction.connection_id != shortcut_source_event.connection_id
                or interaction.interaction_type
                is not ExternalChannelInteractionType.SHORTCUT
                or (interaction.principal_id is None)
                or (shortcut_source_event.provider_tenant_id is None)
            ):
                raise ValueError("Shortcut source is unavailable.")
            connection = await self.repository.lock_connection_for_routing(
                session, connection_id=shortcut_source_event.connection_id
            )
            if (
                connection is None
                or connection.app_mode is not ExternalChannelAppMode.MULTI
            ):
                raise ShortcutSelectionUnavailable("Shortcut selection is unavailable.")
            if (
                connection.configuration_generation
                != connection_snapshot.configuration_generation
                or connection.provider_bot_user_id
                != connection_snapshot.provider_bot_user_id
                or connection.provider is not connection_snapshot.provider
            ):
                raise ShortcutSelectionUnavailable(
                    "Shortcut connection changed during source preparation."
                )
            provider_resource_key = projection.provider_resource_key
            position_scope_kind = projection.position_scope_kind
            position_provider_channel_id = projection.position_provider_channel_id
            position_provider_thread_key = projection.position_provider_thread_key
            provider_parent_channel_id = projection.provider_parent_channel_id
            delivery_thread_key = projection.delivery_thread_key
            trigger_provider_message_id = projection.trigger_provider_message_id
            labels = projection.labels
            position = await self.repository.create_conversation_position_idempotent(
                session,
                ExternalChannelConversationPositionCreate(
                    connection_id=connection.id,
                    scope_kind=position_scope_kind,
                    provider_channel_id=position_provider_channel_id,
                    provider_thread_key=position_provider_thread_key,
                    read_through_position=None,
                ),
            )
            resource = await self.repository.create_resource_idempotent(
                session,
                ExternalChannelResourceCreate(
                    connection_id=connection.id,
                    resource_type=ExternalChannelResourceType.THREAD,
                    provider_resource_key=provider_resource_key,
                    labels=labels,
                    status=ExternalChannelResourceStatus.ACTIVE,
                    latest_activity_at=projection.provider_created_at,
                    unavailable_at=None,
                    deleted_at=None,
                ),
            )
            resource = await self.repository.lock_resource(
                session, resource_id=resource.id
            )
            if (
                resource is None
                or resource.status is not ExternalChannelResourceStatus.ACTIVE
            ):
                raise ShortcutSelectionUnavailable("Shortcut source is unavailable.")
            binding = await self.repository.lock_connected_binding_by_resource(
                session, resource_id=resource.id
            )
            if binding is not None:
                await session.write_session.commit()
                return ExternalChannelShortcutSourceMaterialization(
                    selector_interaction=None
                )
            if (
                position_scope_kind
                is ExternalChannelConversationScopeKind.PARENT_CHANNEL
                and await self.repository.get_active_participation_setting(
                    session,
                    connection_id=connection.id,
                    provider_parent_channel_id=provider_parent_channel_id,
                )
                is None
            ):
                claim = await self._ensure_setup_claim(
                    session,
                    connection=connection,
                    interaction=interaction,
                    position=position,
                    resource=resource,
                    provider_event_type=shortcut_source_event.event_type,
                    provider_tenant_id=shortcut_source_event.provider_tenant_id,
                    provider_channel_id=position_provider_channel_id,
                    provider_parent_channel_id=provider_parent_channel_id,
                    delivery_thread_key=delivery_thread_key,
                    provider_resource_key=provider_resource_key,
                    trigger_provider_message_key=projection.provider_message_key,
                    trigger_provider_message_id=trigger_provider_message_id,
                    trigger_position=projection.provider_position,
                    now=now,
                )
                selector = await self._ensure_setup_selector(
                    session,
                    connection=connection,
                    interaction=interaction,
                    position=position,
                    resource=resource,
                    claim=claim,
                    trigger_provider_message_key=projection.provider_message_key,
                    trigger_position=projection.provider_position,
                    now=now,
                )
                await session.write_session.commit()
                return ExternalChannelShortcutSourceMaterialization(
                    selector_interaction=selector
                )
            selector_state = ExternalChannelSelectorState(
                connection_id=connection.id,
                resource_id=resource.id,
                principal_id=interaction.principal_id,
                conversation_position_id=position.id,
                trigger_provider_message_key=projection.provider_message_key,
                range_start_position=position.read_through_position,
                trigger_position=projection.provider_position,
                selected_route_id=None,
            )
            try:
                existing_state = selector_state_from_interaction(interaction)
            except ValueError:
                existing_state = None
            if existing_state is not None:
                expected_state = selector_state.model_copy(
                    update={"selected_route_id": existing_state.selected_route_id}
                )
                if existing_state != expected_state:
                    raise ValueError("Shortcut selector state is incompatible.")
                await session.write_session.commit()
                return ExternalChannelShortcutSourceMaterialization(
                    selector_interaction=interaction
                )
            updated = await self.repository.replace_interaction_projection(
                session,
                interaction_id=interaction.id,
                projection=projection_with_selector_state(
                    interaction.projection, selector_state
                ),
            )
            if updated is None:
                raise RuntimeError("Shortcut interaction disappeared.")
            await session.write_session.commit()
            return ExternalChannelShortcutSourceMaterialization(
                selector_interaction=updated
            )

    async def read_connection(
        self, connection_id: str
    ) -> ExternalChannelConnection | None:
        """Capture source normalization identity in an independent native read."""
        async with self.read_session_manager() as session:
            return await self.repository.get_connection(
                session, connection_id=connection_id
            )
