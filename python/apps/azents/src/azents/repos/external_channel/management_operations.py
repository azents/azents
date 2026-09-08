"""Completed DB-only External Channel management operations."""

import datetime
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelProvider,
    ExternalChannelResponseMode,
    ExternalChannelRouteCatalogStatus,
    ExternalChannelRouteMode,
    ExternalChannelTransport,
)
from azents.core.external_channel_provider import (
    DiscordThreadAutoArchiveDurationMinutes,
)
from azents.core.external_channel_provider_effect import ProviderEffectPlan
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
    ExternalChannelMultiRouteRemoval,
)
from azents.repos.external_channel.lifecycle import ExternalChannelLifecycleRepository
from azents.repos.external_channel.management import (
    ExternalChannelBindingMutationScope,
    ExternalChannelChannelDefaultTransition,
    ExternalChannelManagementRepository,
)
from azents.repos.external_channel.management_data import (
    ManagedApprovalRequest,
    ManagedBinding,
    ManagedChannelDefault,
    ManagedConnection,
    ManagedGrant,
    ManagedMultiConnection,
    ManagedMultiRoute,
    ManagedSlackManagementHandoff,
)
from azents.repos.external_channel.management_operation_data import (
    ExternalChannelManagementGenerationChanged,
    ExternalChannelManagementNotFound,
    ManagedAgentAccess,
    ManagedConnectionDisconnectResult,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.workspace_user import WorkspaceUserRepository


@dataclass
class ExternalChannelManagementOperationRepository:
    """Own bounded management transactions and return detached projections."""

    domain_repository: Annotated[
        ExternalChannelRepository, Depends(ExternalChannelRepository.create)
    ]
    repository: Annotated[
        ExternalChannelManagementRepository,
        Depends(ExternalChannelManagementRepository.create),
    ]
    lifecycle_repository: Annotated[
        ExternalChannelLifecycleRepository,
        Depends(ExternalChannelLifecycleRepository.create),
    ]
    agent_repository: Annotated[AgentRepository, Depends()]
    agent_admin_repository: Annotated[AgentAdminRepository, Depends()]
    workspace_user_repository: Annotated[WorkspaceUserRepository, Depends()]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]

    async def add_multi_route(
        self,
        *,
        workspace_id: str,
        connection_id: str,
        provider: ExternalChannelProvider,
        agent_id: str,
    ) -> ManagedMultiRoute:
        """Commit an active Agent association and return its completed projection."""
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

    async def create_dedicated_route(
        self, *, connection_id: str, agent_id: str
    ) -> None:
        """Commit a dedicated route before provider validation or activation."""
        async with self.session_manager() as session:
            await self.domain_repository.create_agent_route(
                session,
                ExternalChannelAgentRouteCreate(
                    connection_id=connection_id,
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

    async def require_owned_grant(self, *, agent_id: str, grant_id: str) -> None:
        """Finish the grant ownership read before access-service effects."""
        async with self.session_manager() as session:
            owned = await self.repository.grant_belongs_to_agent(
                session, agent_id=agent_id, grant_id=grant_id
            )
        if not owned:
            raise ExternalChannelManagementNotFound(grant_id)

    async def require_owned_block(self, *, agent_id: str, block_id: str) -> None:
        """Finish the block ownership read before access-service effects."""
        async with self.session_manager() as session:
            owned = await self.repository.block_belongs_to_agent(
                session, agent_id=agent_id, block_id=block_id
            )
        if not owned:
            raise ExternalChannelManagementNotFound(block_id)

    async def disconnect_binding(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        agent_session_id: str,
        binding_id: str,
        now: datetime.datetime,
    ) -> tuple[ProviderEffectPlan, ...]:
        """Commit the disconnection before returning terminal-control plans."""
        async with self.session_manager() as session:
            cleanup_plans = await self.repository.disconnect_binding(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                agent_session_id=agent_session_id,
                binding_id=binding_id,
                now=now,
                reason="manager_disconnected",
            )
            if cleanup_plans is None:
                raise ExternalChannelManagementNotFound(binding_id)
            await session.commit()
        return cleanup_plans

    async def list_connections(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        workspace_user_id: str,
    ) -> list[ManagedConnection]:
        await self.require_agent(
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

    async def list_agent_multi_connections(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        workspace_user_id: str,
    ) -> list[ManagedMultiConnection]:
        """List read-only Multi Apps associated with one visible Agent."""
        await self.require_agent(
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

    async def list_agent_access(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        workspace_user_id: str,
    ) -> ManagedAgentAccess:
        await self.require_agent(
            workspace_id=workspace_id,
            agent_id=agent_id,
            workspace_user_id=workspace_user_id,
            admin=False,
        )
        async with self.session_manager() as session:
            return ManagedAgentAccess(
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
        await self.require_agent(
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

    async def get_owned_connection_provider(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        workspace_user_id: str,
        connection_id: str,
    ) -> ExternalChannelProvider:
        """Read authorized provider identity without returning live DB objects."""
        await self.require_agent(
            workspace_id=workspace_id,
            agent_id=agent_id,
            workspace_user_id=workspace_user_id,
            admin=True,
        )
        async with self.session_manager() as session:
            row = await self.repository.get_connection(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                connection_id=connection_id,
            )
            if row is None:
                raise ExternalChannelManagementNotFound(connection_id)
            return row.connection.provider

    async def require_owned_connection(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        workspace_user_id: str,
        connection_id: str,
    ) -> None:
        await self.require_agent(
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

    async def require_agent(
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
        async with self.session_manager() as session:
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

    async def remove_multi_route(
        self,
        *,
        workspace_id: str,
        connection_id: str,
        provider: ExternalChannelProvider,
        route_id: str,
        user_id: str,
        expected_generation: datetime.datetime,
    ) -> ExternalChannelMultiRouteRemoval:
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
        return removal

    async def disconnect_multi_connection(
        self,
        *,
        workspace_id: str,
        connection_id: str,
        provider: ExternalChannelProvider,
        expected_generation: datetime.datetime,
    ) -> ExternalChannelMultiConnectionDisconnect:
        """Generation-fence terminal Multi App disconnect around provider I/O."""
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
            disconnected = await self.lifecycle_repository.disconnect_multi_connection(
                session,
                connection_id=connection.id,
                now=now,
                reason="manager_disconnected",
                defer_provider_state_purge=True,
            )
            if disconnected is None:
                raise ExternalChannelManagementNotFound(connection_id)
            await (
                self.lifecycle_repository.purge_disconnected_connection_provider_state(
                    session,
                    connection_ids=[connection.id],
                )
            )
            connection.updated_at = now
            await session.commit()
        return disconnected

    async def disconnect_connection(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        workspace_user_id: str,
        connection_id: str,
    ) -> ManagedConnectionDisconnectResult:
        await self.require_agent(
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
        return ManagedConnectionDisconnectResult(connection, cleanup_plans)

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
        now: datetime.datetime,
    ) -> ExternalChannelChannelDefaultTransition:
        """Commit a generation-fenced default mutation with DB operations only."""
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
        return transition

    async def clear_multi_channel_default(
        self,
        *,
        workspace_id: str,
        connection_id: str,
        provider: ExternalChannelProvider,
        provider_channel_id: str,
        expected_generation: datetime.datetime,
        now: datetime.datetime,
    ) -> ExternalChannelChannelDefaultTransition:
        """Commit a generation-fenced default mutation with DB operations only."""
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
        return transition

    async def update_multi_discord_thread_auto_archive_duration(
        self,
        *,
        workspace_id: str,
        connection_id: str,
        expected_generation: datetime.datetime,
        thread_auto_archive_duration_minutes: DiscordThreadAutoArchiveDurationMinutes,
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
                    duration=thread_auto_archive_duration_minutes,
                )
            )
            if managed is None:
                raise ExternalChannelManagementNotFound(connection_id)
            await session.commit()
        return managed

    async def update_multi_discord_url_preview_suppression(
        self,
        *,
        workspace_id: str,
        connection_id: str,
        expected_generation: datetime.datetime,
        suppress_url_previews: bool,
    ) -> ManagedMultiConnection:
        """Replace one Multi App URL-preview policy without reactivation."""
        async with self.session_manager() as session:
            connection = await self._lock_multi_connection_generation(
                session,
                workspace_id=workspace_id,
                connection_id=connection_id,
                provider=ExternalChannelProvider.DISCORD,
                expected_generation=expected_generation,
            )
            managed = (
                await self.repository.update_multi_discord_url_preview_suppression(
                    session,
                    connection=connection,
                    suppress_url_previews=suppress_url_previews,
                )
            )
            if managed is None:
                raise ExternalChannelManagementNotFound(connection_id)
            await session.commit()
        return managed

    async def get_binding_mutation_scope(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        agent_session_id: str,
        binding_id: str,
    ) -> ExternalChannelBindingMutationScope | None:
        """Return detached provider scope before acquiring coordination leases."""
        async with self.session_manager() as session:
            scope = await self.repository.get_binding_mutation_scope(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                agent_session_id=agent_session_id,
                binding_id=binding_id,
            )
        return scope

    async def update_binding_response_mode(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        agent_session_id: str,
        binding_id: str,
        user_id: str,
        response_mode: ExternalChannelResponseMode,
    ) -> None:
        """Commit the exact connected binding mutation without lease I/O."""
        async with self.session_manager() as session:
            updated = await self.repository.update_binding_response_mode(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                agent_session_id=agent_session_id,
                binding_id=binding_id,
                configured_by_user_id=user_id,
                response_mode=response_mode,
            )
            if not updated:
                raise ExternalChannelManagementNotFound(binding_id)
            await session.commit()

    async def replace_multi_slack_configuration(
        self,
        *,
        workspace_id: str,
        connection_id: str,
        app_id: str,
        encrypted: str,
        transport: ExternalChannelTransport,
    ) -> None:
        """Commit prepared configuration before provider validation or activation."""
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

    async def replace_multi_discord_configuration(
        self,
        *,
        workspace_id: str,
        connection_id: str,
        app_id: str,
        encrypted: str,
        provider_config: dict[str, object],
    ) -> None:
        """Commit prepared configuration before provider validation or activation."""
        async with self.session_manager() as session:
            connection = await self.repository.replace_multi_discord_configuration(
                session,
                workspace_id=workspace_id,
                connection_id=connection_id,
                provider_app_id=app_id,
                encrypted_credentials=encrypted,
                provider_config=provider_config,
            )
            if connection is None:
                raise ExternalChannelManagementNotFound(connection_id)
            await session.commit()

    async def replace_slack_configuration(
        self,
        *,
        workspace_id: str,
        connection_id: str,
        app_id: str,
        encrypted: str,
        agent_id: str,
        transport: ExternalChannelTransport,
    ) -> None:
        """Commit prepared configuration before provider validation or activation."""
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

    async def replace_discord_configuration(
        self,
        *,
        workspace_id: str,
        connection_id: str,
        app_id: str,
        encrypted: str,
        agent_id: str,
        provider_config: dict[str, object],
    ) -> None:
        """Commit prepared configuration before provider validation or activation."""
        async with self.session_manager() as session:
            connection = await self.repository.replace_discord_configuration(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                connection_id=connection_id,
                provider_app_id=app_id,
                encrypted_credentials=encrypted,
                provider_config=provider_config,
            )
            if connection is None:
                raise ExternalChannelManagementNotFound(connection_id)
            await session.commit()

    async def update_default_response_mode(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        workspace_user_id: str,
        response_mode: ExternalChannelResponseMode,
    ) -> ExternalChannelResponseMode:
        """Replace only the Agent default without rewriting existing bindings."""
        await self.require_agent(
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
                response_mode=response_mode,
            )
            if agent is None or agent.workspace_id != workspace_id:
                raise ExternalChannelManagementNotFound(agent_id)
            await session.commit()
        return agent.external_channel_default_response_mode

    async def update_discord_thread_auto_archive_duration(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        workspace_user_id: str,
        connection_id: str,
        thread_auto_archive_duration_minutes: DiscordThreadAutoArchiveDurationMinutes,
    ) -> ManagedConnection:
        """Replace one dedicated Thread policy without provider reactivation."""
        await self.require_owned_connection(
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
                    duration=thread_auto_archive_duration_minutes,
                )
            )
            if connection is None:
                raise ExternalChannelManagementNotFound(connection_id)
            await session.commit()
        return connection

    async def update_discord_url_preview_suppression(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        workspace_user_id: str,
        connection_id: str,
        suppress_url_previews: bool,
    ) -> ManagedConnection:
        """Replace one dedicated URL-preview policy without reactivation."""
        await self.require_owned_connection(
            workspace_id=workspace_id,
            agent_id=agent_id,
            workspace_user_id=workspace_user_id,
            connection_id=connection_id,
        )
        async with self.session_manager() as session:
            connection = await self.repository.update_discord_url_preview_suppression(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                connection_id=connection_id,
                suppress_url_previews=suppress_url_previews,
            )
            if connection is None:
                raise ExternalChannelManagementNotFound(connection_id)
            await session.commit()
        return connection

    async def update_connection_access_policy(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        workspace_user_id: str,
        connection_id: str,
        open_access_enabled: bool,
    ) -> ManagedConnection:
        """Update one dedicated connection's route-scoped ingress policy."""
        await self.require_owned_connection(
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
                open_access_enabled=open_access_enabled,
            )
            if connection is None:
                raise ExternalChannelManagementNotFound(connection_id)
            await session.commit()
        return connection
