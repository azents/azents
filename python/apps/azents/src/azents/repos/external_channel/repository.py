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

from azents.core.enums import (
    AgentLifecycleStatus,
    AgentSessionKind,
    ExternalChannelAccessGrantScope,
    ExternalChannelAccessRequestStatus,
    ExternalChannelAppMode,
    ExternalChannelChannelDefaultStatus,
    ExternalChannelConnectionStatus,
    ExternalChannelConversationScopeKind,
    ExternalChannelDeliveryOperation,
    ExternalChannelDeliveryOriginType,
    ExternalChannelDeliveryStatus,
    ExternalChannelIngressProfile,
    ExternalChannelInteractionStatus,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelRouteCatalogStatus,
    ExternalChannelRouteMode,
    ExternalChannelSessionActivationState,
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
    RDBExternalChannelAppClaim,
    RDBExternalChannelBinding,
    RDBExternalChannelBlock,
    RDBExternalChannelChannelDefault,
    RDBExternalChannelConnection,
    RDBExternalChannelConversationPosition,
    RDBExternalChannelDeliveryAttempt,
    RDBExternalChannelIngressLease,
    RDBExternalChannelInteraction,
    RDBExternalChannelPrincipal,
    RDBExternalChannelResource,
    RDBExternalChannelSessionActivation,
    RDBExternalChannelSessionActivationDelivery,
    RDBExternalChannelWork,
)
from azents.rdb.models.mailbox_item import RDBMailboxItem

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
    ExternalChannelConversationPosition,
    ExternalChannelConversationPositionCreate,
    ExternalChannelDeliveryAttempt,
    ExternalChannelDeliveryAttemptCreate,
    ExternalChannelIngressLease,
    ExternalChannelIngressLeaseClaim,
    ExternalChannelInteraction,
    ExternalChannelInteractionAdmission,
    ExternalChannelInteractionCreate,
    ExternalChannelPrincipal,
    ExternalChannelPrincipalCreate,
    ExternalChannelResource,
    ExternalChannelResourceCreate,
    ExternalChannelSessionActivation,
    ExternalChannelSessionActivationCreate,
    ExternalChannelSessionActivationDelivery,
    ExternalChannelSessionActivationDeliveryCreate,
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


async def block_initializing_session_activations(
    session: AsyncSession,
    *,
    binding_condition: sa.ColumnElement[bool],
    now: datetime.datetime,
) -> None:
    """Block retained Session input after its binding becomes terminal."""
    await session.execute(
        sa.update(RDBExternalChannelSessionActivation)
        .where(
            binding_condition,
            RDBExternalChannelSessionActivation.state
            == ExternalChannelSessionActivationState.INITIALIZING,
        )
        .values(
            state=ExternalChannelSessionActivationState.BLOCKED,
            failure_kind="binding_disconnected",
            failure_summary=("The binding disconnected before activation completed."),
            blocked_at=now,
        )
    )


class ExternalChannelRepository:
    """Provider-generic SQLAlchemy repository for External Channel state."""

    async def create_conversation_position_idempotent(
        self,
        session: AsyncSession,
        create: ExternalChannelConversationPositionCreate,
    ) -> ExternalChannelConversationPosition:
        """Create or return one connection-scoped conversation position."""
        if (
            create.scope_kind is ExternalChannelConversationScopeKind.PARENT_CHANNEL
            and create.provider_thread_key is not None
        ) or (
            create.scope_kind is ExternalChannelConversationScopeKind.THREAD
            and not create.provider_thread_key
        ):
            raise ValueError("Conversation position scope identity is invalid.")
        rdb = await self._insert_or_lookup(
            session,
            RDBExternalChannelConversationPosition,
            create,
            lambda: session.scalar(
                sa.select(RDBExternalChannelConversationPosition).where(
                    RDBExternalChannelConversationPosition.connection_id
                    == create.connection_id,
                    RDBExternalChannelConversationPosition.scope_kind
                    == create.scope_kind,
                    RDBExternalChannelConversationPosition.provider_channel_id
                    == create.provider_channel_id,
                    RDBExternalChannelConversationPosition.provider_thread_key
                    == create.provider_thread_key,
                )
            ),
        )
        return ExternalChannelConversationPosition.model_validate(rdb)

    async def get_conversation_position(
        self,
        session: AsyncSession,
        *,
        position_id: str,
    ) -> ExternalChannelConversationPosition | None:
        """Fetch one durable conversation position."""
        return self._as(
            ExternalChannelConversationPosition,
            await session.get(RDBExternalChannelConversationPosition, position_id),
        )

    async def get_conversation_position_by_scope(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        scope_kind: ExternalChannelConversationScopeKind,
        provider_channel_id: str,
        provider_thread_key: str | None,
    ) -> ExternalChannelConversationPosition | None:
        """Fetch a durable position by its canonical provider scope."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelConversationPosition).where(
                RDBExternalChannelConversationPosition.connection_id == connection_id,
                RDBExternalChannelConversationPosition.scope_kind == scope_kind,
                RDBExternalChannelConversationPosition.provider_channel_id
                == provider_channel_id,
                RDBExternalChannelConversationPosition.provider_thread_key
                == provider_thread_key,
            )
        )
        return self._as(ExternalChannelConversationPosition, rdb)

    async def lock_conversation_position(
        self,
        session: AsyncSession,
        *,
        position_id: str,
    ) -> ExternalChannelConversationPosition | None:
        """Lock one durable conversation position for compare-and-set."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelConversationPosition)
            .where(RDBExternalChannelConversationPosition.id == position_id)
            .with_for_update()
        )
        return self._as(ExternalChannelConversationPosition, rdb)

    async def advance_conversation_position_if_current(
        self,
        session: AsyncSession,
        *,
        position_id: str,
        expected_read_through_position: str | None,
        read_through_position: str,
    ) -> bool:
        """Advance a position only when its prior value still matches."""
        if not read_through_position:
            raise ValueError("Conversation read-through position must not be blank.")
        expected_predicate = (
            RDBExternalChannelConversationPosition.read_through_position.is_(None)
            if expected_read_through_position is None
            else RDBExternalChannelConversationPosition.read_through_position
            == expected_read_through_position
        )
        result = await session.execute(
            sa.update(RDBExternalChannelConversationPosition)
            .where(
                RDBExternalChannelConversationPosition.id == position_id,
                expected_predicate,
            )
            .values(read_through_position=read_through_position)
            .returning(RDBExternalChannelConversationPosition.id)
        )
        await session.flush()
        return result.scalar_one_or_none() is not None

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

    async def get_discord_http_configuration_by_selector_hash(
        self,
        session: AsyncSession,
        *,
        selector_hash: str,
    ) -> ExternalChannelConnectionConfiguration | None:
        """Fetch one active Discord callback target by its opaque selector hash."""
        rows = list(
            await session.scalars(
                sa.select(RDBExternalChannelConnection)
                .where(
                    RDBExternalChannelConnection.provider
                    == ExternalChannelProvider.DISCORD,
                    RDBExternalChannelConnection.ingress_profile
                    == ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP,
                    RDBExternalChannelConnection.http_callback_selector_hash
                    == selector_hash,
                    RDBExternalChannelConnection.status.in_(
                        (
                            ExternalChannelConnectionStatus.CONFIGURING,
                            ExternalChannelConnectionStatus.ACTIVE,
                            ExternalChannelConnectionStatus.DEGRADED,
                        )
                    ),
                )
                .limit(2)
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
        rdb.last_health_code = None
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

    async def activate_discord_connection(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        expected_encrypted_credentials: str,
        expected_configuration_generation: int,
        provider_app_id: str,
        provider_tenant_id: str,
        provider_bot_user_id: str | None,
        interaction_public_key: str,
        message_command_id: str,
        capabilities: dict[str, object],
        callback_selector_hash: str,
        checked_at: datetime.datetime,
    ) -> ExternalChannelConnection | None:
        """Activate a Discord App and current claim behind a credential fence."""
        connection = await session.scalar(
            sa.select(RDBExternalChannelConnection)
            .where(
                RDBExternalChannelConnection.id == connection_id,
                RDBExternalChannelConnection.provider
                == ExternalChannelProvider.DISCORD,
                RDBExternalChannelConnection.encrypted_credentials
                == expected_encrypted_credentials,
                RDBExternalChannelConnection.configuration_generation
                == expected_configuration_generation,
                RDBExternalChannelConnection.http_callback_selector_hash
                == callback_selector_hash,
                RDBExternalChannelConnection.status.not_in(
                    (
                        ExternalChannelConnectionStatus.DISCONNECTING,
                        ExternalChannelConnectionStatus.DISCONNECTED,
                    )
                ),
            )
            .with_for_update()
        )
        if connection is None:
            return None
        if connection.provider_app_id != provider_app_id:
            return None
        claim = await session.scalar(
            sa.select(RDBExternalChannelAppClaim)
            .where(
                RDBExternalChannelAppClaim.provider == ExternalChannelProvider.DISCORD,
                RDBExternalChannelAppClaim.provider_app_id == provider_app_id,
            )
            .with_for_update()
        )
        if claim is not None and claim.connection_id != connection_id:
            claimed_connection = await session.get(
                RDBExternalChannelConnection,
                claim.connection_id,
            )
            if (
                claimed_connection is None
                or claimed_connection.status
                is not ExternalChannelConnectionStatus.DISCONNECTED
            ):
                return None
            claim.connection_id = connection_id
        if claim is None:
            claim = RDBExternalChannelAppClaim(
                provider=ExternalChannelProvider.DISCORD,
                provider_app_id=provider_app_id,
                connection_id=connection_id,
                claim_generation=1,
            )
            session.add(claim)
        else:
            claim.claim_generation += 1
        connection.provider_tenant_id = provider_tenant_id
        connection.provider_bot_user_id = provider_bot_user_id
        connection.http_callback_selector_hash = callback_selector_hash
        connection.capabilities = {
            **capabilities,
            "interaction_public_key": interaction_public_key,
            "message_command_id": message_command_id,
        }
        connection.configuration_generation += 1
        connection.status = ExternalChannelConnectionStatus.ACTIVE
        connection.last_verified_at = checked_at
        connection.last_health_at = checked_at
        connection.last_health_code = None
        connection.disconnected_at = None
        await session.flush()
        await session.refresh(connection, attribute_names=["updated_at"])
        return ExternalChannelConnection.model_validate(connection)

    async def prepare_discord_callback(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        expected_encrypted_credentials: str,
        expected_configuration_generation: int,
        provider_app_id: str,
        interaction_public_key: str,
        callback_selector_hash: str,
    ) -> bool:
        """Persist PING-verification material before Discord verifies the callback."""
        connection = await session.scalar(
            sa.select(RDBExternalChannelConnection)
            .where(
                RDBExternalChannelConnection.id == connection_id,
                RDBExternalChannelConnection.provider
                == ExternalChannelProvider.DISCORD,
                RDBExternalChannelConnection.encrypted_credentials
                == expected_encrypted_credentials,
                RDBExternalChannelConnection.configuration_generation
                == expected_configuration_generation,
                RDBExternalChannelConnection.provider_app_id == provider_app_id,
                RDBExternalChannelConnection.status.not_in(
                    (
                        ExternalChannelConnectionStatus.DISCONNECTING,
                        ExternalChannelConnectionStatus.DISCONNECTED,
                    )
                ),
            )
            .with_for_update()
        )
        if connection is None:
            return False
        connection.http_callback_selector_hash = callback_selector_hash
        connection.capabilities = {
            "interaction_public_key": interaction_public_key,
        }
        connection.status = ExternalChannelConnectionStatus.CONFIGURING
        await session.flush()
        return True

    async def clear_prepared_discord_callback(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        expected_encrypted_credentials: str,
        expected_configuration_generation: int,
        callback_selector_hash: str,
        checked_at: datetime.datetime,
    ) -> bool:
        """Remove callback verification material after provider registration fails."""
        connection = await session.scalar(
            sa.select(RDBExternalChannelConnection)
            .where(
                RDBExternalChannelConnection.id == connection_id,
                RDBExternalChannelConnection.provider
                == ExternalChannelProvider.DISCORD,
                RDBExternalChannelConnection.encrypted_credentials
                == expected_encrypted_credentials,
                RDBExternalChannelConnection.configuration_generation
                == expected_configuration_generation,
                RDBExternalChannelConnection.http_callback_selector_hash
                == callback_selector_hash,
                RDBExternalChannelConnection.status.not_in(
                    (
                        ExternalChannelConnectionStatus.DISCONNECTING,
                        ExternalChannelConnectionStatus.DISCONNECTED,
                    )
                ),
            )
            .with_for_update()
        )
        if connection is None:
            return False
        connection.http_callback_selector_hash = None
        connection.capabilities = None
        connection.configuration_generation += 1
        connection.status = ExternalChannelConnectionStatus.RECONNECT_REQUIRED
        connection.last_health_at = checked_at
        await session.flush()
        return True

    async def record_discord_activation_failure(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        expected_encrypted_credentials: str,
        expected_configuration_generation: int,
        failure_code: str,
        checked_at: datetime.datetime,
    ) -> ExternalChannelConnection | None:
        """Persist one fenced, operator-safe Discord activation failure code."""
        connection = await session.scalar(
            sa.select(RDBExternalChannelConnection)
            .where(
                RDBExternalChannelConnection.id == connection_id,
                RDBExternalChannelConnection.provider
                == ExternalChannelProvider.DISCORD,
                RDBExternalChannelConnection.encrypted_credentials
                == expected_encrypted_credentials,
                RDBExternalChannelConnection.configuration_generation
                == expected_configuration_generation,
                RDBExternalChannelConnection.status.not_in(
                    (
                        ExternalChannelConnectionStatus.DISCONNECTING,
                        ExternalChannelConnectionStatus.DISCONNECTED,
                    )
                ),
            )
            .with_for_update()
        )
        if connection is None:
            return None
        connection.status = ExternalChannelConnectionStatus.RECONNECT_REQUIRED
        connection.last_health_at = checked_at
        connection.last_health_code = failure_code
        connection.socket_lease_owner = None
        connection.socket_lease_until = None
        connection.socket_heartbeat_at = None
        connection.socket_gap_detected_at = None
        connection.socket_gap_reason = None
        await session.flush()
        await session.refresh(connection, attribute_names=["updated_at"])
        return ExternalChannelConnection.model_validate(connection)

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

    async def list_discord_gateway_connection_ids(
        self,
        session: AsyncSession,
    ) -> list[str]:
        """List active Discord connections with a current App claim."""
        result = await session.scalars(
            sa.select(RDBExternalChannelConnection.id)
            .join(
                RDBExternalChannelAppClaim,
                RDBExternalChannelAppClaim.connection_id
                == RDBExternalChannelConnection.id,
            )
            .where(
                RDBExternalChannelConnection.provider
                == ExternalChannelProvider.DISCORD,
                RDBExternalChannelConnection.ingress_profile
                == ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP,
                RDBExternalChannelConnection.status.in_(
                    (
                        ExternalChannelConnectionStatus.ACTIVE,
                        ExternalChannelConnectionStatus.DEGRADED,
                    )
                ),
                RDBExternalChannelAppClaim.provider == ExternalChannelProvider.DISCORD,
            )
            .order_by(RDBExternalChannelConnection.id)
        )
        return list(result)

    async def claim_discord_gateway_lease(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        lease_owner: str,
        now: datetime.datetime,
        lease_until: datetime.datetime,
    ) -> ExternalChannelIngressLeaseClaim | None:
        """Claim one Discord lease while snapshotting current authority generations."""
        await session.execute(
            pg_insert(RDBExternalChannelIngressLease)
            .values(id=uuid7().hex, connection_id=connection_id)
            .on_conflict_do_nothing(index_elements=["connection_id"])
        )
        result = await session.execute(
            sa.update(RDBExternalChannelIngressLease)
            .where(
                RDBExternalChannelIngressLease.connection_id == connection_id,
                RDBExternalChannelIngressLease.connection_id
                == RDBExternalChannelConnection.id,
                RDBExternalChannelAppClaim.connection_id
                == RDBExternalChannelConnection.id,
                RDBExternalChannelConnection.provider
                == ExternalChannelProvider.DISCORD,
                RDBExternalChannelConnection.ingress_profile
                == ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP,
                RDBExternalChannelConnection.status.in_(
                    (
                        ExternalChannelConnectionStatus.ACTIVE,
                        ExternalChannelConnectionStatus.DEGRADED,
                    )
                ),
                RDBExternalChannelAppClaim.provider == ExternalChannelProvider.DISCORD,
                sa.or_(
                    RDBExternalChannelIngressLease.lease_owner == lease_owner,
                    RDBExternalChannelIngressLease.lease_until.is_(None),
                    RDBExternalChannelIngressLease.lease_until < now,
                ),
            )
            .values(
                lease_owner=lease_owner,
                lease_generation=RDBExternalChannelIngressLease.lease_generation + 1,
                lease_until=lease_until,
                heartbeat_at=now,
                required_configuration_generation=(
                    RDBExternalChannelConnection.configuration_generation
                ),
                required_app_claim_generation=(
                    RDBExternalChannelAppClaim.claim_generation
                ),
            )
            .returning(RDBExternalChannelIngressLease)
        )
        lease = result.scalar_one_or_none()
        if lease is None:
            return None
        return ExternalChannelIngressLeaseClaim(
            lease=ExternalChannelIngressLease.model_validate(lease)
        )

    async def get_owned_discord_gateway_configuration(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        lease_owner: str,
        lease_generation: int,
        now: datetime.datetime,
    ) -> ExternalChannelConnectionConfiguration | None:
        """Return credentials only when every Gateway authority fence matches."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelConnection)
            .join(
                RDBExternalChannelIngressLease,
                RDBExternalChannelIngressLease.connection_id
                == RDBExternalChannelConnection.id,
            )
            .join(
                RDBExternalChannelAppClaim,
                RDBExternalChannelAppClaim.connection_id
                == RDBExternalChannelConnection.id,
            )
            .where(
                _discord_gateway_lease_fence(
                    connection_id=connection_id,
                    lease_owner=lease_owner,
                    lease_generation=lease_generation,
                    now=now,
                )
            )
        )
        return self._as(ExternalChannelConnectionConfiguration, rdb)

    async def renew_discord_gateway_lease(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        lease_owner: str,
        lease_generation: int,
        now: datetime.datetime,
        lease_until: datetime.datetime,
    ) -> bool:
        """Renew only a current Discord Gateway owner with unchanged authority."""
        result = await session.execute(
            sa.update(RDBExternalChannelIngressLease)
            .where(
                _discord_gateway_lease_fence(
                    connection_id=connection_id,
                    lease_owner=lease_owner,
                    lease_generation=lease_generation,
                    now=now,
                )
            )
            .values(lease_until=lease_until, heartbeat_at=now)
            .returning(RDBExternalChannelIngressLease.id)
        )
        return result.scalar_one_or_none() is not None

    async def record_discord_gateway_gap(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        lease_owner: str,
        lease_generation: int,
        now: datetime.datetime,
        reason: str,
    ) -> bool:
        """Record a gap only for the current fenced Discord Gateway owner."""
        result = await session.execute(
            sa.select(
                RDBExternalChannelConnection,
                RDBExternalChannelIngressLease,
            )
            .join(
                RDBExternalChannelIngressLease,
                RDBExternalChannelIngressLease.connection_id
                == RDBExternalChannelConnection.id,
            )
            .join(
                RDBExternalChannelAppClaim,
                RDBExternalChannelAppClaim.connection_id
                == RDBExternalChannelConnection.id,
            )
            .where(
                _discord_gateway_lease_fence(
                    connection_id=connection_id,
                    lease_owner=lease_owner,
                    lease_generation=lease_generation,
                    now=now,
                )
            )
            .with_for_update()
        )
        owned = result.tuples().one_or_none()
        if owned is None:
            return False
        connection, lease = owned
        connection.status = ExternalChannelConnectionStatus.DEGRADED
        lease.gap_detected_at = now
        lease.gap_reason = reason
        lease.heartbeat_at = now
        await session.flush()
        return True

    async def mark_discord_gateway_active(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        lease_owner: str,
        lease_generation: int,
        now: datetime.datetime,
    ) -> bool:
        """Mark one current Discord Gateway lease active and clear its gap."""
        result = await session.execute(
            sa.select(
                RDBExternalChannelConnection,
                RDBExternalChannelIngressLease,
            )
            .join(
                RDBExternalChannelIngressLease,
                RDBExternalChannelIngressLease.connection_id
                == RDBExternalChannelConnection.id,
            )
            .join(
                RDBExternalChannelAppClaim,
                RDBExternalChannelAppClaim.connection_id
                == RDBExternalChannelConnection.id,
            )
            .where(
                _discord_gateway_lease_fence(
                    connection_id=connection_id,
                    lease_owner=lease_owner,
                    lease_generation=lease_generation,
                    now=now,
                )
            )
            .with_for_update()
        )
        owned = result.tuples().one_or_none()
        if owned is None:
            return False
        connection, lease = owned
        connection.status = ExternalChannelConnectionStatus.ACTIVE
        lease.gap_detected_at = None
        lease.gap_reason = None
        lease.heartbeat_at = now
        await session.flush()
        return True

    async def mark_discord_gateway_reconnect_required(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        lease_owner: str,
        lease_generation: int,
        now: datetime.datetime,
        reason: str,
    ) -> bool:
        """Terminalize one current Discord Gateway lease and preserve its route."""
        result = await session.execute(
            sa.select(
                RDBExternalChannelConnection,
                RDBExternalChannelIngressLease,
            )
            .join(
                RDBExternalChannelIngressLease,
                RDBExternalChannelIngressLease.connection_id
                == RDBExternalChannelConnection.id,
            )
            .join(
                RDBExternalChannelAppClaim,
                RDBExternalChannelAppClaim.connection_id
                == RDBExternalChannelConnection.id,
            )
            .where(
                _discord_gateway_lease_fence(
                    connection_id=connection_id,
                    lease_owner=lease_owner,
                    lease_generation=lease_generation,
                    now=now,
                )
            )
            .with_for_update()
        )
        owned = result.tuples().one_or_none()
        if owned is None:
            return False
        connection, lease = owned
        connection.status = ExternalChannelConnectionStatus.RECONNECT_REQUIRED
        lease.lease_owner = None
        lease.lease_until = None
        lease.heartbeat_at = now
        lease.gap_detected_at = now
        lease.gap_reason = reason
        await session.flush()
        return True

    async def release_discord_gateway_lease(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        lease_owner: str,
        lease_generation: int,
        now: datetime.datetime,
    ) -> bool:
        """Release one current Discord lease without mutating connection authority."""
        result = await session.execute(
            sa.update(RDBExternalChannelIngressLease)
            .where(
                _discord_gateway_lease_fence(
                    connection_id=connection_id,
                    lease_owner=lease_owner,
                    lease_generation=lease_generation,
                    now=now,
                )
            )
            .values(lease_owner=None, lease_until=None, heartbeat_at=now)
            .returning(RDBExternalChannelIngressLease.id)
        )
        return result.scalar_one_or_none() is not None

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
        required_configuration_generation: int | None,
        required_socket_lease_owner: str | None,
        defer_provider_state_purge: bool,
    ) -> tuple[str, ...] | None:
        """Fence provider resources after an explicit App uninstall."""
        if status is not ExternalChannelConnectionStatus.DISCONNECTED:
            raise ValueError("Provider termination requires disconnection.")
        statement = sa.select(RDBExternalChannelConnection).where(
            RDBExternalChannelConnection.id == connection_id
        )
        if required_configuration_generation is not None:
            statement = statement.where(
                RDBExternalChannelConnection.configuration_generation
                == required_configuration_generation
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
            if binding.disconnected_at is None:
                binding.disconnected_at = now
                binding.disconnect_reason = reason
        await block_initializing_session_activations(
            session,
            binding_condition=(
                RDBExternalChannelSessionActivation.binding_id.in_(binding_ids)
            ),
            now=now,
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
        required_configuration_generation: int | None,
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
        if required_configuration_generation is not None:
            statement = statement.where(
                RDBExternalChannelConnection.configuration_generation
                == required_configuration_generation
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
        await session.refresh(rdb, attribute_names=["updated_at"])
        return ExternalChannelInteraction.model_validate(rdb)

    async def replace_interaction_projection(
        self,
        session: AsyncSession,
        *,
        interaction_id: str,
        projection: dict[str, Any],
    ) -> ExternalChannelInteraction | None:
        """Replace bounded interaction metadata under the interaction lock."""
        validate_interaction_projection(projection)
        rdb = await session.scalar(
            sa.select(RDBExternalChannelInteraction)
            .where(RDBExternalChannelInteraction.id == interaction_id)
            .with_for_update()
        )
        if rdb is None:
            return None
        rdb.projection = projection
        await session.flush()
        await session.refresh(rdb, attribute_names=["updated_at"])
        return ExternalChannelInteraction.model_validate(rdb)

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
        author_type: ExternalChannelPrincipalAuthorType,
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
        if author_type is not ExternalChannelPrincipalAuthorType.HUMAN:
            return []
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

    async def get_discord_resource_by_delivery_channel(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        guild_id: str,
        delivery_channel_id: str,
    ) -> ExternalChannelResource | None:
        """Fetch one Discord resource by its retained conversation thread identity."""
        rows = list(
            await session.scalars(
                sa.select(RDBExternalChannelResource)
                .where(
                    RDBExternalChannelResource.connection_id == connection_id,
                    RDBExternalChannelResource.labels.contains(
                        {
                            "provider": ExternalChannelProvider.DISCORD.value,
                            "guild_id": guild_id,
                            "delivery_channel_id": delivery_channel_id,
                        }
                    ),
                )
                .limit(2)
            )
        )
        if len(rows) != 1:
            return None
        return ExternalChannelResource.model_validate(rows[0])

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
                RDBExternalChannelBinding.disconnected_at.is_(None),
            )
            .values(
                disconnected_at=now,
                disconnect_reason=reason,
            )
        )
        await block_initializing_session_activations(
            session,
            binding_condition=(
                RDBExternalChannelSessionActivation.binding_id.in_(binding_ids)
            ),
            now=now,
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

    async def create_binding_idempotent(
        self,
        session: AsyncSession,
        create: ExternalChannelBindingCreate,
        *,
        expected_access_request_id: str | None,
    ) -> ExternalChannelBinding:
        """Create or return the active binding for one resource and route."""
        resource = await self.lock_resource(
            session,
            resource_id=create.resource_id,
        )
        if resource is None:
            raise ValueError("External Channel binding resource does not exist.")
        existing = await self.lock_connected_binding_by_resource(
            session,
            resource_id=create.resource_id,
        )
        await self._validate_binding_owners(
            session,
            create,
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
        rdb = RDBExternalChannelBinding(**create.model_dump())
        session.add(rdb)
        await session.flush()
        return ExternalChannelBinding.model_validate(rdb)

    async def _validate_binding_owners(
        self,
        session: AsyncSession,
        create: ExternalChannelBindingCreate,
        *,
        expected_access_request_id: str | None,
    ) -> None:
        """Validate owners and any durable access-request authority."""
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

    async def get_connected_binding_by_resource(
        self,
        session: AsyncSession,
        *,
        resource_id: str,
    ) -> ExternalChannelBinding | None:
        """Fetch the one connected binding allowed for an external resource."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelBinding).where(
                RDBExternalChannelBinding.resource_id == resource_id,
                RDBExternalChannelBinding.disconnected_at.is_(None),
            )
        )
        return self._as(ExternalChannelBinding, rdb)

    async def lock_connected_binding_by_resource(
        self,
        session: AsyncSession,
        *,
        resource_id: str,
    ) -> ExternalChannelBinding | None:
        """Lock the one connected binding after its resource lock."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelBinding)
            .where(
                RDBExternalChannelBinding.resource_id == resource_id,
                RDBExternalChannelBinding.disconnected_at.is_(None),
            )
            .with_for_update()
        )
        return self._as(ExternalChannelBinding, rdb)

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

    async def create_session_activation_idempotent(
        self,
        session: AsyncSession,
        create: ExternalChannelSessionActivationCreate,
    ) -> ExternalChannelSessionActivation:
        """Create or return one activation for a canonical provider trigger."""
        rdb = await self._insert_or_lookup(
            session,
            RDBExternalChannelSessionActivation,
            create,
            lambda: session.scalar(
                sa.select(RDBExternalChannelSessionActivation).where(
                    RDBExternalChannelSessionActivation.conversation_position_id
                    == create.conversation_position_id,
                    RDBExternalChannelSessionActivation.trigger_provider_message_key
                    == create.trigger_provider_message_key,
                    RDBExternalChannelSessionActivation.trigger_position
                    == create.trigger_position,
                )
            ),
        )
        activation = ExternalChannelSessionActivation.model_validate(rdb)
        if (
            activation.connection_id != create.connection_id
            or activation.binding_id != create.binding_id
            or activation.agent_session_id != create.agent_session_id
            or activation.range_start_position != create.range_start_position
            or activation.mailbox_item_id != create.mailbox_item_id
        ):
            raise ValueError("External Channel activation retry is incompatible.")
        return activation

    async def get_session_activation_state_by_mailbox_item_id(
        self,
        session: AsyncSession,
        *,
        mailbox_item_id: str,
    ) -> ExternalChannelSessionActivationState | None:
        """Return the durable execution gate for one canonical mailbox item."""
        return await session.scalar(
            sa.select(RDBExternalChannelSessionActivation.state).where(
                RDBExternalChannelSessionActivation.mailbox_item_id == mailbox_item_id
            )
        )

    async def get_session_activation_by_trigger(
        self,
        session: AsyncSession,
        *,
        conversation_position_id: str,
        trigger_provider_message_key: str,
        trigger_position: str,
    ) -> ExternalChannelSessionActivation | None:
        """Fetch the activation retained for one canonical provider trigger."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelSessionActivation).where(
                RDBExternalChannelSessionActivation.conversation_position_id
                == conversation_position_id,
                RDBExternalChannelSessionActivation.trigger_provider_message_key
                == trigger_provider_message_key,
                RDBExternalChannelSessionActivation.trigger_position
                == trigger_position,
            )
        )
        return self._as(ExternalChannelSessionActivation, rdb)

    async def get_open_session_activation_by_position(
        self,
        session: AsyncSession,
        *,
        conversation_position_id: str,
    ) -> ExternalChannelSessionActivation | None:
        """Fetch the current activation barrier for a conversation position."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelSessionActivation).where(
                RDBExternalChannelSessionActivation.conversation_position_id
                == conversation_position_id,
                RDBExternalChannelSessionActivation.state.in_(
                    (
                        ExternalChannelSessionActivationState.INITIALIZING,
                        ExternalChannelSessionActivationState.BLOCKED,
                    )
                ),
            )
        )
        return self._as(ExternalChannelSessionActivation, rdb)

    async def lock_session_activation(
        self,
        session: AsyncSession,
        *,
        activation_id: str,
    ) -> ExternalChannelSessionActivation | None:
        """Lock one activation before a terminal transition."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelSessionActivation)
            .where(RDBExternalChannelSessionActivation.id == activation_id)
            .with_for_update()
        )
        return self._as(ExternalChannelSessionActivation, rdb)

    async def create_session_activation_delivery_idempotent(
        self,
        session: AsyncSession,
        create: ExternalChannelSessionActivationDeliveryCreate,
    ) -> ExternalChannelSessionActivationDelivery:
        """Create or return one stable ordered activation delivery link."""
        rdb = await self._insert_or_lookup(
            session,
            RDBExternalChannelSessionActivationDelivery,
            create,
            lambda: session.scalar(
                sa.select(RDBExternalChannelSessionActivationDelivery).where(
                    RDBExternalChannelSessionActivationDelivery.activation_id
                    == create.activation_id,
                    RDBExternalChannelSessionActivationDelivery.ordinal
                    == create.ordinal,
                )
            ),
        )
        delivery = ExternalChannelSessionActivationDelivery.model_validate(rdb)
        if delivery.delivery_attempt_id != create.delivery_attempt_id:
            raise ValueError(
                "External Channel activation delivery retry is incompatible."
            )
        return delivery

    async def list_session_activation_deliveries(
        self,
        session: AsyncSession,
        *,
        activation_id: str,
    ) -> tuple[ExternalChannelSessionActivationDelivery, ...]:
        """List required provider deliveries in activation order."""
        rows = await session.scalars(
            sa.select(RDBExternalChannelSessionActivationDelivery)
            .where(
                RDBExternalChannelSessionActivationDelivery.activation_id
                == activation_id
            )
            .order_by(RDBExternalChannelSessionActivationDelivery.ordinal)
        )
        return tuple(
            ExternalChannelSessionActivationDelivery.model_validate(row) for row in rows
        )

    async def block_session_activation(
        self,
        session: AsyncSession,
        *,
        activation_id: str,
        failure_kind: str,
        failure_summary: str,
        blocked_at: datetime.datetime,
    ) -> ExternalChannelSessionActivation | None:
        """Terminally block one initializing activation without execution."""
        result = await session.execute(
            sa.update(RDBExternalChannelSessionActivation)
            .where(
                RDBExternalChannelSessionActivation.id == activation_id,
                RDBExternalChannelSessionActivation.state
                == ExternalChannelSessionActivationState.INITIALIZING,
            )
            .values(
                state=ExternalChannelSessionActivationState.BLOCKED,
                failure_kind=failure_kind,
                failure_summary=failure_summary,
                blocked_at=blocked_at,
            )
            .returning(RDBExternalChannelSessionActivation)
        )
        return self._as(ExternalChannelSessionActivation, result.scalar_one_or_none())

    async def activate_session_activation(
        self,
        session: AsyncSession,
        *,
        activation_id: str,
        mailbox_item_id: str,
        activated_at: datetime.datetime,
    ) -> ExternalChannelSessionActivation | None:
        """Mark one fully initialized activation executable exactly once."""
        linked_deliveries = sa.select(
            RDBExternalChannelSessionActivationDelivery.id
        ).where(
            RDBExternalChannelSessionActivationDelivery.activation_id == activation_id
        )
        incomplete_deliveries = (
            sa.select(RDBExternalChannelSessionActivationDelivery.id)
            .join(
                RDBExternalChannelDeliveryAttempt,
                RDBExternalChannelDeliveryAttempt.id
                == RDBExternalChannelSessionActivationDelivery.delivery_attempt_id,
            )
            .where(
                RDBExternalChannelSessionActivationDelivery.activation_id
                == activation_id,
                RDBExternalChannelDeliveryAttempt.status
                != ExternalChannelDeliveryStatus.DELIVERED,
            )
        )
        connected_binding = sa.select(RDBExternalChannelBinding.id).where(
            RDBExternalChannelBinding.id
            == RDBExternalChannelSessionActivation.binding_id,
            RDBExternalChannelBinding.disconnected_at.is_(None),
        )
        owned_mailbox_item = sa.select(RDBMailboxItem.id).where(
            RDBMailboxItem.id == mailbox_item_id,
            RDBMailboxItem.session_id
            == RDBExternalChannelSessionActivation.agent_session_id,
            RDBExternalChannelSessionActivation.mailbox_item_id == mailbox_item_id,
        )
        result = await session.execute(
            sa.update(RDBExternalChannelSessionActivation)
            .where(
                RDBExternalChannelSessionActivation.id == activation_id,
                RDBExternalChannelSessionActivation.state
                == ExternalChannelSessionActivationState.INITIALIZING,
                sa.exists(linked_deliveries),
                ~sa.exists(incomplete_deliveries),
                sa.exists(connected_binding),
                sa.exists(owned_mailbox_item),
            )
            .values(
                state=ExternalChannelSessionActivationState.ACTIVATED,
                activated_at=activated_at,
            )
            .returning(RDBExternalChannelSessionActivation)
        )
        return self._as(ExternalChannelSessionActivation, result.scalar_one_or_none())

    async def create_access_request_idempotent(
        self,
        session: AsyncSession,
        create: ExternalChannelAccessRequestCreate,
    ) -> ExternalChannelAccessRequest:
        """Create or return an access request for one provider trigger."""
        if create.connection_id is None:
            connection_id = await session.scalar(
                sa.select(RDBExternalChannelResource.connection_id).where(
                    RDBExternalChannelResource.id == create.resource_id
                )
            )
            create = create.model_copy(update={"connection_id": connection_id})
        rdb = await self._insert_or_lookup(
            session,
            RDBExternalChannelAccessRequest,
            create,
            lambda: session.scalar(
                sa.select(RDBExternalChannelAccessRequest).where(
                    RDBExternalChannelAccessRequest.route_id == create.route_id,
                    RDBExternalChannelAccessRequest.trigger_provider_message_key
                    == create.trigger_provider_message_key,
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
        provider = await session.scalar(
            sa.select(RDBExternalChannelConnection.provider)
            .join(
                RDBExternalChannelAgentRoute,
                RDBExternalChannelAgentRoute.connection_id
                == RDBExternalChannelConnection.id,
            )
            .join(
                RDBExternalChannelAccessRequest,
                RDBExternalChannelAccessRequest.route_id
                == RDBExternalChannelAgentRoute.id,
            )
            .where(RDBExternalChannelAccessRequest.id == access_request_id)
        )
        if provider is ExternalChannelProvider.DISCORD:
            guild_id = control.request_payload.get("guild_id")
            channel_id = control.request_payload.get("channel_id")
            if (
                not isinstance(guild_id, str)
                or not guild_id
                or not isinstance(channel_id, str)
                or not channel_id
            ):
                return None
            payload = {
                "guild_id": guild_id,
                "channel_id": channel_id,
                "provider_message_key": control.provider_message_key,
            }
            for key in ("thread_parent_channel_id", "thread_root_message_id"):
                value = control.request_payload.get(key)
                if isinstance(value, str) and value:
                    payload[key] = value
        elif provider is ExternalChannelProvider.SLACK:
            channel_id = control.request_payload.get("channel_id")
            thread_ts = control.request_payload.get("thread_ts")
            if not isinstance(channel_id, str) or not isinstance(thread_ts, str):
                return None
            payload = {
                "channel_id": channel_id,
                "thread_ts": thread_ts,
                "provider_message_key": control.provider_message_key,
            }
        else:
            return None
        return await self.create_delivery_attempt_idempotent(
            session,
            ExternalChannelDeliveryAttemptCreate(
                origin_type=ExternalChannelDeliveryOriginType.ACCESS_REQUEST,
                origin_id=access_request_id,
                channel_action_id=None,
                binding_id=None,
                operation=ExternalChannelDeliveryOperation.PROGRESS_DELETE,
                request_payload=payload,
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
            RDBExternalChannelDeliveryAttempt.part_ordinal == create.part_ordinal,
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


def _discord_gateway_lease_fence(
    *,
    connection_id: str,
    lease_owner: str,
    lease_generation: int,
    now: datetime.datetime,
) -> sa.ColumnElement[bool]:
    """Return the complete current-authority predicate for Discord lease mutation."""
    return sa.and_(
        RDBExternalChannelIngressLease.connection_id == connection_id,
        RDBExternalChannelIngressLease.connection_id == RDBExternalChannelConnection.id,
        RDBExternalChannelAppClaim.connection_id == RDBExternalChannelConnection.id,
        RDBExternalChannelConnection.provider == ExternalChannelProvider.DISCORD,
        RDBExternalChannelConnection.ingress_profile
        == ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP,
        RDBExternalChannelConnection.status.in_(
            (
                ExternalChannelConnectionStatus.ACTIVE,
                ExternalChannelConnectionStatus.DEGRADED,
            )
        ),
        RDBExternalChannelAppClaim.provider == ExternalChannelProvider.DISCORD,
        RDBExternalChannelIngressLease.lease_owner == lease_owner,
        RDBExternalChannelIngressLease.lease_generation == lease_generation,
        RDBExternalChannelIngressLease.lease_until >= now,
        RDBExternalChannelIngressLease.required_configuration_generation
        == RDBExternalChannelConnection.configuration_generation,
        RDBExternalChannelIngressLease.required_app_claim_generation
        == RDBExternalChannelAppClaim.claim_generation,
    )


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
