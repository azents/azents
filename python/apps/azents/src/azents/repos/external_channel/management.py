"""External Channel management queries and lifecycle mutations."""

import datetime
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentLifecycleStatus,
    ExternalChannelAccessGrantScope,
    ExternalChannelAppMode,
    ExternalChannelChannelDefaultStatus,
    ExternalChannelConnectionStatus,
    ExternalChannelConversationLocation,
    ExternalChannelInteractionStatus,
    ExternalChannelInteractionType,
    ExternalChannelParticipationSettingStatus,
    ExternalChannelProvider,
    ExternalChannelResourceType,
    ExternalChannelResponseMode,
    ExternalChannelRouteCatalogStatus,
    ExternalChannelSetupClaimStatus,
    ExternalChannelTransport,
    ExternalChannelWorkProjectionStatus,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.external_channel import (
    RDBExternalChannelAccessGrant,
    RDBExternalChannelAccessRequest,
    RDBExternalChannelAgentRoute,
    RDBExternalChannelAppClaim,
    RDBExternalChannelBinding,
    RDBExternalChannelBlock,
    RDBExternalChannelChannelDefault,
    RDBExternalChannelConnection,
    RDBExternalChannelInteraction,
    RDBExternalChannelParticipationSetting,
    RDBExternalChannelPrincipal,
    RDBExternalChannelResource,
    RDBExternalChannelSetupClaim,
)
from azents.repos.external_channel.management_data import (
    ManagedApprovalRequest,
    ManagedBinding,
    ManagedBlock,
    ManagedChannelDefault,
    ManagedConnection,
    ManagedGrant,
    ManagedMultiConnection,
    ManagedMultiRoute,
    ManagedSlackManagementHandoff,
    ManagedWork,
    ManagedWorkSource,
    ManagedWorkTask,
)
from azents.repos.external_channel.work import (
    projection_state,
    terminate_binding_with_plans,
)
from azents.repos.external_channel.work_state import (
    ChannelWorkState,
    ExternalChannelWorkStateStore,
)
from azents.repos.scheduled_task.lifecycle import ScheduledTaskLifecycleRepository
from azents.services.external_channel.provider_effect import ProviderEffectPlan


@dataclass(frozen=True)
class ExternalChannelChannelDefaultTransition:
    """Committed selected-Agent transition and independent cleanup intents."""

    channel_default: ManagedChannelDefault | None
    changed: bool
    invalidated_setting_count: int
    terminated_setup_claim_count: int
    expired_interaction_count: int
    disconnected_parent_binding_count: int
    cleanup_plans: tuple[ProviderEffectPlan, ...]


@dataclass(frozen=True)
class ExternalChannelBindingMutationScope:
    """Stable provider conversation scope required before binding mutation."""

    connection_id: str
    provider_parent_channel_id: str
    resource_type: ExternalChannelResourceType


class ExternalChannelManagementRepository:
    """Own safe management projections and explicit disconnect transitions."""

    @classmethod
    def create(cls) -> "ExternalChannelManagementRepository":
        """Create a management repository for application dependency injection."""
        return cls()

    def __init__(
        self,
        work_state_store: ExternalChannelWorkStateStore | None = None,
        scheduled_task_lifecycle_repository: ScheduledTaskLifecycleRepository
        | None = None,
    ) -> None:
        """Create the management repository."""
        self.work_state_store = work_state_store or ExternalChannelWorkStateStore()
        self.scheduled_task_lifecycle_repository = (
            scheduled_task_lifecycle_repository or ScheduledTaskLifecycleRepository()
        )

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
    ) -> ExternalChannelChannelDefaultTransition | None:
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
        if existing is not None and existing.route_id == route.id:
            return ExternalChannelChannelDefaultTransition(
                channel_default=_channel_default(existing, route, agent.name),
                changed=False,
                invalidated_setting_count=0,
                terminated_setup_claim_count=0,
                expired_interaction_count=0,
                disconnected_parent_binding_count=0,
                cleanup_plans=(),
            )
        transition = await self._terminalize_channel_participation(
            session,
            connection_id=connection.id,
            provider_parent_channel_id=provider_channel_id,
            old_route_id=None if existing is None else existing.route_id,
            now=now,
            reason="selected_agent_replaced",
            claim_status=ExternalChannelSetupClaimStatus.INVALIDATED,
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
        return ExternalChannelChannelDefaultTransition(
            channel_default=_channel_default(channel_default, route, agent.name),
            changed=True,
            invalidated_setting_count=transition.invalidated_setting_count,
            terminated_setup_claim_count=transition.terminated_setup_claim_count,
            expired_interaction_count=transition.expired_interaction_count,
            disconnected_parent_binding_count=(
                transition.disconnected_parent_binding_count
            ),
            cleanup_plans=transition.cleanup_plans,
        )

    async def clear_multi_channel_default(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        connection_id: str,
        provider: ExternalChannelProvider,
        provider_channel_id: str,
        now: datetime.datetime,
    ) -> ExternalChannelChannelDefaultTransition | None:
        """Invalidate one active default and all selected-Agent parent state."""
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
            return None
        transition = await self._terminalize_channel_participation(
            session,
            connection_id=connection.id,
            provider_parent_channel_id=provider_channel_id,
            old_route_id=channel_default.route_id,
            now=now,
            reason="selected_agent_cleared",
            claim_status=ExternalChannelSetupClaimStatus.EXPIRED,
        )
        channel_default.status = ExternalChannelChannelDefaultStatus.INVALIDATED
        channel_default.invalidated_at = now
        channel_default.invalidation_reason = "cleared"
        await session.flush()
        return transition

    async def _terminalize_channel_participation(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        provider_parent_channel_id: str,
        old_route_id: str | None,
        now: datetime.datetime,
        reason: str,
        claim_status: ExternalChannelSetupClaimStatus,
    ) -> ExternalChannelChannelDefaultTransition:
        """Terminalize only selected-Agent parent state in canonical lock order."""
        setting = await session.scalar(
            sa.select(RDBExternalChannelParticipationSetting)
            .where(
                RDBExternalChannelParticipationSetting.connection_id == connection_id,
                RDBExternalChannelParticipationSetting.provider_parent_channel_id
                == provider_parent_channel_id,
                RDBExternalChannelParticipationSetting.status
                == ExternalChannelParticipationSettingStatus.ACTIVE,
            )
            .with_for_update()
        )
        claim = await session.scalar(
            sa.select(RDBExternalChannelSetupClaim)
            .where(
                RDBExternalChannelSetupClaim.connection_id == connection_id,
                RDBExternalChannelSetupClaim.provider_parent_channel_id
                == provider_parent_channel_id,
                RDBExternalChannelSetupClaim.status.in_(
                    (
                        ExternalChannelSetupClaimStatus.PENDING_AGENT,
                        ExternalChannelSetupClaimStatus.PENDING_LOCATION,
                        ExternalChannelSetupClaimStatus.SELECTED,
                    )
                ),
            )
            .with_for_update()
        )
        interactions = list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelInteraction)
                    .where(
                        RDBExternalChannelInteraction.connection_id == connection_id,
                        RDBExternalChannelInteraction.status.in_(
                            (
                                ExternalChannelInteractionStatus.ACCEPTED,
                                ExternalChannelInteractionStatus.PROCESSING,
                                ExternalChannelInteractionStatus.COMPLETED,
                            )
                        ),
                        RDBExternalChannelInteraction.expires_at > now,
                        RDBExternalChannelInteraction.projection[
                            "provider_parent_channel_id"
                        ].as_string()
                        == provider_parent_channel_id,
                    )
                    .order_by(RDBExternalChannelInteraction.id)
                    .with_for_update()
                )
            ).all()
        )
        resource = await session.scalar(
            sa.select(RDBExternalChannelResource)
            .where(
                RDBExternalChannelResource.connection_id == connection_id,
                RDBExternalChannelResource.resource_type
                == ExternalChannelResourceType.PARENT_CHANNEL,
                RDBExternalChannelResource.provider_resource_key
                == provider_parent_channel_id,
            )
            .with_for_update()
        )
        binding = (
            None
            if resource is None or old_route_id is None
            else await session.scalar(
                sa.select(RDBExternalChannelBinding)
                .where(
                    RDBExternalChannelBinding.resource_id == resource.id,
                    RDBExternalChannelBinding.route_id == old_route_id,
                    RDBExternalChannelBinding.disconnected_at.is_(None),
                )
                .with_for_update()
            )
        )
        invalidated_setting_count = 0
        if setting is not None:
            setting.status = ExternalChannelParticipationSettingStatus.INVALIDATED
            setting.settings_generation += 1
            setting.invalidated_at = now
            setting.invalidation_reason = reason
            invalidated_setting_count = 1
        terminated_setup_claim_count = 0
        if claim is not None:
            claim.status = claim_status
            claim.claim_generation += 1
            terminated_setup_claim_count = 1
        for interaction in interactions:
            interaction.status = ExternalChannelInteractionStatus.EXPIRED
        cleanup_plans: tuple[ProviderEffectPlan, ...] = ()
        disconnected_parent_binding_count = 0
        if resource is not None and binding is not None:
            cleanup_plans = await self.terminate_binding(
                session,
                binding=binding,
                resource=resource,
                now=now,
                reason=reason,
            )
            disconnected_parent_binding_count = 1
        await session.flush()
        return ExternalChannelChannelDefaultTransition(
            channel_default=None,
            changed=True,
            invalidated_setting_count=invalidated_setting_count,
            terminated_setup_claim_count=terminated_setup_claim_count,
            expired_interaction_count=len(interactions),
            disconnected_parent_binding_count=disconnected_parent_binding_count,
            cleanup_plans=cleanup_plans,
        )

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
        work_states = await self.work_state_store.list_for_session(
            session,
            agent_id=agent_id,
            session_id=agent_session_id,
        )
        result: list[ManagedBinding] = []
        for binding, resource, connection in rows:
            work = work_states.get(binding.id)
            result.append(
                ManagedBinding(
                    id=binding.id,
                    agent_session_id=binding.agent_session_id,
                    provider=connection.provider,
                    response_mode=binding.response_mode,
                    resource_type=resource.resource_type,
                    conversation_location=(
                        ExternalChannelConversationLocation.CHANNEL
                        if resource.resource_type
                        is ExternalChannelResourceType.PARENT_CHANNEL
                        else ExternalChannelConversationLocation.THREADS
                    ),
                    resource_label=_resource_label(resource.labels, binding.id),
                    connected_at=binding.connected_at,
                    disconnected_at=binding.disconnected_at,
                    disconnect_reason=binding.disconnect_reason,
                    latest_activity_at=resource.latest_activity_at,
                    work=(None if work is None else _work(work)),
                )
            )
        return result

    async def get_binding_mutation_scope(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        agent_id: str,
        agent_session_id: str,
        binding_id: str,
    ) -> ExternalChannelBindingMutationScope | None:
        """Resolve the provider scope needed for a coordinated binding mutation."""
        row = (
            await session.execute(
                sa.select(
                    RDBExternalChannelAgentRoute.connection_id,
                    RDBExternalChannelResource.provider_resource_key,
                    RDBExternalChannelResource.resource_type,
                )
                .join(
                    RDBExternalChannelBinding,
                    RDBExternalChannelBinding.route_id
                    == RDBExternalChannelAgentRoute.id,
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
                    RDBExternalChannelBinding.disconnected_at.is_(None),
                    RDBAgentSession.workspace_id == workspace_id,
                    RDBAgentSession.agent_id == agent_id,
                )
            )
        ).one_or_none()
        if row is None:
            return None
        connection_id, provider_resource_key, resource_type = row
        return ExternalChannelBindingMutationScope(
            connection_id=connection_id,
            provider_parent_channel_id=provider_resource_key,
            resource_type=resource_type,
        )

    async def update_binding_response_mode(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        agent_id: str,
        agent_session_id: str,
        binding_id: str,
        configured_by_user_id: str,
        response_mode: ExternalChannelResponseMode,
    ) -> bool:
        """Update a thread Binding or one parent setting and Binding atomically."""
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
            )
        ).one_or_none()
        if snapshot is None:
            return False
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
            return False
        route = await session.scalar(
            sa.select(RDBExternalChannelAgentRoute)
            .where(
                RDBExternalChannelAgentRoute.id == route_id,
                RDBExternalChannelAgentRoute.connection_id == connection.id,
            )
            .with_for_update()
        )
        if route is None:
            return False
        resource = await session.scalar(
            sa.select(RDBExternalChannelResource)
            .where(
                RDBExternalChannelResource.id == resource_id,
                RDBExternalChannelResource.connection_id == connection.id,
            )
            .with_for_update()
        )
        if resource is None:
            return False
        binding = await session.scalar(
            sa.select(RDBExternalChannelBinding)
            .where(
                RDBExternalChannelBinding.id == binding_id,
                RDBExternalChannelBinding.route_id == route.id,
                RDBExternalChannelBinding.resource_id == resource.id,
                RDBExternalChannelBinding.agent_session_id == agent_session_id,
                RDBExternalChannelBinding.disconnected_at.is_(None),
            )
            .with_for_update()
        )
        if binding is None:
            return False
        if resource.resource_type is ExternalChannelResourceType.PARENT_CHANNEL:
            setting = await session.scalar(
                sa.select(RDBExternalChannelParticipationSetting)
                .where(
                    RDBExternalChannelParticipationSetting.connection_id
                    == connection.id,
                    RDBExternalChannelParticipationSetting.provider_parent_channel_id
                    == resource.provider_resource_key,
                    RDBExternalChannelParticipationSetting.route_id == route.id,
                    RDBExternalChannelParticipationSetting.status
                    == ExternalChannelParticipationSettingStatus.ACTIVE,
                )
                .with_for_update()
            )
            if setting is None:
                return False
            setting.response_mode = response_mode
            setting.settings_generation += 1
            setting.configured_by_user_id = configured_by_user_id
            setting.configured_by_principal_id = None
        binding.response_mode = response_mode
        await session.flush()
        return True

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
    ) -> tuple[ProviderEffectPlan, ...] | None:
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
        return await self.terminate_binding(
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
    ) -> tuple[ProviderEffectPlan, ...] | None:
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
        return await self.terminate_binding(
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
    ) -> tuple[ProviderEffectPlan, ...] | None:
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
        cleanup_plans: list[ProviderEffectPlan] = []
        for binding in bindings:
            resource = resources_by_id.get(binding.resource_id)
            if resource is None:
                continue
            cleanup_plans.extend(
                await self.terminate_binding(
                    session,
                    binding=binding,
                    resource=resource,
                    now=now,
                    reason="connection_disconnected",
                )
            )
        await session.flush()
        return tuple(cleanup_plans)

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

    async def terminate_binding(
        self,
        session: AsyncSession,
        *,
        binding: RDBExternalChannelBinding,
        resource: RDBExternalChannelResource,
        now: datetime.datetime,
        reason: str,
    ) -> tuple[ProviderEffectPlan, ...]:
        return await terminate_binding_with_plans(
            session,
            work_state_store=self.work_state_store,
            scheduled_task_lifecycle_repository=(
                self.scheduled_task_lifecycle_repository
            ),
            binding=binding,
            resource=resource,
            now=now,
            reason=reason,
            emit_leave_presence=True,
        )


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
    return ManagedChannelDefault(
        id=channel_default.id,
        provider_channel_id=channel_default.provider_channel_id,
        route_id=route.id,
        agent_id=route.agent_id,
        agent_name=agent_name,
        status=channel_default.status,
        configured_by_user_id=channel_default.configured_by_user_id,
        configured_by_principal_id=channel_default.configured_by_principal_id,
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


def _work(work: ChannelWorkState) -> ManagedWork:
    return ManagedWork(
        id=work.work_cycle_id,
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
            for task in work.tasks
        ],
        state_revision=work.state_revision,
        desired_progress_revision=work.desired_progress_revision,
        progress_projected=any(
            part.status is ExternalChannelWorkProjectionStatus.PRESENT
            and part.provider_message_key is not None
            for part in work.projection_parts
        ),
        projection_state=projection_state(work),
        finished_at=work.finished_at,
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
