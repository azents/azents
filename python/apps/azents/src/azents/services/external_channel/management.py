"""Authorized provider-neutral External Channel management operations."""

import datetime
import json
import re
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelAccessGrantScope,
    ExternalChannelAppMode,
    ExternalChannelConversationScopeKind,
    ExternalChannelIngressProfile,
    ExternalChannelProvider,
    ExternalChannelResourceType,
    ExternalChannelResponseMode,
    ExternalChannelRouteCatalogStatus,
    ExternalChannelRouteMode,
    ExternalChannelTransport,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.models.external_channel import RDBExternalChannelConnection
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.external_channel.data import (
    ExternalChannelAgentRouteCreate,
    ExternalChannelMultiConnectionDisconnect,
    ExternalChannelMultiConnectionImpact,
    ExternalChannelMultiRouteImpact,
)
from azents.repos.external_channel.lifecycle import (
    ExternalChannelLifecycleRepository,
)
from azents.repos.external_channel.management import (
    ExternalChannelChannelDefaultTransition,
    ExternalChannelManagementRepository,
)
from azents.repos.external_channel.management_data import (
    ManagedApprovalRequest,
    ManagedBinding,
    ManagedBlock,
    ManagedChannelDefault,
    ManagedChannelDefaultMutation,
    ManagedConnection,
    ManagedGrant,
    ManagedMultiConnection,
    ManagedMultiConnectionDisconnect,
    ManagedMultiRoute,
    ManagedSlackManagementHandoff,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.workspace_user import WorkspaceUserRepository
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
from azents.services.external_channel.data import (
    DiscordConnectionConfiguration,
    DiscordConnectionCredentials,
    DiscordThreadAutoArchiveDurationMinutes,
    ExternalChannelConnectionCredentialPayload,
    ExternalChannelConnectionStatusSnapshot,
    SlackConnectionCredentials,
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


class ExternalChannelManagementNotFound(LookupError):
    """A management resource is unavailable to the caller."""


class ExternalChannelManagementGenerationChanged(RuntimeError):
    """A destructive management request observed a newer Multi App generation."""


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


@dataclass
class ExternalChannelManagementService:
    """Authorize and orchestrate External Channel management boundaries."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    repository: Annotated[
        ExternalChannelManagementRepository,
        Depends(ExternalChannelManagementRepository.create),
    ]
    domain_repository: Annotated[
        ExternalChannelRepository,
        Depends(ExternalChannelRepository.create),
    ]
    lifecycle_repository: Annotated[
        ExternalChannelLifecycleRepository,
        Depends(ExternalChannelLifecycleRepository.create),
    ]
    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    agent_admin_repository: Annotated[
        AgentAdminRepository,
        Depends(AgentAdminRepository),
    ]
    workspace_user_repository: Annotated[
        WorkspaceUserRepository,
        Depends(WorkspaceUserRepository),
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
        await self._require_agent(
            workspace_id=workspace_id,
            agent_id=agent_id,
            workspace_user_id=workspace_user_id,
            admin=False,
        )
        async with self.session_manager() as session:
            return await self.repository.list_connections(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
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
        await self._require_agent(
            workspace_id=workspace_id,
            agent_id=agent_id,
            workspace_user_id=workspace_user_id,
            admin=True,
        )
        async with self.session_manager() as session:
            update_default = (
                self.agent_repository.update_external_channel_default_response_mode
            )
            agent = await update_default(
                session,
                agent_id=agent_id,
                response_mode=setting.response_mode,
            )
            if agent is None or agent.workspace_id != workspace_id:
                raise ExternalChannelManagementNotFound(agent_id)
            await session.commit()
        return ExternalChannelResponseModeSetting(
            response_mode=agent.external_channel_default_response_mode
        )

    async def list_agent_multi_connections(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        workspace_user_id: str,
    ) -> list[ManagedMultiConnection]:
        """List read-only Multi Apps associated with one visible Agent."""
        await self._require_agent(
            workspace_id=workspace_id,
            agent_id=agent_id,
            workspace_user_id=workspace_user_id,
            admin=False,
        )
        async with self.session_manager() as session:
            return await self.repository.list_agent_multi_connections(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
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
        async with self.session_manager() as session:
            await self.domain_repository.create_agent_route(
                session,
                ExternalChannelAgentRouteCreate(
                    connection_id=setup.connection.id,
                    agent_id=agent_id,
                    agent_id_snapshot=agent_id,
                    route_mode=ExternalChannelRouteMode.DEDICATED,
                    connection_app_mode=ExternalChannelAppMode.SINGLE,
                    catalog_status=ExternalChannelRouteCatalogStatus.AVAILABLE,
                    catalog_removed_at=None,
                    catalog_removed_by_user_id=None,
                ),
            )
            await session.commit()
        await self.connection_service.validate_connection(
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
        async with self.session_manager() as session:
            await self.domain_repository.create_agent_route(
                session,
                ExternalChannelAgentRouteCreate(
                    connection_id=setup.connection.id,
                    agent_id=agent_id,
                    agent_id_snapshot=agent_id,
                    route_mode=ExternalChannelRouteMode.DEDICATED,
                    connection_app_mode=ExternalChannelAppMode.SINGLE,
                    catalog_status=ExternalChannelRouteCatalogStatus.AVAILABLE,
                    catalog_removed_at=None,
                    catalog_removed_by_user_id=None,
                ),
            )
            await session.commit()
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
        async with self.session_manager() as session:
            return await self.repository.list_multi_connections(
                session,
                workspace_id=workspace_id,
                provider=provider,
                offset=offset,
                limit=limit,
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
        async with self.session_manager() as session:
            connection = await self.repository.get_managed_multi_connection(
                session,
                workspace_id=workspace_id,
                connection_id=connection_id,
                provider=provider,
                include_disconnected=include_disconnected,
            )
        if connection is None:
            raise ExternalChannelManagementNotFound(connection_id)
        return connection

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
            connection_id=setup.connection.id
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
            connection_id=connection_id
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
        async with self.session_manager() as session:
            connection = await self.repository.replace_multi_slack_configuration(
                session,
                workspace_id=workspace_id,
                connection_id=connection_id,
                provider_app_id=app_id,
                transport=transport,
                encrypted_credentials=encrypted,
            )
            if connection is None:
                raise ExternalChannelManagementNotFound(connection_id)
            await session.commit()
        return await self.connection_service.validate_connection(
            connection_id=connection_id
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
        async with self.session_manager() as session:
            connection = await self.repository.replace_multi_discord_configuration(
                session,
                workspace_id=workspace_id,
                connection_id=connection_id,
                provider_app_id=app_id,
                encrypted_credentials=encrypted,
                provider_config=configuration.model_dump(mode="json"),
            )
            if connection is None:
                raise ExternalChannelManagementNotFound(connection_id)
            await session.commit()
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
        async with self.session_manager() as session:
            connection = await self._lock_multi_connection_generation(
                session,
                workspace_id=workspace_id,
                connection_id=connection_id,
                provider=ExternalChannelProvider.DISCORD,
                expected_generation=expected_generation,
            )
            managed = (
                await self.repository.update_multi_discord_thread_auto_archive_duration(
                    session,
                    connection=connection,
                    duration=setting.thread_auto_archive_duration_minutes,
                )
            )
            if managed is None:
                raise ExternalChannelManagementNotFound(connection_id)
            await session.commit()
        return managed

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
        async with self.session_manager() as session:
            routes = await self.repository.list_multi_routes(
                session,
                workspace_id=workspace_id,
                connection_id=connection_id,
                provider=provider,
                offset=offset,
                limit=limit,
            )
        if routes is None:
            raise ExternalChannelManagementNotFound(connection_id)
        return routes

    async def add_multi_route(
        self,
        *,
        workspace_id: str,
        connection_id: str,
        provider: ExternalChannelProvider,
        agent_id: str,
    ) -> ManagedMultiRoute:
        """Add one active Workspace Agent to a Multi App catalog."""
        now = datetime.datetime.now(datetime.UTC)
        async with self.session_manager() as session:
            connection = await self.repository.get_multi_connection(
                session,
                workspace_id=workspace_id,
                connection_id=connection_id,
                provider=provider,
                lock=True,
            )
            agent = await self.agent_repository.get_by_id(session, agent_id)
            if (
                connection is None
                or agent is None
                or agent.workspace_id != workspace_id
            ):
                raise ExternalChannelManagementNotFound(connection_id)
            existing = await self.repository.get_multi_route_by_agent(
                session,
                workspace_id=workspace_id,
                connection_id=connection.id,
                provider=provider,
                agent_id=agent_id,
            )
            if existing is not None:
                if (
                    existing.catalog_status
                    is ExternalChannelRouteCatalogStatus.AVAILABLE
                    and existing.agent_id == agent_id
                ):
                    return existing
                raise ValueError(
                    "Removed Multi App Agent associations must be re-enabled."
                )
            route = await self.domain_repository.create_agent_route(
                session,
                ExternalChannelAgentRouteCreate(
                    connection_id=connection.id,
                    agent_id=agent_id,
                    agent_id_snapshot=agent_id,
                    route_mode=ExternalChannelRouteMode.DEDICATED,
                    connection_app_mode=ExternalChannelAppMode.MULTI,
                    catalog_status=ExternalChannelRouteCatalogStatus.AVAILABLE,
                    catalog_removed_at=None,
                    catalog_removed_by_user_id=None,
                ),
            )
            connection.updated_at = now
            await session.commit()
            managed = await self.repository.get_multi_route(
                session,
                workspace_id=workspace_id,
                connection_id=connection_id,
                provider=provider,
                route_id=route.id,
            )
        if managed is None:
            raise ExternalChannelManagementNotFound(connection_id)
        return managed

    async def get_multi_route_impact(
        self,
        *,
        workspace_id: str,
        connection_id: str,
        provider: ExternalChannelProvider,
        route_id: str,
    ) -> ExternalChannelMultiRouteImpact:
        """Return a sanitized count-only removal impact preview."""
        async with self.session_manager() as session:
            connection = await self.repository.get_multi_connection(
                session,
                workspace_id=workspace_id,
                connection_id=connection_id,
                provider=provider,
                include_disconnected=True,
            )
            if connection is None:
                raise ExternalChannelManagementNotFound(connection_id)
            impact = await self.lifecycle_repository.project_multi_route_impact(
                session,
                connection_id=connection_id,
                route_id=route_id,
            )
        if impact is None:
            raise ExternalChannelManagementNotFound(route_id)
        return impact

    async def get_multi_connection_impact(
        self,
        *,
        workspace_id: str,
        connection_id: str,
        provider: ExternalChannelProvider,
    ) -> ExternalChannelMultiConnectionImpact:
        """Return sanitized impact before disconnecting one whole Multi App."""
        async with self.session_manager() as session:
            connection = await self.repository.get_multi_connection(
                session,
                workspace_id=workspace_id,
                connection_id=connection_id,
                provider=provider,
            )
            if connection is None:
                raise ExternalChannelManagementNotFound(connection_id)
            impact = await self.lifecycle_repository.project_multi_connection_impact(
                session,
                connection_id=connection.id,
            )
        if impact is None:
            raise ExternalChannelManagementNotFound(connection_id)
        return impact

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
        now = datetime.datetime.now(datetime.UTC)
        async with self.session_manager() as session:
            connection = await self._lock_multi_connection_generation(
                session,
                workspace_id=workspace_id,
                connection_id=connection_id,
                provider=provider,
                expected_generation=expected_generation,
                include_disconnected=True,
            )
            removal = await self.lifecycle_repository.remove_multi_route(
                session,
                connection_id=connection.id,
                route_id=route_id,
                removed_by_user_id=user_id,
                now=now,
            )
            if removal is None:
                raise ExternalChannelManagementNotFound(route_id)
            connection.updated_at = now
            await session.commit()
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
        now = datetime.datetime.now(datetime.UTC)
        async with self.session_manager() as session:
            connection = await self.repository.get_multi_connection(
                session,
                workspace_id=workspace_id,
                connection_id=connection_id,
                provider=provider,
                lock=True,
            )
            if connection is None:
                raise ExternalChannelManagementNotFound(connection_id)
            if not await self.lifecycle_repository.reenable_multi_route(
                session,
                connection_id=connection_id,
                route_id=route_id,
            ):
                raise ExternalChannelManagementNotFound(route_id)
            connection.updated_at = now
            await session.commit()
            route = await self.repository.get_multi_route(
                session,
                workspace_id=workspace_id,
                connection_id=connection_id,
                provider=provider,
                route_id=route_id,
            )
        if route is None:
            raise ExternalChannelManagementNotFound(route_id)
        return route

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
        async with self.session_manager() as session:
            defaults = await self.repository.list_multi_channel_defaults(
                session,
                workspace_id=workspace_id,
                connection_id=connection_id,
                provider=provider,
                offset=offset,
                limit=limit,
            )
        if defaults is None:
            raise ExternalChannelManagementNotFound(connection_id)
        return defaults

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
                async with self.session_manager() as session:
                    connection = await self._lock_multi_connection_generation(
                        session,
                        workspace_id=workspace_id,
                        connection_id=connection_id,
                        provider=provider,
                        expected_generation=expected_generation,
                    )
                    transition = await self.repository.replace_multi_channel_default(
                        session,
                        workspace_id=workspace_id,
                        connection_id=connection.id,
                        provider=provider,
                        provider_channel_id=provider_channel_id,
                        route_id=route_id,
                        configured_by_user_id=user_id,
                        now=now,
                    )
                    if transition is None or transition.channel_default is None:
                        raise ExternalChannelManagementNotFound(route_id)
                    if transition.changed:
                        connection.updated_at = now
                    await session.commit()
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
                async with self.session_manager() as session:
                    connection = await self._lock_multi_connection_generation(
                        session,
                        workspace_id=workspace_id,
                        connection_id=connection_id,
                        provider=provider,
                        expected_generation=expected_generation,
                    )
                    transition = await self.repository.clear_multi_channel_default(
                        session,
                        workspace_id=workspace_id,
                        connection_id=connection.id,
                        provider=provider,
                        provider_channel_id=provider_channel_id,
                        now=now,
                    )
                    if transition is None:
                        raise ExternalChannelManagementNotFound(provider_channel_id)
                    connection.updated_at = now
                    await session.commit()
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
        now = datetime.datetime.now(datetime.UTC)
        cleanup_plans = ()
        async with self.session_manager() as session:
            connection = await self._lock_multi_connection_generation(
                session,
                workspace_id=workspace_id,
                connection_id=connection_id,
                provider=provider,
                expected_generation=expected_generation,
                include_disconnected=True,
            )
            disconnected = await self.lifecycle_repository.disconnect_multi_connection(
                session,
                connection_id=connection.id,
                now=now,
                reason="manager_disconnected",
                defer_provider_state_purge=True,
            )
            if disconnected is None:
                raise ExternalChannelManagementNotFound(connection_id)
            cleanup_plans = disconnected.cleanup_plans
            await (
                self.lifecycle_repository.purge_disconnected_connection_provider_state(
                    session,
                    connection_ids=[connection.id],
                )
            )
            connection.updated_at = now
            await session.commit()
        for plan in cleanup_plans:
            await self.action_service.execute_terminal_control(plan)
        return _managed_multi_disconnect(disconnected)

    async def load_multi_management_handoff(
        self,
        *,
        workspace_id: str,
        interaction_id: str,
    ) -> ManagedSlackManagementHandoff:
        """Load one opaque Slack management handoff after Workspace authorization."""
        now = datetime.datetime.now(datetime.UTC)
        async with self.session_manager() as session:
            handoff = await self.repository.load_multi_management_handoff(
                session,
                workspace_id=workspace_id,
                interaction_id=interaction_id,
                now=now,
            )
        if handoff is None:
            raise ExternalChannelManagementNotFound(interaction_id)
        return handoff

    async def validate_connection(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        workspace_user_id: str,
        connection_id: str,
    ) -> ExternalChannelConnectionStatusSnapshot:
        await self._require_owned_connection(
            workspace_id=workspace_id,
            agent_id=agent_id,
            workspace_user_id=workspace_user_id,
            connection_id=connection_id,
        )
        async with self.session_manager() as session:
            connection = await self.domain_repository.get_connection(
                session,
                connection_id=connection_id,
            )
        if connection is None:
            raise ExternalChannelManagementNotFound(connection_id)
        if connection.provider is ExternalChannelProvider.DISCORD:
            return await self.discord_activation_service.activate(
                connection_id=connection_id
            )
        return await self.connection_service.validate_connection(
            connection_id=connection_id
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
        async with self.session_manager() as session:
            connection = await self.repository.replace_slack_configuration(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                connection_id=connection_id,
                provider_app_id=app_id,
                transport=transport,
                encrypted_credentials=encrypted,
            )
            if connection is None:
                raise ExternalChannelManagementNotFound(connection_id)
            await session.commit()
        return await self.connection_service.validate_connection(
            connection_id=connection_id
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
        async with self.session_manager() as session:
            connection = await self.repository.replace_discord_configuration(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                connection_id=connection_id,
                provider_app_id=app_id,
                encrypted_credentials=encrypted,
                provider_config=configuration.model_dump(mode="json"),
            )
            if connection is None:
                raise ExternalChannelManagementNotFound(connection_id)
            await session.commit()
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
        await self._require_owned_connection(
            workspace_id=workspace_id,
            agent_id=agent_id,
            workspace_user_id=workspace_user_id,
            connection_id=connection_id,
        )
        async with self.session_manager() as session:
            connection = (
                await self.repository.update_discord_thread_auto_archive_duration(
                    session,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    connection_id=connection_id,
                    duration=setting.thread_auto_archive_duration_minutes,
                )
            )
            if connection is None:
                raise ExternalChannelManagementNotFound(connection_id)
            await session.commit()
        return connection

    async def disconnect_connection(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        workspace_user_id: str,
        connection_id: str,
    ) -> ManagedConnection:
        await self._require_agent(
            workspace_id=workspace_id,
            agent_id=agent_id,
            workspace_user_id=workspace_user_id,
            admin=True,
        )
        now = datetime.datetime.now(datetime.UTC)
        async with self.session_manager() as session:
            cleanup_plans = await self.repository.begin_connection_disconnect(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                connection_id=connection_id,
                now=now,
            )
            if cleanup_plans is None:
                raise ExternalChannelManagementNotFound(connection_id)
            await session.commit()
        async with self.session_manager() as session:
            disconnected = await self.lifecycle_repository.disconnect_single_connection(
                session,
                connection_id=connection_id,
                now=datetime.datetime.now(datetime.UTC),
                reason="manager_disconnected",
            )
            if disconnected is None:
                raise ExternalChannelManagementNotFound(connection_id)
            connection = await self.repository.complete_connection_disconnect(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                connection_id=connection_id,
                now=datetime.datetime.now(datetime.UTC),
            )
            if connection is None:
                raise ExternalChannelManagementNotFound(connection_id)
            await session.commit()
        for plan in cleanup_plans:
            await self.action_service.execute_terminal_control(plan)
        return connection

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
        await self._require_owned_connection(
            workspace_id=workspace_id,
            agent_id=agent_id,
            workspace_user_id=workspace_user_id,
            connection_id=connection_id,
        )
        async with self.session_manager() as session:
            connection = await self.repository.update_connection_access_policy(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                connection_id=connection_id,
                open_access_enabled=policy.open_access_enabled,
            )
            if connection is None:
                raise ExternalChannelManagementNotFound(connection_id)
            await session.commit()
        return connection

    async def list_bindings(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        agent_session_id: str,
    ) -> list[ManagedBinding]:
        async with self.session_manager() as session:
            return await self.repository.list_bindings(
                session,
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
        async with self.session_manager() as session:
            cleanup_plans = await self.repository.disconnect_binding(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                agent_session_id=agent_session_id,
                binding_id=binding_id,
                now=datetime.datetime.now(datetime.UTC),
                reason="manager_disconnected",
            )
            if cleanup_plans is None:
                raise ExternalChannelManagementNotFound(binding_id)
            await session.commit()
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
        async with self.session_manager() as session:
            scope = await self.repository.get_binding_mutation_scope(
                session,
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
                    async with self.session_manager() as session:
                        updated = await self.repository.update_binding_response_mode(
                            session,
                            workspace_id=workspace_id,
                            agent_id=agent_id,
                            agent_session_id=agent_session_id,
                            binding_id=binding_id,
                            configured_by_user_id=user_id,
                            response_mode=setting.response_mode,
                        )
                        if not updated:
                            raise ExternalChannelManagementNotFound(binding_id)
                        await session.commit()
        else:
            async with self.session_manager() as session:
                updated = await self.repository.update_binding_response_mode(
                    session,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    agent_session_id=agent_session_id,
                    binding_id=binding_id,
                    configured_by_user_id=user_id,
                    response_mode=setting.response_mode,
                )
                if not updated:
                    raise ExternalChannelManagementNotFound(binding_id)
                await session.commit()
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
    ) -> tuple[list[ManagedGrant], list[ManagedBlock]]:
        await self._require_agent(
            workspace_id=workspace_id,
            agent_id=agent_id,
            workspace_user_id=workspace_user_id,
            admin=False,
        )
        async with self.session_manager() as session:
            return (
                await self.repository.list_grants(
                    session,
                    agent_id=agent_id,
                    agent_session_id=None,
                ),
                await self.repository.list_blocks(session, agent_id=agent_id),
            )

    async def list_session_grants(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        workspace_user_id: str,
        agent_session_id: str,
    ) -> list[ManagedGrant]:
        await self._require_agent(
            workspace_id=workspace_id,
            agent_id=agent_id,
            workspace_user_id=workspace_user_id,
            admin=False,
        )
        async with self.session_manager() as session:
            return await self.repository.list_grants(
                session,
                agent_id=agent_id,
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
        async with self.session_manager() as session:
            owned = await self.repository.grant_belongs_to_agent(
                session,
                agent_id=agent_id,
                grant_id=grant_id,
            )
        if not owned:
            raise ExternalChannelManagementNotFound(grant_id)
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
        async with self.session_manager() as session:
            owned = await self.repository.block_belongs_to_agent(
                session,
                agent_id=agent_id,
                block_id=block_id,
            )
        if not owned:
            raise ExternalChannelManagementNotFound(block_id)
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
        async with self.session_manager() as session:
            request = await self.repository.get_approval_request(
                session,
                access_request_id=access_request_id,
            )
            if request is None:
                raise ExternalChannelManagementNotFound(access_request_id)
            member = await self.workspace_user_repository.get_by_workspace_and_user(
                session,
                request.workspace_id,
                user_id,
            )
            if member is None or not await self.agent_admin_repository.is_admin(
                session,
                request.agent_id,
                member.id,
            ):
                raise ExternalChannelManagementNotFound(access_request_id)
            return request

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

    async def _lock_multi_connection_generation(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        connection_id: str,
        provider: ExternalChannelProvider,
        expected_generation: datetime.datetime,
        include_disconnected: bool = False,
    ) -> RDBExternalChannelConnection:
        """Lock one Multi App and reject a stale destructive mutation."""
        connection = await self.repository.get_multi_connection(
            session,
            workspace_id=workspace_id,
            connection_id=connection_id,
            provider=provider,
            lock=True,
            include_disconnected=include_disconnected,
        )
        if connection is None:
            raise ExternalChannelManagementNotFound(connection_id)
        if connection.updated_at != expected_generation:
            raise ExternalChannelManagementGenerationChanged(
                "The Multi App changed. Reload it before retrying the operation."
            )
        return connection

    async def _require_owned_connection(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        workspace_user_id: str,
        connection_id: str,
    ) -> None:
        await self._require_agent(
            workspace_id=workspace_id,
            agent_id=agent_id,
            workspace_user_id=workspace_user_id,
            admin=True,
        )
        async with self.session_manager() as session:
            if (
                await self.repository.get_connection(
                    session,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    connection_id=connection_id,
                )
                is None
            ):
                raise ExternalChannelManagementNotFound(connection_id)

    async def _require_agent(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        workspace_user_id: str,
        admin: bool,
    ) -> Agent:
        async with self.session_manager() as session:
            agent = await self.agent_repository.get_by_id(session, agent_id)
            if agent is None or agent.workspace_id != workspace_id:
                raise ExternalChannelManagementNotFound(agent_id)
            if admin and not await self.agent_admin_repository.is_admin(
                session,
                agent_id,
                workspace_user_id,
            ):
                raise ExternalChannelManagementNotFound(agent_id)
            return agent


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
