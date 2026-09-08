"""Authorized provider-neutral External Channel management operations."""

import datetime
import json
import re
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends
from pydantic import BaseModel, ConfigDict, Field

from azents.core.enums import (
    ExternalChannelAccessGrantScope,
    ExternalChannelAppMode,
    ExternalChannelConversationScopeKind,
    ExternalChannelIngressProfile,
    ExternalChannelProvider,
    ExternalChannelResourceType,
    ExternalChannelResponseMode,
    ExternalChannelTransport,
)
from azents.core.external_channel_provider import (
    DiscordConnectionConfiguration,
    DiscordConnectionCredentials,
    DiscordThreadAutoArchiveDurationMinutes,
    ExternalChannelConnectionCredentialPayload,
    ExternalChannelConnectionStatusSnapshot,
    SlackConnectionCredentials,
)
from azents.repos.agent.data import Agent
from azents.repos.external_channel.data import (
    ExternalChannelMultiConnectionDisconnect,
    ExternalChannelMultiConnectionImpact,
    ExternalChannelMultiRouteImpact,
)
from azents.repos.external_channel.management import (
    ExternalChannelChannelDefaultTransition,
)
from azents.repos.external_channel.management_data import (
    ManagedApprovalRequest,
    ManagedBinding,
    ManagedChannelDefault,
    ManagedChannelDefaultMutation,
    ManagedConnection,
    ManagedGrant,
    ManagedMultiConnection,
    ManagedMultiConnectionDisconnect,
    ManagedMultiRoute,
    ManagedSlackManagementHandoff,
)
from azents.repos.external_channel.management_operation_data import (
    ExternalChannelManagementNotFound,
    ManagedAgentAccess,
)
from azents.repos.external_channel.management_operations import (
    ExternalChannelManagementOperationRepository,
)
from azents.services.external_channel.access import ExternalChannelAccessService
from azents.services.external_channel.channel_action import ExternalChannelActionService
from azents.services.external_channel.connection import (
    ExternalChannelConnectionService,
)
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
from azents.services.external_channel.discord_activation import (
    DiscordConnectionActivationService,
)
from azents.services.external_channel.provider import (
    DiscordExternalChannelProviderContract,
    SlackExternalChannelProviderContract,
)
from azents.services.external_channel.slack_http import (
    SLACK_AZENTS_COMMAND,
    SLACK_INVOCATION_SHORTCUT_CALLBACK_ID,
    SLACK_OPTIONAL_FILE_BOT_SCOPES,
    SLACK_REQUIRED_BOT_SCOPES,
    SLACK_SETTINGS_SHORTCUT_CALLBACK_ID,
)


class ManagedConnectionSetup(BaseModel):
    model_config = ConfigDict(frozen=True)

    connection: ManagedConnection


class ManagedMultiConnectionSetup(BaseModel):
    """Created redacted Multi App connection."""

    model_config = ConfigDict(frozen=True)

    connection: ManagedMultiConnection


class SlackManifestGuidance(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: Literal["slack"] = "slack"
    transport: ExternalChannelTransport
    bot_scopes: tuple[str, ...]
    event_subscriptions: tuple[str, ...]
    socket_mode_enabled: bool
    app_token_scope: str | None
    callback_url: str | None
    manifest: dict[str, object]
    manifest_json: str


class ExternalChannelDecisionInput(BaseModel):
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    decision: Literal["allow_session", "allow_agent", "deny", "block"]
    summary: str | None = Field(default=None, max_length=1000)


class ExternalChannelAccessPolicyInput(BaseModel):
    """Non-secret ingress policy for one dedicated External Channel route."""

    model_config = ConfigDict(frozen=True)

    open_access_enabled: bool = True


class ExternalChannelResponseModeSetting(BaseModel):
    """Canonical full-value External Channel response-mode setting."""

    model_config = ConfigDict(frozen=True)

    response_mode: ExternalChannelResponseMode


class DiscordThreadAutoArchiveDurationSetting(BaseModel):
    """Canonical full-value Discord Thread automatic archive setting."""

    model_config = ConfigDict(frozen=True)

    thread_auto_archive_duration_minutes: DiscordThreadAutoArchiveDurationMinutes


class DiscordUrlPreviewSuppressionSetting(BaseModel):
    """Canonical full-value Discord automatic URL-preview setting."""

    model_config = ConfigDict(frozen=True)

    suppress_url_previews: bool


@dataclass
class ExternalChannelManagementService:
    """Authorize and orchestrate External Channel management boundaries."""

    operation_repository: Annotated[
        ExternalChannelManagementOperationRepository, Depends()
    ]
    connection_service: Annotated[
        ExternalChannelConnectionService,
        Depends(ExternalChannelConnectionService),
    ]
    discord_activation_service: Annotated[
        DiscordConnectionActivationService,
        Depends(DiscordConnectionActivationService),
    ]
    action_service: Annotated[
        ExternalChannelActionService,
        Depends(ExternalChannelActionService),
    ]
    access_service: Annotated[
        ExternalChannelAccessService,
        Depends(ExternalChannelAccessService),
    ]
    conversation_lock: Annotated[
        ExternalChannelConversationLock,
        Depends(get_external_channel_conversation_lock),
    ]
    participation_lock: Annotated[
        ExternalChannelParticipationLock,
        Depends(get_external_channel_participation_lock),
    ]

    async def list_connections(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        workspace_user_id: str,
    ) -> list[ManagedConnection]:
        return await self.operation_repository.list_connections(
            workspace_id=workspace_id,
            agent_id=agent_id,
            workspace_user_id=workspace_user_id,
        )

    async def get_default_response_mode(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        workspace_user_id: str,
    ) -> ExternalChannelResponseModeSetting:
        """Read the default copied to subsequently created bindings."""
        agent = await self._require_agent(
            workspace_id=workspace_id,
            agent_id=agent_id,
            workspace_user_id=workspace_user_id,
            admin=False,
        )
        return ExternalChannelResponseModeSetting(
            response_mode=agent.external_channel_default_response_mode
        )

    async def update_default_response_mode(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        workspace_user_id: str,
        setting: ExternalChannelResponseModeSetting,
    ) -> ExternalChannelResponseModeSetting:
        """Replace only the Agent default without rewriting existing bindings."""
        response_mode = await self.operation_repository.update_default_response_mode(
            workspace_id=workspace_id,
            agent_id=agent_id,
            workspace_user_id=workspace_user_id,
            response_mode=setting.response_mode,
        )
        return ExternalChannelResponseModeSetting(response_mode=response_mode)

    async def list_agent_multi_connections(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        workspace_user_id: str,
    ) -> list[ManagedMultiConnection]:
        """List read-only Multi Apps associated with one visible Agent."""
        return await self.operation_repository.list_agent_multi_connections(
            workspace_id=workspace_id,
            agent_id=agent_id,
            workspace_user_id=workspace_user_id,
        )

    async def setup_slack(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        workspace_user_id: str,
        app_id: str,
        transport: ExternalChannelTransport,
        credentials: SlackConnectionCredentials,
    ) -> ManagedConnectionSetup:
        await self._require_agent(
            workspace_id=workspace_id,
            agent_id=agent_id,
            workspace_user_id=workspace_user_id,
            admin=True,
        )
        setup = await self.connection_service.create_slack_connection(
            workspace_id=workspace_id,
            app_id=app_id,
            transport=transport,
            credentials=credentials,
        )
        await self.operation_repository.create_dedicated_route(
            connection_id=setup.connection.id, agent_id=agent_id
        )
        await self.connection_service.validate_connection(
            workspace_id=workspace_id,
            connection_id=setup.connection.id,
        )
        connections = await self.list_connections(
            workspace_id=workspace_id,
            agent_id=agent_id,
            workspace_user_id=workspace_user_id,
        )
        connection = next(
            item for item in connections if item.id == setup.connection.id
        )
        return ManagedConnectionSetup(connection=connection)

    async def setup_discord(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        workspace_user_id: str,
        app_id: str,
        configuration: DiscordConnectionConfiguration,
        credentials: DiscordConnectionCredentials,
    ) -> ManagedConnectionSetup:
        """Create a configuring dedicated Discord App and its sole Agent route."""
        await self._require_agent(
            workspace_id=workspace_id,
            agent_id=agent_id,
            workspace_user_id=workspace_user_id,
            admin=True,
        )
        setup = await self.connection_service.create_discord_connection(
            workspace_id=workspace_id,
            app_id=app_id,
            configuration=configuration,
            credentials=credentials,
        )
        await self.operation_repository.create_dedicated_route(
            connection_id=setup.connection.id, agent_id=agent_id
        )
        await self.discord_activation_service.activate(
            connection_id=setup.connection.id
        )
        connections = await self.list_connections(
            workspace_id=workspace_id,
            agent_id=agent_id,
            workspace_user_id=workspace_user_id,
        )
        connection = next(
            item for item in connections if item.id == setup.connection.id
        )
        return ManagedConnectionSetup(connection=connection)

    async def list_multi_connections(
        self,
        *,
        workspace_id: str,
        provider: ExternalChannelProvider | None,
        offset: int,
        limit: int,
    ) -> list[ManagedMultiConnection]:
        """List redacted Workspace-owned Multi Apps for one optional provider."""
        return await self.operation_repository.list_multi_connections(
            workspace_id=workspace_id, provider=provider, offset=offset, limit=limit
        )

    async def get_multi_connection(
        self,
        *,
        workspace_id: str,
        connection_id: str,
        provider: ExternalChannelProvider,
        include_disconnected: bool = False,
    ) -> ManagedMultiConnection:
        """Load one provider-scoped Workspace Multi App."""
        return await self.operation_repository.get_multi_connection(
            workspace_id=workspace_id,
            connection_id=connection_id,
            provider=provider,
            include_disconnected=include_disconnected,
        )

    async def setup_multi_slack(
        self,
        *,
        workspace_id: str,
        app_id: str,
        transport: ExternalChannelTransport,
        credentials: SlackConnectionCredentials,
    ) -> ManagedMultiConnectionSetup:
        """Create a zero-Agent-capable Workspace Slack Multi App."""
        setup = await self.connection_service.create_slack_connection(
            workspace_id=workspace_id,
            app_id=app_id,
            transport=transport,
            credentials=credentials,
            app_mode=ExternalChannelAppMode.MULTI,
        )
        await self.connection_service.validate_connection(
            workspace_id=workspace_id,
            connection_id=setup.connection.id,
        )
        connection = await self.get_multi_connection(
            workspace_id=workspace_id,
            connection_id=setup.connection.id,
            provider=ExternalChannelProvider.SLACK,
        )
        return ManagedMultiConnectionSetup(connection=connection)

    async def setup_multi_discord(
        self,
        *,
        workspace_id: str,
        app_id: str,
        configuration: DiscordConnectionConfiguration,
        credentials: DiscordConnectionCredentials,
    ) -> ManagedMultiConnectionSetup:
        """Create a zero-Agent-capable configuring Workspace Discord Multi App."""
        setup = await self.connection_service.create_discord_connection(
            workspace_id=workspace_id,
            app_id=app_id,
            configuration=configuration,
            credentials=credentials,
            app_mode=ExternalChannelAppMode.MULTI,
        )
        await self.discord_activation_service.activate(
            connection_id=setup.connection.id
        )
        connection = await self.get_multi_connection(
            workspace_id=workspace_id,
            connection_id=setup.connection.id,
            provider=ExternalChannelProvider.DISCORD,
        )
        return ManagedMultiConnectionSetup(connection=connection)

    async def validate_multi_connection(
        self,
        *,
        workspace_id: str,
        connection_id: str,
        provider: ExternalChannelProvider,
    ) -> ExternalChannelConnectionStatusSnapshot:
        """Validate one Workspace-owned Multi App without exposing credentials."""
        connection = await self.get_multi_connection(
            workspace_id=workspace_id,
            connection_id=connection_id,
            provider=provider,
        )
        if connection.provider is ExternalChannelProvider.DISCORD:
            return await self.discord_activation_service.activate(
                connection_id=connection_id
            )
        return await self.connection_service.validate_connection(
            workspace_id=workspace_id,
            connection_id=connection_id,
        )

    async def update_multi_slack(
        self,
        *,
        workspace_id: str,
        connection_id: str,
        app_id: str,
        transport: ExternalChannelTransport,
        credentials: SlackConnectionCredentials,
    ) -> ExternalChannelConnectionStatusSnapshot:
        """Replace complete Multi App setup and validate its new credentials."""
        if not app_id.strip():
            raise ValueError("Slack App ID must not be blank.")
        contract = SlackExternalChannelProviderContract()
        validated = contract.validate_connection_credentials(
            ExternalChannelConnectionCredentialPayload(
                provider=credentials.provider,
                transport=transport,
                ingress_profile=(
                    ExternalChannelIngressProfile.SLACK_SOCKET
                    if transport is ExternalChannelTransport.SOCKET
                    else ExternalChannelIngressProfile.SLACK_HTTP
                ),
                credentials=credentials,
            )
        )
        encrypted = self.connection_service.credentials_codec.encrypt(validated)
        await self.operation_repository.replace_multi_slack_configuration(
            workspace_id=workspace_id,
            connection_id=connection_id,
            app_id=app_id,
            encrypted=encrypted,
            transport=transport,
        )
        return await self.connection_service.validate_connection(
            workspace_id=workspace_id,
            connection_id=connection_id,
        )

    async def update_multi_discord(
        self,
        *,
        workspace_id: str,
        connection_id: str,
        app_id: str,
        configuration: DiscordConnectionConfiguration,
        credentials: DiscordConnectionCredentials,
    ) -> ExternalChannelConnectionStatusSnapshot:
        """Fence Discord Multi credentials, then reactivate callback authority."""
        if not app_id.strip():
            raise ValueError("Discord App ID must not be blank.")
        contract = DiscordExternalChannelProviderContract()
        validated = contract.validate_connection_credentials(
            ExternalChannelConnectionCredentialPayload(
                provider=credentials.provider,
                transport=ExternalChannelTransport.HTTP,
                ingress_profile=ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP,
                credentials=credentials,
            )
        )
        encrypted = self.connection_service.credentials_codec.encrypt(validated)
        await self.operation_repository.replace_multi_discord_configuration(
            workspace_id=workspace_id,
            connection_id=connection_id,
            app_id=app_id,
            encrypted=encrypted,
            provider_config=configuration.model_dump(mode="json"),
        )
        return await self.discord_activation_service.activate(
            connection_id=connection_id
        )

    async def update_multi_discord_thread_auto_archive_duration(
        self,
        *,
        workspace_id: str,
        connection_id: str,
        expected_generation: datetime.datetime,
        setting: DiscordThreadAutoArchiveDurationSetting,
    ) -> ManagedMultiConnection:
        """Replace one Multi App Thread policy without provider reactivation."""
        return await (
            self.operation_repository.update_multi_discord_thread_auto_archive_duration(
                workspace_id=workspace_id,
                connection_id=connection_id,
                expected_generation=expected_generation,
                thread_auto_archive_duration_minutes=(
                    setting.thread_auto_archive_duration_minutes
                ),
            )
        )

    async def update_multi_discord_url_preview_suppression(
        self,
        *,
        workspace_id: str,
        connection_id: str,
        expected_generation: datetime.datetime,
        setting: DiscordUrlPreviewSuppressionSetting,
    ) -> ManagedMultiConnection:
        """Replace one Multi App URL-preview policy without reactivation."""
        return await (
            self.operation_repository.update_multi_discord_url_preview_suppression(
                workspace_id=workspace_id,
                connection_id=connection_id,
                expected_generation=expected_generation,
                suppress_url_previews=setting.suppress_url_previews,
            )
        )

    async def list_multi_routes(
        self,
        *,
        workspace_id: str,
        connection_id: str,
        provider: ExternalChannelProvider,
        offset: int,
        limit: int,
    ) -> list[ManagedMultiRoute]:
        """List the complete paged catalog, including removed history."""
        return await self.operation_repository.list_multi_routes(
            workspace_id=workspace_id,
            connection_id=connection_id,
            provider=provider,
            offset=offset,
            limit=limit,
        )

    async def add_multi_route(
        self,
        *,
        workspace_id: str,
        connection_id: str,
        provider: ExternalChannelProvider,
        agent_id: str,
    ) -> ManagedMultiRoute:
        """Add one active Workspace Agent to a Multi App catalog."""
        return await self.operation_repository.add_multi_route(
            workspace_id=workspace_id,
            connection_id=connection_id,
            provider=provider,
            agent_id=agent_id,
        )

    async def get_multi_route_impact(
        self,
        *,
        workspace_id: str,
        connection_id: str,
        provider: ExternalChannelProvider,
        route_id: str,
    ) -> ExternalChannelMultiRouteImpact:
        """Return a sanitized count-only removal impact preview."""
        return await self.operation_repository.get_multi_route_impact(
            workspace_id=workspace_id,
            connection_id=connection_id,
            provider=provider,
            route_id=route_id,
        )

    async def get_multi_connection_impact(
        self,
        *,
        workspace_id: str,
        connection_id: str,
        provider: ExternalChannelProvider,
    ) -> ExternalChannelMultiConnectionImpact:
        """Return sanitized impact before disconnecting one whole Multi App."""
        return await self.operation_repository.get_multi_connection_impact(
            workspace_id=workspace_id, connection_id=connection_id, provider=provider
        )

    async def remove_multi_route(
        self,
        *,
        workspace_id: str,
        connection_id: str,
        provider: ExternalChannelProvider,
        route_id: str,
        user_id: str,
        expected_generation: datetime.datetime,
    ) -> ExternalChannelMultiRouteImpact:
        """Generation-fence one destructive Multi App catalog removal."""
        removal = await self.operation_repository.remove_multi_route(
            workspace_id=workspace_id,
            connection_id=connection_id,
            provider=provider,
            route_id=route_id,
            user_id=user_id,
            expected_generation=expected_generation,
        )
        for plan in removal.cleanup_plans:
            await self.action_service.execute_terminal_control(plan)
        return removal.impact

    async def reenable_multi_route(
        self,
        *,
        workspace_id: str,
        connection_id: str,
        provider: ExternalChannelProvider,
        route_id: str,
    ) -> ManagedMultiRoute:
        """Re-enable a removed Multi App route without reviving old state."""
        return await self.operation_repository.reenable_multi_route(
            workspace_id=workspace_id,
            connection_id=connection_id,
            provider=provider,
            route_id=route_id,
        )

    async def list_multi_channel_defaults(
        self,
        *,
        workspace_id: str,
        connection_id: str,
        provider: ExternalChannelProvider,
        offset: int,
        limit: int,
    ) -> list[ManagedChannelDefault]:
        """List paged Multi App channel defaults without channel message content."""
        return await self.operation_repository.list_multi_channel_defaults(
            workspace_id=workspace_id,
            connection_id=connection_id,
            provider=provider,
            offset=offset,
            limit=limit,
        )

    async def replace_multi_channel_default(
        self,
        *,
        workspace_id: str,
        connection_id: str,
        provider: ExternalChannelProvider,
        provider_channel_id: str,
        route_id: str,
        user_id: str,
        expected_generation: datetime.datetime,
    ) -> ManagedChannelDefaultMutation:
        """Generation-fence replacement of one Multi App channel default."""
        now = datetime.datetime.now(datetime.UTC)
        deadline = ExternalChannelOperationDeadline(
            now + datetime.timedelta(seconds=30)
        )
        conversation_scope = ExternalChannelConversationScope(
            connection_id=connection_id,
            kind=ExternalChannelConversationScopeKind.PARENT_CHANNEL,
            provider_channel_id=provider_channel_id,
            provider_thread_key=None,
        )
        participation_scope = ExternalChannelParticipationScope(
            connection_id=connection_id,
            provider_parent_channel_id=provider_channel_id,
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
                transition = (
                    await self.operation_repository.replace_multi_channel_default(
                        workspace_id=workspace_id,
                        connection_id=connection_id,
                        provider=provider,
                        provider_channel_id=provider_channel_id,
                        route_id=route_id,
                        user_id=user_id,
                        expected_generation=expected_generation,
                        now=now,
                    )
                )
        for plan in transition.cleanup_plans:
            await self.action_service.execute_terminal_control(plan)
        return _managed_channel_default_mutation(transition)

    async def clear_multi_channel_default(
        self,
        *,
        workspace_id: str,
        connection_id: str,
        provider: ExternalChannelProvider,
        provider_channel_id: str,
        expected_generation: datetime.datetime,
    ) -> ManagedChannelDefaultMutation:
        """Generation-fence removal of one active Multi App channel default."""
        now = datetime.datetime.now(datetime.UTC)
        deadline = ExternalChannelOperationDeadline(
            now + datetime.timedelta(seconds=30)
        )
        conversation_scope = ExternalChannelConversationScope(
            connection_id=connection_id,
            kind=ExternalChannelConversationScopeKind.PARENT_CHANNEL,
            provider_channel_id=provider_channel_id,
            provider_thread_key=None,
        )
        participation_scope = ExternalChannelParticipationScope(
            connection_id=connection_id,
            provider_parent_channel_id=provider_channel_id,
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
                transition = (
                    await self.operation_repository.clear_multi_channel_default(
                        workspace_id=workspace_id,
                        connection_id=connection_id,
                        provider=provider,
                        provider_channel_id=provider_channel_id,
                        expected_generation=expected_generation,
                        now=now,
                    )
                )
        for plan in transition.cleanup_plans:
            await self.action_service.execute_terminal_control(plan)
        return _managed_channel_default_mutation(transition)

    async def disconnect_multi_connection(
        self,
        *,
        workspace_id: str,
        connection_id: str,
        provider: ExternalChannelProvider,
        expected_generation: datetime.datetime,
    ) -> ManagedMultiConnectionDisconnect:
        """Generation-fence terminal Multi App disconnect around provider I/O."""
        result = await self.operation_repository.disconnect_multi_connection(
            workspace_id=workspace_id,
            connection_id=connection_id,
            provider=provider,
            expected_generation=expected_generation,
        )
        for plan in result.cleanup_plans:
            await self.action_service.execute_terminal_control(plan)
        return _managed_multi_disconnect(result)

    async def load_multi_management_handoff(
        self,
        *,
        workspace_id: str,
        interaction_id: str,
    ) -> ManagedSlackManagementHandoff:
        """Load one opaque Slack management handoff after Workspace authorization."""
        return await self.operation_repository.load_multi_management_handoff(
            workspace_id=workspace_id, interaction_id=interaction_id
        )

    async def validate_connection(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        workspace_user_id: str,
        connection_id: str,
    ) -> ExternalChannelConnectionStatusSnapshot:
        provider = await self.operation_repository.get_owned_connection_provider(
            workspace_id=workspace_id,
            agent_id=agent_id,
            workspace_user_id=workspace_user_id,
            connection_id=connection_id,
        )
        if provider is ExternalChannelProvider.DISCORD:
            return await self.discord_activation_service.activate(
                connection_id=connection_id
            )
        return await self.connection_service.validate_connection(
            workspace_id=workspace_id,
            connection_id=connection_id,
        )

    async def update_slack(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        workspace_user_id: str,
        connection_id: str,
        app_id: str,
        transport: ExternalChannelTransport,
        credentials: SlackConnectionCredentials,
    ) -> ExternalChannelConnectionStatusSnapshot:
        await self._require_owned_connection(
            workspace_id=workspace_id,
            agent_id=agent_id,
            workspace_user_id=workspace_user_id,
            connection_id=connection_id,
        )
        if not app_id.strip():
            raise ValueError("Slack App ID must not be blank.")
        contract = SlackExternalChannelProviderContract()
        validated = contract.validate_connection_credentials(
            ExternalChannelConnectionCredentialPayload(
                provider=credentials.provider,
                transport=transport,
                ingress_profile=(
                    ExternalChannelIngressProfile.SLACK_SOCKET
                    if transport is ExternalChannelTransport.SOCKET
                    else ExternalChannelIngressProfile.SLACK_HTTP
                ),
                credentials=credentials,
            ),
        )
        encrypted = self.connection_service.credentials_codec.encrypt(validated)
        await self.operation_repository.replace_slack_configuration(
            workspace_id=workspace_id,
            connection_id=connection_id,
            app_id=app_id,
            encrypted=encrypted,
            agent_id=agent_id,
            transport=transport,
        )
        return await self.connection_service.validate_connection(
            workspace_id=workspace_id,
            connection_id=connection_id,
        )

    async def update_discord(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        workspace_user_id: str,
        connection_id: str,
        app_id: str,
        configuration: DiscordConnectionConfiguration,
        credentials: DiscordConnectionCredentials,
    ) -> ExternalChannelConnectionStatusSnapshot:
        """Fence Discord credentials, then reactivate callback authority."""
        await self._require_owned_connection(
            workspace_id=workspace_id,
            agent_id=agent_id,
            workspace_user_id=workspace_user_id,
            connection_id=connection_id,
        )
        if not app_id.strip():
            raise ValueError("Discord App ID must not be blank.")
        contract = DiscordExternalChannelProviderContract()
        validated = contract.validate_connection_credentials(
            ExternalChannelConnectionCredentialPayload(
                provider=credentials.provider,
                transport=ExternalChannelTransport.HTTP,
                ingress_profile=ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP,
                credentials=credentials,
            )
        )
        encrypted = self.connection_service.credentials_codec.encrypt(validated)
        await self.operation_repository.replace_discord_configuration(
            workspace_id=workspace_id,
            connection_id=connection_id,
            app_id=app_id,
            encrypted=encrypted,
            agent_id=agent_id,
            provider_config=configuration.model_dump(mode="json"),
        )
        return await self.discord_activation_service.activate(
            connection_id=connection_id
        )

    async def update_discord_thread_auto_archive_duration(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        workspace_user_id: str,
        connection_id: str,
        setting: DiscordThreadAutoArchiveDurationSetting,
    ) -> ManagedConnection:
        """Replace one dedicated Thread policy without provider reactivation."""
        return await (
            self.operation_repository.update_discord_thread_auto_archive_duration(
                workspace_id=workspace_id,
                agent_id=agent_id,
                workspace_user_id=workspace_user_id,
                connection_id=connection_id,
                thread_auto_archive_duration_minutes=(
                    setting.thread_auto_archive_duration_minutes
                ),
            )
        )

    async def update_discord_url_preview_suppression(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        workspace_user_id: str,
        connection_id: str,
        setting: DiscordUrlPreviewSuppressionSetting,
    ) -> ManagedConnection:
        """Replace one dedicated URL-preview policy without reactivation."""
        return await self.operation_repository.update_discord_url_preview_suppression(
            workspace_id=workspace_id,
            agent_id=agent_id,
            workspace_user_id=workspace_user_id,
            connection_id=connection_id,
            suppress_url_previews=setting.suppress_url_previews,
        )

    async def disconnect_connection(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        workspace_user_id: str,
        connection_id: str,
    ) -> ManagedConnection:
        result = await self.operation_repository.disconnect_connection(
            workspace_id=workspace_id,
            agent_id=agent_id,
            workspace_user_id=workspace_user_id,
            connection_id=connection_id,
        )
        for plan in result.cleanup_plans:
            await self.action_service.execute_terminal_control(plan)
        return result.connection

    async def update_connection_access_policy(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        workspace_user_id: str,
        connection_id: str,
        policy: ExternalChannelAccessPolicyInput,
    ) -> ManagedConnection:
        """Update one dedicated connection's route-scoped ingress policy."""
        return await self.operation_repository.update_connection_access_policy(
            workspace_id=workspace_id,
            agent_id=agent_id,
            workspace_user_id=workspace_user_id,
            connection_id=connection_id,
            open_access_enabled=policy.open_access_enabled,
        )

    async def list_bindings(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        agent_session_id: str,
    ) -> list[ManagedBinding]:
        return await self.operation_repository.list_bindings(
            workspace_id=workspace_id,
            agent_id=agent_id,
            agent_session_id=agent_session_id,
        )

    async def disconnect_binding(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        workspace_user_id: str,
        agent_session_id: str,
        binding_id: str,
    ) -> list[ManagedBinding]:
        await self._require_agent(
            workspace_id=workspace_id,
            agent_id=agent_id,
            workspace_user_id=workspace_user_id,
            admin=True,
        )
        cleanup_plans = await self.operation_repository.disconnect_binding(
            workspace_id=workspace_id,
            agent_id=agent_id,
            agent_session_id=agent_session_id,
            binding_id=binding_id,
            now=datetime.datetime.now(datetime.UTC),
        )
        for plan in cleanup_plans:
            await self.action_service.execute_terminal_control(plan)
        return await self.list_bindings(
            workspace_id=workspace_id,
            agent_id=agent_id,
            agent_session_id=agent_session_id,
        )

    async def update_binding_response_mode(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        workspace_user_id: str,
        user_id: str,
        agent_session_id: str,
        binding_id: str,
        setting: ExternalChannelResponseModeSetting,
    ) -> ManagedBinding:
        """Replace one connected binding's concrete response mode."""
        await self._require_agent(
            workspace_id=workspace_id,
            agent_id=agent_id,
            workspace_user_id=workspace_user_id,
            admin=True,
        )
        scope = await self.operation_repository.get_binding_mutation_scope(
            workspace_id=workspace_id,
            agent_id=agent_id,
            agent_session_id=agent_session_id,
            binding_id=binding_id,
        )
        if scope is None:
            raise ExternalChannelManagementNotFound(binding_id)
        if scope.resource_type is ExternalChannelResourceType.PARENT_CHANNEL:
            now = datetime.datetime.now(datetime.UTC)
            deadline = ExternalChannelOperationDeadline(
                now + datetime.timedelta(seconds=30)
            )
            conversation_scope = ExternalChannelConversationScope(
                connection_id=scope.connection_id,
                kind=ExternalChannelConversationScopeKind.PARENT_CHANNEL,
                provider_channel_id=scope.provider_parent_channel_id,
                provider_thread_key=None,
            )
            participation_scope = ExternalChannelParticipationScope(
                connection_id=scope.connection_id,
                provider_parent_channel_id=scope.provider_parent_channel_id,
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
                    await self.operation_repository.update_binding_response_mode(
                        workspace_id=workspace_id,
                        agent_id=agent_id,
                        agent_session_id=agent_session_id,
                        binding_id=binding_id,
                        user_id=user_id,
                        response_mode=setting.response_mode,
                    )
        else:
            await self.operation_repository.update_binding_response_mode(
                workspace_id=workspace_id,
                agent_id=agent_id,
                agent_session_id=agent_session_id,
                binding_id=binding_id,
                user_id=user_id,
                response_mode=setting.response_mode,
            )
        bindings = await self.list_bindings(
            workspace_id=workspace_id,
            agent_id=agent_id,
            agent_session_id=agent_session_id,
        )
        for binding in bindings:
            if binding.id == binding_id:
                return binding
        raise ExternalChannelManagementNotFound(binding_id)

    async def list_agent_access(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        workspace_user_id: str,
    ) -> ManagedAgentAccess:
        return await self.operation_repository.list_agent_access(
            workspace_id=workspace_id,
            agent_id=agent_id,
            workspace_user_id=workspace_user_id,
        )

    async def list_session_grants(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        workspace_user_id: str,
        agent_session_id: str,
    ) -> list[ManagedGrant]:
        return await self.operation_repository.list_session_grants(
            workspace_id=workspace_id,
            agent_id=agent_id,
            workspace_user_id=workspace_user_id,
            agent_session_id=agent_session_id,
        )

    async def revoke_grant(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        workspace_user_id: str,
        user_id: str,
        grant_id: str,
    ) -> None:
        await self._require_agent(
            workspace_id=workspace_id,
            agent_id=agent_id,
            workspace_user_id=workspace_user_id,
            admin=True,
        )
        await self.operation_repository.require_owned_grant(
            agent_id=agent_id, grant_id=grant_id
        )
        await self.access_service.revoke_grant(
            grant_id=grant_id,
        )

    async def remove_block(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        workspace_user_id: str,
        user_id: str,
        block_id: str,
    ) -> None:
        await self._require_agent(
            workspace_id=workspace_id,
            agent_id=agent_id,
            workspace_user_id=workspace_user_id,
            admin=True,
        )
        await self.operation_repository.require_owned_block(
            agent_id=agent_id, block_id=block_id
        )
        await self.access_service.remove_block(
            block_id=block_id,
            removed_by_user_id=user_id,
            now=datetime.datetime.now(datetime.UTC),
        )

    async def get_approval(
        self,
        *,
        access_request_id: str,
        user_id: str,
    ) -> ManagedApprovalRequest:
        return await self.operation_repository.get_approval(
            access_request_id=access_request_id, user_id=user_id
        )

    async def decide_approval(
        self,
        *,
        access_request_id: str,
        user_id: str,
        decision: ExternalChannelDecisionInput,
    ) -> ManagedApprovalRequest:
        await self.get_approval(access_request_id=access_request_id, user_id=user_id)
        now = datetime.datetime.now(datetime.UTC)
        if decision.decision == "allow_session":
            result = await self.access_service.allow(
                access_request_id=access_request_id,
                scope=ExternalChannelAccessGrantScope.SESSION,
                decided_by_user_id=user_id,
                decision_summary=decision.summary,
                now=now,
            )
        elif decision.decision == "allow_agent":
            result = await self.access_service.allow(
                access_request_id=access_request_id,
                scope=ExternalChannelAccessGrantScope.AGENT,
                decided_by_user_id=user_id,
                decision_summary=decision.summary,
                now=now,
            )
        elif decision.decision == "deny":
            result = await self.access_service.deny(
                access_request_id=access_request_id,
                decided_by_user_id=user_id,
                decision_summary=decision.summary,
                now=now,
            )
        else:
            result = await self.access_service.block(
                access_request_id=access_request_id,
                decided_by_user_id=user_id,
                decision_summary=decision.summary,
                now=now,
            )
        if result.control_delete_plan is not None:
            await self.action_service.execute_direct_control(result.control_delete_plan)
        return await self.get_approval(
            access_request_id=access_request_id,
            user_id=user_id,
        )

    async def _require_owned_connection(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        workspace_user_id: str,
        connection_id: str,
    ) -> None:
        return await self.operation_repository.require_owned_connection(
            workspace_id=workspace_id,
            agent_id=agent_id,
            workspace_user_id=workspace_user_id,
            connection_id=connection_id,
        )

    async def _require_agent(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        workspace_user_id: str,
        admin: bool,
    ) -> Agent:
        return await self.operation_repository.require_agent(
            workspace_id=workspace_id,
            agent_id=agent_id,
            workspace_user_id=workspace_user_id,
            admin=admin,
        )


def _managed_multi_disconnect(
    disconnected: ExternalChannelMultiConnectionDisconnect,
) -> ManagedMultiConnectionDisconnect:
    return ManagedMultiConnectionDisconnect(
        disconnected_route_count=disconnected.disconnected_route_count,
        invalidated_default_count=disconnected.invalidated_default_count,
        invalidated_participation_setting_count=(
            disconnected.invalidated_participation_setting_count
        ),
        terminated_setup_claim_count=disconnected.terminated_setup_claim_count,
        expired_admission_count=disconnected.expired_admission_count,
        expired_access_request_count=disconnected.expired_access_request_count,
        unavailable_resource_count=disconnected.unavailable_resource_count,
        disconnected_binding_count=disconnected.disconnected_binding_count,
    )


def _managed_channel_default_mutation(
    transition: ExternalChannelChannelDefaultTransition,
) -> ManagedChannelDefaultMutation:
    """Project one committed selected-Agent transition without intent identifiers."""
    return ManagedChannelDefaultMutation(
        channel_default=transition.channel_default,
        changed=transition.changed,
        invalidated_participation_setting_count=transition.invalidated_setting_count,
        terminated_setup_claim_count=transition.terminated_setup_claim_count,
        expired_interaction_count=transition.expired_interaction_count,
        disconnected_parent_binding_count=(
            transition.disconnected_parent_binding_count
        ),
        direct_cleanup_count=len(transition.cleanup_plans),
    )


def slack_manifest_guidance(
    transport: ExternalChannelTransport,
    *,
    callback_url: str,
    app_name: str,
) -> SlackManifestGuidance:
    """Return a copy-ready Slack App Manifest and setup metadata."""
    bot_scopes = (*SLACK_REQUIRED_BOT_SCOPES, *SLACK_OPTIONAL_FILE_BOT_SCOPES)
    event_subscriptions = (
        "app_mention",
        "message.channels",
        "message.groups",
        "app_uninstalled",
        "tokens_revoked",
    )
    normalized_name = app_name.strip() or "Azents Agent"
    bot_name = re.sub(r"[^a-z0-9_-]+", "-", normalized_name.casefold()).strip("-")
    bot_name = (bot_name or "azents-agent")[:80]
    event_settings: dict[str, object] = {
        "bot_events": list(event_subscriptions),
    }
    if transport is ExternalChannelTransport.HTTP:
        event_settings["request_url"] = callback_url
    slash_command: dict[str, object] = {
        "command": SLACK_AZENTS_COMMAND,
        "description": "Open Azents conversation settings",
        "usage_hint": "settings",
        "should_escape": False,
    }
    interactivity: dict[str, object] = {"is_enabled": True}
    if transport is ExternalChannelTransport.HTTP:
        slash_command["url"] = callback_url
        interactivity["request_url"] = callback_url
    settings: dict[str, object] = {
        "event_subscriptions": event_settings,
        "interactivity": interactivity,
        "org_deploy_enabled": False,
        "socket_mode_enabled": transport is ExternalChannelTransport.SOCKET,
        "token_rotation_enabled": False,
    }
    manifest: dict[str, object] = {
        "display_information": {
            "name": normalized_name[:35],
            "description": f"{normalized_name[:60]} powered by Azents",
        },
        "features": {
            "agent_view": {
                "agent_description": (f"{normalized_name[:240]} powered by Azents"),
            },
            "app_home": {
                "home_tab_enabled": False,
                "messages_tab_enabled": True,
                "messages_tab_read_only_enabled": True,
            },
            "bot_user": {
                "display_name": bot_name,
                "always_online": False,
            },
            "slash_commands": [slash_command],
            "shortcuts": [
                {
                    "name": "Ask an Azents Agent",
                    "type": "message",
                    "callback_id": SLACK_INVOCATION_SHORTCUT_CALLBACK_ID,
                    "description": "Ask an Azents Agent about this message",
                },
                {
                    "name": "Conversation settings",
                    "type": "message",
                    "callback_id": SLACK_SETTINGS_SHORTCUT_CALLBACK_ID,
                    "description": "View or change Azents conversation settings",
                },
            ],
        },
        "oauth_config": {"scopes": {"bot": list(bot_scopes)}},
        "settings": settings,
    }
    return SlackManifestGuidance(
        transport=transport,
        bot_scopes=bot_scopes,
        event_subscriptions=event_subscriptions,
        socket_mode_enabled=transport is ExternalChannelTransport.SOCKET,
        app_token_scope=(
            "connections:write"
            if transport is ExternalChannelTransport.SOCKET
            else None
        ),
        callback_url=(
            callback_url if transport is ExternalChannelTransport.HTTP else None
        ),
        manifest=manifest,
        manifest_json=json.dumps(manifest, indent=2),
    )
