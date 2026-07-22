"""External Channel management queries and lifecycle mutations."""

import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from azents.core.enums import (
    ExternalChannelAccessGrantScope,
    ExternalChannelBindingStatus,
    ExternalChannelConnectionStatus,
    ExternalChannelDeliveryOperation,
    ExternalChannelDeliveryOriginType,
    ExternalChannelDeliveryStatus,
    ExternalChannelRouteStatus,
    ExternalChannelTransport,
    ExternalChannelWorkStatus,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.external_channel import (
    RDBExternalChannelAccessGrant,
    RDBExternalChannelAccessRequest,
    RDBExternalChannelAgentRoute,
    RDBExternalChannelBinding,
    RDBExternalChannelBlock,
    RDBExternalChannelConnection,
    RDBExternalChannelDeliveryAttempt,
    RDBExternalChannelMessage,
    RDBExternalChannelMessageRevision,
    RDBExternalChannelPendingContext,
    RDBExternalChannelPrincipal,
    RDBExternalChannelResource,
    RDBExternalChannelWork,
)
from azents.repos.external_channel.management_data import (
    ManagedApprovalRequest,
    ManagedBinding,
    ManagedBlock,
    ManagedConnection,
    ManagedDelivery,
    ManagedGrant,
    ManagedWork,
)


class ExternalChannelManagementRepository:
    """Own safe management projections and explicit disconnect transitions."""

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
                )
                .order_by(RDBExternalChannelConnection.created_at)
            )
        ).all()
        return [_connection(connection, route) for connection, route in rows]

    async def get_connection(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        agent_id: str,
        connection_id: str,
        lock: bool = False,
    ) -> tuple[RDBExternalChannelConnection, RDBExternalChannelAgentRoute] | None:
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
                RDBExternalChannelAgentRoute.agent_id == agent_id,
            )
        )
        if lock:
            statement = statement.with_for_update()
        row = (await session.execute(statement)).one_or_none()
        return None if row is None else (row[0], row[1])

    async def switch_transport(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        agent_id: str,
        connection_id: str,
        transport: ExternalChannelTransport,
        selector_hash: str | None,
    ) -> ManagedConnection | None:
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
        if connection.status is ExternalChannelConnectionStatus.DISCONNECTED:
            raise ValueError(
                "Disconnected External Channel connections cannot switch transport."
            )
        connection.transport = transport
        connection.http_callback_selector_hash = selector_hash
        connection.status = ExternalChannelConnectionStatus.CONFIGURING
        connection.socket_lease_owner = None
        connection.socket_lease_until = None
        connection.socket_heartbeat_at = None
        connection.socket_gap_detected_at = None
        connection.socket_gap_reason = None
        await session.flush()
        return _connection(connection, route)

    async def replace_credentials(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        agent_id: str,
        connection_id: str,
        encrypted_credentials: str,
    ) -> ManagedConnection | None:
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
        if connection.status is ExternalChannelConnectionStatus.DISCONNECTED:
            raise ValueError(
                "Disconnected External Channel connections cannot reconnect."
            )
        connection.encrypted_credentials = encrypted_credentials
        connection.status = ExternalChannelConnectionStatus.CONFIGURING
        connection.disconnected_at = None
        await session.flush()
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
            result.append(
                ManagedBinding(
                    id=binding.id,
                    agent_session_id=binding.agent_session_id,
                    provider=connection.provider,
                    resource_type=resource.resource_type.value,
                    resource_label=_resource_label(resource.labels, binding.id),
                    status=binding.status,
                    activation_status=binding.activation_status,
                    truncated_message_count=binding.truncated_message_count,
                    truncated_size=binding.truncated_size,
                    connected_at=binding.connected_at,
                    disconnected_at=binding.disconnected_at,
                    disconnect_reason=binding.disconnect_reason,
                    latest_activity_at=resource.latest_activity_at,
                    work=None if work is None else _work(work),
                    deliveries=[_delivery(item) for item in deliveries],
                )
            )
        return result

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
        row = (
            await session.execute(
                sa.select(
                    RDBExternalChannelBinding,
                    RDBExternalChannelResource,
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
                .with_for_update()
            )
        ).one_or_none()
        if row is None:
            return None
        binding, resource = row
        return await self._terminate_binding(
            session,
            binding=binding,
            resource=resource,
            now=now,
            reason=reason,
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
        )
        if row is None:
            return None
        connection, route = row
        if connection.status is ExternalChannelConnectionStatus.DISCONNECTED:
            return ()
        connection.status = ExternalChannelConnectionStatus.DISCONNECTING
        route.status = ExternalChannelRouteStatus.INACTIVE
        route.deactivated_at = now
        bindings = list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelBinding)
                    .where(
                        RDBExternalChannelBinding.route_id == route.id,
                        RDBExternalChannelBinding.status
                        == ExternalChannelBindingStatus.ACTIVE,
                    )
                    .order_by(RDBExternalChannelBinding.id)
                    .with_for_update()
                )
            ).all()
        )
        cleanup_ids: list[str] = []
        for binding in bindings:
            resource = await session.get(
                RDBExternalChannelResource,
                binding.resource_id,
            )
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
        connection.encrypted_credentials = None
        connection.status = ExternalChannelConnectionStatus.DISCONNECTED
        connection.disconnected_at = now
        connection.socket_lease_owner = None
        connection.socket_lease_until = None
        await session.flush()
        return _connection(connection, route)

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

    async def get_approval_request(
        self,
        session: AsyncSession,
        *,
        access_request_id: str,
    ) -> ManagedApprovalRequest | None:
        revision = aliased(RDBExternalChannelMessageRevision)
        row = (
            await session.execute(
                sa.select(
                    RDBExternalChannelAccessRequest,
                    RDBExternalChannelAgentRoute,
                    RDBExternalChannelConnection,
                    RDBExternalChannelResource,
                    RDBExternalChannelPrincipal,
                    RDBExternalChannelMessage,
                    revision,
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
                    RDBExternalChannelMessage,
                    RDBExternalChannelMessage.id
                    == RDBExternalChannelAccessRequest.source_message_id,
                )
                .outerjoin(
                    revision,
                    revision.id == RDBExternalChannelMessage.current_revision_id,
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
        request, route, connection, resource, principal, message, current, agent = row
        return ManagedApprovalRequest(
            id=request.id,
            agent_id=route.agent_id,
            workspace_id=agent.workspace_id,
            agent_session_id=request.agent_session_id,
            provider=connection.provider,
            status=request.status,
            principal_id=principal.id,
            principal_label=(principal.display_name or principal.provider_user_id),
            resource_label=_resource_label(resource.labels, resource.id),
            source_text=None if current is None else current.normalized_body,
            original_url=message.original_url,
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
        if binding.status is ExternalChannelBindingStatus.DISCONNECTED:
            return ()
        binding.status = ExternalChannelBindingStatus.DISCONNECTED
        binding.disconnected_at = now
        binding.disconnect_reason = reason
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
        cleanup_ids: list[str] = []
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
            cleanup_ids.append(attempt.id)
        await session.execute(
            sa.delete(RDBExternalChannelPendingContext).where(
                RDBExternalChannelPendingContext.route_id == binding.route_id,
                RDBExternalChannelPendingContext.resource_id == binding.resource_id,
            )
        )
        await session.flush()
        return tuple(cleanup_ids)


def _connection(
    connection: RDBExternalChannelConnection,
    route: RDBExternalChannelAgentRoute,
) -> ManagedConnection:
    return ManagedConnection(
        id=connection.id,
        route_id=route.id,
        agent_id=route.agent_id,
        provider=connection.provider,
        transport=connection.transport,
        status=connection.status,
        route_status=route.status,
        provider_app_id=connection.provider_app_id,
        provider_tenant_id=connection.provider_tenant_id,
        provider_bot_user_id=connection.provider_bot_user_id,
        credentials_configured=connection.encrypted_credentials is not None,
        capabilities=connection.capabilities,
        last_verified_at=connection.last_verified_at,
        last_health_at=connection.last_health_at,
        socket_gap_detected_at=connection.socket_gap_detected_at,
        socket_gap_reason=connection.socket_gap_reason,
        disconnected_at=connection.disconnected_at,
    )


def _resource_label(labels: dict[str, object] | None, fallback: str) -> str:
    labels = labels or {}
    for key in ("display_name", "channel_name", "label", "channel_id"):
        value = labels.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def _work(work: RDBExternalChannelWork) -> ManagedWork:
    return ManagedWork(
        id=work.id,
        status=work.status,
        tasks=list(work.tasks),
        state_revision=work.state_revision,
        desired_progress_revision=work.desired_progress_revision,
        progress_projected=work.progress_provider_message_key is not None,
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
        reason=block.reason,
        created_at=block.created_at,
        removed_at=block.removed_at,
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
