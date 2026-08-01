"""External Channel management queries and lifecycle mutations."""

import datetime
from typing import Literal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentLifecycleStatus,
    ExternalChannelAccessGrantScope,
    ExternalChannelAppMode,
    ExternalChannelChannelDefaultStatus,
    ExternalChannelConnectionStatus,
    ExternalChannelDeliveryOperation,
    ExternalChannelDeliveryOriginType,
    ExternalChannelDeliveryStatus,
    ExternalChannelInteractionStatus,
    ExternalChannelInteractionType,
    ExternalChannelProvider,
    ExternalChannelResourceType,
    ExternalChannelResponseMode,
    ExternalChannelRouteCatalogStatus,
    ExternalChannelTransport,
    ExternalChannelWorkStatus,
)
from azents.core.external_channel_progress import ExternalChannelWorkTask
from azents.core.external_channel_session_presence import session_presence_payload
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.external_channel import (
    RDBExternalChannelAccessGrant,
    RDBExternalChannelAccessRequest,
    RDBExternalChannelAction,
    RDBExternalChannelAgentRoute,
    RDBExternalChannelAppClaim,
    RDBExternalChannelBinding,
    RDBExternalChannelBlock,
    RDBExternalChannelChannelDefault,
    RDBExternalChannelConnection,
    RDBExternalChannelDeliveryAttempt,
    RDBExternalChannelInteraction,
    RDBExternalChannelPrincipal,
    RDBExternalChannelResource,
    RDBExternalChannelWork,
)
from azents.repos.external_channel.management_data import (
    ManagedApprovalRequest,
    ManagedBinding,
    ManagedBlock,
    ManagedChannelDefault,
    ManagedConnection,
    ManagedDelivery,
    ManagedGrant,
    ManagedMultiConnection,
    ManagedMultiRoute,
    ManagedSlackManagementHandoff,
    ManagedWork,
    ManagedWorkSource,
    ManagedWorkTask,
)


class ExternalChannelManagementRepository:
    """Own safe management projections and explicit disconnect transitions."""

    @staticmethod
    def _has_sole_route() -> sa.ColumnElement[bool]:
        """Require one exact route before Agent-scoped Single management."""
        return (
            sa.select(sa.func.count())
            .select_from(RDBExternalChannelAgentRoute)
            .where(
                RDBExternalChannelAgentRoute.connection_id
                == RDBExternalChannelConnection.id
            )
            .correlate(RDBExternalChannelConnection)
            .scalar_subquery()
            == 1
        )

    async def list_connections(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        agent_id: str,
    ) -> list[ManagedConnection]:
        rows = (
            await session.execute(
                sa.select(RDBExternalChannelConnection, RDBExternalChannelAgentRoute)
                .join(
                    RDBExternalChannelAgentRoute,
                    RDBExternalChannelAgentRoute.connection_id
                    == RDBExternalChannelConnection.id,
                )
                .where(
                    RDBExternalChannelConnection.workspace_id == workspace_id,
                    RDBExternalChannelAgentRoute.agent_id == agent_id,
                    RDBExternalChannelConnection.app_mode
                    == ExternalChannelAppMode.SINGLE,
                    RDBExternalChannelAgentRoute.connection_app_mode
                    == ExternalChannelAppMode.SINGLE,
                    self._has_sole_route(),
                    RDBExternalChannelConnection.status
                    != ExternalChannelConnectionStatus.DISCONNECTED,
                )
                .order_by(RDBExternalChannelConnection.created_at)
            )
        ).all()
        return [_connection(connection, route) for connection, route in rows]

    async def update_connection_access_policy(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        agent_id: str,
        connection_id: str,
        open_access_enabled: bool,
    ) -> ManagedConnection | None:
        """Persist one dedicated route's non-secret ingress policy."""
        row = (
            await session.execute(
                sa.select(RDBExternalChannelConnection, RDBExternalChannelAgentRoute)
                .join(
                    RDBExternalChannelAgentRoute,
                    RDBExternalChannelAgentRoute.connection_id
                    == RDBExternalChannelConnection.id,
                )
                .where(
                    RDBExternalChannelConnection.id == connection_id,
                    RDBExternalChannelConnection.workspace_id == workspace_id,
                    RDBExternalChannelConnection.app_mode
                    == ExternalChannelAppMode.SINGLE,
                    RDBExternalChannelAgentRoute.connection_app_mode
                    == ExternalChannelAppMode.SINGLE,
                    RDBExternalChannelAgentRoute.agent_id == agent_id,
                    self._has_sole_route(),
                    RDBExternalChannelConnection.status
                    != ExternalChannelConnectionStatus.DISCONNECTED,
                )
                .with_for_update()
            )
        ).one_or_none()
        if row is None:
            return None
        connection, route = row
        route.open_access_enabled = open_access_enabled
        await session.flush()
        await session.refresh(route, attribute_names=["updated_at"])
        return _connection(connection, route)

    async def list_multi_connections(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        provider: ExternalChannelProvider | None,
        offset: int,
        limit: int,
    ) -> list[ManagedMultiConnection]:
        """List redacted Workspace-owned Multi Apps in one stable page."""
        if offset < 0 or limit <= 0 or limit > 100:
            raise ValueError("External Channel page is invalid.")
        active_route_counts = (
            sa.select(
                RDBExternalChannelAgentRoute.connection_id,
                sa.func.count().label("active_agent_count"),
            )
            .where(
                RDBExternalChannelAgentRoute.connection_app_mode
                == ExternalChannelAppMode.MULTI,
                RDBExternalChannelAgentRoute.catalog_status
                == ExternalChannelRouteCatalogStatus.AVAILABLE,
                RDBExternalChannelAgentRoute.agent_id.is_not(None),
            )
            .group_by(RDBExternalChannelAgentRoute.connection_id)
            .subquery()
        )
        configured_default_counts = (
            sa.select(
                RDBExternalChannelChannelDefault.connection_id,
                sa.func.count().label("configured_default_count"),
            )
            .where(
                RDBExternalChannelChannelDefault.status
                == ExternalChannelChannelDefaultStatus.ACTIVE
            )
            .group_by(RDBExternalChannelChannelDefault.connection_id)
            .subquery()
        )
        rows = (
            await session.execute(
                sa.select(
                    RDBExternalChannelConnection,
                    sa.func.coalesce(active_route_counts.c.active_agent_count, 0).label(
                        "active_agent_count"
                    ),
                    sa.func.coalesce(
                        configured_default_counts.c.configured_default_count, 0
                    ).label("configured_default_count"),
                )
                .outerjoin(
                    active_route_counts,
                    active_route_counts.c.connection_id
                    == RDBExternalChannelConnection.id,
                )
                .outerjoin(
                    configured_default_counts,
                    configured_default_counts.c.connection_id
                    == RDBExternalChannelConnection.id,
                )
                .where(
                    RDBExternalChannelConnection.workspace_id == workspace_id,
                    RDBExternalChannelConnection.app_mode
                    == ExternalChannelAppMode.MULTI,
                    *(
                        ()
                        if provider is None
                        else (RDBExternalChannelConnection.provider == provider,)
                    ),
                )
                .order_by(
                    RDBExternalChannelConnection.created_at,
                    RDBExternalChannelConnection.id,
                )
                .offset(offset)
                .limit(limit)
            )
        ).all()
        return [
            _multi_connection(
                connection,
                active_agent_count=active_agent_count,
                configured_default_count=configured_default_count,
            )
            for connection, active_agent_count, configured_default_count in rows
        ]

    async def list_agent_multi_connections(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        agent_id: str,
    ) -> list[ManagedMultiConnection]:
        """List active Multi Apps associated with one visible Agent."""
        active_route_counts = (
            sa.select(
                RDBExternalChannelAgentRoute.connection_id,
                sa.func.count().label("active_agent_count"),
            )
            .where(
                RDBExternalChannelAgentRoute.connection_app_mode
                == ExternalChannelAppMode.MULTI,
                RDBExternalChannelAgentRoute.catalog_status
                == ExternalChannelRouteCatalogStatus.AVAILABLE,
                RDBExternalChannelAgentRoute.agent_id.is_not(None),
            )
            .group_by(RDBExternalChannelAgentRoute.connection_id)
            .subquery()
        )
        configured_default_counts = (
            sa.select(
                RDBExternalChannelChannelDefault.connection_id,
                sa.func.count().label("configured_default_count"),
            )
            .where(
                RDBExternalChannelChannelDefault.status
                == ExternalChannelChannelDefaultStatus.ACTIVE
            )
            .group_by(RDBExternalChannelChannelDefault.connection_id)
            .subquery()
        )
        rows = (
            await session.execute(
                sa.select(
                    RDBExternalChannelConnection,
                    sa.func.coalesce(active_route_counts.c.active_agent_count, 0).label(
                        "active_agent_count"
                    ),
                    sa.func.coalesce(
                        configured_default_counts.c.configured_default_count, 0
                    ).label("configured_default_count"),
                )
                .join(
                    RDBExternalChannelAgentRoute,
                    RDBExternalChannelAgentRoute.connection_id
                    == RDBExternalChannelConnection.id,
                )
                .outerjoin(
                    active_route_counts,
                    active_route_counts.c.connection_id
                    == RDBExternalChannelConnection.id,
                )
                .outerjoin(
                    configured_default_counts,
                    configured_default_counts.c.connection_id
                    == RDBExternalChannelConnection.id,
                )
                .where(
                    RDBExternalChannelConnection.workspace_id == workspace_id,
                    RDBExternalChannelConnection.app_mode
                    == ExternalChannelAppMode.MULTI,
                    RDBExternalChannelConnection.status
                    != ExternalChannelConnectionStatus.DISCONNECTED,
                    RDBExternalChannelAgentRoute.agent_id == agent_id,
                    RDBExternalChannelAgentRoute.connection_app_mode
                    == ExternalChannelAppMode.MULTI,
                    RDBExternalChannelAgentRoute.catalog_status
                    == ExternalChannelRouteCatalogStatus.AVAILABLE,
                )
                .order_by(
                    RDBExternalChannelConnection.created_at,
                    RDBExternalChannelConnection.id,
                )
            )
        ).all()
        return [
            _multi_connection(
                connection,
                active_agent_count=active_agent_count,
                configured_default_count=configured_default_count,
            )
            for connection, active_agent_count, configured_default_count in rows
        ]

    async def get_multi_connection(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        connection_id: str,
        provider: ExternalChannelProvider,
        lock: bool = False,
        include_disconnected: bool = False,
    ) -> RDBExternalChannelConnection | None:
        """Fetch one provider-scoped Multi App, optionally under a row lock."""
        predicates: list[sa.ColumnElement[bool]] = [
            RDBExternalChannelConnection.id == connection_id,
            RDBExternalChannelConnection.workspace_id == workspace_id,
            RDBExternalChannelConnection.provider == provider,
            RDBExternalChannelConnection.app_mode == ExternalChannelAppMode.MULTI,
        ]
        if not include_disconnected:
            predicates.append(
                RDBExternalChannelConnection.status
                != ExternalChannelConnectionStatus.DISCONNECTED
            )
        statement = sa.select(RDBExternalChannelConnection).where(*predicates)
        if lock:
            statement = statement.with_for_update()
        return await session.scalar(statement)

    async def get_managed_multi_connection(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        connection_id: str,
        provider: ExternalChannelProvider,
        include_disconnected: bool = False,
    ) -> ManagedMultiConnection | None:
        """Load a redacted Multi App projection."""
        connection = await self.get_multi_connection(
            session,
            workspace_id=workspace_id,
            connection_id=connection_id,
            provider=provider,
            include_disconnected=include_disconnected,
        )
        if connection is None:
            return None
        active_agent_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(RDBExternalChannelAgentRoute)
            .where(
                RDBExternalChannelAgentRoute.connection_id == connection.id,
                RDBExternalChannelAgentRoute.connection_app_mode
                == ExternalChannelAppMode.MULTI,
                RDBExternalChannelAgentRoute.catalog_status
                == ExternalChannelRouteCatalogStatus.AVAILABLE,
                RDBExternalChannelAgentRoute.agent_id.is_not(None),
            )
        )
        configured_default_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(RDBExternalChannelChannelDefault)
            .where(
                RDBExternalChannelChannelDefault.connection_id == connection.id,
                RDBExternalChannelChannelDefault.status
                == ExternalChannelChannelDefaultStatus.ACTIVE,
            )
        )
        return _multi_connection(
            connection,
            active_agent_count=active_agent_count or 0,
            configured_default_count=configured_default_count or 0,
        )

    async def replace_multi_slack_configuration(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        connection_id: str,
        provider_app_id: str,
        transport: ExternalChannelTransport,
        encrypted_credentials: str,
    ) -> ManagedMultiConnection | None:
        """Replace complete Slack Multi App configuration without exposing secrets."""
        connection = await self.get_multi_connection(
            session,
            workspace_id=workspace_id,
            connection_id=connection_id,
            provider=ExternalChannelProvider.SLACK,
            lock=True,
        )
        if connection is None:
            return None
        connection.provider_app_id = provider_app_id
        connection.provider_tenant_id = None
        connection.provider_bot_user_id = None
        connection.transport = transport
        connection.http_callback_selector_hash = None
        connection.encrypted_credentials = encrypted_credentials
        connection.capabilities = None
        connection.status = ExternalChannelConnectionStatus.CONFIGURING
        connection.last_verified_at = None
        connection.last_health_at = None
        connection.last_health_code = None
        connection.disconnected_at = None
        connection.socket_lease_owner = None
        connection.socket_lease_until = None
        connection.socket_heartbeat_at = None
        connection.socket_gap_detected_at = None
        connection.socket_gap_reason = None
        await session.flush()
        await session.refresh(connection, attribute_names=["updated_at"])
        return await self.get_managed_multi_connection(
            session,
            workspace_id=workspace_id,
            connection_id=connection.id,
            provider=ExternalChannelProvider.SLACK,
        )

    async def replace_multi_discord_configuration(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        connection_id: str,
        provider_app_id: str,
        encrypted_credentials: str,
        provider_config: dict[str, object],
    ) -> ManagedMultiConnection | None:
        """Fence one Workspace Discord configuration before callback activation."""
        connection = await self.get_multi_connection(
            session,
            workspace_id=workspace_id,
            connection_id=connection_id,
            provider=ExternalChannelProvider.DISCORD,
            lock=True,
        )
        if connection is None:
            return None
        await _release_discord_app_claim(session, connection_id=connection.id)
        _reset_discord_configuration(
            connection,
            provider_app_id=provider_app_id,
            encrypted_credentials=encrypted_credentials,
            provider_config=provider_config,
        )
        await session.flush()
        await session.refresh(connection, attribute_names=["updated_at"])
        return await self.get_managed_multi_connection(
            session,
            workspace_id=workspace_id,
            connection_id=connection.id,
            provider=ExternalChannelProvider.DISCORD,
        )

    async def list_multi_routes(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        connection_id: str,
        provider: ExternalChannelProvider,
        offset: int,
        limit: int,
    ) -> list[ManagedMultiRoute] | None:
        """List one Multi App catalog, including removed route history."""
        if offset < 0 or limit <= 0 or limit > 100:
            raise ValueError("External Channel page is invalid.")
        connection = await self.get_multi_connection(
            session,
            workspace_id=workspace_id,
            connection_id=connection_id,
            provider=provider,
            include_disconnected=True,
        )
        if connection is None:
            return None
        rows = (
            await session.execute(
                sa.select(RDBExternalChannelAgentRoute, RDBAgent.name)
                .outerjoin(
                    RDBAgent,
                    RDBAgent.id == RDBExternalChannelAgentRoute.agent_id,
                )
                .where(
                    RDBExternalChannelAgentRoute.connection_id == connection.id,
                    RDBExternalChannelAgentRoute.connection_app_mode
                    == ExternalChannelAppMode.MULTI,
                )
                .order_by(
                    RDBExternalChannelAgentRoute.created_at,
                    RDBExternalChannelAgentRoute.id,
                )
                .offset(offset)
                .limit(limit)
            )
        ).all()
        return [_multi_route(route, agent_name) for route, agent_name in rows]

    async def get_multi_route(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        connection_id: str,
        provider: ExternalChannelProvider,
        route_id: str,
    ) -> ManagedMultiRoute | None:
        """Load one Multi App route under its Workspace owner."""
        row = (
            await session.execute(
                sa.select(RDBExternalChannelAgentRoute, RDBAgent.name)
                .join(
                    RDBExternalChannelConnection,
                    RDBExternalChannelConnection.id
                    == RDBExternalChannelAgentRoute.connection_id,
                )
                .outerjoin(
                    RDBAgent,
                    RDBAgent.id == RDBExternalChannelAgentRoute.agent_id,
                )
                .where(
                    RDBExternalChannelConnection.id == connection_id,
                    RDBExternalChannelConnection.workspace_id == workspace_id,
                    RDBExternalChannelConnection.provider == provider,
                    RDBExternalChannelConnection.app_mode
                    == ExternalChannelAppMode.MULTI,
                    RDBExternalChannelAgentRoute.id == route_id,
                    RDBExternalChannelAgentRoute.connection_app_mode
                    == ExternalChannelAppMode.MULTI,
                )
            )
        ).one_or_none()
        return None if row is None else _multi_route(*row)

    async def get_multi_route_by_agent(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        connection_id: str,
        provider: ExternalChannelProvider,
        agent_id: str,
    ) -> ManagedMultiRoute | None:
        """Load the stable Multi App association for one Agent identity."""
        row = (
            await session.execute(
                sa.select(RDBExternalChannelAgentRoute, RDBAgent.name)
                .join(
                    RDBExternalChannelConnection,
                    RDBExternalChannelConnection.id
                    == RDBExternalChannelAgentRoute.connection_id,
                )
                .outerjoin(
                    RDBAgent,
                    RDBAgent.id == RDBExternalChannelAgentRoute.agent_id,
                )
                .where(
                    RDBExternalChannelConnection.id == connection_id,
                    RDBExternalChannelConnection.workspace_id == workspace_id,
                    RDBExternalChannelConnection.provider == provider,
                    RDBExternalChannelConnection.app_mode
                    == ExternalChannelAppMode.MULTI,
                    RDBExternalChannelAgentRoute.connection_app_mode
                    == ExternalChannelAppMode.MULTI,
                    RDBExternalChannelAgentRoute.agent_id_snapshot == agent_id,
                )
            )
        ).one_or_none()
        return None if row is None else _multi_route(*row)

    async def list_multi_channel_defaults(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        connection_id: str,
        provider: ExternalChannelProvider,
        offset: int,
        limit: int,
    ) -> list[ManagedChannelDefault] | None:
        """List current and historical defaults for one Workspace Multi App."""
        if offset < 0 or limit <= 0 or limit > 100:
            raise ValueError("External Channel page is invalid.")
        connection = await self.get_multi_connection(
            session,
            workspace_id=workspace_id,
            connection_id=connection_id,
            provider=provider,
            include_disconnected=True,
        )
        if connection is None:
            return None
        rows = (
            await session.execute(
                sa.select(
                    RDBExternalChannelChannelDefault,
                    RDBExternalChannelAgentRoute,
                    RDBAgent.name,
                )
                .join(
                    RDBExternalChannelAgentRoute,
                    RDBExternalChannelAgentRoute.id
                    == RDBExternalChannelChannelDefault.route_id,
                )
                .outerjoin(
                    RDBAgent,
                    RDBAgent.id == RDBExternalChannelAgentRoute.agent_id,
                )
                .where(RDBExternalChannelChannelDefault.connection_id == connection.id)
                .order_by(
                    RDBExternalChannelChannelDefault.created_at.desc(),
                    RDBExternalChannelChannelDefault.id.desc(),
                )
                .offset(offset)
                .limit(limit)
            )
        ).all()
        return [
            _channel_default(channel_default, route, agent_name)
            for channel_default, route, agent_name in rows
        ]

    async def replace_multi_channel_default(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        connection_id: str,
        provider: ExternalChannelProvider,
        provider_channel_id: str,
        route_id: str,
        configured_by_user_id: str,
        now: datetime.datetime,
    ) -> ManagedChannelDefault | None:
        """Replace one active channel default after validating its Multi route."""
        connection = await self.get_multi_connection(
            session,
            workspace_id=workspace_id,
            connection_id=connection_id,
            provider=provider,
            lock=True,
        )
        if connection is None:
            return None
        route = await session.scalar(
            sa.select(RDBExternalChannelAgentRoute)
            .where(
                RDBExternalChannelAgentRoute.id == route_id,
                RDBExternalChannelAgentRoute.connection_id == connection.id,
                RDBExternalChannelAgentRoute.connection_app_mode
                == ExternalChannelAppMode.MULTI,
                RDBExternalChannelAgentRoute.catalog_status
                == ExternalChannelRouteCatalogStatus.AVAILABLE,
            )
            .with_for_update()
        )
        if route is None or route.agent_id is None:
            return None
        agent = await session.scalar(
            sa.select(RDBAgent)
            .where(
                RDBAgent.id == route.agent_id,
                RDBAgent.workspace_id == connection.workspace_id,
                RDBAgent.lifecycle_status == AgentLifecycleStatus.ACTIVE,
            )
            .with_for_update()
        )
        if agent is None:
            return None
        existing = await session.scalar(
            sa.select(RDBExternalChannelChannelDefault)
            .where(
                RDBExternalChannelChannelDefault.connection_id == connection.id,
                RDBExternalChannelChannelDefault.provider_channel_id
                == provider_channel_id,
                RDBExternalChannelChannelDefault.status
                == ExternalChannelChannelDefaultStatus.ACTIVE,
            )
            .with_for_update()
        )
        if existing is not None:
            existing.status = ExternalChannelChannelDefaultStatus.INVALIDATED
            existing.invalidated_at = now
            existing.invalidation_reason = "replaced"
        channel_default = RDBExternalChannelChannelDefault(
            connection_id=connection.id,
            provider_channel_id=provider_channel_id,
            route_id=route.id,
            status=ExternalChannelChannelDefaultStatus.ACTIVE,
            configured_by_user_id=configured_by_user_id,
            configured_by_principal_id=None,
            invalidated_at=None,
            invalidation_reason=None,
        )
        session.add(channel_default)
        await session.flush()
        await session.refresh(
            channel_default,
            attribute_names=["created_at", "updated_at"],
        )
        return _channel_default(channel_default, route, agent.name)

    async def clear_multi_channel_default(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        connection_id: str,
        provider: ExternalChannelProvider,
        provider_channel_id: str,
        now: datetime.datetime,
    ) -> bool | None:
        """Invalidate one active default; false means the channel had no default."""
        connection = await self.get_multi_connection(
            session,
            workspace_id=workspace_id,
            connection_id=connection_id,
            provider=provider,
            lock=True,
        )
        if connection is None:
            return None
        channel_default = await session.scalar(
            sa.select(RDBExternalChannelChannelDefault)
            .where(
                RDBExternalChannelChannelDefault.connection_id == connection.id,
                RDBExternalChannelChannelDefault.provider_channel_id
                == provider_channel_id,
                RDBExternalChannelChannelDefault.status
                == ExternalChannelChannelDefaultStatus.ACTIVE,
            )
            .with_for_update()
        )
        if channel_default is None:
            return False
        channel_default.status = ExternalChannelChannelDefaultStatus.INVALIDATED
        channel_default.invalidated_at = now
        channel_default.invalidation_reason = "cleared"
        await session.flush()
        return True

    async def load_multi_management_handoff(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        interaction_id: str,
        now: datetime.datetime,
    ) -> ManagedSlackManagementHandoff | None:
        """Resolve opaque Slack management state under Workspace authority."""
        row = (
            await session.execute(
                sa.select(RDBExternalChannelInteraction, RDBExternalChannelConnection)
                .join(
                    RDBExternalChannelConnection,
                    RDBExternalChannelConnection.id
                    == RDBExternalChannelInteraction.connection_id,
                )
                .where(
                    RDBExternalChannelInteraction.id == interaction_id,
                    RDBExternalChannelInteraction.interaction_type
                    == ExternalChannelInteractionType.MANAGEMENT_ACTION,
                    RDBExternalChannelInteraction.status
                    == ExternalChannelInteractionStatus.COMPLETED,
                    RDBExternalChannelInteraction.expires_at > now,
                    RDBExternalChannelInteraction.resource_correlation_key.is_not(None),
                    RDBExternalChannelConnection.workspace_id == workspace_id,
                    RDBExternalChannelConnection.app_mode
                    == ExternalChannelAppMode.MULTI,
                    RDBExternalChannelConnection.status.in_(
                        (
                            ExternalChannelConnectionStatus.ACTIVE,
                            ExternalChannelConnectionStatus.DEGRADED,
                        )
                    ),
                )
            )
        ).one_or_none()
        if row is None:
            return None
        interaction, connection = row
        assert interaction.resource_correlation_key is not None
        provider_channel_id, separator, provider_thread_id = (
            interaction.resource_correlation_key.partition(":")
        )
        if not provider_channel_id:
            return None
        return ManagedSlackManagementHandoff(
            interaction_id=interaction.id,
            connection_id=connection.id,
            provider=connection.provider,
            provider_app_id=connection.provider_app_id,
            provider_channel_id=provider_channel_id,
            provider_thread_id=provider_thread_id if separator else None,
            expires_at=interaction.expires_at,
        )

    async def get_connection(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        agent_id: str,
        connection_id: str,
        lock: bool = False,
        include_disconnected: bool = False,
    ) -> tuple[RDBExternalChannelConnection, RDBExternalChannelAgentRoute] | None:
        route_owner = RDBExternalChannelAgentRoute.agent_id == agent_id
        if include_disconnected:
            route_owner = sa.or_(
                route_owner,
                sa.and_(
                    RDBExternalChannelConnection.status
                    == ExternalChannelConnectionStatus.DISCONNECTED,
                    RDBExternalChannelAgentRoute.agent_id_snapshot == agent_id,
                ),
            )
        status_predicates = (
            ()
            if include_disconnected
            else (
                RDBExternalChannelConnection.status
                != ExternalChannelConnectionStatus.DISCONNECTED,
            )
        )
        statement = (
            sa.select(RDBExternalChannelConnection, RDBExternalChannelAgentRoute)
            .join(
                RDBExternalChannelAgentRoute,
                RDBExternalChannelAgentRoute.connection_id
                == RDBExternalChannelConnection.id,
            )
            .where(
                RDBExternalChannelConnection.id == connection_id,
                RDBExternalChannelConnection.workspace_id == workspace_id,
                route_owner,
                RDBExternalChannelConnection.app_mode == ExternalChannelAppMode.SINGLE,
                RDBExternalChannelAgentRoute.connection_app_mode
                == ExternalChannelAppMode.SINGLE,
                self._has_sole_route(),
                *status_predicates,
            )
        )
        row = (await session.execute(statement)).one_or_none()
        if row is None:
            return None
        if not lock:
            return row[0], row[1]
        connection_snapshot, route_snapshot = row
        connection = await session.scalar(
            sa.select(RDBExternalChannelConnection)
            .where(
                RDBExternalChannelConnection.id == connection_snapshot.id,
                RDBExternalChannelConnection.workspace_id == workspace_id,
                RDBExternalChannelConnection.app_mode == ExternalChannelAppMode.SINGLE,
                self._has_sole_route(),
                *status_predicates,
            )
            .with_for_update()
        )
        if connection is None:
            return None
        locked_route_owner = RDBExternalChannelAgentRoute.agent_id == agent_id
        if (
            include_disconnected
            and connection.status is ExternalChannelConnectionStatus.DISCONNECTED
        ):
            locked_route_owner = (
                RDBExternalChannelAgentRoute.agent_id_snapshot == agent_id
            )
        route = await session.scalar(
            sa.select(RDBExternalChannelAgentRoute)
            .where(
                RDBExternalChannelAgentRoute.id == route_snapshot.id,
                RDBExternalChannelAgentRoute.connection_id == connection.id,
                locked_route_owner,
                RDBExternalChannelAgentRoute.connection_app_mode
                == ExternalChannelAppMode.SINGLE,
            )
            .with_for_update()
        )
        if route is None:
            return None
        return connection, route

    async def replace_slack_configuration(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        agent_id: str,
        connection_id: str,
        provider_app_id: str,
        transport: ExternalChannelTransport,
        encrypted_credentials: str,
    ) -> ManagedConnection | None:
        """Replace one Slack connection configuration without a lifecycle guard."""
        row = await self.get_connection(
            session,
            workspace_id=workspace_id,
            agent_id=agent_id,
            connection_id=connection_id,
            lock=True,
        )
        if row is None:
            return None
        connection, route = row
        connection.provider_app_id = provider_app_id
        connection.provider_tenant_id = None
        connection.provider_bot_user_id = None
        connection.transport = transport
        connection.http_callback_selector_hash = None
        connection.encrypted_credentials = encrypted_credentials
        connection.capabilities = None
        connection.status = ExternalChannelConnectionStatus.CONFIGURING
        connection.last_verified_at = None
        connection.last_health_at = None
        connection.last_health_code = None
        connection.disconnected_at = None
        connection.socket_lease_owner = None
        connection.socket_lease_until = None
        connection.socket_heartbeat_at = None
        connection.socket_gap_detected_at = None
        connection.socket_gap_reason = None
        await session.flush()
        await session.refresh(connection, attribute_names=["updated_at"])
        return _connection(connection, route)

    async def replace_discord_configuration(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        agent_id: str,
        connection_id: str,
        provider_app_id: str,
        encrypted_credentials: str,
        provider_config: dict[str, object],
    ) -> ManagedConnection | None:
        """Fence a dedicated Discord configuration before callback activation."""
        row = await self.get_connection(
            session,
            workspace_id=workspace_id,
            agent_id=agent_id,
            connection_id=connection_id,
            lock=True,
        )
        if row is None:
            return None
        connection, route = row
        if connection.provider is not ExternalChannelProvider.DISCORD:
            return None
        await _release_discord_app_claim(session, connection_id=connection.id)
        _reset_discord_configuration(
            connection,
            provider_app_id=provider_app_id,
            encrypted_credentials=encrypted_credentials,
            provider_config=provider_config,
        )
        await session.flush()
        await session.refresh(connection, attribute_names=["updated_at"])
        return _connection(connection, route)

    async def list_bindings(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        agent_id: str,
        agent_session_id: str,
    ) -> list[ManagedBinding]:
        rows = (
            await session.execute(
                sa.select(
                    RDBExternalChannelBinding,
                    RDBExternalChannelResource,
                    RDBExternalChannelConnection,
                )
                .join(
                    RDBExternalChannelAgentRoute,
                    RDBExternalChannelAgentRoute.id
                    == RDBExternalChannelBinding.route_id,
                )
                .join(
                    RDBExternalChannelConnection,
                    RDBExternalChannelConnection.id
                    == RDBExternalChannelAgentRoute.connection_id,
                )
                .join(
                    RDBExternalChannelResource,
                    RDBExternalChannelResource.id
                    == RDBExternalChannelBinding.resource_id,
                )
                .join(
                    RDBAgentSession,
                    RDBAgentSession.id == RDBExternalChannelBinding.agent_session_id,
                )
                .where(
                    RDBAgentSession.workspace_id == workspace_id,
                    RDBAgentSession.agent_id == agent_id,
                    RDBExternalChannelBinding.agent_session_id == agent_session_id,
                )
                .order_by(
                    RDBExternalChannelBinding.connected_at.desc(),
                    RDBExternalChannelBinding.id,
                )
            )
        ).all()
        result: list[ManagedBinding] = []
        for binding, resource, connection in rows:
            work = await session.scalar(
                sa.select(RDBExternalChannelWork)
                .where(RDBExternalChannelWork.binding_id == binding.id)
                .order_by(
                    RDBExternalChannelWork.created_at.desc(),
                    RDBExternalChannelWork.id.desc(),
                )
                .limit(1)
            )
            deliveries = list(
                (
                    await session.scalars(
                        sa.select(RDBExternalChannelDeliveryAttempt)
                        .where(
                            RDBExternalChannelDeliveryAttempt.binding_id == binding.id
                        )
                        .order_by(
                            RDBExternalChannelDeliveryAttempt.created_at.desc(),
                            RDBExternalChannelDeliveryAttempt.id.desc(),
                        )
                        .limit(20)
                    )
                ).all()
            )
            progress_delivery = (
                None
                if work is None
                else await self.get_latest_work_progress_delivery(
                    session,
                    binding_id=binding.id,
                    work=work,
                )
            )
            result.append(
                ManagedBinding(
                    id=binding.id,
                    agent_session_id=binding.agent_session_id,
                    provider=connection.provider,
                    response_mode=binding.response_mode,
                    resource_type=resource.resource_type.value,
                    resource_label=_resource_label(resource.labels, binding.id),
                    connected_at=binding.connected_at,
                    disconnected_at=binding.disconnected_at,
                    disconnect_reason=binding.disconnect_reason,
                    latest_activity_at=resource.latest_activity_at,
                    work=(
                        None
                        if work is None
                        else _work(work, progress_delivery=progress_delivery)
                    ),
                    deliveries=[_delivery(item) for item in deliveries],
                )
            )
        return result

    async def update_binding_response_mode(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        agent_id: str,
        agent_session_id: str,
        binding_id: str,
        response_mode: ExternalChannelResponseMode,
    ) -> bool:
        """Update one connected binding owned by the requested Agent Session."""
        binding = await session.scalar(
            sa.select(RDBExternalChannelBinding)
            .join(
                RDBAgentSession,
                RDBAgentSession.id == RDBExternalChannelBinding.agent_session_id,
            )
            .where(
                RDBExternalChannelBinding.id == binding_id,
                RDBExternalChannelBinding.agent_session_id == agent_session_id,
                RDBExternalChannelBinding.disconnected_at.is_(None),
                RDBAgentSession.workspace_id == workspace_id,
                RDBAgentSession.agent_id == agent_id,
            )
            .with_for_update()
        )
        if binding is None:
            return False
        binding.response_mode = response_mode
        await session.flush()
        return True

    async def get_latest_work_progress_delivery(
        self,
        session: AsyncSession,
        *,
        binding_id: str,
        work: RDBExternalChannelWork,
    ) -> RDBExternalChannelDeliveryAttempt | None:
        """Load the latest progress outcome belonging to one work cycle."""
        return await session.scalar(
            sa.select(RDBExternalChannelDeliveryAttempt)
            .outerjoin(
                RDBExternalChannelAction,
                RDBExternalChannelAction.id
                == RDBExternalChannelDeliveryAttempt.channel_action_id,
            )
            .where(
                RDBExternalChannelDeliveryAttempt.binding_id == binding_id,
                RDBExternalChannelDeliveryAttempt.operation.in_(
                    (
                        ExternalChannelDeliveryOperation.PROGRESS_CREATE,
                        ExternalChannelDeliveryOperation.PROGRESS_UPDATE,
                        ExternalChannelDeliveryOperation.PROGRESS_DELETE,
                    )
                ),
                sa.or_(
                    RDBExternalChannelAction.work_id == work.id,
                    sa.and_(
                        RDBExternalChannelDeliveryAttempt.channel_action_id.is_(None),
                        RDBExternalChannelDeliveryAttempt.created_at >= work.created_at,
                    ),
                ),
            )
            .order_by(
                RDBExternalChannelDeliveryAttempt.created_at.desc(),
                RDBExternalChannelDeliveryAttempt.id.desc(),
            )
            .limit(1)
        )

    async def disconnect_binding(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        agent_id: str,
        agent_session_id: str,
        binding_id: str,
        now: datetime.datetime,
        reason: str,
    ) -> tuple[str, ...] | None:
        snapshot = (
            await session.execute(
                sa.select(
                    RDBExternalChannelBinding.route_id,
                    RDBExternalChannelBinding.resource_id,
                    RDBExternalChannelAgentRoute.connection_id,
                )
                .join(
                    RDBExternalChannelAgentRoute,
                    RDBExternalChannelAgentRoute.id
                    == RDBExternalChannelBinding.route_id,
                )
                .join(
                    RDBExternalChannelConnection,
                    RDBExternalChannelConnection.id
                    == RDBExternalChannelAgentRoute.connection_id,
                )
                .join(
                    RDBExternalChannelResource,
                    RDBExternalChannelResource.id
                    == RDBExternalChannelBinding.resource_id,
                )
                .join(
                    RDBAgentSession,
                    RDBAgentSession.id == RDBExternalChannelBinding.agent_session_id,
                )
                .where(
                    RDBExternalChannelBinding.id == binding_id,
                    RDBExternalChannelBinding.agent_session_id == agent_session_id,
                    RDBAgentSession.workspace_id == workspace_id,
                    RDBAgentSession.agent_id == agent_id,
                )
            )
        ).one_or_none()
        if snapshot is None:
            return None
        route_id, resource_id, connection_id = snapshot
        connection = await session.scalar(
            sa.select(RDBExternalChannelConnection)
            .where(
                RDBExternalChannelConnection.id == connection_id,
                RDBExternalChannelConnection.workspace_id == workspace_id,
            )
            .with_for_update()
        )
        if connection is None:
            return None
        route = await session.scalar(
            sa.select(RDBExternalChannelAgentRoute)
            .where(
                RDBExternalChannelAgentRoute.id == route_id,
                RDBExternalChannelAgentRoute.connection_id == connection.id,
            )
            .with_for_update()
        )
        if route is None:
            return None
        resource = await session.scalar(
            sa.select(RDBExternalChannelResource)
            .where(
                RDBExternalChannelResource.id == resource_id,
                RDBExternalChannelResource.connection_id == connection.id,
            )
            .with_for_update()
        )
        if resource is None:
            return None
        binding = await session.scalar(
            sa.select(RDBExternalChannelBinding)
            .where(
                RDBExternalChannelBinding.id == binding_id,
                RDBExternalChannelBinding.route_id == route.id,
                RDBExternalChannelBinding.resource_id == resource.id,
                RDBExternalChannelBinding.agent_session_id == agent_session_id,
            )
            .with_for_update()
        )
        if binding is None:
            return None
        return await self._terminate_binding(
            session,
            binding=binding,
            resource=resource,
            now=now,
            reason=reason,
        )

    async def disconnect_parent_binding_for_participation(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        route_id: str,
        resource_id: str,
        binding_id: str,
        now: datetime.datetime,
    ) -> tuple[str, ...] | None:
        """Disconnect one exact parent binding after participation locks are held."""
        connection = await session.scalar(
            sa.select(RDBExternalChannelConnection)
            .where(RDBExternalChannelConnection.id == connection_id)
            .with_for_update()
        )
        route = await session.scalar(
            sa.select(RDBExternalChannelAgentRoute)
            .where(
                RDBExternalChannelAgentRoute.id == route_id,
                RDBExternalChannelAgentRoute.connection_id == connection_id,
            )
            .with_for_update()
        )
        resource = await session.scalar(
            sa.select(RDBExternalChannelResource)
            .where(
                RDBExternalChannelResource.id == resource_id,
                RDBExternalChannelResource.connection_id == connection_id,
                RDBExternalChannelResource.resource_type
                == ExternalChannelResourceType.PARENT_CHANNEL,
            )
            .with_for_update()
        )
        binding = await session.scalar(
            sa.select(RDBExternalChannelBinding)
            .where(
                RDBExternalChannelBinding.id == binding_id,
                RDBExternalChannelBinding.route_id == route_id,
                RDBExternalChannelBinding.resource_id == resource_id,
            )
            .with_for_update()
        )
        if connection is None or route is None or resource is None or binding is None:
            return None
        return await self._terminate_binding(
            session,
            binding=binding,
            resource=resource,
            now=now,
            reason="participation_location_changed",
        )

    async def begin_connection_disconnect(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        agent_id: str,
        connection_id: str,
        now: datetime.datetime,
    ) -> tuple[str, ...] | None:
        row = await self.get_connection(
            session,
            workspace_id=workspace_id,
            agent_id=agent_id,
            connection_id=connection_id,
            lock=True,
            include_disconnected=True,
        )
        if row is None:
            return None
        connection, route = row
        connection.status = ExternalChannelConnectionStatus.DISCONNECTING
        resource_ids = sa.select(RDBExternalChannelBinding.resource_id).where(
            RDBExternalChannelBinding.route_id == route.id,
        )
        resources = list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelResource)
                    .where(RDBExternalChannelResource.id.in_(resource_ids))
                    .order_by(RDBExternalChannelResource.id)
                    .with_for_update()
                )
            ).all()
        )
        bindings = list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelBinding)
                    .where(RDBExternalChannelBinding.route_id == route.id)
                    .order_by(RDBExternalChannelBinding.resource_id)
                    .with_for_update()
                )
            ).all()
        )
        resources_by_id = {resource.id: resource for resource in resources}
        cleanup_ids: list[str] = []
        for binding in bindings:
            resource = resources_by_id.get(binding.resource_id)
            if resource is None:
                continue
            cleanup_ids.extend(
                await self._terminate_binding(
                    session,
                    binding=binding,
                    resource=resource,
                    now=now,
                    reason="connection_disconnected",
                )
            )
        await session.flush()
        return tuple(cleanup_ids)

    async def complete_connection_disconnect(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        agent_id: str,
        connection_id: str,
        now: datetime.datetime,
    ) -> ManagedConnection | None:
        del now
        row = (
            await session.execute(
                sa.select(
                    RDBExternalChannelConnection,
                    RDBExternalChannelAgentRoute,
                )
                .join(
                    RDBExternalChannelAgentRoute,
                    RDBExternalChannelAgentRoute.connection_id
                    == RDBExternalChannelConnection.id,
                )
                .where(
                    RDBExternalChannelConnection.id == connection_id,
                    RDBExternalChannelConnection.workspace_id == workspace_id,
                    RDBExternalChannelConnection.app_mode
                    == ExternalChannelAppMode.SINGLE,
                    RDBExternalChannelConnection.status
                    == ExternalChannelConnectionStatus.DISCONNECTED,
                    RDBExternalChannelAgentRoute.connection_app_mode
                    == ExternalChannelAppMode.SINGLE,
                    RDBExternalChannelAgentRoute.agent_id_snapshot == agent_id,
                    self._has_sole_route(),
                )
            )
        ).one_or_none()
        if row is None:
            return None
        connection, route = row
        return _connection(connection, route, agent_id=agent_id)

    async def list_grants(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        agent_session_id: str | None,
    ) -> list[ManagedGrant]:
        predicates = [RDBExternalChannelAccessGrant.agent_id == agent_id]
        if agent_session_id is not None:
            predicates.append(
                RDBExternalChannelAccessGrant.agent_session_id == agent_session_id
            )
        else:
            predicates.append(
                RDBExternalChannelAccessGrant.scope
                == ExternalChannelAccessGrantScope.AGENT
            )
        predicates.append(RDBExternalChannelAccessGrant.revoked_at.is_(None))
        rows = (
            await session.execute(
                sa.select(
                    RDBExternalChannelAccessGrant,
                    RDBExternalChannelPrincipal,
                )
                .join(
                    RDBExternalChannelPrincipal,
                    RDBExternalChannelPrincipal.id
                    == RDBExternalChannelAccessGrant.principal_id,
                )
                .where(*predicates)
                .order_by(RDBExternalChannelAccessGrant.created_at.desc())
            )
        ).all()
        return [_grant(grant, principal) for grant, principal in rows]

    async def list_blocks(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
    ) -> list[ManagedBlock]:
        rows = (
            await session.execute(
                sa.select(RDBExternalChannelBlock, RDBExternalChannelPrincipal)
                .join(
                    RDBExternalChannelPrincipal,
                    RDBExternalChannelPrincipal.id
                    == RDBExternalChannelBlock.principal_id,
                )
                .where(RDBExternalChannelBlock.agent_id == agent_id)
                .order_by(RDBExternalChannelBlock.created_at.desc())
            )
        ).all()
        return [_block(block, principal) for block, principal in rows]

    async def grant_belongs_to_agent(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        grant_id: str,
    ) -> bool:
        return bool(
            await session.scalar(
                sa.select(
                    sa.exists().where(
                        RDBExternalChannelAccessGrant.id == grant_id,
                        RDBExternalChannelAccessGrant.agent_id == agent_id,
                    )
                )
            )
        )

    async def block_belongs_to_agent(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        block_id: str,
    ) -> bool:
        return bool(
            await session.scalar(
                sa.select(
                    sa.exists().where(
                        RDBExternalChannelBlock.id == block_id,
                        RDBExternalChannelBlock.agent_id == agent_id,
                    )
                )
            )
        )

    async def get_approval_request(
        self,
        session: AsyncSession,
        *,
        access_request_id: str,
    ) -> ManagedApprovalRequest | None:
        row = (
            await session.execute(
                sa.select(
                    RDBExternalChannelAccessRequest,
                    RDBExternalChannelAgentRoute,
                    RDBExternalChannelConnection,
                    RDBExternalChannelResource,
                    RDBExternalChannelPrincipal,
                    RDBAgent,
                )
                .join(
                    RDBExternalChannelAgentRoute,
                    RDBExternalChannelAgentRoute.id
                    == RDBExternalChannelAccessRequest.route_id,
                )
                .join(
                    RDBExternalChannelConnection,
                    RDBExternalChannelConnection.id
                    == RDBExternalChannelAgentRoute.connection_id,
                )
                .join(
                    RDBExternalChannelResource,
                    RDBExternalChannelResource.id
                    == RDBExternalChannelAccessRequest.resource_id,
                )
                .join(
                    RDBExternalChannelPrincipal,
                    RDBExternalChannelPrincipal.id
                    == RDBExternalChannelAccessRequest.principal_id,
                )
                .join(
                    RDBAgent,
                    RDBAgent.id == RDBExternalChannelAgentRoute.agent_id,
                )
                .where(RDBExternalChannelAccessRequest.id == access_request_id)
            )
        ).one_or_none()
        if row is None:
            return None
        request, route, connection, resource, principal, agent = row
        if route.agent_id is None:
            return None
        return ManagedApprovalRequest(
            id=request.id,
            agent_id=route.agent_id,
            workspace_id=agent.workspace_id,
            agent_session_id=request.agent_session_id,
            provider=connection.provider,
            status=request.status,
            principal_id=principal.id,
            principal_label=(principal.display_name or principal.provider_user_id),
            principal_provider_user_id=principal.provider_user_id,
            resource_label=_resource_label(resource.labels, resource.id),
            expires_at=request.expires_at,
            decided_at=request.decided_at,
            decision_summary=request.decision_summary,
        )

    async def _terminate_binding(
        self,
        session: AsyncSession,
        *,
        binding: RDBExternalChannelBinding,
        resource: RDBExternalChannelResource,
        now: datetime.datetime,
        reason: str,
    ) -> tuple[str, ...]:
        if binding.disconnected_at is not None:
            return await self._pending_binding_disconnect_intent_ids(
                session,
                binding_id=binding.id,
            )
        binding.disconnected_at = now
        binding.disconnect_reason = reason
        presence = await session.scalar(
            sa.select(RDBExternalChannelDeliveryAttempt).where(
                RDBExternalChannelDeliveryAttempt.origin_type
                == ExternalChannelDeliveryOriginType.BINDING_DISCONNECT,
                RDBExternalChannelDeliveryAttempt.origin_id == binding.id,
                RDBExternalChannelDeliveryAttempt.binding_id == binding.id,
                RDBExternalChannelDeliveryAttempt.operation
                == ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
            )
        )
        if presence is None:
            presence = RDBExternalChannelDeliveryAttempt(
                origin_type=ExternalChannelDeliveryOriginType.BINDING_DISCONNECT,
                origin_id=binding.id,
                operation=ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
                request_payload=session_presence_payload(
                    resource.labels,
                    state="left",
                ),
                status=ExternalChannelDeliveryStatus.PENDING,
                channel_action_id=None,
                binding_id=binding.id,
                provider_message_key=None,
                error_kind=None,
                error_summary=None,
                attempted_at=None,
                completed_at=None,
            )
            session.add(presence)
            await session.flush()
        works = list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelWork)
                    .where(
                        RDBExternalChannelWork.binding_id == binding.id,
                        RDBExternalChannelWork.status
                        == ExternalChannelWorkStatus.ACTIVE,
                    )
                    .with_for_update()
                )
            ).all()
        )
        for work in works:
            work.status = ExternalChannelWorkStatus.FINISHED
            work.finished_at = now
            work.state_revision += 1
            work.desired_progress_revision += 1
            work.desired_progress_payload = None
            if work.progress_provider_message_key is None:
                continue
            existing = await session.scalar(
                sa.select(RDBExternalChannelDeliveryAttempt).where(
                    RDBExternalChannelDeliveryAttempt.origin_type
                    == ExternalChannelDeliveryOriginType.BINDING_DISCONNECT,
                    RDBExternalChannelDeliveryAttempt.origin_id == binding.id,
                    RDBExternalChannelDeliveryAttempt.binding_id == binding.id,
                    RDBExternalChannelDeliveryAttempt.operation
                    == ExternalChannelDeliveryOperation.PROGRESS_DELETE,
                )
            )
            if existing is not None:
                continue
            attempt = RDBExternalChannelDeliveryAttempt(
                origin_type=ExternalChannelDeliveryOriginType.BINDING_DISCONNECT,
                origin_id=binding.id,
                operation=ExternalChannelDeliveryOperation.PROGRESS_DELETE,
                request_payload=_provider_payload(
                    resource.labels,
                    work.progress_provider_message_key,
                ),
                status=ExternalChannelDeliveryStatus.PENDING,
                channel_action_id=None,
                binding_id=binding.id,
                provider_message_key=work.progress_provider_message_key,
                error_kind=None,
                error_summary=None,
                attempted_at=None,
                completed_at=None,
            )
            session.add(attempt)
            await session.flush()
        await session.flush()
        return await self._pending_binding_disconnect_intent_ids(
            session,
            binding_id=binding.id,
        )

    @staticmethod
    async def _pending_binding_disconnect_intent_ids(
        session: AsyncSession,
        *,
        binding_id: str,
    ) -> tuple[str, ...]:
        """Return retryable disconnect intents before provider authority changes."""
        ids = await session.scalars(
            sa.select(RDBExternalChannelDeliveryAttempt.id)
            .where(
                RDBExternalChannelDeliveryAttempt.origin_type
                == ExternalChannelDeliveryOriginType.BINDING_DISCONNECT,
                RDBExternalChannelDeliveryAttempt.origin_id == binding_id,
                RDBExternalChannelDeliveryAttempt.binding_id == binding_id,
                RDBExternalChannelDeliveryAttempt.status
                == ExternalChannelDeliveryStatus.PENDING,
            )
            .order_by(RDBExternalChannelDeliveryAttempt.id)
        )
        return tuple(ids)


def _connection(
    connection: RDBExternalChannelConnection,
    route: RDBExternalChannelAgentRoute,
    *,
    agent_id: str | None = None,
) -> ManagedConnection:
    active_agent_id = route.agent_id if agent_id is None else agent_id
    if active_agent_id is None:
        raise RuntimeError(
            "Managed External Channel connection has no active Agent association."
        )
    return ManagedConnection(
        id=connection.id,
        route_id=route.id,
        agent_id=active_agent_id,
        provider=connection.provider,
        transport=connection.transport,
        status=connection.status,
        provider_app_id=connection.provider_app_id,
        provider_tenant_id=connection.provider_tenant_id,
        provider_bot_user_id=connection.provider_bot_user_id,
        open_access_enabled=route.open_access_enabled,
        credentials_configured=connection.encrypted_credentials is not None,
        capabilities=connection.capabilities,
        provider_config=connection.provider_config,
        last_verified_at=connection.last_verified_at,
        last_health_at=connection.last_health_at,
        last_health_code=connection.last_health_code,
        socket_gap_detected_at=connection.socket_gap_detected_at,
        socket_gap_reason=connection.socket_gap_reason,
        disconnected_at=connection.disconnected_at,
    )


def _multi_connection(
    connection: RDBExternalChannelConnection,
    *,
    active_agent_count: int,
    configured_default_count: int,
) -> ManagedMultiConnection:
    return ManagedMultiConnection(
        id=connection.id,
        provider=connection.provider,
        transport=connection.transport,
        app_mode=connection.app_mode,
        status=connection.status,
        provider_app_id=connection.provider_app_id,
        provider_tenant_id=connection.provider_tenant_id,
        provider_bot_user_id=connection.provider_bot_user_id,
        credentials_configured=connection.encrypted_credentials is not None,
        capabilities=connection.capabilities,
        provider_config=connection.provider_config,
        last_verified_at=connection.last_verified_at,
        last_health_at=connection.last_health_at,
        last_health_code=connection.last_health_code,
        socket_gap_detected_at=connection.socket_gap_detected_at,
        socket_gap_reason=connection.socket_gap_reason,
        disconnected_at=connection.disconnected_at,
        generation=connection.updated_at,
        active_agent_count=active_agent_count,
        configured_default_count=configured_default_count,
    )


def _multi_route(
    route: RDBExternalChannelAgentRoute,
    agent_name: str | None,
) -> ManagedMultiRoute:
    return ManagedMultiRoute(
        id=route.id,
        agent_id=route.agent_id,
        agent_id_snapshot=route.agent_id_snapshot,
        agent_name=agent_name,
        catalog_status=route.catalog_status,
        catalog_removed_at=route.catalog_removed_at,
        created_at=route.created_at,
        updated_at=route.updated_at,
    )


def _channel_default(
    channel_default: RDBExternalChannelChannelDefault,
    route: RDBExternalChannelAgentRoute,
    agent_name: str | None,
) -> ManagedChannelDefault:
    if channel_default.configured_by_user_id is None:
        raise ValueError(
            "Provider-authored channel defaults are not exposed before rollout."
        )
    return ManagedChannelDefault(
        id=channel_default.id,
        provider_channel_id=channel_default.provider_channel_id,
        route_id=route.id,
        agent_id=route.agent_id,
        agent_name=agent_name,
        status=channel_default.status,
        configured_by_user_id=channel_default.configured_by_user_id,
        invalidated_at=channel_default.invalidated_at,
        invalidation_reason=channel_default.invalidation_reason,
        created_at=channel_default.created_at,
        updated_at=channel_default.updated_at,
    )


def _resource_label(labels: dict[str, object] | None, fallback: str) -> str:
    labels = labels or {}
    for key in ("display_name", "channel_name", "label", "channel_id"):
        value = labels.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def _work(
    work: RDBExternalChannelWork,
    *,
    progress_delivery: RDBExternalChannelDeliveryAttempt | None,
) -> ManagedWork:
    tasks = [ExternalChannelWorkTask.model_validate(task) for task in work.tasks]
    return ManagedWork(
        id=work.id,
        status=work.status,
        title=work.title,
        tasks=[
            ManagedWorkTask(
                id=task.id,
                title=task.title,
                status=task.status,
                details=task.details,
                output=task.output,
                sources=[
                    ManagedWorkSource(url=source.url, label=source.label)
                    for source in task.sources
                ],
            )
            for task in tasks
        ],
        state_revision=work.state_revision,
        desired_progress_revision=work.desired_progress_revision,
        progress_projected=work.progress_provider_message_key is not None,
        projection_state=progress_projection_state(work, progress_delivery),
        finished_at=work.finished_at,
    )


def _delivery(delivery: RDBExternalChannelDeliveryAttempt) -> ManagedDelivery:
    return ManagedDelivery(
        id=delivery.id,
        operation=delivery.operation,
        status=delivery.status,
        error_kind=delivery.error_kind,
        error_summary=delivery.error_summary,
        attempted_at=delivery.attempted_at,
        completed_at=delivery.completed_at,
        created_at=delivery.created_at,
    )


def _grant(
    grant: RDBExternalChannelAccessGrant,
    principal: RDBExternalChannelPrincipal,
) -> ManagedGrant:
    return ManagedGrant(
        id=grant.id,
        agent_id=grant.agent_id,
        principal_id=grant.principal_id,
        principal_label=principal.display_name or principal.provider_user_id,
        principal_provider_user_id=principal.provider_user_id,
        scope=grant.scope,
        agent_session_id=grant.agent_session_id,
        created_at=grant.created_at,
        revoked_at=grant.revoked_at,
    )


def _block(
    block: RDBExternalChannelBlock,
    principal: RDBExternalChannelPrincipal,
) -> ManagedBlock:
    return ManagedBlock(
        id=block.id,
        agent_id=block.agent_id,
        principal_id=block.principal_id,
        principal_label=principal.display_name or principal.provider_user_id,
        principal_provider_user_id=principal.provider_user_id,
        reason=block.reason,
        created_at=block.created_at,
        removed_at=block.removed_at,
    )


def _reset_discord_configuration(
    connection: RDBExternalChannelConnection,
    *,
    provider_app_id: str,
    encrypted_credentials: str,
    provider_config: dict[str, object],
) -> None:
    """Invalidate every prior Discord authority fence before reactivation."""
    connection.provider_app_id = provider_app_id
    connection.provider_tenant_id = None
    connection.provider_bot_user_id = None
    connection.http_callback_selector_hash = None
    connection.encrypted_credentials = encrypted_credentials
    connection.capabilities = None
    connection.provider_config = provider_config
    connection.configuration_generation += 1
    connection.status = ExternalChannelConnectionStatus.CONFIGURING
    connection.last_verified_at = None
    connection.last_health_at = None
    connection.last_health_code = None
    connection.disconnected_at = None
    connection.socket_lease_owner = None
    connection.socket_lease_until = None
    connection.socket_heartbeat_at = None
    connection.socket_gap_detected_at = None
    connection.socket_gap_reason = None


async def _release_discord_app_claim(
    session: AsyncSession,
    *,
    connection_id: str,
) -> None:
    """Release every current Discord App claim owned by one connection."""
    await session.execute(
        sa.delete(RDBExternalChannelAppClaim).where(
            RDBExternalChannelAppClaim.provider == ExternalChannelProvider.DISCORD,
            RDBExternalChannelAppClaim.connection_id == connection_id,
        )
    )


def _provider_payload(
    labels: dict[str, object] | None,
    provider_message_key: str,
) -> dict[str, object]:
    labels = labels or {}
    channel_id = labels.get("channel_id")
    thread_ts = labels.get("thread_ts")
    if not isinstance(channel_id, str) or not isinstance(thread_ts, str):
        raise ValueError("External Channel resource has no provider target.")
    return {
        "channel_id": channel_id,
        "thread_ts": thread_ts,
        "provider_message_key": provider_message_key,
    }


def progress_projection_state(
    work: RDBExternalChannelWork,
    progress: RDBExternalChannelDeliveryAttempt | None,
) -> Literal[
    "synchronized",
    "missing",
    "stale",
    "delete_failed",
    "unknown",
    "none",
]:
    if progress is not None:
        if progress.status is ExternalChannelDeliveryStatus.UNKNOWN:
            return "unknown"
        if progress.status in {
            ExternalChannelDeliveryStatus.FAILED,
            ExternalChannelDeliveryStatus.NOT_ATTEMPTED,
        }:
            return (
                "delete_failed"
                if progress.operation
                is ExternalChannelDeliveryOperation.PROGRESS_DELETE
                else "stale"
            )
        if progress.status in {
            ExternalChannelDeliveryStatus.PENDING,
            ExternalChannelDeliveryStatus.ATTEMPTING,
        }:
            return "stale"
    if work.desired_progress_payload is not None:
        return (
            "missing" if work.progress_provider_message_key is None else "synchronized"
        )
    return "none" if work.progress_provider_message_key is None else "stale"
