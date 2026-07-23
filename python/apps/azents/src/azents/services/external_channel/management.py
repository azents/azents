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
    ExternalChannelRouteMode,
    ExternalChannelTransport,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.external_channel.data import ExternalChannelAgentRouteCreate
from azents.repos.external_channel.management import (
    ExternalChannelManagementRepository,
)
from azents.repos.external_channel.management_data import (
    ManagedApprovalRequest,
    ManagedBinding,
    ManagedBlock,
    ManagedConnection,
    ManagedGrant,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.services.external_channel.access import ExternalChannelAccessService
from azents.services.external_channel.channel_action import ExternalChannelActionService
from azents.services.external_channel.connection import (
    ExternalChannelConnectionService,
)
from azents.services.external_channel.data import (
    ExternalChannelConnectionCredentialPayload,
    ExternalChannelConnectionStatusSnapshot,
    SlackConnectionCredentials,
)
from azents.services.external_channel.provider import (
    SlackExternalChannelProviderContract,
)
from azents.services.external_channel.slack_http import (
    SLACK_OPTIONAL_FILE_BOT_SCOPES,
    SLACK_REQUIRED_BOT_SCOPES,
)


class ExternalChannelManagementNotFound(LookupError):
    """A management resource is unavailable to the caller."""


class ManagedConnectionSetup(BaseModel):
    model_config = ConfigDict(frozen=True)

    connection: ManagedConnection


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


@dataclass
class ExternalChannelManagementService:
    """Authorize and orchestrate External Channel management boundaries."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    repository: Annotated[
        ExternalChannelManagementRepository,
        Depends(ExternalChannelManagementRepository),
    ]
    domain_repository: Annotated[
        ExternalChannelRepository,
        Depends(ExternalChannelRepository),
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
    action_service: Annotated[
        ExternalChannelActionService,
        Depends(ExternalChannelActionService),
    ]
    access_service: Annotated[
        ExternalChannelAccessService,
        Depends(ExternalChannelAccessService),
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
                    route_mode=ExternalChannelRouteMode.DEDICATED,
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

    async def disconnect_connection(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        workspace_user_id: str,
        connection_id: str,
    ) -> ManagedConnection:
        await self._require_owned_connection(
            workspace_id=workspace_id,
            agent_id=agent_id,
            workspace_user_id=workspace_user_id,
            connection_id=connection_id,
        )
        now = datetime.datetime.now(datetime.UTC)
        async with self.session_manager() as session:
            cleanup_ids = await self.repository.begin_connection_disconnect(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                connection_id=connection_id,
                now=now,
            )
            if cleanup_ids is None:
                raise ExternalChannelManagementNotFound(connection_id)
            await session.commit()
        cleanup_targets = []
        for cleanup_id in cleanup_ids:
            target = await self.action_service.prepare_delivery(cleanup_id)
            if target is not None:
                cleanup_targets.append(target)
        async with self.session_manager() as session:
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
        for target in cleanup_targets:
            await self.action_service.attempt_prepared_delivery(target)
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
            cleanup_ids = await self.repository.disconnect_binding(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                agent_session_id=agent_session_id,
                binding_id=binding_id,
                now=datetime.datetime.now(datetime.UTC),
                reason="manager_disconnected",
            )
            if cleanup_ids is None:
                raise ExternalChannelManagementNotFound(binding_id)
            await session.commit()
        for cleanup_id in cleanup_ids:
            await self.action_service.attempt_delivery(cleanup_id)
        return await self.list_bindings(
            workspace_id=workspace_id,
            agent_id=agent_id,
            agent_session_id=agent_session_id,
        )

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
        if result.control_delete_delivery_id is not None:
            await self.action_service.attempt_delivery(
                result.control_delete_delivery_id
            )
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
    ) -> None:
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
    settings: dict[str, object] = {
        "event_subscriptions": event_settings,
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
            }
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
