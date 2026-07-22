"""External Channel persistence repository."""

import datetime
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar, cast

import sqlalchemy as sa
from azcommon.uuid import uuid7
from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelAccessGrantScope,
    ExternalChannelAccessRequestStatus,
    ExternalChannelBindingActivationStatus,
    ExternalChannelBindingStatus,
    ExternalChannelConnectionStatus,
    ExternalChannelDeliveryStatus,
    ExternalChannelEventEligibilityState,
    ExternalChannelEventStatus,
    ExternalChannelHydrationStatus,
    ExternalChannelMessageLifecycle,
    ExternalChannelMessageRevisionKind,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelResourceStatus,
    ExternalChannelRouteStatus,
    ExternalChannelTransport,
    ExternalChannelWorkStatus,
)
from azents.rdb.models.base import RDBModel
from azents.rdb.models.external_channel import (
    RDBExternalChannelAccessGrant,
    RDBExternalChannelAccessRequest,
    RDBExternalChannelAction,
    RDBExternalChannelAgentRoute,
    RDBExternalChannelBinding,
    RDBExternalChannelBlock,
    RDBExternalChannelConnection,
    RDBExternalChannelDeliveryAttempt,
    RDBExternalChannelEvent,
    RDBExternalChannelInvocationBatch,
    RDBExternalChannelInvocationBatchItem,
    RDBExternalChannelMessage,
    RDBExternalChannelMessageRevision,
    RDBExternalChannelPendingContext,
    RDBExternalChannelPrincipal,
    RDBExternalChannelResource,
    RDBExternalChannelWork,
)

from .data import (
    ExternalChannelAccessGrant,
    ExternalChannelAccessGrantCreate,
    ExternalChannelAccessRequest,
    ExternalChannelAccessRequestCreate,
    ExternalChannelAction,
    ExternalChannelActionCreate,
    ExternalChannelAgentRoute,
    ExternalChannelAgentRouteCreate,
    ExternalChannelBinding,
    ExternalChannelBindingCreate,
    ExternalChannelBlock,
    ExternalChannelBlockCreate,
    ExternalChannelConnection,
    ExternalChannelConnectionConfiguration,
    ExternalChannelConnectionCreate,
    ExternalChannelDeliveryAttempt,
    ExternalChannelDeliveryAttemptCreate,
    ExternalChannelEvent,
    ExternalChannelEventAdmission,
    ExternalChannelEventBoundary,
    ExternalChannelEventCreate,
    ExternalChannelInvocationBatch,
    ExternalChannelInvocationBatchCreate,
    ExternalChannelInvocationBatchItem,
    ExternalChannelInvocationBatchItemCreate,
    ExternalChannelInvocationProjectionItem,
    ExternalChannelMessage,
    ExternalChannelMessageCreate,
    ExternalChannelMessageRevision,
    ExternalChannelMessageRevisionCreate,
    ExternalChannelPendingContext,
    ExternalChannelPendingContextCreate,
    ExternalChannelPendingContextTrim,
    ExternalChannelPrincipal,
    ExternalChannelPrincipalCreate,
    ExternalChannelResource,
    ExternalChannelResourceCreate,
    ExternalChannelWork,
    ExternalChannelWorkCreate,
)

_RecordT = TypeVar("_RecordT", bound=BaseModel)


class ExternalChannelRepository:
    """Provider-generic SQLAlchemy repository for External Channel state."""

    async def create_connection(
        self,
        session: AsyncSession,
        create: ExternalChannelConnectionCreate,
    ) -> ExternalChannelConnection:
        """Create a Workspace-owned provider connection."""
        return ExternalChannelConnection.model_validate(
            await self._create(session, RDBExternalChannelConnection, create)
        )

    async def get_connection(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
    ) -> ExternalChannelConnection | None:
        """Fetch a connection by its stable identity."""
        rdb = await session.get(RDBExternalChannelConnection, connection_id)
        return self._as(ExternalChannelConnection, rdb)

    async def get_connection_by_http_callback_selector_hash(
        self,
        session: AsyncSession,
        *,
        http_callback_selector_hash: str,
    ) -> ExternalChannelConnection | None:
        """Fetch the sole HTTP callback candidate before signature verification."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelConnection).where(
                RDBExternalChannelConnection.http_callback_selector_hash
                == http_callback_selector_hash
            )
        )
        return self._as(ExternalChannelConnection, rdb)

    async def get_connection_configuration(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
    ) -> ExternalChannelConnectionConfiguration | None:
        """Fetch one internal connection configuration including ciphertext."""
        rdb = await session.get(RDBExternalChannelConnection, connection_id)
        return self._as(ExternalChannelConnectionConfiguration, rdb)

    async def get_connection_configuration_by_http_callback_selector_hash(
        self,
        session: AsyncSession,
        *,
        http_callback_selector_hash: str,
    ) -> ExternalChannelConnectionConfiguration | None:
        """Fetch the internal callback configuration selected by an opaque hash."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelConnection).where(
                RDBExternalChannelConnection.http_callback_selector_hash
                == http_callback_selector_hash
            )
        )
        return self._as(ExternalChannelConnectionConfiguration, rdb)

    async def update_connection_health(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        status: ExternalChannelConnectionStatus,
        provider_tenant_id: str | None,
        provider_bot_user_id: str | None,
        capabilities: dict[str, object] | None,
        checked_at: datetime.datetime,
    ) -> ExternalChannelConnection | None:
        """Update redacted provider identity and health after validation."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelConnection)
            .where(RDBExternalChannelConnection.id == connection_id)
            .with_for_update()
        )
        if rdb is None:
            return None
        rdb.status = status
        if provider_tenant_id is not None:
            rdb.provider_tenant_id = provider_tenant_id
        if provider_bot_user_id is not None:
            rdb.provider_bot_user_id = provider_bot_user_id
        if capabilities is not None:
            rdb.capabilities = capabilities
        rdb.last_health_at = checked_at
        if status is ExternalChannelConnectionStatus.ACTIVE:
            rdb.last_verified_at = checked_at
        await session.flush()
        await session.refresh(rdb, attribute_names=["updated_at"])
        return ExternalChannelConnection.model_validate(rdb)

    async def list_socket_connection_ids(
        self,
        session: AsyncSession,
    ) -> list[str]:
        """List Socket Mode connections eligible for manager ownership."""
        result = await session.scalars(
            sa.select(RDBExternalChannelConnection.id)
            .where(
                RDBExternalChannelConnection.transport
                == ExternalChannelTransport.SOCKET,
                RDBExternalChannelConnection.status.in_(
                    (
                        ExternalChannelConnectionStatus.ACTIVE,
                        ExternalChannelConnectionStatus.DEGRADED,
                    )
                ),
            )
            .order_by(RDBExternalChannelConnection.id)
        )
        return list(result)

    async def claim_socket_connection(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        lease_owner: str,
        now: datetime.datetime,
        lease_until: datetime.datetime,
    ) -> ExternalChannelConnectionConfiguration | None:
        """Claim one Socket Mode connection with an empty or expired lease."""
        result = await session.execute(
            sa.update(RDBExternalChannelConnection)
            .where(
                RDBExternalChannelConnection.id == connection_id,
                RDBExternalChannelConnection.transport
                == ExternalChannelTransport.SOCKET,
                RDBExternalChannelConnection.status.in_(
                    (
                        ExternalChannelConnectionStatus.ACTIVE,
                        ExternalChannelConnectionStatus.DEGRADED,
                    )
                ),
                sa.or_(
                    RDBExternalChannelConnection.socket_lease_owner == lease_owner,
                    RDBExternalChannelConnection.socket_lease_until.is_(None),
                    RDBExternalChannelConnection.socket_lease_until < now,
                ),
            )
            .values(
                socket_lease_owner=lease_owner,
                socket_lease_until=lease_until,
                socket_heartbeat_at=now,
            )
            .returning(RDBExternalChannelConnection)
        )
        rdb = result.scalar_one_or_none()
        return self._as(ExternalChannelConnectionConfiguration, rdb)

    async def renew_socket_connection_lease(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        lease_owner: str,
        now: datetime.datetime,
        lease_until: datetime.datetime,
    ) -> bool:
        """Renew a Socket Mode lease only for its current owner."""
        result = await session.execute(
            sa.update(RDBExternalChannelConnection)
            .where(
                RDBExternalChannelConnection.id == connection_id,
                RDBExternalChannelConnection.transport
                == ExternalChannelTransport.SOCKET,
                RDBExternalChannelConnection.status.in_(
                    (
                        ExternalChannelConnectionStatus.ACTIVE,
                        ExternalChannelConnectionStatus.DEGRADED,
                    )
                ),
                RDBExternalChannelConnection.socket_lease_owner == lease_owner,
                RDBExternalChannelConnection.socket_lease_until >= now,
            )
            .values(
                socket_lease_until=lease_until,
                socket_heartbeat_at=now,
            )
            .returning(RDBExternalChannelConnection.id)
        )
        return result.scalar_one_or_none() is not None

    async def release_socket_connection_lease(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        lease_owner: str,
        now: datetime.datetime,
        gap_reason: str | None,
        gap_status: ExternalChannelConnectionStatus | None,
    ) -> bool:
        """Release Socket ownership and record a visible delivery gap when present."""
        values: dict[str, object] = {
            "socket_lease_owner": None,
            "socket_lease_until": None,
            "socket_heartbeat_at": now,
        }
        if gap_reason is not None:
            if gap_status is None:
                raise ValueError("Socket gap status is required with a gap reason.")
            values.update(
                status=gap_status,
                socket_gap_detected_at=now,
                socket_gap_reason=gap_reason,
            )
        result = await session.execute(
            sa.update(RDBExternalChannelConnection)
            .where(
                RDBExternalChannelConnection.id == connection_id,
                RDBExternalChannelConnection.transport
                == ExternalChannelTransport.SOCKET,
                RDBExternalChannelConnection.status.in_(
                    (
                        ExternalChannelConnectionStatus.ACTIVE,
                        ExternalChannelConnectionStatus.DEGRADED,
                    )
                ),
                RDBExternalChannelConnection.socket_lease_owner == lease_owner,
                RDBExternalChannelConnection.socket_lease_until >= now,
            )
            .values(**values)
            .returning(RDBExternalChannelConnection.id)
        )
        return result.scalar_one_or_none() is not None

    async def record_socket_connection_gap(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        lease_owner: str,
        now: datetime.datetime,
        gap_reason: str,
    ) -> bool:
        """Record a visible Socket Mode gap while retaining current ownership."""
        result = await session.execute(
            sa.update(RDBExternalChannelConnection)
            .where(
                RDBExternalChannelConnection.id == connection_id,
                RDBExternalChannelConnection.transport
                == ExternalChannelTransport.SOCKET,
                RDBExternalChannelConnection.status.in_(
                    (
                        ExternalChannelConnectionStatus.ACTIVE,
                        ExternalChannelConnectionStatus.DEGRADED,
                    )
                ),
                RDBExternalChannelConnection.socket_lease_owner == lease_owner,
                RDBExternalChannelConnection.socket_lease_until >= now,
            )
            .values(
                status=ExternalChannelConnectionStatus.DEGRADED,
                socket_heartbeat_at=now,
                socket_gap_detected_at=now,
                socket_gap_reason=gap_reason,
            )
            .returning(RDBExternalChannelConnection.id)
        )
        return result.scalar_one_or_none() is not None

    async def mark_socket_connection_active(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        lease_owner: str,
        now: datetime.datetime,
    ) -> bool:
        """Mark a leased socket connected and clear its prior gap indicator."""
        result = await session.execute(
            sa.update(RDBExternalChannelConnection)
            .where(
                RDBExternalChannelConnection.id == connection_id,
                RDBExternalChannelConnection.transport
                == ExternalChannelTransport.SOCKET,
                RDBExternalChannelConnection.status.in_(
                    (
                        ExternalChannelConnectionStatus.ACTIVE,
                        ExternalChannelConnectionStatus.DEGRADED,
                    )
                ),
                RDBExternalChannelConnection.socket_lease_owner == lease_owner,
                RDBExternalChannelConnection.socket_lease_until >= now,
            )
            .values(
                status=ExternalChannelConnectionStatus.ACTIVE,
                socket_heartbeat_at=now,
                socket_gap_detected_at=None,
                socket_gap_reason=None,
            )
            .returning(RDBExternalChannelConnection.id)
        )
        return result.scalar_one_or_none() is not None

    async def socket_connection_owned_active(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        lease_owner: str,
        now: datetime.datetime,
    ) -> ExternalChannelConnection | None:
        """Verify an unexpired Socket owner before provider-event admission."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelConnection).where(
                RDBExternalChannelConnection.id == connection_id,
                RDBExternalChannelConnection.transport
                == ExternalChannelTransport.SOCKET,
                RDBExternalChannelConnection.status.in_(
                    (
                        ExternalChannelConnectionStatus.ACTIVE,
                        ExternalChannelConnectionStatus.DEGRADED,
                    )
                ),
                RDBExternalChannelConnection.socket_lease_owner == lease_owner,
                RDBExternalChannelConnection.socket_lease_until >= now,
            )
        )
        return self._as(ExternalChannelConnection, rdb)

    async def lock_connection(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
    ) -> ExternalChannelConnection | None:
        """Lock one connection for a connection-state transition."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelConnection)
            .where(RDBExternalChannelConnection.id == connection_id)
            .with_for_update()
        )
        return self._as(ExternalChannelConnection, rdb)

    async def terminate_connection_for_provider_event(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        status: ExternalChannelConnectionStatus,
        reason: str,
        now: datetime.datetime,
        required_socket_lease_owner: str | None,
    ) -> bool:
        """Fence routes and bindings after uninstall or credential revocation."""
        if status not in {
            ExternalChannelConnectionStatus.RECONNECT_REQUIRED,
            ExternalChannelConnectionStatus.DISCONNECTED,
        }:
            raise ValueError(
                "Provider termination requires a terminal connection state."
            )
        statement = sa.select(RDBExternalChannelConnection).where(
            RDBExternalChannelConnection.id == connection_id
        )
        if required_socket_lease_owner is not None:
            statement = statement.where(
                RDBExternalChannelConnection.transport
                == ExternalChannelTransport.SOCKET,
                RDBExternalChannelConnection.status.in_(
                    (
                        ExternalChannelConnectionStatus.ACTIVE,
                        ExternalChannelConnectionStatus.DEGRADED,
                    )
                ),
                RDBExternalChannelConnection.socket_lease_owner
                == required_socket_lease_owner,
                RDBExternalChannelConnection.socket_lease_until >= now,
            )
        connection = await session.scalar(statement.with_for_update())
        if connection is None:
            return False
        route_ids = sa.select(RDBExternalChannelAgentRoute.id).where(
            RDBExternalChannelAgentRoute.connection_id == connection_id
        )
        binding_ids = sa.select(RDBExternalChannelBinding.id).where(
            RDBExternalChannelBinding.route_id.in_(route_ids)
        )
        await session.execute(
            sa.update(RDBExternalChannelWork)
            .where(
                RDBExternalChannelWork.binding_id.in_(binding_ids),
                RDBExternalChannelWork.status == ExternalChannelWorkStatus.ACTIVE,
            )
            .values(
                status=ExternalChannelWorkStatus.FINISHED,
                finished_at=now,
            )
        )
        await session.execute(
            sa.update(RDBExternalChannelBinding)
            .where(
                RDBExternalChannelBinding.route_id.in_(route_ids),
                RDBExternalChannelBinding.status == ExternalChannelBindingStatus.ACTIVE,
            )
            .values(
                status=ExternalChannelBindingStatus.DISCONNECTED,
                disconnected_at=now,
                disconnect_reason=reason,
            )
        )
        await session.execute(
            sa.delete(RDBExternalChannelPendingContext).where(
                RDBExternalChannelPendingContext.route_id.in_(route_ids)
            )
        )
        await session.execute(
            sa.update(RDBExternalChannelAgentRoute)
            .where(
                RDBExternalChannelAgentRoute.connection_id == connection_id,
                RDBExternalChannelAgentRoute.status
                == ExternalChannelRouteStatus.ACTIVE,
            )
            .values(
                status=ExternalChannelRouteStatus.INACTIVE,
                deactivated_at=now,
            )
        )
        await session.execute(
            sa.update(RDBExternalChannelResource)
            .where(
                RDBExternalChannelResource.connection_id == connection_id,
                RDBExternalChannelResource.status
                == ExternalChannelResourceStatus.ACTIVE,
            )
            .values(
                status=ExternalChannelResourceStatus.UNAVAILABLE,
                unavailable_at=now,
            )
        )
        connection.status = status
        connection.disconnected_at = now
        connection.socket_lease_owner = None
        connection.socket_lease_until = None
        connection.socket_heartbeat_at = now
        connection.socket_gap_detected_at = now
        connection.socket_gap_reason = reason
        await session.flush()
        return True

    async def create_agent_route(
        self,
        session: AsyncSession,
        create: ExternalChannelAgentRouteCreate,
    ) -> ExternalChannelAgentRoute:
        """Create a route from a connection to one Agent."""
        return ExternalChannelAgentRoute.model_validate(
            await self._create(session, RDBExternalChannelAgentRoute, create)
        )

    async def get_active_route_by_connection_id(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
    ) -> ExternalChannelAgentRoute | None:
        """Fetch the active route selected for a connection."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelAgentRoute).where(
                RDBExternalChannelAgentRoute.connection_id == connection_id,
                RDBExternalChannelAgentRoute.status
                == ExternalChannelRouteStatus.ACTIVE,
            )
        )
        return self._as(ExternalChannelAgentRoute, rdb)

    async def get_agent_route(
        self,
        session: AsyncSession,
        *,
        route_id: str,
    ) -> ExternalChannelAgentRoute | None:
        """Fetch one Agent route by stable identity."""
        return self._as(
            ExternalChannelAgentRoute,
            await session.get(RDBExternalChannelAgentRoute, route_id),
        )

    async def create_resource_idempotent(
        self,
        session: AsyncSession,
        create: ExternalChannelResourceCreate,
    ) -> ExternalChannelResource:
        """Create or return one canonical provider resource."""
        rdb = await self._insert_or_lookup(
            session,
            RDBExternalChannelResource,
            create,
            lambda: session.scalar(
                sa.select(RDBExternalChannelResource).where(
                    RDBExternalChannelResource.connection_id == create.connection_id,
                    RDBExternalChannelResource.resource_type == create.resource_type,
                    RDBExternalChannelResource.provider_resource_key
                    == create.provider_resource_key,
                )
            ),
        )
        return ExternalChannelResource.model_validate(rdb)

    async def get_resource_by_provider_key(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        provider_resource_key: str,
    ) -> ExternalChannelResource | None:
        """Fetch one canonical resource by connection-scoped provider identity."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelResource).where(
                RDBExternalChannelResource.connection_id == connection_id,
                RDBExternalChannelResource.provider_resource_key
                == provider_resource_key,
            )
        )
        return self._as(ExternalChannelResource, rdb)

    async def get_resource(
        self,
        session: AsyncSession,
        *,
        resource_id: str,
    ) -> ExternalChannelResource | None:
        """Fetch one canonical external resource."""
        return self._as(
            ExternalChannelResource,
            await session.get(RDBExternalChannelResource, resource_id),
        )

    async def lock_resource(
        self,
        session: AsyncSession,
        *,
        resource_id: str,
    ) -> ExternalChannelResource | None:
        """Lock one resource before hydration or availability mutation."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelResource)
            .where(RDBExternalChannelResource.id == resource_id)
            .with_for_update()
        )
        return self._as(ExternalChannelResource, rdb)

    async def mark_resource_hydration_running(
        self,
        session: AsyncSession,
        *,
        resource_id: str,
        started_at: datetime.datetime,
    ) -> ExternalChannelResource | None:
        """Mark initial history hydration running while preserving its cursor."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelResource)
            .where(RDBExternalChannelResource.id == resource_id)
            .with_for_update()
        )
        if rdb is None:
            return None
        if rdb.hydration_status in {
            ExternalChannelHydrationStatus.COMPLETE,
            ExternalChannelHydrationStatus.BOUNDED,
            ExternalChannelHydrationStatus.INCOMPLETE,
        }:
            return ExternalChannelResource.model_validate(rdb)
        rdb.hydration_status = ExternalChannelHydrationStatus.RUNNING
        if rdb.hydration_started_at is None:
            rdb.hydration_started_at = started_at
        rdb.hydration_error_kind = None
        rdb.hydration_error_summary = None
        await session.flush()
        await session.refresh(rdb, attribute_names=["updated_at"])
        return ExternalChannelResource.model_validate(rdb)

    async def update_resource_hydration_cursor(
        self,
        session: AsyncSession,
        *,
        resource_id: str,
        cursor: str | None,
        high_watermark_position: str | None,
        latest_activity_at: datetime.datetime | None,
    ) -> ExternalChannelResource | None:
        """Persist one completed hydration page for retry-safe pagination."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelResource)
            .where(RDBExternalChannelResource.id == resource_id)
            .with_for_update()
        )
        if rdb is None:
            return None
        rdb.hydration_cursor = cursor
        if high_watermark_position is not None:
            if (
                rdb.hydration_high_watermark_position is None
                or high_watermark_position > rdb.hydration_high_watermark_position
            ):
                rdb.hydration_high_watermark_position = high_watermark_position
        if latest_activity_at is not None:
            if (
                rdb.latest_activity_at is None
                or latest_activity_at > rdb.latest_activity_at
            ):
                rdb.latest_activity_at = latest_activity_at
        await session.flush()
        await session.refresh(rdb, attribute_names=["updated_at"])
        return ExternalChannelResource.model_validate(rdb)

    async def complete_resource_hydration(
        self,
        session: AsyncSession,
        *,
        resource_id: str,
        status: ExternalChannelHydrationStatus,
        boundary: ExternalChannelEventBoundary,
        completed_at: datetime.datetime,
        error_kind: str | None,
        error_summary: str | None,
    ) -> ExternalChannelResource | None:
        """Record a terminal hydration outcome and reconciliation boundary."""
        if status not in {
            ExternalChannelHydrationStatus.COMPLETE,
            ExternalChannelHydrationStatus.BOUNDED,
            ExternalChannelHydrationStatus.INCOMPLETE,
        }:
            raise ValueError("Hydration completion requires a terminal status.")
        rdb = await session.scalar(
            sa.select(RDBExternalChannelResource)
            .where(RDBExternalChannelResource.id == resource_id)
            .with_for_update()
        )
        if rdb is None:
            return None
        rdb.hydration_status = status
        rdb.hydration_cursor = None
        rdb.reconciliation_boundary_received_at = boundary.received_at
        rdb.reconciliation_boundary_event_id = boundary.event_id
        rdb.hydration_error_kind = error_kind
        rdb.hydration_error_summary = error_summary
        rdb.hydration_completed_at = completed_at
        await session.flush()
        await session.refresh(rdb, attribute_names=["updated_at"])
        return ExternalChannelResource.model_validate(rdb)

    async def mark_resource_unavailable(
        self,
        session: AsyncSession,
        *,
        resource_id: str,
        now: datetime.datetime,
    ) -> bool:
        """Mark provider resource loss without deleting canonical history."""
        result = await session.execute(
            sa.update(RDBExternalChannelResource)
            .where(RDBExternalChannelResource.id == resource_id)
            .values(
                status=ExternalChannelResourceStatus.UNAVAILABLE,
                unavailable_at=now,
            )
            .returning(RDBExternalChannelResource.id)
        )
        return result.scalar_one_or_none() is not None

    async def terminate_resource_for_provider_loss(
        self,
        session: AsyncSession,
        *,
        resource_id: str,
        reason: str,
        now: datetime.datetime,
    ) -> bool:
        """Fence one unavailable resource and its Session-owned activity."""
        resource = await session.scalar(
            sa.select(RDBExternalChannelResource)
            .where(RDBExternalChannelResource.id == resource_id)
            .with_for_update()
        )
        if resource is None:
            return False
        binding_ids = sa.select(RDBExternalChannelBinding.id).where(
            RDBExternalChannelBinding.resource_id == resource_id
        )
        await session.execute(
            sa.update(RDBExternalChannelWork)
            .where(
                RDBExternalChannelWork.binding_id.in_(binding_ids),
                RDBExternalChannelWork.status == ExternalChannelWorkStatus.ACTIVE,
            )
            .values(
                status=ExternalChannelWorkStatus.FINISHED,
                finished_at=now,
            )
        )
        await session.execute(
            sa.update(RDBExternalChannelBinding)
            .where(
                RDBExternalChannelBinding.resource_id == resource_id,
                RDBExternalChannelBinding.status == ExternalChannelBindingStatus.ACTIVE,
            )
            .values(
                status=ExternalChannelBindingStatus.DISCONNECTED,
                disconnected_at=now,
                disconnect_reason=reason,
            )
        )
        await session.execute(
            sa.delete(RDBExternalChannelPendingContext).where(
                RDBExternalChannelPendingContext.resource_id == resource_id
            )
        )
        await session.execute(
            sa.update(RDBExternalChannelAccessRequest)
            .where(
                RDBExternalChannelAccessRequest.resource_id == resource_id,
                RDBExternalChannelAccessRequest.status
                == ExternalChannelAccessRequestStatus.PENDING,
            )
            .values(
                status=ExternalChannelAccessRequestStatus.EXPIRED,
                decision_summary="The external conversation became unavailable.",
                decided_at=now,
            )
        )
        resource.status = ExternalChannelResourceStatus.UNAVAILABLE
        resource.unavailable_at = now
        await session.flush()
        return True

    async def admit_event(
        self,
        session: AsyncSession,
        create: ExternalChannelEventCreate,
    ) -> ExternalChannelEventAdmission:
        """Atomically admit one provider event or return its prior admission."""
        result = await session.execute(
            pg_insert(RDBExternalChannelEvent)
            .values(id=uuid7().hex, **create.model_dump())
            .on_conflict_do_nothing(
                constraint="uq_external_channel_events_connection_provider_event"
            )
            .returning(RDBExternalChannelEvent)
        )
        rdb = result.scalar_one_or_none()
        if rdb is not None:
            await session.flush()
            return ExternalChannelEventAdmission(
                event=ExternalChannelEvent.model_validate(rdb),
                created=True,
            )
        existing = await self.get_event_by_provider_identity(
            session,
            connection_id=create.connection_id,
            provider_event_id=create.provider_event_id,
        )
        if existing is None:
            raise RuntimeError("External Channel event admission lookup failed")
        return ExternalChannelEventAdmission(event=existing, created=False)

    async def get_event_by_provider_identity(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        provider_event_id: str,
    ) -> ExternalChannelEvent | None:
        """Fetch a provider event by its durable connection-scoped identity."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelEvent).where(
                RDBExternalChannelEvent.connection_id == connection_id,
                RDBExternalChannelEvent.provider_event_id == provider_event_id,
            )
        )
        return self._as(ExternalChannelEvent, rdb)

    async def lock_event(
        self,
        session: AsyncSession,
        *,
        event_id: str,
    ) -> ExternalChannelEvent | None:
        """Lock one admitted event before a processor state transition."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelEvent)
            .where(RDBExternalChannelEvent.id == event_id)
            .with_for_update()
        )
        return self._as(ExternalChannelEvent, rdb)

    async def claim_events(
        self,
        session: AsyncSession,
        *,
        claim_owner: str,
        now: datetime.datetime,
        claim_until: datetime.datetime,
        limit: int,
    ) -> list[ExternalChannelEvent]:
        """Claim recoverable provider events in stable received order."""
        rows = list(
            await session.scalars(
                sa.select(RDBExternalChannelEvent)
                .where(
                    RDBExternalChannelEvent.status.in_(
                        (
                            ExternalChannelEventStatus.ACCEPTED,
                            ExternalChannelEventStatus.FAILED,
                        )
                    ),
                    sa.or_(
                        RDBExternalChannelEvent.claim_until.is_(None),
                        RDBExternalChannelEvent.claim_until <= now,
                    ),
                )
                .order_by(
                    RDBExternalChannelEvent.received_at,
                    RDBExternalChannelEvent.id,
                )
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        for row in rows:
            row.status = ExternalChannelEventStatus.PROCESSING
            row.claim_owner = claim_owner
            row.claim_until = claim_until
            row.attempt_count += 1
            row.processing_started_at = now
            row.error_kind = None
            row.error_summary = None
        await session.flush()
        for row in rows:
            await session.refresh(row, attribute_names=["updated_at"])
        return [ExternalChannelEvent.model_validate(row) for row in rows]

    async def complete_event(
        self,
        session: AsyncSession,
        *,
        event_id: str,
        claim_owner: str,
        now: datetime.datetime,
        eligibility_state: ExternalChannelEventEligibilityState,
        status: ExternalChannelEventStatus,
        purge_envelope: bool,
    ) -> bool:
        """Complete one event only while the caller still owns its claim."""
        values: dict[str, object] = {
            "eligibility_state": eligibility_state,
            "status": status,
            "claim_owner": None,
            "claim_until": None,
            "error_kind": None,
            "error_summary": None,
            "processed_at": now,
        }
        if purge_envelope:
            values["envelope"] = {}
        result = await session.execute(
            sa.update(RDBExternalChannelEvent)
            .where(
                RDBExternalChannelEvent.id == event_id,
                RDBExternalChannelEvent.status == ExternalChannelEventStatus.PROCESSING,
                RDBExternalChannelEvent.claim_owner == claim_owner,
                RDBExternalChannelEvent.claim_until >= now,
            )
            .values(**values)
            .returning(RDBExternalChannelEvent.id)
        )
        return result.scalar_one_or_none() is not None

    async def defer_event(
        self,
        session: AsyncSession,
        *,
        event_id: str,
        claim_owner: str,
        now: datetime.datetime,
        retry_at: datetime.datetime,
        error_kind: str,
        error_summary: str,
    ) -> bool:
        """Return a claimed event to accepted state for bounded reconciliation."""
        result = await session.execute(
            sa.update(RDBExternalChannelEvent)
            .where(
                RDBExternalChannelEvent.id == event_id,
                RDBExternalChannelEvent.status == ExternalChannelEventStatus.PROCESSING,
                RDBExternalChannelEvent.claim_owner == claim_owner,
                RDBExternalChannelEvent.claim_until >= now,
            )
            .values(
                status=ExternalChannelEventStatus.ACCEPTED,
                claim_owner=None,
                claim_until=retry_at,
                error_kind=error_kind,
                error_summary=error_summary,
            )
            .returning(RDBExternalChannelEvent.id)
        )
        return result.scalar_one_or_none() is not None

    async def fail_event(
        self,
        session: AsyncSession,
        *,
        event_id: str,
        claim_owner: str,
        now: datetime.datetime,
        retry_at: datetime.datetime,
        error_kind: str,
        error_summary: str,
    ) -> bool:
        """Record a recoverable processor failure without losing the event."""
        result = await session.execute(
            sa.update(RDBExternalChannelEvent)
            .where(
                RDBExternalChannelEvent.id == event_id,
                RDBExternalChannelEvent.status == ExternalChannelEventStatus.PROCESSING,
                RDBExternalChannelEvent.claim_owner == claim_owner,
                RDBExternalChannelEvent.claim_until >= now,
            )
            .values(
                status=ExternalChannelEventStatus.FAILED,
                claim_owner=None,
                claim_until=retry_at,
                error_kind=error_kind,
                error_summary=error_summary,
            )
            .returning(RDBExternalChannelEvent.id)
        )
        return result.scalar_one_or_none() is not None

    async def latest_correlated_event_boundary(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        resource_correlation_key: str,
    ) -> ExternalChannelEventBoundary | None:
        """Return the latest admitted boundary for one provider conversation."""
        row = await session.execute(
            sa.select(
                RDBExternalChannelEvent.received_at,
                RDBExternalChannelEvent.id,
            )
            .where(
                RDBExternalChannelEvent.connection_id == connection_id,
                RDBExternalChannelEvent.resource_correlation_key
                == resource_correlation_key,
            )
            .order_by(
                RDBExternalChannelEvent.received_at.desc(),
                RDBExternalChannelEvent.id.desc(),
            )
            .limit(1)
        )
        boundary = row.one_or_none()
        if boundary is None:
            return None
        return ExternalChannelEventBoundary(
            received_at=boundary.received_at,
            event_id=boundary.id,
        )

    async def correlated_event_count_before_boundary(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        resource_correlation_key: str,
        boundary: ExternalChannelEventBoundary,
        terminal: bool,
    ) -> int:
        """Count correlated events through a stable reconciliation boundary."""
        boundary_predicate = sa.or_(
            RDBExternalChannelEvent.received_at < boundary.received_at,
            sa.and_(
                RDBExternalChannelEvent.received_at == boundary.received_at,
                RDBExternalChannelEvent.id <= boundary.event_id,
            ),
        )
        status_predicate = (
            RDBExternalChannelEvent.status.in_(
                (
                    ExternalChannelEventStatus.PROCESSED,
                    ExternalChannelEventStatus.IGNORED_UNLINKED,
                )
            )
            if terminal
            else RDBExternalChannelEvent.status.not_in(
                (
                    ExternalChannelEventStatus.PROCESSED,
                    ExternalChannelEventStatus.IGNORED_UNLINKED,
                )
            )
        )
        return int(
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBExternalChannelEvent)
                .where(
                    RDBExternalChannelEvent.connection_id == connection_id,
                    RDBExternalChannelEvent.resource_correlation_key
                    == resource_correlation_key,
                    boundary_predicate,
                    status_predicate,
                )
            )
            or 0
        )

    async def create_principal_idempotent(
        self,
        session: AsyncSession,
        create: ExternalChannelPrincipalCreate,
    ) -> ExternalChannelPrincipal:
        """Upsert a canonical provider principal and its mutable safe profile."""
        observed_at = datetime.datetime.now(datetime.UTC)
        insert = pg_insert(RDBExternalChannelPrincipal).values(
            id=uuid7().hex,
            **create.model_dump(),
            last_observed_at=observed_at,
        )
        result = await session.execute(
            insert.on_conflict_do_update(
                constraint="uq_external_channel_principals_provider_tenant_user",
                set_={
                    "author_type": insert.excluded.author_type,
                    "display_name": insert.excluded.display_name,
                    "avatar_url": insert.excluded.avatar_url,
                    "profile": insert.excluded.profile,
                    "last_observed_at": observed_at,
                },
            ).returning(RDBExternalChannelPrincipal)
        )
        rdb: RDBExternalChannelPrincipal = result.scalar_one()
        return ExternalChannelPrincipal.model_validate(rdb)

    async def create_message_idempotent(
        self,
        session: AsyncSession,
        create: ExternalChannelMessageCreate,
    ) -> ExternalChannelMessage:
        """Create or return a canonical external message."""
        rdb = await self._insert_or_lookup(
            session,
            RDBExternalChannelMessage,
            create,
            lambda: session.scalar(
                sa.select(RDBExternalChannelMessage).where(
                    RDBExternalChannelMessage.resource_id == create.resource_id,
                    RDBExternalChannelMessage.provider_message_key
                    == create.provider_message_key,
                )
            ),
        )
        return ExternalChannelMessage.model_validate(rdb)

    async def get_message(
        self,
        session: AsyncSession,
        *,
        message_id: str,
    ) -> ExternalChannelMessage | None:
        """Fetch one canonical external message."""
        return self._as(
            ExternalChannelMessage,
            await session.get(RDBExternalChannelMessage, message_id),
        )

    async def get_message_by_provider_key(
        self,
        session: AsyncSession,
        *,
        resource_id: str,
        provider_message_key: str,
    ) -> ExternalChannelMessage | None:
        """Fetch a resource-scoped provider message identity."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelMessage).where(
                RDBExternalChannelMessage.resource_id == resource_id,
                RDBExternalChannelMessage.provider_message_key == provider_message_key,
            )
        )
        return self._as(ExternalChannelMessage, rdb)

    async def create_message_revision_idempotent(
        self,
        session: AsyncSession,
        create: ExternalChannelMessageRevisionCreate,
    ) -> ExternalChannelMessageRevision:
        """Create or return an immutable message revision."""
        rdb = await self._insert_or_lookup(
            session,
            RDBExternalChannelMessageRevision,
            create,
            lambda: session.scalar(
                sa.select(RDBExternalChannelMessageRevision).where(
                    RDBExternalChannelMessageRevision.message_id == create.message_id,
                    RDBExternalChannelMessageRevision.revision_key
                    == create.revision_key,
                )
            ),
        )
        return ExternalChannelMessageRevision.model_validate(rdb)

    async def apply_message_revision(
        self,
        session: AsyncSession,
        *,
        message_id: str,
        revision_id: str,
        principal_id: str | None,
        author_type: ExternalChannelPrincipalAuthorType,
        lifecycle: ExternalChannelMessageLifecycle,
        pending_size: int,
        provider_created_at: datetime.datetime | None,
        provider_updated_at: datetime.datetime | None,
        original_url: str | None,
    ) -> ExternalChannelMessage | None:
        """Make one non-stale immutable revision the provider-current state."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelMessage)
            .where(RDBExternalChannelMessage.id == message_id)
            .with_for_update()
        )
        if rdb is None:
            return None
        current_rank = _message_lifecycle_rank(rdb.lifecycle)
        incoming_rank = _message_lifecycle_rank(lifecycle)
        current_occurred_at = rdb.provider_updated_at or rdb.provider_created_at
        incoming_occurred_at = provider_updated_at or provider_created_at
        if incoming_rank < current_rank or (
            incoming_rank == current_rank
            and current_occurred_at is not None
            and (
                incoming_occurred_at is None
                or incoming_occurred_at < current_occurred_at
            )
        ):
            return ExternalChannelMessage.model_validate(rdb)
        rdb.current_revision_id = revision_id
        rdb.principal_id = principal_id
        rdb.author_type = author_type
        rdb.lifecycle = lifecycle
        rdb.pending_size = pending_size
        if provider_created_at is not None:
            rdb.provider_created_at = provider_created_at
        if provider_updated_at is not None:
            rdb.provider_updated_at = provider_updated_at
        if original_url is not None:
            rdb.original_url = original_url
        await session.flush()
        await session.refresh(rdb, attribute_names=["updated_at"])
        return ExternalChannelMessage.model_validate(rdb)

    async def create_pending_context_idempotent(
        self,
        session: AsyncSession,
        create: ExternalChannelPendingContextCreate,
    ) -> ExternalChannelPendingContext:
        """Create or return pending context for one message revision."""
        rdb = await self._insert_or_lookup(
            session,
            RDBExternalChannelPendingContext,
            create,
            lambda: session.scalar(
                sa.select(RDBExternalChannelPendingContext).where(
                    RDBExternalChannelPendingContext.route_id == create.route_id,
                    RDBExternalChannelPendingContext.resource_id == create.resource_id,
                    RDBExternalChannelPendingContext.message_revision_id
                    == create.message_revision_id,
                )
            ),
        )
        return ExternalChannelPendingContext.model_validate(rdb)

    async def trim_pending_context(
        self,
        session: AsyncSession,
        *,
        route_id: str,
        resource_id: str,
        now: datetime.datetime,
        max_message_count: int,
        max_size: int,
    ) -> ExternalChannelPendingContextTrim:
        """Expire and trim oldest pending context within both retention bounds."""
        if max_message_count <= 0 or max_size <= 0:
            raise ValueError("Pending-context limits must be positive.")
        rows = list(
            await session.scalars(
                sa.select(RDBExternalChannelPendingContext)
                .where(
                    RDBExternalChannelPendingContext.route_id == route_id,
                    RDBExternalChannelPendingContext.resource_id == resource_id,
                )
                .order_by(
                    RDBExternalChannelPendingContext.provider_position,
                    RDBExternalChannelPendingContext.id,
                )
                .with_for_update()
            )
        )
        deleted_count = 0
        deleted_size = 0
        retained = []
        for row in rows:
            if row.expires_at <= now:
                deleted_count += 1
                deleted_size += row.normalized_size
                await session.delete(row)
            else:
                retained.append(row)
        retained_size = sum(row.normalized_size for row in retained)
        while (
            len(retained) > max_message_count or retained_size > max_size
        ) and retained:
            removed = retained.pop(0)
            deleted_count += 1
            deleted_size += removed.normalized_size
            retained_size -= removed.normalized_size
            await session.delete(removed)
        await session.flush()
        return ExternalChannelPendingContextTrim(
            deleted_message_count=deleted_count,
            deleted_size=deleted_size,
            retained_message_count=len(retained),
            retained_size=retained_size,
        )

    async def list_pending_context(
        self,
        session: AsyncSession,
        *,
        route_id: str,
        resource_id: str,
        now: datetime.datetime,
        through_provider_position: str | None,
    ) -> list[ExternalChannelPendingContext]:
        """List unexpired pending context in deterministic provider order."""
        predicates = [
            RDBExternalChannelPendingContext.route_id == route_id,
            RDBExternalChannelPendingContext.resource_id == resource_id,
            RDBExternalChannelPendingContext.expires_at > now,
        ]
        if through_provider_position is not None:
            predicates.append(
                RDBExternalChannelPendingContext.provider_position
                <= through_provider_position
            )
        rows = await session.scalars(
            sa.select(RDBExternalChannelPendingContext)
            .where(*predicates)
            .order_by(
                RDBExternalChannelPendingContext.provider_position,
                RDBExternalChannelPendingContext.id,
            )
            .with_for_update()
        )
        return [ExternalChannelPendingContext.model_validate(row) for row in rows]

    async def delete_pending_context_ids(
        self,
        session: AsyncSession,
        *,
        pending_context_ids: list[str],
    ) -> int:
        """Delete released pending rows by their stable identities."""
        if not pending_context_ids:
            return 0
        result = cast(
            CursorResult[Any],
            await session.execute(
                sa.delete(RDBExternalChannelPendingContext).where(
                    RDBExternalChannelPendingContext.id.in_(pending_context_ids)
                )
            ),
        )
        return int(result.rowcount or 0)

    async def create_binding_idempotent(
        self,
        session: AsyncSession,
        create: ExternalChannelBindingCreate,
    ) -> ExternalChannelBinding:
        """Create or return the active binding for one resource and route."""
        rdb = await self._insert_or_lookup(
            session,
            RDBExternalChannelBinding,
            create,
            lambda: session.scalar(
                sa.select(RDBExternalChannelBinding).where(
                    RDBExternalChannelBinding.resource_id == create.resource_id,
                    RDBExternalChannelBinding.route_id == create.route_id,
                    RDBExternalChannelBinding.status
                    == ExternalChannelBindingStatus.ACTIVE,
                )
            ),
        )
        return ExternalChannelBinding.model_validate(rdb)

    async def get_active_binding_by_route_resource(
        self,
        session: AsyncSession,
        *,
        route_id: str,
        resource_id: str,
    ) -> ExternalChannelBinding | None:
        """Fetch the active binding for one route and external resource."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelBinding).where(
                RDBExternalChannelBinding.route_id == route_id,
                RDBExternalChannelBinding.resource_id == resource_id,
                RDBExternalChannelBinding.status == ExternalChannelBindingStatus.ACTIVE,
            )
        )
        return self._as(ExternalChannelBinding, rdb)

    async def lock_active_binding_by_route_resource(
        self,
        session: AsyncSession,
        *,
        route_id: str,
        resource_id: str,
    ) -> ExternalChannelBinding | None:
        """Lock the active binding before pending-context mutations."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelBinding)
            .where(
                RDBExternalChannelBinding.route_id == route_id,
                RDBExternalChannelBinding.resource_id == resource_id,
                RDBExternalChannelBinding.status == ExternalChannelBindingStatus.ACTIVE,
            )
            .with_for_update()
        )
        return self._as(ExternalChannelBinding, rdb)

    async def list_waiting_binding_ids(
        self,
        session: AsyncSession,
        *,
        limit: int,
    ) -> list[str]:
        """List active bindings waiting for hydration reconciliation."""
        result = await session.scalars(
            sa.select(RDBExternalChannelBinding.id)
            .where(
                RDBExternalChannelBinding.status == ExternalChannelBindingStatus.ACTIVE,
                RDBExternalChannelBinding.activation_status
                == ExternalChannelBindingActivationStatus.WAITING_HYDRATION,
            )
            .order_by(RDBExternalChannelBinding.connected_at)
            .limit(limit)
        )
        return list(result)

    async def lock_binding(
        self,
        session: AsyncSession,
        *,
        binding_id: str,
    ) -> ExternalChannelBinding | None:
        """Lock one Session-bound binding for an atomic transition."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelBinding)
            .where(RDBExternalChannelBinding.id == binding_id)
            .with_for_update()
        )
        return self._as(ExternalChannelBinding, rdb)

    async def mark_binding_activated(
        self,
        session: AsyncSession,
        *,
        binding_id: str,
        now: datetime.datetime,
        projected_through_position: str,
    ) -> ExternalChannelBinding | None:
        """Complete initial hydration activation after its invocation batch exists."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelBinding)
            .where(
                RDBExternalChannelBinding.id == binding_id,
                RDBExternalChannelBinding.status == ExternalChannelBindingStatus.ACTIVE,
            )
            .with_for_update()
        )
        if rdb is None:
            return None
        rdb.activation_status = ExternalChannelBindingActivationStatus.ACTIVE
        rdb.activated_at = now
        rdb.projected_through_position = projected_through_position
        rdb.truncated_message_count = 0
        rdb.truncated_size = 0
        await session.flush()
        await session.refresh(rdb, attribute_names=["updated_at"])
        return ExternalChannelBinding.model_validate(rdb)

    async def advance_binding_projection(
        self,
        session: AsyncSession,
        *,
        binding_id: str,
        projected_through_position: str,
    ) -> ExternalChannelBinding | None:
        """Advance one active binding after releasing authorized pending context."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelBinding)
            .where(
                RDBExternalChannelBinding.id == binding_id,
                RDBExternalChannelBinding.status == ExternalChannelBindingStatus.ACTIVE,
            )
            .with_for_update()
        )
        if rdb is None:
            return None
        if (
            rdb.projected_through_position is None
            or projected_through_position > rdb.projected_through_position
        ):
            rdb.projected_through_position = projected_through_position
        rdb.truncated_message_count = 0
        rdb.truncated_size = 0
        await session.flush()
        await session.refresh(rdb, attribute_names=["updated_at"])
        return ExternalChannelBinding.model_validate(rdb)

    async def record_binding_truncation(
        self,
        session: AsyncSession,
        *,
        binding_id: str,
        truncated_message_count: int,
        truncated_size: int,
    ) -> ExternalChannelBinding | None:
        """Accumulate pending-context omissions before their next release."""
        if truncated_message_count == 0 and truncated_size == 0:
            return await self.lock_binding(session, binding_id=binding_id)
        rdb = await session.scalar(
            sa.select(RDBExternalChannelBinding)
            .where(
                RDBExternalChannelBinding.id == binding_id,
                RDBExternalChannelBinding.status == ExternalChannelBindingStatus.ACTIVE,
            )
            .with_for_update()
        )
        if rdb is None:
            return None
        rdb.truncated_message_count += truncated_message_count
        rdb.truncated_size += truncated_size
        await session.flush()
        await session.refresh(rdb, attribute_names=["updated_at"])
        return ExternalChannelBinding.model_validate(rdb)

    async def create_invocation_batch_idempotent(
        self,
        session: AsyncSession,
        create: ExternalChannelInvocationBatchCreate,
    ) -> ExternalChannelInvocationBatch:
        """Create or return a binding-scoped trigger invocation batch."""
        rdb = await self._insert_or_lookup(
            session,
            RDBExternalChannelInvocationBatch,
            create,
            lambda: session.scalar(
                sa.select(RDBExternalChannelInvocationBatch).where(
                    RDBExternalChannelInvocationBatch.binding_id == create.binding_id,
                    RDBExternalChannelInvocationBatch.trigger_message_id
                    == create.trigger_message_id,
                )
            ),
        )
        return ExternalChannelInvocationBatch.model_validate(rdb)

    async def get_invocation_batch(
        self,
        session: AsyncSession,
        *,
        binding_id: str,
        trigger_message_id: str,
    ) -> ExternalChannelInvocationBatch | None:
        """Fetch an invocation identity independently from provider events."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelInvocationBatch).where(
                RDBExternalChannelInvocationBatch.binding_id == binding_id,
                RDBExternalChannelInvocationBatch.trigger_message_id
                == trigger_message_id,
            )
        )
        return self._as(ExternalChannelInvocationBatch, rdb)

    async def lock_invocation_batch(
        self,
        session: AsyncSession,
        *,
        batch_id: str,
    ) -> ExternalChannelInvocationBatch | None:
        """Lock one invocation batch before linking its session input."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelInvocationBatch)
            .where(RDBExternalChannelInvocationBatch.id == batch_id)
            .with_for_update()
        )
        return self._as(ExternalChannelInvocationBatch, rdb)

    async def link_invocation_batch_input_buffer(
        self,
        session: AsyncSession,
        *,
        batch_id: str,
        input_buffer_id: str,
    ) -> ExternalChannelInvocationBatch | None:
        """Link one batch to its idempotent reference-only InputBuffer."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelInvocationBatch)
            .where(RDBExternalChannelInvocationBatch.id == batch_id)
            .with_for_update()
        )
        if rdb is None:
            return None
        if rdb.input_buffer_id is None:
            rdb.input_buffer_id = input_buffer_id
            await session.flush()
        elif rdb.input_buffer_id != input_buffer_id:
            raise ValueError("Invocation batch is linked to another InputBuffer.")
        return ExternalChannelInvocationBatch.model_validate(rdb)

    async def create_invocation_batch_item_idempotent(
        self,
        session: AsyncSession,
        create: ExternalChannelInvocationBatchItemCreate,
    ) -> ExternalChannelInvocationBatchItem:
        """Create or return an immutable batch revision membership item."""
        rdb = await self._insert_or_lookup(
            session,
            RDBExternalChannelInvocationBatchItem,
            create,
            lambda: session.scalar(
                sa.select(RDBExternalChannelInvocationBatchItem).where(
                    RDBExternalChannelInvocationBatchItem.batch_id == create.batch_id,
                    RDBExternalChannelInvocationBatchItem.message_revision_id
                    == create.message_revision_id,
                )
            ),
        )
        return ExternalChannelInvocationBatchItem.model_validate(rdb)

    async def list_invocation_projection_items(
        self,
        session: AsyncSession,
        *,
        batch_id: str,
    ) -> list[ExternalChannelInvocationProjectionItem]:
        """Load one invocation batch in immutable provider order."""
        rows = await session.execute(
            sa.select(
                RDBExternalChannelInvocationBatch.id.label("batch_id"),
                RDBExternalChannelInvocationBatch.binding_id,
                RDBExternalChannelInvocationBatch.trigger_message_id,
                RDBExternalChannelInvocationBatch.truncation_message_count,
                RDBExternalChannelInvocationBatch.truncation_size,
                RDBExternalChannelInvocationBatchItem.sequence,
                RDBExternalChannelMessage.id.label("message_id"),
                RDBExternalChannelMessageRevision.id.label("revision_id"),
                RDBExternalChannelMessageRevision.revision_kind,
                RDBExternalChannelMessageRevision.normalized_body.label(
                    "revision_body"
                ),
                RDBExternalChannelMessageRevision.attachment_metadata,
                RDBExternalChannelMessageRevision.provider_occurred_at,
                RDBExternalChannelMessage.resource_id,
                RDBExternalChannelResource.provider_resource_key,
                RDBExternalChannelResource.resource_type,
                RDBExternalChannelResource.labels.label("resource_labels"),
                RDBExternalChannelConnection.provider,
                RDBExternalChannelConnection.provider_tenant_id,
                RDBExternalChannelMessage.provider_message_key,
                RDBExternalChannelMessage.provider_position,
                RDBExternalChannelMessage.principal_id,
                RDBExternalChannelPrincipal.provider_user_id,
                RDBExternalChannelPrincipal.display_name.label("sender_display_name"),
                RDBExternalChannelMessage.author_type,
                RDBExternalChannelMessage.provider_created_at,
                RDBExternalChannelMessage.provider_updated_at,
                RDBExternalChannelMessage.original_url,
                sa.case(
                    (
                        RDBExternalChannelMessageRevision.revision_kind
                        != ExternalChannelMessageRevisionKind.ORIGINAL,
                        sa.select(RDBExternalChannelMessageRevision.id)
                        .where(
                            RDBExternalChannelMessageRevision.message_id
                            == RDBExternalChannelMessage.id,
                            RDBExternalChannelMessageRevision.revision_kind
                            == ExternalChannelMessageRevisionKind.ORIGINAL,
                        )
                        .order_by(
                            RDBExternalChannelMessageRevision.created_at,
                            RDBExternalChannelMessageRevision.id,
                        )
                        .limit(1)
                        .scalar_subquery(),
                    ),
                    else_=None,
                ).label("correction_of_revision_id"),
            )
            .select_from(RDBExternalChannelInvocationBatch)
            .join(
                RDBExternalChannelInvocationBatchItem,
                RDBExternalChannelInvocationBatchItem.batch_id
                == RDBExternalChannelInvocationBatch.id,
            )
            .join(
                RDBExternalChannelMessageRevision,
                RDBExternalChannelMessageRevision.id
                == RDBExternalChannelInvocationBatchItem.message_revision_id,
            )
            .join(
                RDBExternalChannelMessage,
                RDBExternalChannelMessage.id
                == RDBExternalChannelMessageRevision.message_id,
            )
            .join(
                RDBExternalChannelBinding,
                RDBExternalChannelBinding.id
                == RDBExternalChannelInvocationBatch.binding_id,
            )
            .join(
                RDBExternalChannelResource,
                RDBExternalChannelResource.id == RDBExternalChannelBinding.resource_id,
            )
            .join(
                RDBExternalChannelConnection,
                RDBExternalChannelConnection.id
                == RDBExternalChannelResource.connection_id,
            )
            .outerjoin(
                RDBExternalChannelPrincipal,
                RDBExternalChannelPrincipal.id
                == RDBExternalChannelMessage.principal_id,
            )
            .where(RDBExternalChannelInvocationBatch.id == batch_id)
            .order_by(
                RDBExternalChannelInvocationBatchItem.sequence,
                RDBExternalChannelInvocationBatchItem.id,
            )
        )
        return [
            ExternalChannelInvocationProjectionItem.model_validate(row)
            for row in rows.mappings()
        ]

    async def create_access_request_idempotent(
        self,
        session: AsyncSession,
        create: ExternalChannelAccessRequestCreate,
    ) -> ExternalChannelAccessRequest:
        """Create or return an access request for a source message."""
        rdb = await self._insert_or_lookup(
            session,
            RDBExternalChannelAccessRequest,
            create,
            lambda: session.scalar(
                sa.select(RDBExternalChannelAccessRequest).where(
                    RDBExternalChannelAccessRequest.route_id == create.route_id,
                    RDBExternalChannelAccessRequest.source_message_id
                    == create.source_message_id,
                )
            ),
        )
        return ExternalChannelAccessRequest.model_validate(rdb)

    async def lock_access_request(
        self,
        session: AsyncSession,
        *,
        access_request_id: str,
    ) -> ExternalChannelAccessRequest | None:
        """Lock one access request before an idempotent decision."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelAccessRequest)
            .where(RDBExternalChannelAccessRequest.id == access_request_id)
            .with_for_update()
        )
        return self._as(ExternalChannelAccessRequest, rdb)

    async def get_access_request(
        self,
        session: AsyncSession,
        *,
        access_request_id: str,
    ) -> ExternalChannelAccessRequest | None:
        """Fetch one access request before acquiring shared-domain locks."""
        return self._as(
            ExternalChannelAccessRequest,
            await session.get(
                RDBExternalChannelAccessRequest,
                access_request_id,
            ),
        )

    async def record_pending_access_request_truncation(
        self,
        session: AsyncSession,
        *,
        route_id: str,
        resource_id: str,
        truncated_message_count: int,
        truncated_size: int,
    ) -> ExternalChannelAccessRequest | None:
        """Accumulate pre-binding omissions in the durable policy snapshot."""
        if truncated_message_count == 0 and truncated_size == 0:
            return None
        rdb = await session.scalar(
            sa.select(RDBExternalChannelAccessRequest)
            .where(
                RDBExternalChannelAccessRequest.route_id == route_id,
                RDBExternalChannelAccessRequest.resource_id == resource_id,
                RDBExternalChannelAccessRequest.status
                == ExternalChannelAccessRequestStatus.PENDING,
            )
            .order_by(RDBExternalChannelAccessRequest.created_at.desc())
            .limit(1)
            .with_for_update()
        )
        if rdb is None:
            return None
        snapshot = dict(rdb.decision_policy_snapshot)
        prior_count = snapshot.get("pending_truncation_message_count", 0)
        prior_size = snapshot.get("pending_truncation_size", 0)
        snapshot["pending_truncation_message_count"] = (
            int(prior_count) + truncated_message_count
            if isinstance(prior_count, int)
            else truncated_message_count
        )
        snapshot["pending_truncation_size"] = (
            int(prior_size) + truncated_size
            if isinstance(prior_size, int)
            else truncated_size
        )
        rdb.decision_policy_snapshot = snapshot
        await session.flush()
        await session.refresh(rdb, attribute_names=["updated_at"])
        return ExternalChannelAccessRequest.model_validate(rdb)

    async def decide_access_request(
        self,
        session: AsyncSession,
        *,
        access_request_id: str,
        status: ExternalChannelAccessRequestStatus,
        agent_session_id: str | None,
        decided_by_user_id: str,
        decision_summary: str | None,
        decided_at: datetime.datetime,
    ) -> ExternalChannelAccessRequest | None:
        """Persist one terminal approver decision while holding request identity."""
        if status not in {
            ExternalChannelAccessRequestStatus.ALLOWED,
            ExternalChannelAccessRequestStatus.DENIED,
            ExternalChannelAccessRequestStatus.BLOCKED,
        }:
            raise ValueError("Access decision must be terminal.")
        rdb = await session.scalar(
            sa.select(RDBExternalChannelAccessRequest)
            .where(RDBExternalChannelAccessRequest.id == access_request_id)
            .with_for_update()
        )
        if rdb is None:
            return None
        if rdb.status is not ExternalChannelAccessRequestStatus.PENDING:
            return ExternalChannelAccessRequest.model_validate(rdb)
        rdb.status = status
        rdb.agent_session_id = agent_session_id
        rdb.decided_by_user_id = decided_by_user_id
        rdb.decision_summary = decision_summary
        rdb.decided_at = decided_at
        await session.flush()
        await session.refresh(rdb, attribute_names=["updated_at"])
        return ExternalChannelAccessRequest.model_validate(rdb)

    async def expire_access_requests(
        self,
        session: AsyncSession,
        *,
        now: datetime.datetime,
        limit: int,
    ) -> int:
        """Expire bounded pending requests without provider side effects."""
        result = cast(
            CursorResult[Any],
            await session.execute(
                sa.update(RDBExternalChannelAccessRequest)
                .where(
                    RDBExternalChannelAccessRequest.id.in_(
                        sa.select(RDBExternalChannelAccessRequest.id)
                        .where(
                            RDBExternalChannelAccessRequest.status
                            == ExternalChannelAccessRequestStatus.PENDING,
                            RDBExternalChannelAccessRequest.expires_at <= now,
                        )
                        .order_by(RDBExternalChannelAccessRequest.expires_at)
                        .limit(limit)
                    )
                )
                .values(
                    status=ExternalChannelAccessRequestStatus.EXPIRED,
                    decided_at=now,
                    decision_summary="The access request expired.",
                )
            ),
        )
        return int(result.rowcount or 0)

    async def create_access_grant(
        self,
        session: AsyncSession,
        create: ExternalChannelAccessGrantCreate,
    ) -> ExternalChannelAccessGrant:
        """Create one durable access grant."""
        return ExternalChannelAccessGrant.model_validate(
            await self._create(session, RDBExternalChannelAccessGrant, create)
        )

    async def ensure_access_grant(
        self,
        session: AsyncSession,
        create: ExternalChannelAccessGrantCreate,
    ) -> ExternalChannelAccessGrant:
        """Create or return the active grant for one Agent or Session scope."""
        predicate = [
            RDBExternalChannelAccessGrant.agent_id == create.agent_id,
            RDBExternalChannelAccessGrant.principal_id == create.principal_id,
            RDBExternalChannelAccessGrant.scope == create.scope,
            RDBExternalChannelAccessGrant.revoked_at.is_(None),
        ]
        if create.scope is ExternalChannelAccessGrantScope.AGENT:
            predicate.append(RDBExternalChannelAccessGrant.agent_session_id.is_(None))
        else:
            if create.agent_session_id is None:
                raise ValueError("Session grant requires an AgentSession.")
            predicate.append(
                RDBExternalChannelAccessGrant.agent_session_id
                == create.agent_session_id
            )
        rdb = await self._insert_or_lookup(
            session,
            RDBExternalChannelAccessGrant,
            create,
            lambda: session.scalar(
                sa.select(RDBExternalChannelAccessGrant).where(*predicate)
            ),
        )
        return ExternalChannelAccessGrant.model_validate(rdb)

    async def get_active_access_grant(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        principal_id: str,
        agent_session_id: str | None,
    ) -> ExternalChannelAccessGrant | None:
        """Resolve Session scope first, then Agent scope for one principal."""
        scope_predicate = [
            sa.and_(
                RDBExternalChannelAccessGrant.scope
                == ExternalChannelAccessGrantScope.AGENT,
                RDBExternalChannelAccessGrant.agent_session_id.is_(None),
            )
        ]
        if agent_session_id is not None:
            scope_predicate.insert(
                0,
                sa.and_(
                    RDBExternalChannelAccessGrant.scope
                    == ExternalChannelAccessGrantScope.SESSION,
                    RDBExternalChannelAccessGrant.agent_session_id == agent_session_id,
                ),
            )
        rdb = await session.scalar(
            sa.select(RDBExternalChannelAccessGrant)
            .where(
                RDBExternalChannelAccessGrant.agent_id == agent_id,
                RDBExternalChannelAccessGrant.principal_id == principal_id,
                RDBExternalChannelAccessGrant.revoked_at.is_(None),
                sa.or_(*scope_predicate),
            )
            .order_by(
                sa.case(
                    (
                        RDBExternalChannelAccessGrant.scope
                        == ExternalChannelAccessGrantScope.SESSION,
                        0,
                    ),
                    else_=1,
                )
            )
            .limit(1)
        )
        return self._as(ExternalChannelAccessGrant, rdb)

    async def revoke_access_grant(
        self,
        session: AsyncSession,
        *,
        grant_id: str,
        revoked_by_user_id: str,
        revoked_at: datetime.datetime,
    ) -> ExternalChannelAccessGrant | None:
        """Revoke one grant without deleting its authorization history."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelAccessGrant)
            .where(RDBExternalChannelAccessGrant.id == grant_id)
            .with_for_update()
        )
        if rdb is None:
            return None
        if rdb.revoked_at is None:
            rdb.revoked_by_user_id = revoked_by_user_id
            rdb.revoked_at = revoked_at
            await session.flush()
        await session.refresh(rdb, attribute_names=["updated_at"])
        return ExternalChannelAccessGrant.model_validate(rdb)

    async def create_block_idempotent(
        self,
        session: AsyncSession,
        create: ExternalChannelBlockCreate,
    ) -> ExternalChannelBlock:
        """Create or reactivate the unique Agent-and-principal block record."""
        insert = pg_insert(RDBExternalChannelBlock).values(
            id=uuid7().hex,
            **create.model_dump(),
        )
        result = await session.execute(
            insert.on_conflict_do_update(
                constraint="uq_external_channel_blocks_agent_principal",
                set_={
                    "blocked_by_user_id": insert.excluded.blocked_by_user_id,
                    "reason": insert.excluded.reason,
                    "removed_by_user_id": None,
                    "removed_at": None,
                },
            ).returning(RDBExternalChannelBlock)
        )
        rdb: RDBExternalChannelBlock = result.scalar_one()
        return ExternalChannelBlock.model_validate(rdb)

    async def get_active_block(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        principal_id: str,
    ) -> ExternalChannelBlock | None:
        """Fetch an active Agent-level block overriding every grant."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelBlock).where(
                RDBExternalChannelBlock.agent_id == agent_id,
                RDBExternalChannelBlock.principal_id == principal_id,
                RDBExternalChannelBlock.removed_at.is_(None),
            )
        )
        return self._as(ExternalChannelBlock, rdb)

    async def remove_block(
        self,
        session: AsyncSession,
        *,
        block_id: str,
        removed_by_user_id: str,
        removed_at: datetime.datetime,
    ) -> ExternalChannelBlock | None:
        """Remove one active block while retaining its policy history."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelBlock)
            .where(RDBExternalChannelBlock.id == block_id)
            .with_for_update()
        )
        if rdb is None:
            return None
        if rdb.removed_at is None:
            rdb.removed_by_user_id = removed_by_user_id
            rdb.removed_at = removed_at
            await session.flush()
        await session.refresh(rdb, attribute_names=["updated_at"])
        return ExternalChannelBlock.model_validate(rdb)

    async def create_work_idempotent(
        self,
        session: AsyncSession,
        create: ExternalChannelWorkCreate,
    ) -> ExternalChannelWork:
        """Create or return active Channel Work for one binding."""
        rdb = await self._insert_or_lookup(
            session,
            RDBExternalChannelWork,
            create,
            lambda: session.scalar(
                sa.select(RDBExternalChannelWork).where(
                    RDBExternalChannelWork.binding_id == create.binding_id,
                    RDBExternalChannelWork.status == ExternalChannelWorkStatus.ACTIVE,
                )
            ),
        )
        return ExternalChannelWork.model_validate(rdb)

    async def ensure_active_work(
        self,
        session: AsyncSession,
        *,
        binding_id: str,
    ) -> ExternalChannelWork:
        """Create or return the active Channel Work for an invoked binding."""
        return await self.create_work_idempotent(
            session,
            ExternalChannelWorkCreate(
                binding_id=binding_id,
                status=ExternalChannelWorkStatus.ACTIVE,
                schema_version=1,
                tasks=[],
                state_revision=1,
                desired_progress_revision=0,
                desired_progress_payload=None,
                progress_provider_message_key=None,
                finished_at=None,
            ),
        )

    async def lock_work_by_binding_id(
        self,
        session: AsyncSession,
        *,
        binding_id: str,
    ) -> ExternalChannelWork | None:
        """Lock the active Channel Work for one binding."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelWork)
            .where(
                RDBExternalChannelWork.binding_id == binding_id,
                RDBExternalChannelWork.status == ExternalChannelWorkStatus.ACTIVE,
            )
            .with_for_update()
        )
        return self._as(ExternalChannelWork, rdb)

    async def create_action_idempotent(
        self,
        session: AsyncSession,
        create: ExternalChannelActionCreate,
    ) -> ExternalChannelAction:
        """Create or return the committed action for one durable tool call."""
        rdb = await self._insert_or_lookup(
            session,
            RDBExternalChannelAction,
            create,
            lambda: session.scalar(
                sa.select(RDBExternalChannelAction).where(
                    RDBExternalChannelAction.agent_session_id
                    == create.agent_session_id,
                    RDBExternalChannelAction.client_tool_call_id
                    == create.client_tool_call_id,
                )
            ),
        )
        return ExternalChannelAction.model_validate(rdb)

    async def create_delivery_attempt_idempotent(
        self,
        session: AsyncSession,
        create: ExternalChannelDeliveryAttemptCreate,
    ) -> ExternalChannelDeliveryAttempt:
        """Create or return a durable at-most-once provider operation intent."""
        predicate = [
            RDBExternalChannelDeliveryAttempt.origin_type == create.origin_type,
            RDBExternalChannelDeliveryAttempt.origin_id == create.origin_id,
            RDBExternalChannelDeliveryAttempt.operation == create.operation,
        ]
        if create.binding_id is None:
            predicate.append(RDBExternalChannelDeliveryAttempt.binding_id.is_(None))
        else:
            predicate.append(
                RDBExternalChannelDeliveryAttempt.binding_id == create.binding_id
            )
        rdb = await self._insert_or_lookup(
            session,
            RDBExternalChannelDeliveryAttempt,
            create,
            lambda: session.scalar(
                sa.select(RDBExternalChannelDeliveryAttempt).where(*predicate)
            ),
        )
        return ExternalChannelDeliveryAttempt.model_validate(rdb)

    async def delivery_provider_message_exists(
        self,
        session: AsyncSession,
        *,
        provider_message_key: str,
    ) -> bool:
        """Return whether a known provider operation owns the message identity."""
        exists = await session.scalar(
            sa.select(
                sa.exists().where(
                    RDBExternalChannelDeliveryAttempt.provider_message_key
                    == provider_message_key
                )
            )
        )
        return bool(exists)

    async def lock_delivery_attempt(
        self,
        session: AsyncSession,
        *,
        delivery_attempt_id: str,
    ) -> ExternalChannelDeliveryAttempt | None:
        """Lock one delivery ledger row before its sole provider attempt."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelDeliveryAttempt)
            .where(RDBExternalChannelDeliveryAttempt.id == delivery_attempt_id)
            .with_for_update()
        )
        return self._as(ExternalChannelDeliveryAttempt, rdb)

    async def start_delivery_attempt(
        self,
        session: AsyncSession,
        *,
        delivery_attempt_id: str,
        attempted_at: datetime.datetime,
    ) -> ExternalChannelDeliveryAttempt | None:
        """Commit the sole provider-attempt boundary before network I/O."""
        result = await session.execute(
            sa.update(RDBExternalChannelDeliveryAttempt)
            .where(
                RDBExternalChannelDeliveryAttempt.id == delivery_attempt_id,
                RDBExternalChannelDeliveryAttempt.status
                == ExternalChannelDeliveryStatus.PENDING,
            )
            .values(
                status=ExternalChannelDeliveryStatus.ATTEMPTING,
                attempted_at=attempted_at,
            )
            .returning(RDBExternalChannelDeliveryAttempt)
        )
        rdb = result.scalar_one_or_none()
        return self._as(ExternalChannelDeliveryAttempt, rdb)

    async def finish_delivery_attempt(
        self,
        session: AsyncSession,
        *,
        delivery_attempt_id: str,
        status: ExternalChannelDeliveryStatus,
        provider_message_key: str | None,
        error_kind: str | None,
        error_summary: str | None,
        completed_at: datetime.datetime,
    ) -> ExternalChannelDeliveryAttempt | None:
        """Record the transparent terminal result of one provider attempt."""
        if status not in {
            ExternalChannelDeliveryStatus.DELIVERED,
            ExternalChannelDeliveryStatus.FAILED,
            ExternalChannelDeliveryStatus.UNKNOWN,
            ExternalChannelDeliveryStatus.NOT_ATTEMPTED,
        }:
            raise ValueError("Delivery completion requires a terminal status.")
        result = await session.execute(
            sa.update(RDBExternalChannelDeliveryAttempt)
            .where(
                RDBExternalChannelDeliveryAttempt.id == delivery_attempt_id,
                RDBExternalChannelDeliveryAttempt.status
                == ExternalChannelDeliveryStatus.ATTEMPTING,
            )
            .values(
                status=status,
                provider_message_key=provider_message_key,
                error_kind=error_kind,
                error_summary=error_summary,
                completed_at=completed_at,
            )
            .returning(RDBExternalChannelDeliveryAttempt)
        )
        rdb = result.scalar_one_or_none()
        return self._as(ExternalChannelDeliveryAttempt, rdb)

    async def _create(
        self,
        session: AsyncSession,
        model: type[RDBModel],
        create: BaseModel,
    ) -> RDBModel:
        """Persist one new ORM record and flush generated fields."""
        rdb = model(**create.model_dump())
        session.add(rdb)
        await session.flush()
        return rdb

    async def _insert_or_lookup(
        self,
        session: AsyncSession,
        model: type[RDBModel],
        create: BaseModel,
        lookup: Callable[[], Awaitable[RDBModel | None]],
    ) -> RDBModel:
        """Insert idempotently, then load the unique conflicting record."""
        result = await session.execute(
            pg_insert(model)
            .values(id=uuid7().hex, **create.model_dump())
            .on_conflict_do_nothing()
            .returning(model)
        )
        rdb = result.scalar_one_or_none()
        if rdb is not None:
            await session.flush()
            return rdb
        existing = await lookup()
        if existing is None:
            raise RuntimeError("External Channel idempotent lookup failed")
        return existing

    @staticmethod
    def _as(model: type[_RecordT], rdb: object | None) -> _RecordT | None:
        """Build one immutable repository record when an ORM row exists."""
        if rdb is None:
            return None
        return model.model_validate(rdb)


def _message_lifecycle_rank(
    lifecycle: ExternalChannelMessageLifecycle,
) -> int:
    """Return monotonic provider lifecycle precedence."""
    return {
        ExternalChannelMessageLifecycle.CURRENT: 0,
        ExternalChannelMessageLifecycle.EDITED: 1,
        ExternalChannelMessageLifecycle.DELETED: 2,
    }[lifecycle]
