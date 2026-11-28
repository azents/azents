"""Durable one-shot claims and exact provider delivery authority for Vault requests."""

from dataclasses import dataclass, field
from typing import Annotated

import sqlalchemy as sa
from fastapi import Depends
from pydantic import BaseModel, ConfigDict, ValidationError

from azents.core.enums import (
    AgentSessionStatus,
    ExternalChannelConnectionStatus,
    ExternalChannelProvider,
)
from azents.core.vault_request import VaultChannelReference, VaultRequestField
from azents.rdb.deps import get_session_manager
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.agent_vault_request import (
    RDBAgentVaultRequest,
    VaultRequestStatus,
)
from azents.rdb.models.external_channel import (
    RDBExternalChannelBinding,
    RDBExternalChannelConnection,
)
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_vault_requests import read_vault_clock
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.session_resource_authority import (
    AuthorizedPublicSessionResource,
    resolve_agent_session_resource,
)


class _Destination(VaultChannelReference):
    binding_id: str


class VaultDeliveryReceipt(BaseModel):
    """The observed target and original provider message identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    connection_id: str
    provider: ExternalChannelProvider
    tenant_id: str
    app_id: str
    bot_id: str
    channel_id: str
    provider_message_key: str


@dataclass(frozen=True)
class VaultDeliveryTarget:
    """Ephemeral live target; no plaintext is persisted as delivery evidence."""

    connection_id: str
    provider: ExternalChannelProvider
    tenant_id: str
    app_id: str
    bot_id: str
    channel_id: str
    workspace_handle: str
    agent_id: str
    session_id: str
    status: VaultRequestStatus
    receipt: VaultDeliveryReceipt | None
    purpose: str = field(repr=False)
    field_labels: tuple[str, ...] = field(repr=False)
    encrypted_credentials: str = field(repr=False)

    def matches_receipt(self, receipt: VaultDeliveryReceipt) -> bool:
        """Require the exact provider installation, author, and channel."""
        return (
            self.connection_id == receipt.connection_id
            and self.provider is receipt.provider
            and self.tenant_id == receipt.tenant_id
            and self.app_id == receipt.app_id
            and self.bot_id == receipt.bot_id
            and self.channel_id == receipt.channel_id
        )


@dataclass(frozen=True)
class VaultRequestDeliveryRepository:
    """Coordinate provider effects without doing network I/O under DB locks."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]

    async def claim(self, *, terminal: bool) -> str | None:
        """Claim one eligible attempt; never replay an ambiguous effect."""
        request = RDBAgentVaultRequest
        async with self.session_manager() as session:
            now = await read_vault_clock(session)
            if terminal:
                predicates = (
                    request.terminal_at.is_not(None),
                    request.receipt.is_not(None),
                    request.edit_claimed_at.is_(None),
                )
                order = request.terminal_at
                claim_at = request.edit_claimed_at
            else:
                predicates = (
                    request.status == VaultRequestStatus.OPEN,
                    request.deadline_at > now,
                    request.destination.is_not(None),
                    request.post_claimed_at.is_(None),
                )
                order = request.creation_at
                claim_at = request.post_claimed_at
            candidate = (
                sa.select(request.id)
                .where(*predicates)
                .order_by(order, request.id)
                .limit(1)
                .with_for_update(skip_locked=True)
                .scalar_subquery()
            )
            return await session.write_session.scalar(
                sa.update(request)
                .where(request.id == candidate)
                .values({claim_at: now})
                .returning(request.id)
            )

    async def read_target(
        self, request_id: str, *, terminal: bool
    ) -> VaultDeliveryTarget | None:
        """Recheck exact authority and open or terminal state at dispatch."""
        async with self.session_manager() as session:
            row = await session.read_session.get(RDBAgentVaultRequest, request_id)
            if row is None or row.destination is None:
                return None
            if terminal:
                if row.edit_claimed_at is None or row.status is VaultRequestStatus.OPEN:
                    return None
            elif (
                row.post_claimed_at is None
                or row.status is not VaultRequestStatus.OPEN
                or row.deadline_at <= await read_vault_clock(session)
            ):
                return None
            try:
                destination = _Destination.model_validate(row.destination)
                receipt = (
                    VaultDeliveryReceipt.model_validate(row.receipt)
                    if terminal
                    else None
                )
                field_labels = tuple(
                    VaultRequestField.model_validate(item).label for item in row.fields
                )
            except ValidationError:
                return None
            sessions = AgentSessionRepository()
            source = await sessions.get_by_id(session, row.session_id)
            if source is None:
                return None
            root_id: str | None = None
            if not terminal:
                authority = await resolve_agent_session_resource(
                    session,
                    agent_session=source,
                    expected_workspace_id=source.workspace_id,
                    expected_agent_id=source.agent_id,
                    agent_session_repository=sessions,
                )
                if (
                    not isinstance(authority, AuthorizedPublicSessionResource)
                    or source.stop_requested_at is not None
                    or authority.root_session.stop_requested_at is not None
                ):
                    return None
                root_id = authority.root_session.id
            routes = ExternalChannelRepository()
            binding = await routes.find_exact_connected_channel(
                session,
                workspace_id=source.workspace_id,
                agent_id=source.agent_id,
                provider=destination.provider,
                channel_id=destination.channel_id,
            )
            if binding is None or binding.id != destination.binding_id:
                return None
            resource = await routes.get_resource(
                session, resource_id=binding.resource_id
            )
            if resource is None:
                return None
            connection = await routes.get_connection_configuration(
                session, connection_id=resource.connection_id
            )
            if (
                connection is None
                or connection.provider is not destination.provider
                or connection.workspace_id != source.workspace_id
                or connection.disconnected_at is not None
                or connection.status
                not in {
                    ExternalChannelConnectionStatus.ACTIVE,
                    ExternalChannelConnectionStatus.DEGRADED,
                }
                or not connection.provider_tenant_id
                or not connection.provider_app_id
                or not connection.provider_bot_user_id
                or not connection.encrypted_credentials
            ):
                return None
            workspace_handle = await session.read_session.scalar(
                sa.select(RDBWorkspace.handle).where(
                    RDBWorkspace.id == source.workspace_id
                )
            )
            if workspace_handle is None:
                return None
            target = VaultDeliveryTarget(
                connection_id=connection.id,
                provider=connection.provider,
                tenant_id=connection.provider_tenant_id,
                app_id=connection.provider_app_id,
                bot_id=connection.provider_bot_user_id,
                channel_id=destination.channel_id,
                workspace_handle=workspace_handle,
                agent_id=source.agent_id,
                session_id=source.id,
                status=row.status,
                receipt=receipt,
                purpose=row.purpose,
                field_labels=field_labels,
                encrypted_credentials=connection.encrypted_credentials,
            )
            if receipt is not None and not target.matches_receipt(receipt):
                return None
            # Check the prepared target and request in one fresh DB snapshot,
            # without provider network activity in the transaction.
            request = RDBAgentVaultRequest
            valid_request = sa.exists().where(
                request.id == request_id,
                request.session_id == source.id,
                request.status == row.status,
            )
            if terminal:
                valid_request = valid_request.where(
                    request.edit_claimed_at.is_not(None), request.receipt == row.receipt
                )
            else:
                assert root_id is not None
                eligible_session_ids = (
                    sa.select(sa.func.count(RDBAgentSession.id))
                    .where(
                        RDBAgentSession.id.in_({root_id, source.id}),
                        RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                        RDBAgentSession.stop_requested_at.is_(None),
                    )
                    .scalar_subquery()
                )
                valid_request = valid_request.where(
                    request.post_claimed_at.is_not(None),
                    request.deadline_at > sa.func.clock_timestamp(),
                    eligible_session_ids == len({root_id, source.id}),
                )
            connection_row = RDBExternalChannelConnection
            candidates = routes.exact_connected_channel_statement(
                workspace_id=source.workspace_id,
                agent_id=source.agent_id,
                provider=destination.provider,
                channel_id=destination.channel_id,
            ).with_only_columns(
                RDBExternalChannelBinding.id,
                sa.and_(
                    valid_request,
                    connection_row.id == target.connection_id,
                    connection_row.provider_tenant_id == target.tenant_id,
                    connection_row.provider_app_id == target.app_id,
                    connection_row.provider_bot_user_id == target.bot_id,
                    connection_row.encrypted_credentials
                    == target.encrypted_credentials,
                    connection_row.configuration_generation
                    == connection.configuration_generation,
                ).label("effect_allowed"),
            )
            eligible = (await session.read_session.execute(candidates)).all()
            return target if eligible == [(destination.binding_id, True)] else None

    async def record_receipt(
        self, request_id: str, receipt: VaultDeliveryReceipt
    ) -> None:
        """Save the exact receipt even if settlement beat the provider reply."""
        async with self.session_manager() as session:
            await session.write_session.execute(
                sa.update(RDBAgentVaultRequest)
                .where(
                    RDBAgentVaultRequest.id == request_id,
                    RDBAgentVaultRequest.post_claimed_at.is_not(None),
                    RDBAgentVaultRequest.receipt.is_(None),
                )
                .values(receipt=receipt.model_dump(mode="json"))
            )
