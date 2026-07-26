"""External Channel persistence repository."""

import datetime
import json
import re
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar, cast

import sqlalchemy as sa
from azcommon.uuid import uuid7
from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from azents.core.enums import (
    AgentLifecycleStatus,
    AgentSessionKind,
    ExternalChannelAccessGrantScope,
    ExternalChannelAccessRequestStatus,
    ExternalChannelAppMode,
    ExternalChannelBindingActivationStatus,
    ExternalChannelBindingStatus,
    ExternalChannelChannelDefaultStatus,
    ExternalChannelConnectionStatus,
    ExternalChannelConversationAdmissionStatus,
    ExternalChannelDeliveryOperation,
    ExternalChannelDeliveryOriginType,
    ExternalChannelDeliveryStatus,
    ExternalChannelEventEligibilityState,
    ExternalChannelEventStatus,
    ExternalChannelHydrationStatus,
    ExternalChannelInteractionStatus,
    ExternalChannelMessageLifecycle,
    ExternalChannelMessageRevisionKind,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelRouteCatalogStatus,
    ExternalChannelRouteMode,
    ExternalChannelTransport,
    ExternalChannelWorkStatus,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.base import RDBModel
from azents.rdb.models.external_channel import (
    RDBExternalChannelAccessGrant,
    RDBExternalChannelAccessRequest,
    RDBExternalChannelAction,
    RDBExternalChannelAgentRoute,
    RDBExternalChannelBinding,
    RDBExternalChannelBlock,
    RDBExternalChannelChannelDefault,
    RDBExternalChannelConnection,
    RDBExternalChannelConversationAdmission,
    RDBExternalChannelDeliveryAttempt,
    RDBExternalChannelEvent,
    RDBExternalChannelInteraction,
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
    ExternalChannelCatalogRoute,
    ExternalChannelChannelDefault,
    ExternalChannelChannelDefaultCreate,
    ExternalChannelConnection,
    ExternalChannelConnectionConfiguration,
    ExternalChannelConnectionCreate,
    ExternalChannelConversationAdmission,
    ExternalChannelConversationAdmissionCreate,
    ExternalChannelDeliveryAttempt,
    ExternalChannelDeliveryAttemptCreate,
    ExternalChannelEvent,
    ExternalChannelEventAdmission,
    ExternalChannelEventBoundary,
    ExternalChannelEventCreate,
    ExternalChannelInteraction,
    ExternalChannelInteractionAdmission,
    ExternalChannelInteractionCreate,
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

_MAX_INTERACTION_PROJECTION_BYTES = 16 * 1024
_MAX_INTERACTION_PROJECTION_DEPTH = 4
_MAX_INTERACTION_PROJECTION_ENTRIES = 64
_MAX_INTERACTION_PROJECTION_KEY_LENGTH = 128
_MAX_INTERACTION_PROJECTION_STRING_LENGTH = 2048
_FORBIDDEN_INTERACTION_PROJECTION_KEY_PARTS = (
    "token",
    "secret",
    "authorization",
    "cookie",
    "responseurl",
    "rawbody",
    "body",
    "payload",
    "messagetext",
    "messagebody",
    "content",
    "filebytes",
    "attachment",
)
_FORBIDDEN_INTERACTION_PROJECTION_VALUE_PATTERNS = (
    re.compile(r"(?i)(?:https?|slack)://"),
    re.compile(r"(?i)(?:^|[^a-z0-9])(?:xox[a-z]?|xapp|xoxe|xoxs)-[a-z0-9-]+"),
    re.compile(r"(?i)^\s*(?:bearer|basic)\s+\S+"),
    re.compile(r"(?i)^\s*cookie\s*:\s*\S+"),
)
_INTERACTION_OPAQUE_VALUE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/=@+-]*$")


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

    async def get_connection_configuration(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
    ) -> ExternalChannelConnectionConfiguration | None:
        """Fetch one internal connection configuration including ciphertext."""
        rdb = await session.get(RDBExternalChannelConnection, connection_id)
        return self._as(ExternalChannelConnectionConfiguration, rdb)

    async def get_slack_http_configuration_by_provider_identity(
        self,
        session: AsyncSession,
        *,
        provider_app_id: str,
        provider_tenant_id: str,
    ) -> ExternalChannelConnectionConfiguration | None:
        """Fetch one callback candidate selected by untrusted provider identity."""
        rows = list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelConnection)
                    .where(
                        RDBExternalChannelConnection.provider
                        == ExternalChannelProvider.SLACK,
                        RDBExternalChannelConnection.transport
                        == ExternalChannelTransport.HTTP,
                        RDBExternalChannelConnection.provider_app_id == provider_app_id,
                        RDBExternalChannelConnection.provider_tenant_id
                        == provider_tenant_id,
                        RDBExternalChannelConnection.status.in_(
                            (
                                ExternalChannelConnectionStatus.ACTIVE,
                                ExternalChannelConnectionStatus.DEGRADED,
                            )
                        ),
                    )
                    .limit(2)
                )
            )
        )
        if len(rows) != 1:
            return None
        return ExternalChannelConnectionConfiguration.model_validate(rows[0])

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
        expected_encrypted_credentials: str,
    ) -> ExternalChannelConnection | None:
        """Update redacted provider identity and health after validation."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelConnection)
            .where(
                RDBExternalChannelConnection.id == connection_id,
                RDBExternalChannelConnection.encrypted_credentials
                == expected_encrypted_credentials,
                RDBExternalChannelConnection.status.not_in(
                    (
                        ExternalChannelConnectionStatus.DISCONNECTING,
                        ExternalChannelConnectionStatus.DISCONNECTED,
                    )
                ),
            )
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
        if rdb.transport is ExternalChannelTransport.HTTP:
            rdb.socket_lease_owner = None
            rdb.socket_lease_until = None
            rdb.socket_heartbeat_at = None
            rdb.socket_gap_detected_at = None
            rdb.socket_gap_reason = None
        if status is ExternalChannelConnectionStatus.ACTIVE:
            rdb.last_verified_at = checked_at
            rdb.disconnected_at = None
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
        defer_provider_state_purge: bool,
    ) -> tuple[str, ...] | None:
        """Fence provider resources after an explicit App uninstall."""
        if status is not ExternalChannelConnectionStatus.DISCONNECTED:
            raise ValueError("Provider termination requires disconnection.")
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
            return None
        routes = list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelAgentRoute)
                    .where(RDBExternalChannelAgentRoute.connection_id == connection_id)
                    .order_by(RDBExternalChannelAgentRoute.id)
                    .with_for_update()
                )
            ).all()
        )
        route_ids = [route.id for route in routes]
        resources = list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelResource)
                    .where(RDBExternalChannelResource.connection_id == connection_id)
                    .order_by(RDBExternalChannelResource.id)
                    .with_for_update()
                )
            ).all()
        )
        bindings = list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelBinding)
                    .where(RDBExternalChannelBinding.route_id.in_(route_ids))
                    .order_by(
                        RDBExternalChannelBinding.resource_id,
                        RDBExternalChannelBinding.id,
                    )
                    .with_for_update()
                )
            ).all()
        )
        admissions = list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelConversationAdmission)
                    .where(
                        RDBExternalChannelConversationAdmission.connection_id
                        == connection_id,
                        RDBExternalChannelConversationAdmission.status.in_(
                            (
                                ExternalChannelConversationAdmissionStatus.PENDING_SELECTION,
                                ExternalChannelConversationAdmissionStatus.SELECTED,
                                ExternalChannelConversationAdmissionStatus.AWAITING_ACCESS,
                            )
                        ),
                    )
                    .order_by(RDBExternalChannelConversationAdmission.id)
                    .with_for_update()
                )
            ).all()
        )
        access_requests = list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelAccessRequest)
                    .where(
                        RDBExternalChannelAccessRequest.route_id.in_(route_ids),
                        RDBExternalChannelAccessRequest.status
                        == ExternalChannelAccessRequestStatus.PENDING,
                    )
                    .order_by(RDBExternalChannelAccessRequest.id)
                    .with_for_update()
                )
            ).all()
        )
        binding_ids = [binding.id for binding in bindings]
        works = list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelWork)
                    .where(
                        RDBExternalChannelWork.binding_id.in_(binding_ids),
                        RDBExternalChannelWork.status
                        == ExternalChannelWorkStatus.ACTIVE,
                    )
                    .order_by(RDBExternalChannelWork.id)
                    .with_for_update()
                )
            ).all()
        )
        resource_labels = {resource.id: resource.labels for resource in resources}
        binding_resource_ids = {binding.id: binding.resource_id for binding in bindings}
        progress_delete_intent_ids: list[str] = []
        for work in works:
            if work.progress_provider_message_key is None:
                continue
            result = await session.execute(
                pg_insert(RDBExternalChannelDeliveryAttempt)
                .values(
                    id=uuid7().hex,
                    origin_type=ExternalChannelDeliveryOriginType.BINDING_DISCONNECT,
                    origin_id=work.binding_id,
                    channel_action_id=None,
                    binding_id=work.binding_id,
                    operation=ExternalChannelDeliveryOperation.PROGRESS_DELETE,
                    request_payload=_progress_delete_payload(
                        resource_labels.get(binding_resource_ids[work.binding_id]),
                        work.progress_provider_message_key,
                    ),
                    status=ExternalChannelDeliveryStatus.PENDING,
                    provider_message_key=work.progress_provider_message_key,
                    error_kind=None,
                    error_summary=None,
                    attempted_at=None,
                    completed_at=None,
                )
                .on_conflict_do_nothing()
                .returning(RDBExternalChannelDeliveryAttempt.id)
            )
            created_id = result.scalar_one_or_none()
            if created_id is not None:
                progress_delete_intent_ids.append(created_id)
        for work in works:
            work.status = ExternalChannelWorkStatus.FINISHED
            work.finished_at = now
            work.state_revision += 1
            work.desired_progress_payload = None
            work.desired_progress_revision += 1
        for binding in bindings:
            if binding.status is ExternalChannelBindingStatus.ACTIVE:
                binding.status = ExternalChannelBindingStatus.DISCONNECTED
                binding.disconnected_at = now
                binding.disconnect_reason = reason
        await session.execute(
            sa.delete(RDBExternalChannelPendingContext).where(
                RDBExternalChannelPendingContext.route_id.in_(route_ids)
            )
        )
        await session.execute(
            sa.update(RDBExternalChannelChannelDefault)
            .where(
                RDBExternalChannelChannelDefault.connection_id == connection_id,
                RDBExternalChannelChannelDefault.status
                == ExternalChannelChannelDefaultStatus.ACTIVE,
            )
            .values(
                status=ExternalChannelChannelDefaultStatus.INVALIDATED,
                invalidated_at=now,
                invalidation_reason=reason,
            )
        )
        for admission in admissions:
            admission.status = ExternalChannelConversationAdmissionStatus.EXPIRED
        for request in access_requests:
            request.status = ExternalChannelAccessRequestStatus.EXPIRED
            request.decision_summary = (
                "The External Channel connection was disconnected."
            )
            request.decided_at = now
        for resource in resources:
            if resource.status is ExternalChannelResourceStatus.ACTIVE:
                resource.status = ExternalChannelResourceStatus.UNAVAILABLE
                resource.unavailable_at = now
        for route in routes:
            if route.catalog_status is not ExternalChannelRouteCatalogStatus.REMOVED:
                route.catalog_status = ExternalChannelRouteCatalogStatus.REMOVED
                route.catalog_removed_at = now
                route.catalog_removed_by_user_id = None
            route.agent_id = None
        connection.status = status
        connection.disconnected_at = now
        connection.socket_lease_owner = None
        connection.socket_lease_until = None
        if connection.transport is ExternalChannelTransport.SOCKET:
            connection.socket_heartbeat_at = now
            connection.socket_gap_detected_at = now
            connection.socket_gap_reason = reason
        else:
            connection.socket_heartbeat_at = None
            connection.socket_gap_detected_at = None
            connection.socket_gap_reason = None
        if not defer_provider_state_purge:
            self._purge_connection_provider_state(connection)
        await session.flush()
        return tuple(progress_delete_intent_ids)

    async def purge_disconnected_connection_provider_state(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
    ) -> bool:
        """Clear provider secrets after cleanup targets have been captured."""
        connection = await session.scalar(
            sa.select(RDBExternalChannelConnection)
            .where(
                RDBExternalChannelConnection.id == connection_id,
                RDBExternalChannelConnection.status
                == ExternalChannelConnectionStatus.DISCONNECTED,
            )
            .with_for_update()
        )
        if connection is None:
            return False
        self._purge_connection_provider_state(connection)
        await session.flush()
        return True

    @staticmethod
    def _purge_connection_provider_state(
        connection: RDBExternalChannelConnection,
    ) -> None:
        """Remove provider identity and credentials from one terminal connection."""
        connection.encrypted_credentials = None
        connection.provider_tenant_id = None
        connection.provider_bot_user_id = None
        connection.capabilities = None

    async def mark_connection_reconnect_required(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        reason: str,
        now: datetime.datetime,
        required_socket_lease_owner: str | None,
    ) -> bool:
        """Record provider credential health without mutating Agent routing."""
        eligible_statuses = (
            (
                ExternalChannelConnectionStatus.ACTIVE,
                ExternalChannelConnectionStatus.DEGRADED,
            )
            if required_socket_lease_owner is not None
            else (
                ExternalChannelConnectionStatus.ACTIVE,
                ExternalChannelConnectionStatus.DEGRADED,
                ExternalChannelConnectionStatus.RECONNECT_REQUIRED,
            )
        )
        statement = sa.select(RDBExternalChannelConnection).where(
            RDBExternalChannelConnection.id == connection_id,
            RDBExternalChannelConnection.status.in_(eligible_statuses),
        )
        if required_socket_lease_owner is not None:
            statement = statement.where(
                RDBExternalChannelConnection.transport
                == ExternalChannelTransport.SOCKET,
                RDBExternalChannelConnection.socket_lease_owner
                == required_socket_lease_owner,
                RDBExternalChannelConnection.socket_lease_until >= now,
            )
        connection = await session.scalar(statement.with_for_update())
        if connection is None:
            return False
        connection.status = ExternalChannelConnectionStatus.RECONNECT_REQUIRED
        connection.socket_lease_owner = None
        connection.socket_lease_until = None
        if connection.transport is ExternalChannelTransport.SOCKET:
            connection.socket_heartbeat_at = now
            connection.socket_gap_detected_at = now
            connection.socket_gap_reason = reason
        else:
            connection.socket_heartbeat_at = None
            connection.socket_gap_detected_at = None
            connection.socket_gap_reason = None
        await session.flush()
        return True

    async def create_agent_route(
        self,
        session: AsyncSession,
        create: ExternalChannelAgentRouteCreate,
    ) -> ExternalChannelAgentRoute:
        """Create a workspace-fenced route with the authoritative App mode."""
        connection = await session.scalar(
            sa.select(RDBExternalChannelConnection)
            .where(RDBExternalChannelConnection.id == create.connection_id)
            .with_for_update()
        )
        if connection is None:
            raise ValueError("External Channel connection does not exist.")
        if connection.app_mode is not create.connection_app_mode:
            raise ValueError(
                "External Channel route App mode does not match connection."
            )
        if create.route_mode is not ExternalChannelRouteMode.DEDICATED:
            raise ValueError("New External Channel routes must use dedicated mode.")
        if create.catalog_status is not ExternalChannelRouteCatalogStatus.AVAILABLE:
            raise ValueError("New External Channel routes must be catalog-available.")
        if create.agent_id_snapshot != create.agent_id:
            raise ValueError(
                "New External Channel route Agent snapshot must match its Agent."
            )
        if (
            create.catalog_removed_at is not None
            or create.catalog_removed_by_user_id is not None
        ):
            raise ValueError(
                "New External Channel routes cannot include catalog-removal metadata."
            )
        agent = await session.scalar(
            sa.select(RDBAgent).where(RDBAgent.id == create.agent_id).with_for_update()
        )
        if (
            agent is None
            or agent.workspace_id != connection.workspace_id
            or agent.lifecycle_status is not AgentLifecycleStatus.ACTIVE
        ):
            raise ValueError(
                "External Channel route Agent must be active in connection Workspace."
            )
        return ExternalChannelAgentRoute.model_validate(
            await self._create(session, RDBExternalChannelAgentRoute, create)
        )

    async def admit_interaction(
        self,
        session: AsyncSession,
        create: ExternalChannelInteractionCreate,
    ) -> ExternalChannelInteractionAdmission:
        """Atomically admit one provider interaction or return its prior admission."""
        if create.status is not ExternalChannelInteractionStatus.ACCEPTED:
            raise ValueError(
                "New External Channel interactions must start as accepted."
            )
        if create.error_kind is not None or create.error_summary is not None:
            raise ValueError(
                "New External Channel interactions cannot include error metadata."
            )
        _validate_interaction_identifier(
            "provider interaction key",
            create.provider_interaction_key,
            max_length=128,
        )
        for field_name, value, max_length in (
            ("callback ID", create.callback_id, 255),
            ("action ID", create.action_id, 255),
            ("resource correlation key", create.resource_correlation_key, 512),
        ):
            if value is not None:
                _validate_interaction_identifier(
                    field_name,
                    value,
                    max_length=max_length,
                )
        validate_interaction_projection(create.projection)
        if create.principal_id is not None:
            connection = await session.get(
                RDBExternalChannelConnection,
                create.connection_id,
            )
            principal = await session.get(
                RDBExternalChannelPrincipal,
                create.principal_id,
            )
            if (
                connection is None
                or principal is None
                or principal.provider is not connection.provider
                or principal.provider_tenant_id != connection.provider_tenant_id
            ):
                raise ValueError(
                    "External Channel interaction principal does not match connection."
                )
        result = await session.execute(
            pg_insert(RDBExternalChannelInteraction)
            .values(id=uuid7().hex, **create.model_dump())
            .on_conflict_do_nothing(
                constraint="uq_external_channel_interactions_connection_provider_key"
            )
            .returning(RDBExternalChannelInteraction)
        )
        rdb = result.scalar_one_or_none()
        if rdb is not None:
            return ExternalChannelInteractionAdmission(
                interaction=ExternalChannelInteraction.model_validate(rdb),
                created=True,
            )
        existing = await self.get_interaction_by_provider_key(
            session,
            connection_id=create.connection_id,
            provider_interaction_key=create.provider_interaction_key,
        )
        if existing is None:
            raise RuntimeError("External Channel interaction admission lookup failed")
        if not _interaction_admission_is_compatible(existing, create):
            raise ValueError("External Channel interaction retry is incompatible.")
        return ExternalChannelInteractionAdmission(interaction=existing, created=False)

    async def get_interaction_by_provider_key(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        provider_interaction_key: str,
    ) -> ExternalChannelInteraction | None:
        """Fetch an interaction by its connection-scoped provider identity."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelInteraction).where(
                RDBExternalChannelInteraction.connection_id == connection_id,
                RDBExternalChannelInteraction.provider_interaction_key
                == provider_interaction_key,
            )
        )
        return self._as(ExternalChannelInteraction, rdb)

    async def lock_interaction(
        self,
        session: AsyncSession,
        *,
        interaction_id: str,
    ) -> ExternalChannelInteraction | None:
        """Lock one retained interaction before a trigger-bearing provider mutation."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelInteraction)
            .where(RDBExternalChannelInteraction.id == interaction_id)
            .with_for_update()
        )
        return self._as(ExternalChannelInteraction, rdb)

    async def transition_interaction(
        self,
        session: AsyncSession,
        *,
        interaction_id: str,
        status: ExternalChannelInteractionStatus,
        error_kind: str | None,
        error_summary: str | None,
        transitioned_at: datetime.datetime | None = None,
    ) -> ExternalChannelInteraction | None:
        """Apply one guarded interaction state transition without replaying I/O."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelInteraction)
            .where(RDBExternalChannelInteraction.id == interaction_id)
            .with_for_update()
        )
        if rdb is None:
            return None
        allowed = {
            ExternalChannelInteractionStatus.ACCEPTED: {
                ExternalChannelInteractionStatus.PROCESSING,
                ExternalChannelInteractionStatus.EXPIRED,
                ExternalChannelInteractionStatus.REJECTED,
            },
            ExternalChannelInteractionStatus.PROCESSING: {
                ExternalChannelInteractionStatus.COMPLETED,
                ExternalChannelInteractionStatus.FAILED,
                ExternalChannelInteractionStatus.EXPIRED,
            },
            ExternalChannelInteractionStatus.COMPLETED: {
                ExternalChannelInteractionStatus.COMPLETED,
            },
            ExternalChannelInteractionStatus.FAILED: {
                ExternalChannelInteractionStatus.FAILED,
            },
            ExternalChannelInteractionStatus.EXPIRED: {
                ExternalChannelInteractionStatus.EXPIRED,
            },
            ExternalChannelInteractionStatus.REJECTED: {
                ExternalChannelInteractionStatus.REJECTED,
            },
        }
        if status not in allowed[rdb.status]:
            raise ValueError("External Channel interaction transition is invalid.")
        rdb.status = status
        rdb.error_kind = error_kind
        rdb.error_summary = error_summary
        if transitioned_at is not None:
            rdb.updated_at = transitioned_at
        await session.flush()
        return ExternalChannelInteraction.model_validate(rdb)

    async def create_conversation_admission_idempotent(
        self,
        session: AsyncSession,
        create: ExternalChannelConversationAdmissionCreate,
    ) -> ExternalChannelConversationAdmission:
        """Create or return the open route-neutral admission for one resource."""
        await self._validate_conversation_admission_owners(session, create)
        rdb = await self._insert_or_lookup(
            session,
            RDBExternalChannelConversationAdmission,
            create,
            lambda: session.scalar(
                sa.select(RDBExternalChannelConversationAdmission).where(
                    RDBExternalChannelConversationAdmission.resource_id
                    == create.resource_id,
                    RDBExternalChannelConversationAdmission.status.in_(
                        (
                            "pending_selection",
                            "selected",
                            "awaiting_access",
                        )
                    ),
                )
            ),
        )
        return ExternalChannelConversationAdmission.model_validate(rdb)

    async def _validate_conversation_admission_owners(
        self,
        session: AsyncSession,
        create: ExternalChannelConversationAdmissionCreate,
    ) -> None:
        """Reject foreign owners before an idempotent conflict can mask them."""
        connection = await session.get(
            RDBExternalChannelConnection,
            create.connection_id,
        )
        resource = await session.get(
            RDBExternalChannelResource,
            create.resource_id,
        )
        source_message = await session.get(
            RDBExternalChannelMessage,
            create.source_message_id,
        )
        if (
            connection is None
            or resource is None
            or resource.connection_id != connection.id
        ):
            raise ValueError(
                "External Channel admission resource does not match connection."
            )
        if source_message is None or source_message.resource_id != resource.id:
            raise ValueError(
                "External Channel admission source message does not match resource."
            )
        if create.selected_route_id is not None:
            route = await session.get(
                RDBExternalChannelAgentRoute,
                create.selected_route_id,
            )
            if route is None or route.connection_id != connection.id:
                raise ValueError(
                    "External Channel admission route does not match connection."
                )
        if create.interaction_id is not None:
            interaction = await session.get(
                RDBExternalChannelInteraction,
                create.interaction_id,
            )
            if interaction is None or interaction.connection_id != connection.id:
                raise ValueError(
                    "External Channel admission interaction does not match connection."
                )
        if create.initiating_principal_id is not None:
            principal = await session.get(
                RDBExternalChannelPrincipal,
                create.initiating_principal_id,
            )
            if (
                principal is None
                or principal.provider is not connection.provider
                or principal.provider_tenant_id != connection.provider_tenant_id
            ):
                raise ValueError(
                    "External Channel admission principal does not match connection."
                )

    async def create_channel_default(
        self,
        session: AsyncSession,
        create: ExternalChannelChannelDefaultCreate,
    ) -> ExternalChannelChannelDefault:
        """Create an active, eligible Multi App channel default."""
        if create.status is not ExternalChannelChannelDefaultStatus.ACTIVE:
            raise ValueError("New External Channel defaults must be active.")
        if create.invalidated_at is not None or create.invalidation_reason is not None:
            raise ValueError(
                "Active External Channel defaults cannot include invalidation metadata."
            )
        connection = await session.scalar(
            sa.select(RDBExternalChannelConnection)
            .where(RDBExternalChannelConnection.id == create.connection_id)
            .with_for_update()
        )
        if connection is None:
            raise ValueError(
                "External Channel default connection or route does not exist."
            )
        route = await session.scalar(
            sa.select(RDBExternalChannelAgentRoute)
            .where(
                RDBExternalChannelAgentRoute.id == create.route_id,
                RDBExternalChannelAgentRoute.connection_id == connection.id,
            )
            .with_for_update()
        )
        if route is None:
            raise ValueError(
                "External Channel default connection or route does not exist."
            )
        agent = (
            None
            if route.agent_id is None
            else await session.scalar(
                sa.select(RDBAgent)
                .where(
                    RDBAgent.id == route.agent_id,
                    RDBAgent.lifecycle_status == AgentLifecycleStatus.ACTIVE,
                )
                .with_for_update()
            )
        )
        if (
            connection.app_mode is not ExternalChannelAppMode.MULTI
            or route.connection_id != connection.id
            or route.connection_app_mode is not connection.app_mode
            or route.catalog_status is not ExternalChannelRouteCatalogStatus.AVAILABLE
            or agent is None
            or agent.workspace_id != connection.workspace_id
        ):
            raise ValueError("External Channel default route is not eligible.")
        return ExternalChannelChannelDefault.model_validate(
            await self._create(session, RDBExternalChannelChannelDefault, create)
        )

    async def lock_connection_for_routing(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
    ) -> ExternalChannelConnection | None:
        """Lock one execution-eligible connection before route resolution."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelConnection)
            .where(
                RDBExternalChannelConnection.id == connection_id,
                RDBExternalChannelConnection.status.in_(
                    (
                        ExternalChannelConnectionStatus.ACTIVE,
                        ExternalChannelConnectionStatus.DEGRADED,
                    )
                ),
            )
            .with_for_update()
        )
        return self._as(ExternalChannelConnection, rdb)

    async def get_routable_route_by_id(
        self,
        session: AsyncSession,
        *,
        route_id: str,
    ) -> ExternalChannelAgentRoute | None:
        """Lock and fetch one route if its connection admits new execution."""
        return await self._get_routable_route(
            session,
            route_id=route_id,
        )

    async def lock_routable_single_route(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
    ) -> ExternalChannelAgentRoute | None:
        """Lock the sole eligible Single App route without candidate ordering."""
        route_ids = list(
            await session.scalars(
                sa.select(RDBExternalChannelAgentRoute.id)
                .where(
                    RDBExternalChannelAgentRoute.connection_id == connection_id,
                )
                .with_for_update(of=RDBExternalChannelAgentRoute)
            )
        )
        if len(route_ids) != 1:
            return None
        return await self._get_routable_route(
            session,
            route_id=route_ids[0],
        )

    async def lock_routable_channel_default(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        provider_channel_id: str,
    ) -> ExternalChannelAgentRoute | None:
        """Lock the exact eligible Multi App channel default, if any."""
        rows = list(
            await session.scalars(
                self._routable_route_statement()
                .join(
                    RDBExternalChannelChannelDefault,
                    sa.and_(
                        RDBExternalChannelChannelDefault.connection_id
                        == RDBExternalChannelAgentRoute.connection_id,
                        RDBExternalChannelChannelDefault.route_id
                        == RDBExternalChannelAgentRoute.id,
                    ),
                )
                .where(
                    RDBExternalChannelConnection.id == connection_id,
                    RDBExternalChannelConnection.app_mode
                    == ExternalChannelAppMode.MULTI,
                    RDBExternalChannelAgentRoute.connection_app_mode
                    == ExternalChannelAppMode.MULTI,
                    RDBExternalChannelChannelDefault.provider_channel_id
                    == provider_channel_id,
                    RDBExternalChannelChannelDefault.status
                    == ExternalChannelChannelDefaultStatus.ACTIVE,
                )
                .with_for_update(of=RDBExternalChannelAgentRoute)
            )
        )
        if len(rows) != 1:
            return None
        route = rows[0]
        if not await self._lock_active_route_agent(session, route=route):
            return None
        return ExternalChannelAgentRoute.model_validate(route)

    async def list_routable_multi_catalog_routes(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        principal_id: str,
        search: str | None,
        offset: int,
        limit: int,
    ) -> list[ExternalChannelCatalogRoute]:
        """List current Multi selector routes by canonical Agent name and route ID."""
        if offset < 0 or limit <= 0 or limit > 100:
            raise ValueError("External Channel selector page is invalid.")
        normalized_search = None if search is None else search.strip()
        if normalized_search is not None and len(normalized_search) > 100:
            raise ValueError("External Channel selector search is too long.")
        statement = (
            sa.select(RDBExternalChannelAgentRoute, RDBAgent.name)
            .join(
                RDBExternalChannelConnection,
                RDBExternalChannelConnection.id
                == RDBExternalChannelAgentRoute.connection_id,
            )
            .join(RDBAgent, RDBAgent.id == RDBExternalChannelAgentRoute.agent_id)
            .where(
                RDBExternalChannelConnection.id == connection_id,
                RDBExternalChannelConnection.status.in_(
                    (
                        ExternalChannelConnectionStatus.ACTIVE,
                        ExternalChannelConnectionStatus.DEGRADED,
                    )
                ),
                RDBExternalChannelConnection.app_mode == ExternalChannelAppMode.MULTI,
                RDBExternalChannelAgentRoute.connection_app_mode
                == ExternalChannelAppMode.MULTI,
                RDBExternalChannelAgentRoute.catalog_status
                == ExternalChannelRouteCatalogStatus.AVAILABLE,
                RDBAgent.workspace_id == RDBExternalChannelConnection.workspace_id,
                RDBAgent.lifecycle_status == AgentLifecycleStatus.ACTIVE,
                ~sa.exists().where(
                    RDBExternalChannelBlock.agent_id == RDBAgent.id,
                    RDBExternalChannelBlock.principal_id == principal_id,
                    RDBExternalChannelBlock.removed_at.is_(None),
                ),
            )
            .order_by(sa.func.lower(RDBAgent.name), RDBExternalChannelAgentRoute.id)
            .offset(offset)
            .limit(limit)
        )
        if normalized_search:
            statement = statement.where(RDBAgent.name.ilike(f"%{normalized_search}%"))
        rows = (await session.execute(statement)).all()
        return [
            ExternalChannelCatalogRoute(
                route=ExternalChannelAgentRoute.model_validate(route),
                agent_name=agent_name,
            )
            for route, agent_name in rows
        ]

    async def lock_open_conversation_admission(
        self,
        session: AsyncSession,
        *,
        resource_id: str,
    ) -> ExternalChannelConversationAdmission | None:
        """Lock the one open routing admission for a resource."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelConversationAdmission)
            .where(
                RDBExternalChannelConversationAdmission.resource_id == resource_id,
                RDBExternalChannelConversationAdmission.status.in_(
                    (
                        ExternalChannelConversationAdmissionStatus.PENDING_SELECTION,
                        ExternalChannelConversationAdmissionStatus.SELECTED,
                        ExternalChannelConversationAdmissionStatus.AWAITING_ACCESS,
                    )
                ),
            )
            .with_for_update()
        )
        return self._as(ExternalChannelConversationAdmission, rdb)

    async def get_open_conversation_admission(
        self,
        session: AsyncSession,
        *,
        resource_id: str,
    ) -> ExternalChannelConversationAdmission | None:
        """Fetch the open admission snapshot before canonical lock acquisition."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelConversationAdmission).where(
                RDBExternalChannelConversationAdmission.resource_id == resource_id,
                RDBExternalChannelConversationAdmission.status.in_(
                    (
                        ExternalChannelConversationAdmissionStatus.PENDING_SELECTION,
                        ExternalChannelConversationAdmissionStatus.SELECTED,
                        ExternalChannelConversationAdmissionStatus.AWAITING_ACCESS,
                    )
                ),
            )
        )
        return self._as(ExternalChannelConversationAdmission, rdb)

    async def get_conversation_admission(
        self,
        session: AsyncSession,
        *,
        admission_id: str,
    ) -> ExternalChannelConversationAdmission | None:
        """Fetch one admission snapshot before canonical lock acquisition."""
        return self._as(
            ExternalChannelConversationAdmission,
            await session.get(RDBExternalChannelConversationAdmission, admission_id),
        )

    async def transition_conversation_admission(
        self,
        session: AsyncSession,
        *,
        admission_id: str,
        status: ExternalChannelConversationAdmissionStatus,
        selected_route_id: str | None,
    ) -> ExternalChannelConversationAdmission | None:
        """Apply a routing transition without replacing a recorded route."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelConversationAdmission)
            .where(RDBExternalChannelConversationAdmission.id == admission_id)
            .with_for_update()
        )
        if rdb is None:
            return None
        allowed_transitions = {
            ExternalChannelConversationAdmissionStatus.PENDING_SELECTION: {
                ExternalChannelConversationAdmissionStatus.PENDING_SELECTION,
                ExternalChannelConversationAdmissionStatus.SELECTED,
                ExternalChannelConversationAdmissionStatus.EXPIRED,
                ExternalChannelConversationAdmissionStatus.REJECTED,
            },
            ExternalChannelConversationAdmissionStatus.SELECTED: {
                ExternalChannelConversationAdmissionStatus.SELECTED,
                ExternalChannelConversationAdmissionStatus.AWAITING_ACCESS,
                ExternalChannelConversationAdmissionStatus.BOUND,
                ExternalChannelConversationAdmissionStatus.EXPIRED,
                ExternalChannelConversationAdmissionStatus.REJECTED,
            },
            ExternalChannelConversationAdmissionStatus.AWAITING_ACCESS: {
                ExternalChannelConversationAdmissionStatus.AWAITING_ACCESS,
                ExternalChannelConversationAdmissionStatus.BOUND,
                ExternalChannelConversationAdmissionStatus.EXPIRED,
                ExternalChannelConversationAdmissionStatus.REJECTED,
            },
            ExternalChannelConversationAdmissionStatus.BOUND: {
                ExternalChannelConversationAdmissionStatus.BOUND,
            },
            ExternalChannelConversationAdmissionStatus.EXPIRED: {
                ExternalChannelConversationAdmissionStatus.EXPIRED,
            },
            ExternalChannelConversationAdmissionStatus.REJECTED: {
                ExternalChannelConversationAdmissionStatus.REJECTED,
            },
        }
        if status not in allowed_transitions[rdb.status]:
            raise ValueError(
                "External Channel conversation admission transition is invalid."
            )
        if (
            rdb.selected_route_id is not None
            and selected_route_id is not None
            and rdb.selected_route_id != selected_route_id
        ):
            raise ValueError(
                "External Channel conversation admission route is immutable."
            )
        if (
            status is ExternalChannelConversationAdmissionStatus.PENDING_SELECTION
            and selected_route_id is not None
        ):
            raise ValueError(
                "Pending-selection External Channel admissions cannot select a route."
            )
        if (
            status
            in (
                ExternalChannelConversationAdmissionStatus.SELECTED,
                ExternalChannelConversationAdmissionStatus.AWAITING_ACCESS,
                ExternalChannelConversationAdmissionStatus.BOUND,
            )
            and (selected_route_id or rdb.selected_route_id) is None
        ):
            raise ValueError("Selected External Channel admissions require a route.")
        rdb.status = status
        if rdb.selected_route_id is None:
            rdb.selected_route_id = selected_route_id
        await session.flush()
        await session.refresh(rdb, attribute_names=["updated_at"])
        return ExternalChannelConversationAdmission.model_validate(rdb)

    async def get_routable_route_by_binding_id(
        self,
        session: AsyncSession,
        *,
        binding_id: str,
    ) -> ExternalChannelAgentRoute | None:
        """Lock and fetch the route owning one routable binding."""
        return await self._get_routable_route(
            session,
            route_id=None,
            binding_id=binding_id,
        )

    async def _get_routable_route(
        self,
        session: AsyncSession,
        *,
        route_id: str | None,
        binding_id: str | None = None,
    ) -> ExternalChannelAgentRoute | None:
        """Lock one stable route with all execution ownership boundaries."""
        predicates: list[sa.ColumnElement[bool]] = []
        if route_id is not None:
            predicates.append(RDBExternalChannelAgentRoute.id == route_id)
        if binding_id is not None:
            statement = self._routable_route_statement().join(
                RDBExternalChannelBinding,
                RDBExternalChannelBinding.route_id == RDBExternalChannelAgentRoute.id,
            )
            predicates.append(RDBExternalChannelBinding.id == binding_id)
        else:
            statement = self._routable_route_statement()
        rdb = await session.scalar(
            statement.where(*predicates).with_for_update(
                of=RDBExternalChannelAgentRoute
            )
        )
        if rdb is not None and not await self._lock_active_route_agent(
            session,
            route=rdb,
        ):
            return None
        return self._as(ExternalChannelAgentRoute, rdb)

    @staticmethod
    async def _lock_active_route_agent(
        session: AsyncSession,
        *,
        route: RDBExternalChannelAgentRoute,
    ) -> bool:
        """Serialize route selection with Agent lifecycle fencing."""
        if route.agent_id is None:
            return False
        agent = await session.scalar(
            sa.select(RDBAgent)
            .where(
                RDBAgent.id == route.agent_id,
                RDBAgent.lifecycle_status == AgentLifecycleStatus.ACTIVE,
            )
            .with_for_update()
        )
        return agent is not None

    @staticmethod
    def _routable_route_statement() -> sa.Select[tuple[RDBExternalChannelAgentRoute]]:
        """Build common route eligibility predicates without candidate ordering."""
        return (
            sa.select(RDBExternalChannelAgentRoute)
            .join(
                RDBExternalChannelConnection,
                RDBExternalChannelConnection.id
                == RDBExternalChannelAgentRoute.connection_id,
            )
            .join(RDBAgent, RDBAgent.id == RDBExternalChannelAgentRoute.agent_id)
            .where(
                RDBExternalChannelConnection.status.in_(
                    (
                        ExternalChannelConnectionStatus.ACTIVE,
                        ExternalChannelConnectionStatus.DEGRADED,
                    )
                ),
                RDBExternalChannelAgentRoute.connection_app_mode
                == RDBExternalChannelConnection.app_mode,
                RDBExternalChannelAgentRoute.catalog_status
                == ExternalChannelRouteCatalogStatus.AVAILABLE,
                RDBAgent.workspace_id == RDBExternalChannelConnection.workspace_id,
                RDBAgent.lifecycle_status == AgentLifecycleStatus.ACTIVE,
            )
        )

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
        if rdb.hydration_status in {
            ExternalChannelHydrationStatus.COMPLETE,
            ExternalChannelHydrationStatus.BOUNDED,
            ExternalChannelHydrationStatus.INCOMPLETE,
        }:
            return ExternalChannelResource.model_validate(rdb)
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

    async def get_principal(
        self,
        session: AsyncSession,
        *,
        principal_id: str,
    ) -> ExternalChannelPrincipal | None:
        """Fetch one canonical provider principal by durable identity."""
        return self._as(
            ExternalChannelPrincipal,
            await session.get(RDBExternalChannelPrincipal, principal_id),
        )

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
        *,
        expected_admission_id: str | None,
        expected_access_request_id: str | None,
    ) -> ExternalChannelBinding:
        """Create or return the active binding for one resource and route."""
        resource = await self.lock_resource(
            session,
            resource_id=create.resource_id,
        )
        if resource is None:
            raise ValueError("External Channel binding resource does not exist.")
        existing = await self.lock_active_binding_by_resource(
            session,
            resource_id=create.resource_id,
        )
        await self._validate_binding_owners(
            session,
            create,
            expected_admission_id=expected_admission_id,
            expected_access_request_id=expected_access_request_id,
        )
        if existing is not None:
            if existing.route_id != create.route_id:
                raise ValueError(
                    "External Channel resource already has an active binding "
                    "for another route."
                )
            if existing.agent_session_id != create.agent_session_id:
                raise ValueError(
                    "External Channel resource already has an active binding "
                    "for another Agent Session."
                )
            return existing
        values = create.model_dump(
            exclude={"truncated_message_count", "truncated_size"}
        )
        rdb = RDBExternalChannelBinding(**values)
        rdb.truncated_message_count = create.truncated_message_count
        rdb.truncated_size = create.truncated_size
        session.add(rdb)
        await session.flush()
        return ExternalChannelBinding.model_validate(rdb)

    async def _validate_binding_owners(
        self,
        session: AsyncSession,
        create: ExternalChannelBindingCreate,
        *,
        expected_admission_id: str | None,
        expected_access_request_id: str | None,
    ) -> None:
        """Validate owners and the durable admission/request authority."""
        resource = await session.get(RDBExternalChannelResource, create.resource_id)
        route = await session.get(RDBExternalChannelAgentRoute, create.route_id)
        agent_session = await session.get(RDBAgentSession, create.agent_session_id)
        if resource is None or route is None or agent_session is None:
            raise ValueError("External Channel binding owner does not exist.")
        connection = await session.get(
            RDBExternalChannelConnection, route.connection_id
        )
        agent = await session.get(RDBAgent, route.agent_id)
        if (
            connection is None
            or resource.connection_id != connection.id
            or route.connection_app_mode is not connection.app_mode
            or route.catalog_status is not ExternalChannelRouteCatalogStatus.AVAILABLE
            or agent is None
            or agent.workspace_id != connection.workspace_id
            or agent.lifecycle_status is not AgentLifecycleStatus.ACTIVE
            or agent_session.workspace_id != agent.workspace_id
            or agent_session.agent_id != agent.id
            or agent_session.session_kind is not AgentSessionKind.ROOT
        ):
            raise ValueError("External Channel binding owners are incompatible.")
        if expected_admission_id is not None:
            admission = await session.scalar(
                sa.select(RDBExternalChannelConversationAdmission)
                .where(
                    RDBExternalChannelConversationAdmission.id == expected_admission_id
                )
                .with_for_update()
            )
            if (
                admission is None
                or admission.resource_id != resource.id
                or admission.selected_route_id != route.id
                or admission.status
                not in (
                    ExternalChannelConversationAdmissionStatus.SELECTED,
                    ExternalChannelConversationAdmissionStatus.AWAITING_ACCESS,
                )
            ):
                raise ValueError("External Channel binding admission is incompatible.")
        if expected_access_request_id is not None:
            request = await session.scalar(
                sa.select(RDBExternalChannelAccessRequest)
                .where(RDBExternalChannelAccessRequest.id == expected_access_request_id)
                .with_for_update()
            )
            if (
                request is None
                or request.resource_id != resource.id
                or request.route_id != route.id
                or request.status is not ExternalChannelAccessRequestStatus.PENDING
            ):
                raise ValueError(
                    "External Channel binding access request is incompatible."
                )

    async def get_active_binding_by_resource(
        self,
        session: AsyncSession,
        *,
        resource_id: str,
    ) -> ExternalChannelBinding | None:
        """Fetch the one active binding allowed for an external resource."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelBinding).where(
                RDBExternalChannelBinding.resource_id == resource_id,
                RDBExternalChannelBinding.status == ExternalChannelBindingStatus.ACTIVE,
            )
        )
        return self._as(ExternalChannelBinding, rdb)

    async def lock_active_binding_by_resource(
        self,
        session: AsyncSession,
        *,
        resource_id: str,
    ) -> ExternalChannelBinding | None:
        """Lock the one active binding after its resource lock."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelBinding)
            .where(
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

    async def get_binding(
        self,
        session: AsyncSession,
        *,
        binding_id: str,
    ) -> ExternalChannelBinding | None:
        """Fetch one binding snapshot before canonical lock acquisition."""
        return self._as(
            ExternalChannelBinding,
            await session.get(RDBExternalChannelBinding, binding_id),
        )

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
        if rdb.activation_status is ExternalChannelBindingActivationStatus.ACTIVE:
            return ExternalChannelBinding.model_validate(rdb)
        if (
            rdb.activation_status
            is not ExternalChannelBindingActivationStatus.WAITING_HYDRATION
        ):
            return None
        rdb.activation_status = ExternalChannelBindingActivationStatus.ACTIVE
        rdb.activated_at = now
        rdb.projected_through_position = projected_through_position
        rdb.truncated_message_count = 0
        rdb.truncated_size = 0
        await session.flush()
        await session.refresh(rdb, attribute_names=["updated_at"])
        return ExternalChannelBinding.model_validate(rdb)

    async def get_pending_initial_delivery_attempt_ids(
        self,
        session: AsyncSession,
        *,
        binding_id: str,
    ) -> tuple[str | None, str | None]:
        """Recover pending initial provider intents while activation is waiting."""
        rows = (
            await session.execute(
                sa.select(
                    RDBExternalChannelDeliveryAttempt.id,
                    RDBExternalChannelDeliveryAttempt.origin_id,
                    RDBExternalChannelDeliveryAttempt.operation,
                )
                .where(
                    RDBExternalChannelDeliveryAttempt.binding_id == binding_id,
                    RDBExternalChannelDeliveryAttempt.origin_type
                    == ExternalChannelDeliveryOriginType.MANAGER_OPERATION,
                    RDBExternalChannelDeliveryAttempt.operation.in_(
                        (
                            ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
                            ExternalChannelDeliveryOperation.PROGRESS_CREATE,
                        )
                    ),
                    RDBExternalChannelDeliveryAttempt.status
                    == ExternalChannelDeliveryStatus.PENDING,
                )
                .order_by(
                    RDBExternalChannelDeliveryAttempt.created_at,
                    RDBExternalChannelDeliveryAttempt.id,
                )
            )
        ).all()
        session_link_id = next(
            (
                attempt_id
                for attempt_id, origin_id, operation in rows
                if operation is ExternalChannelDeliveryOperation.CONTROL_MESSAGE
                and origin_id == binding_id
            ),
            None,
        )
        activity_id = next(
            (
                attempt_id
                for attempt_id, _, operation in rows
                if operation is ExternalChannelDeliveryOperation.PROGRESS_CREATE
            ),
            None,
        )
        return session_link_id, activity_id

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
        original_revision = aliased(RDBExternalChannelMessageRevision)
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
                RDBExternalChannelMessageRevision.reference_mappings,
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
                        sa.select(original_revision.id)
                        .where(
                            original_revision.message_id
                            == RDBExternalChannelMessage.id,
                            original_revision.revision_kind
                            == ExternalChannelMessageRevisionKind.ORIGINAL,
                        )
                        .order_by(
                            original_revision.created_at,
                            original_revision.id,
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

    async def delete_access_grant(
        self,
        session: AsyncSession,
        *,
        grant_id: str,
    ) -> ExternalChannelAccessGrant | None:
        """Delete one participant grant while retaining external content."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelAccessGrant)
            .where(RDBExternalChannelAccessGrant.id == grant_id)
            .with_for_update()
        )
        if rdb is None:
            return None
        grant = ExternalChannelAccessGrant.model_validate(rdb)
        await session.delete(rdb)
        await session.flush()
        return grant

    async def create_access_request_control_delete_intent(
        self,
        session: AsyncSession,
        *,
        access_request_id: str,
    ) -> ExternalChannelDeliveryAttempt | None:
        """Create one idempotent delete intent for a delivered control message."""
        request = await session.scalar(
            sa.select(RDBExternalChannelAccessRequest)
            .where(RDBExternalChannelAccessRequest.id == access_request_id)
            .with_for_update()
        )
        if (
            request is None
            or request.status is ExternalChannelAccessRequestStatus.PENDING
        ):
            return None
        control = await session.scalar(
            sa.select(RDBExternalChannelDeliveryAttempt)
            .where(
                RDBExternalChannelDeliveryAttempt.origin_type
                == ExternalChannelDeliveryOriginType.ACCESS_REQUEST,
                RDBExternalChannelDeliveryAttempt.origin_id == access_request_id,
                RDBExternalChannelDeliveryAttempt.operation
                == ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
                RDBExternalChannelDeliveryAttempt.status
                == ExternalChannelDeliveryStatus.DELIVERED,
                RDBExternalChannelDeliveryAttempt.provider_message_key.is_not(None),
            )
            .with_for_update()
        )
        if control is None or control.provider_message_key is None:
            return None
        channel_id = control.request_payload.get("channel_id")
        thread_ts = control.request_payload.get("thread_ts")
        if not isinstance(channel_id, str) or not isinstance(thread_ts, str):
            return None
        return await self.create_delivery_attempt_idempotent(
            session,
            ExternalChannelDeliveryAttemptCreate(
                origin_type=ExternalChannelDeliveryOriginType.ACCESS_REQUEST,
                origin_id=access_request_id,
                channel_action_id=None,
                binding_id=None,
                operation=ExternalChannelDeliveryOperation.PROGRESS_DELETE,
                request_payload={
                    "channel_id": channel_id,
                    "thread_ts": thread_ts,
                    "provider_message_key": control.provider_message_key,
                },
                status=ExternalChannelDeliveryStatus.PENDING,
                provider_message_key=control.provider_message_key,
                error_kind=None,
                error_summary=None,
                attempted_at=None,
                completed_at=None,
            ),
        )

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
        desired_progress_payload: dict[str, object],
    ) -> ExternalChannelWork:
        """Create or return the active Channel Work for an invoked binding."""
        return await self.create_work_idempotent(
            session,
            ExternalChannelWorkCreate(
                binding_id=binding_id,
                status=ExternalChannelWorkStatus.ACTIVE,
                schema_version=2,
                title=None,
                tasks=[],
                state_revision=1,
                desired_progress_revision=1,
                desired_progress_payload=desired_progress_payload,
                progress_provider_message_key=None,
                finished_at=None,
            ),
        )

    async def set_work_progress_provider_message_key(
        self,
        session: AsyncSession,
        *,
        work_id: str,
        binding_id: str,
        provider_message_key: str,
    ) -> bool:
        """Retain the provider identity of a delivered Activity Tracker."""
        result = await session.execute(
            sa.update(RDBExternalChannelWork)
            .where(
                RDBExternalChannelWork.id == work_id,
                RDBExternalChannelWork.binding_id == binding_id,
                RDBExternalChannelWork.progress_provider_message_key.is_(None),
            )
            .values(progress_provider_message_key=provider_message_key)
            .returning(RDBExternalChannelWork.id)
        )
        return result.scalar_one_or_none() is not None

    async def get_work_by_progress_provider_message_key(
        self,
        session: AsyncSession,
        *,
        binding_id: str,
        provider_message_key: str,
    ) -> ExternalChannelWork | None:
        """Find the work cycle that owns one retained Tracker identity."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelWork).where(
                RDBExternalChannelWork.binding_id == binding_id,
                RDBExternalChannelWork.progress_provider_message_key
                == provider_message_key,
            )
        )
        return self._as(ExternalChannelWork, rdb)

    async def clear_work_progress_provider_message_key(
        self,
        session: AsyncSession,
        *,
        work_id: str,
        provider_message_key: str,
    ) -> bool:
        """Clear a Tracker identity only after provider deletion is confirmed."""
        result = await session.execute(
            sa.update(RDBExternalChannelWork)
            .where(
                RDBExternalChannelWork.id == work_id,
                RDBExternalChannelWork.progress_provider_message_key
                == provider_message_key,
            )
            .values(progress_provider_message_key=None)
            .returning(RDBExternalChannelWork.id)
        )
        return result.scalar_one_or_none() is not None

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


def validate_interaction_projection(projection: dict[str, Any]) -> None:
    """Reject unbounded or capability-bearing interaction metadata before storage."""
    _validate_interaction_projection_value(projection, depth=0)
    try:
        encoded = json.dumps(
            projection,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    except (TypeError, ValueError) as error:
        raise ValueError(
            "External Channel interaction projection must be JSON."
        ) from error
    if len(encoded) > _MAX_INTERACTION_PROJECTION_BYTES:
        raise ValueError("External Channel interaction projection exceeds 16 KiB.")


def _interaction_admission_is_compatible(
    existing: ExternalChannelInteraction,
    create: ExternalChannelInteractionCreate,
) -> bool:
    """Keep one provider key bound to one immutable authenticated interaction."""
    return (
        existing.connection_id == create.connection_id
        and existing.transport is create.transport
        and existing.interaction_type is create.interaction_type
        and existing.callback_id == create.callback_id
        and existing.action_id == create.action_id
        and existing.principal_id == create.principal_id
        and existing.resource_correlation_key == create.resource_correlation_key
        and existing.projection == create.projection
    )


def _validate_interaction_identifier(
    field_name: str,
    value: str,
    *,
    max_length: int,
) -> None:
    """Require one bounded non-capability-bearing opaque provider identifier."""
    if not value or len(value) > max_length:
        raise ValueError(
            f"External Channel interaction {field_name} has an invalid length."
        )
    if any(
        pattern.search(value)
        for pattern in _FORBIDDEN_INTERACTION_PROJECTION_VALUE_PATTERNS
    ):
        raise ValueError(
            f"External Channel interaction {field_name} contains a forbidden value."
        )
    if _INTERACTION_OPAQUE_VALUE_PATTERN.fullmatch(value) is None:
        raise ValueError(
            f"External Channel interaction {field_name} must be an opaque identifier."
        )


def _progress_delete_payload(
    labels: dict[str, Any] | None,
    provider_message_key: str,
) -> dict[str, object]:
    """Build one complete provider target for a progress deletion."""
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


def _validate_interaction_projection_value(value: object, *, depth: int) -> None:
    """Validate recursive interaction metadata bounds and safe key names."""
    if depth > _MAX_INTERACTION_PROJECTION_DEPTH:
        raise ValueError(
            "External Channel interaction projection is too deeply nested."
        )
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise ValueError(
            "External Channel interaction projection cannot contain binary."
        )
    if isinstance(value, dict):
        if len(value) > _MAX_INTERACTION_PROJECTION_ENTRIES:
            raise ValueError(
                "External Channel interaction projection has too many entries."
            )
        for key, nested_value in value.items():
            if not isinstance(key, str):
                raise ValueError(
                    "External Channel interaction projection keys must be strings."
                )
            if len(key) > _MAX_INTERACTION_PROJECTION_KEY_LENGTH:
                raise ValueError(
                    "External Channel interaction projection key is too long."
                )
            normalized_key = re.sub(r"[^a-z0-9]", "", key.lower())
            if any(
                forbidden in normalized_key
                for forbidden in _FORBIDDEN_INTERACTION_PROJECTION_KEY_PARTS
            ) or normalized_key.endswith(("url", "uri")):
                raise ValueError(
                    "External Channel interaction projection contains a forbidden key."
                )
            _validate_interaction_projection_value(nested_value, depth=depth + 1)
        return
    if isinstance(value, (list, tuple)):
        if len(value) > _MAX_INTERACTION_PROJECTION_ENTRIES:
            raise ValueError(
                "External Channel interaction projection has too many entries."
            )
        for nested_value in value:
            _validate_interaction_projection_value(nested_value, depth=depth + 1)
        return
    if (
        isinstance(value, str)
        and len(value) > _MAX_INTERACTION_PROJECTION_STRING_LENGTH
    ):
        raise ValueError("External Channel interaction projection string is too long.")
    if isinstance(value, str) and any(
        pattern.search(value)
        for pattern in _FORBIDDEN_INTERACTION_PROJECTION_VALUE_PATTERNS
    ):
        raise ValueError(
            "External Channel interaction projection contains a forbidden value."
        )
    if (
        isinstance(value, str)
        and value
        and _INTERACTION_OPAQUE_VALUE_PATTERN.fullmatch(value) is None
    ):
        raise ValueError(
            "External Channel interaction projection strings must be opaque "
            "identifiers."
        )
    if value is None or isinstance(value, bool | int | float | str):
        return
    raise ValueError(
        "External Channel interaction projection contains an invalid value."
    )
