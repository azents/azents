"""Completed Discord activation and Gateway database operations."""

import dataclasses
import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import (
    DiscordGatewayTypingTarget,
    ExternalChannelConnection,
    ExternalChannelConnectionConfiguration,
    ExternalChannelIngressLeaseClaim,
)
from azents.repos.external_channel.repository import ExternalChannelRepository


@dataclasses.dataclass
class DiscordConnectionOperationRepository:
    """Own completed Discord connection activation and Gateway operations."""

    session_manager: SessionManager[AsyncSession]
    external_channel_repository: ExternalChannelRepository

    async def get_configuration(
        self,
        connection_id: str,
    ) -> ExternalChannelConnectionConfiguration | None:
        """Return one completed connection configuration snapshot."""
        async with self.session_manager() as session:
            return await self.external_channel_repository.get_connection_configuration(
                session,
                connection_id=connection_id,
            )

    async def prepare_callback(
        self,
        *,
        connection_id: str,
        expected_encrypted_credentials: str,
        expected_configuration_generation: int,
        provider_app_id: str,
        interaction_public_key: str,
        callback_selector_hash: str,
    ) -> bool:
        """Persist one provisional callback configuration."""
        async with self.session_manager() as session:
            prepared = await self.external_channel_repository.prepare_discord_callback(
                session,
                connection_id=connection_id,
                expected_encrypted_credentials=expected_encrypted_credentials,
                expected_configuration_generation=expected_configuration_generation,
                provider_app_id=provider_app_id,
                interaction_public_key=interaction_public_key,
                callback_selector_hash=callback_selector_hash,
            )
            if prepared:
                await session.commit()
            return prepared

    async def activate(
        self,
        *,
        connection_id: str,
        expected_encrypted_credentials: str,
        expected_configuration_generation: int,
        provider_app_id: str,
        provider_tenant_id: str,
        provider_bot_user_id: str | None,
        interaction_public_key: str,
        command_set: dict[str, object],
        capabilities: dict[str, object],
        callback_selector_hash: str,
        checked_at: datetime.datetime,
    ) -> ExternalChannelConnection | None:
        """Commit one fenced Discord activation."""
        async with self.session_manager() as session:
            repository = self.external_channel_repository
            activated = await repository.activate_discord_connection(
                session,
                connection_id=connection_id,
                expected_encrypted_credentials=expected_encrypted_credentials,
                expected_configuration_generation=expected_configuration_generation,
                provider_app_id=provider_app_id,
                provider_tenant_id=provider_tenant_id,
                provider_bot_user_id=provider_bot_user_id,
                interaction_public_key=interaction_public_key,
                command_set=command_set,
                capabilities=capabilities,
                callback_selector_hash=callback_selector_hash,
                checked_at=checked_at,
            )
            if activated is not None:
                await session.commit()
            return activated

    async def record_activation_failure(
        self,
        *,
        connection_id: str,
        expected_encrypted_credentials: str,
        expected_configuration_generation: int,
        failure_code: str,
        checked_at: datetime.datetime,
    ) -> ExternalChannelConnection | None:
        """Persist one fenced safe Discord activation failure."""
        async with self.session_manager() as session:
            failed = await (
                self.external_channel_repository.record_discord_activation_failure(
                    session,
                    connection_id=connection_id,
                    expected_encrypted_credentials=expected_encrypted_credentials,
                    expected_configuration_generation=(
                        expected_configuration_generation
                    ),
                    failure_code=failure_code,
                    checked_at=checked_at,
                )
            )
            if failed is not None:
                await session.commit()
            return failed

    async def clear_prepared_callback(
        self,
        *,
        connection_id: str,
        expected_encrypted_credentials: str,
        expected_configuration_generation: int,
        callback_selector_hash: str,
        checked_at: datetime.datetime,
    ) -> bool:
        """Clear one fenced provisional Discord callback."""
        async with self.session_manager() as session:
            cleared = await (
                self.external_channel_repository.clear_prepared_discord_callback(
                    session,
                    connection_id=connection_id,
                    expected_encrypted_credentials=expected_encrypted_credentials,
                    expected_configuration_generation=(
                        expected_configuration_generation
                    ),
                    callback_selector_hash=callback_selector_hash,
                    checked_at=checked_at,
                )
            )
            await session.commit()
            return cleared

    async def list_gateway_connection_ids(self) -> list[str]:
        """Return completed active Discord Gateway connection IDs."""
        async with self.session_manager() as session:
            return await (
                self.external_channel_repository.list_discord_gateway_connection_ids(
                    session
                )
            )

    async def claim_gateway_lease(
        self,
        *,
        connection_id: str,
        lease_owner: str,
        now: datetime.datetime,
        lease_until: datetime.datetime,
    ) -> ExternalChannelIngressLeaseClaim | None:
        """Claim one Discord Gateway lease."""
        async with self.session_manager() as session:
            claim = await self.external_channel_repository.claim_discord_gateway_lease(
                session,
                connection_id=connection_id,
                lease_owner=lease_owner,
                now=now,
                lease_until=lease_until,
            )
            await session.commit()
            return claim

    async def get_owned_gateway_configuration(
        self,
        *,
        connection_id: str,
        lease_owner: str,
        lease_generation: int,
        now: datetime.datetime,
    ) -> ExternalChannelConnectionConfiguration | None:
        """Return configuration under the current owning lease."""
        async with self.session_manager() as session:
            repository = self.external_channel_repository
            return await repository.get_owned_discord_gateway_configuration(
                session,
                connection_id=connection_id,
                lease_owner=lease_owner,
                lease_generation=lease_generation,
                now=now,
            )

    async def renew_gateway_lease(
        self,
        *,
        connection_id: str,
        lease_owner: str,
        lease_generation: int,
        now: datetime.datetime,
        lease_until: datetime.datetime,
    ) -> bool:
        """Renew one owning Discord Gateway lease."""
        async with self.session_manager() as session:
            repository = self.external_channel_repository
            renewed = await repository.renew_discord_gateway_lease(
                session,
                connection_id=connection_id,
                lease_owner=lease_owner,
                lease_generation=lease_generation,
                now=now,
                lease_until=lease_until,
            )
            await session.commit()
            return renewed

    async def list_owned_typing_targets(
        self,
        *,
        connection_id: str,
        lease_owner: str,
        lease_generation: int,
        now: datetime.datetime,
    ) -> tuple[DiscordGatewayTypingTarget, ...] | None:
        """Return typing targets under the current lease fence."""
        async with self.session_manager() as session:
            return await (
                self.external_channel_repository.list_owned_discord_typing_targets(
                    session,
                    connection_id=connection_id,
                    lease_owner=lease_owner,
                    lease_generation=lease_generation,
                    now=now,
                )
            )

    async def record_gateway_gap(
        self,
        *,
        connection_id: str,
        lease_owner: str,
        lease_generation: int,
        now: datetime.datetime,
        reason: str,
    ) -> bool:
        """Record one Gateway continuity gap under the lease fence."""
        async with self.session_manager() as session:
            repository = self.external_channel_repository
            recorded = await repository.record_discord_gateway_gap(
                session,
                connection_id=connection_id,
                lease_owner=lease_owner,
                lease_generation=lease_generation,
                now=now,
                reason=reason,
            )
            await session.commit()
            return recorded

    async def mark_gateway_active(
        self,
        *,
        connection_id: str,
        lease_owner: str,
        lease_generation: int,
        now: datetime.datetime,
    ) -> bool:
        """Mark one owned Discord Gateway active."""
        async with self.session_manager() as session:
            active = await self.external_channel_repository.mark_discord_gateway_active(
                session,
                connection_id=connection_id,
                lease_owner=lease_owner,
                lease_generation=lease_generation,
                now=now,
            )
            await session.commit()
            return active

    async def release_gateway_lease(
        self,
        *,
        connection_id: str,
        lease_owner: str,
        lease_generation: int,
        now: datetime.datetime,
    ) -> bool:
        """Release one owned Discord Gateway lease."""
        async with self.session_manager() as session:
            repository = self.external_channel_repository
            released = await repository.release_discord_gateway_lease(
                session,
                connection_id=connection_id,
                lease_owner=lease_owner,
                lease_generation=lease_generation,
                now=now,
            )
            await session.commit()
            return released

    async def mark_gateway_reconnect_required(
        self,
        *,
        connection_id: str,
        lease_owner: str,
        lease_generation: int,
        now: datetime.datetime,
        reason: str,
    ) -> bool:
        """Terminalize one owned Discord Gateway lease."""
        async with self.session_manager() as session:
            repository = self.external_channel_repository
            terminalized = await repository.mark_discord_gateway_reconnect_required(
                session,
                connection_id=connection_id,
                lease_owner=lease_owner,
                lease_generation=lease_generation,
                now=now,
                reason=reason,
            )
            await session.commit()
            return terminalized
