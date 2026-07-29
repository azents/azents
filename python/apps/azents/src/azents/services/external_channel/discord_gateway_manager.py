"""Lease-fenced Discord Gateway service backed by discord.py."""

import asyncio
import dataclasses
import datetime
import logging
from typing import Annotated
from uuid import uuid4

from cryptography.fernet import InvalidToken
from fastapi import Depends
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.deps import get_config
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import (
    ExternalChannelConnectionConfiguration,
    ExternalChannelEventCreate,
    ExternalChannelIngressLease,
    ExternalChannelIngressLeaseClaim,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.connection import (
    get_external_channel_credentials_codec,
)
from azents.services.external_channel.credentials import ExternalChannelCredentialsCodec
from azents.services.external_channel.data import DiscordConnectionCredentials
from azents.services.external_channel.discord_events import (
    project_discord_gateway_event,
)
from azents.services.external_channel.discord_gateway import (
    DiscordGatewayClient,
    DiscordGatewayConnectionResult,
    DiscordGatewayCredentialError,
    DiscordGatewayError,
    DiscordGatewayIntentsError,
    DiscordGatewayMessageEvent,
    DiscordGatewayRunner,
)

logger = logging.getLogger(__name__)
_POLL_INTERVAL = datetime.timedelta(seconds=5)
_LEASE_DURATION = datetime.timedelta(seconds=45)
_RENEW_INTERVAL = datetime.timedelta(seconds=15)
_RECONNECT_DELAY = datetime.timedelta(seconds=5)
_RATE_LIMIT_RECONNECT_DELAY = datetime.timedelta(minutes=1)
_MAX_RECONNECT_DELAY = datetime.timedelta(minutes=5)


class DiscordGatewayLeaseLost(DiscordGatewayError):
    """The current process no longer owns the authoritative Gateway lease."""


def get_discord_gateway_client() -> DiscordGatewayRunner:
    """Provide the discord.py-backed Gateway runner."""
    return DiscordGatewayClient()


@dataclasses.dataclass
class DiscordGatewayManagerService:
    """Own one discord.py client per current fenced Discord connection."""

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    repository: Annotated[
        ExternalChannelRepository,
        Depends(ExternalChannelRepository),
    ]
    credentials_codec: Annotated[
        ExternalChannelCredentialsCodec,
        Depends(get_external_channel_credentials_codec),
    ]
    manager_id: str = dataclasses.field(default_factory=lambda: uuid4().hex)
    gateway_client: Annotated[
        DiscordGatewayRunner,
        Depends(get_discord_gateway_client),
    ] = dataclasses.field(default_factory=DiscordGatewayClient)
    poll_interval: datetime.timedelta = _POLL_INTERVAL
    lease_duration: datetime.timedelta = _LEASE_DURATION
    renew_interval: datetime.timedelta = _RENEW_INTERVAL
    reconnect_delay: datetime.timedelta = _RECONNECT_DELAY
    config: Annotated[Config | None, Depends(get_config)] = None

    async def run(self, shutdown_event: asyncio.Event) -> None:
        """Continuously claim configured Discord connections until shutdown."""
        tasks: dict[str, asyncio.Task[None]] = {}
        try:
            while not shutdown_event.is_set():
                for connection_id, task in tuple(tasks.items()):
                    if not task.done():
                        continue
                    del tasks[connection_id]
                    try:
                        task.result()
                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        logger.exception(
                            "Discord Gateway task failed",
                            extra={"connection_id": connection_id},
                        )
                for connection_id in await self._list_connection_ids():
                    if connection_id not in tasks:
                        tasks[connection_id] = asyncio.create_task(
                            self._run_owned_connection(
                                connection_id=connection_id,
                                shutdown_event=shutdown_event,
                            )
                        )
                try:
                    await asyncio.wait_for(
                        shutdown_event.wait(),
                        timeout=self.poll_interval.total_seconds(),
                    )
                except TimeoutError:
                    continue
        finally:
            for task in tasks.values():
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks.values(), return_exceptions=True)

    async def _list_connection_ids(self) -> list[str]:
        async with self.session_manager() as session:
            return await self.repository.list_discord_gateway_connection_ids(session)

    async def _run_owned_connection(
        self,
        *,
        connection_id: str,
        shutdown_event: asyncio.Event,
    ) -> None:
        claim = await self._claim(connection_id)
        if claim is None:
            return
        lease = claim.lease
        lease_released = False
        reconnect_attempts = 0
        try:
            configuration = await self._owned_configuration(
                connection_id=connection_id,
                lease=lease,
            )
            if configuration is None:
                return
            credentials = self._credentials(configuration.encrypted_credentials)
            if configuration.provider_tenant_id is None:
                raise DiscordGatewayCredentialError(
                    "Discord Guild identity is unavailable."
                )
            while not shutdown_event.is_set():
                result = await self._run_connection_with_lease(
                    connection_id=connection_id,
                    lease=lease,
                    bot_token=credentials.bot_token,
                    provider_app_id=configuration.provider_app_id,
                    target_guild_id=configuration.provider_tenant_id,
                    shutdown_event=shutdown_event,
                )
                if result is None:
                    return
                if not result.reconnect:
                    await self._mark_reconnect_required(
                        connection_id=connection_id,
                        lease=lease,
                        reason=result.reason,
                    )
                    lease_released = True
                    return
                reconnect_attempts += 1
                if not await self._record_gap(
                    connection_id=connection_id,
                    lease=lease,
                    reason=result.reason,
                ):
                    return
                if not await self._sleep_or_shutdown(
                    shutdown_event,
                    connection_id=connection_id,
                    lease=lease,
                    delay=self._reconnect_delay(
                        reason=result.reason,
                        attempt=reconnect_attempts,
                    ),
                ):
                    return
        except asyncio.CancelledError:
            await asyncio.shield(
                self._release(connection_id=connection_id, lease=lease)
            )
            lease_released = True
            raise
        except DiscordGatewayLeaseLost:
            lease_released = True
        except DiscordGatewayCredentialError:
            await self._mark_reconnect_required(
                connection_id=connection_id,
                lease=lease,
                reason="gateway_credentials_invalid",
            )
            lease_released = True
        except DiscordGatewayIntentsError:
            await self._mark_reconnect_required(
                connection_id=connection_id,
                lease=lease,
                reason="intents_disallowed",
            )
            lease_released = True
        except DiscordGatewayError:
            await self._record_gap(
                connection_id=connection_id,
                lease=lease,
                reason="gateway_transport_unavailable",
            )
        finally:
            if not lease_released:
                await self._release(connection_id=connection_id, lease=lease)

    async def _run_connection_with_lease(
        self,
        *,
        connection_id: str,
        lease: ExternalChannelIngressLease,
        bot_token: str,
        provider_app_id: str | None,
        target_guild_id: str,
        shutdown_event: asyncio.Event,
    ) -> DiscordGatewayConnectionResult | None:
        connection_task = asyncio.create_task(
            self.gateway_client.run_connection(
                bot_token=bot_token,
                target_guild_id=target_guild_id,
                handle_event=lambda event: self._admit_gateway_event(
                    connection_id=connection_id,
                    lease=lease,
                    provider_app_id=provider_app_id,
                    target_guild_id=target_guild_id,
                    event=event,
                ),
            )
        )
        shutdown_task = asyncio.create_task(shutdown_event.wait())
        try:
            while True:
                done, _ = await asyncio.wait(
                    (connection_task, shutdown_task),
                    timeout=self.renew_interval.total_seconds(),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if connection_task in done:
                    return connection_task.result()
                if shutdown_task in done or not await self._renew(
                    connection_id=connection_id,
                    lease=lease,
                ):
                    connection_task.cancel()
                    await asyncio.gather(connection_task, return_exceptions=True)
                    return None
        finally:
            shutdown_task.cancel()
            await asyncio.gather(shutdown_task, return_exceptions=True)

    async def _claim(
        self,
        connection_id: str,
    ) -> ExternalChannelIngressLeaseClaim | None:
        now = _utc_now()
        async with self.session_manager() as session:
            claim = await self.repository.claim_discord_gateway_lease(
                session,
                connection_id=connection_id,
                lease_owner=self.manager_id,
                now=now,
                lease_until=now + self.lease_duration,
            )
            await session.commit()
            return claim

    async def _owned_configuration(
        self,
        *,
        connection_id: str,
        lease: ExternalChannelIngressLease,
    ) -> ExternalChannelConnectionConfiguration | None:
        async with self.session_manager() as session:
            return await self.repository.get_owned_discord_gateway_configuration(
                session,
                connection_id=connection_id,
                lease_owner=self.manager_id,
                lease_generation=lease.lease_generation,
                now=_utc_now(),
            )

    async def _renew(
        self,
        *,
        connection_id: str,
        lease: ExternalChannelIngressLease,
    ) -> bool:
        now = _utc_now()
        async with self.session_manager() as session:
            renewed = await self.repository.renew_discord_gateway_lease(
                session,
                connection_id=connection_id,
                lease_owner=self.manager_id,
                lease_generation=lease.lease_generation,
                now=now,
                lease_until=now + self.lease_duration,
            )
            await session.commit()
            return renewed

    async def _record_gap(
        self,
        *,
        connection_id: str,
        lease: ExternalChannelIngressLease,
        reason: str,
    ) -> bool:
        async with self.session_manager() as session:
            recorded = await self.repository.record_discord_gateway_gap(
                session,
                connection_id=connection_id,
                lease_owner=self.manager_id,
                lease_generation=lease.lease_generation,
                now=_utc_now(),
                reason=reason,
            )
            await session.commit()
            return recorded

    async def _release(
        self,
        *,
        connection_id: str,
        lease: ExternalChannelIngressLease,
    ) -> bool:
        async with self.session_manager() as session:
            released = await self.repository.release_discord_gateway_lease(
                session,
                connection_id=connection_id,
                lease_owner=self.manager_id,
                lease_generation=lease.lease_generation,
                now=_utc_now(),
            )
            await session.commit()
            return released

    async def _mark_reconnect_required(
        self,
        *,
        connection_id: str,
        lease: ExternalChannelIngressLease,
        reason: str,
    ) -> bool:
        async with self.session_manager() as session:
            terminalized = (
                await self.repository.mark_discord_gateway_reconnect_required(
                    session,
                    connection_id=connection_id,
                    lease_owner=self.manager_id,
                    lease_generation=lease.lease_generation,
                    now=_utc_now(),
                    reason=reason,
                )
            )
            await session.commit()
            return terminalized

    async def _admit_gateway_event(
        self,
        *,
        connection_id: str,
        lease: ExternalChannelIngressLease,
        provider_app_id: str | None,
        target_guild_id: str,
        event: DiscordGatewayMessageEvent,
    ) -> None:
        """Durably admit one typed high-level discord.py message event."""
        if (
            self.config is not None
            and self.config.external_channel_conversation.quiesce.discord_gateway
            and event.event_type == "message_create"
        ):
            raise DiscordGatewayError(
                "Discord message ingress is temporarily quiesced."
            )
        create = project_discord_gateway_event(
            connection_id=connection_id,
            provider_app_id=provider_app_id,
            target_guild_id=target_guild_id,
            event=event,
            received_at=_utc_now(),
        )
        if create is None:
            return
        admitted = await self._commit_event(
            connection_id=connection_id,
            lease=lease,
            create=create,
        )
        if not admitted:
            raise DiscordGatewayLeaseLost

    async def _commit_event(
        self,
        *,
        connection_id: str,
        lease: ExternalChannelIngressLease,
        create: ExternalChannelEventCreate,
    ) -> bool:
        """Commit canonical admission under the current lease fence."""
        async with self.session_manager() as session:
            admission = await self.repository.admit_discord_gateway_event(
                session,
                connection_id=connection_id,
                lease_owner=self.manager_id,
                lease_generation=lease.lease_generation,
                now=_utc_now(),
                create=create,
            )
            if admission is None:
                return False
            await session.commit()
            return True

    async def _sleep_or_shutdown(
        self,
        shutdown_event: asyncio.Event,
        *,
        connection_id: str,
        lease: ExternalChannelIngressLease,
        delay: datetime.timedelta,
    ) -> bool:
        """Wait with periodic lease renewal during reconnect backoff."""
        deadline = asyncio.get_running_loop().time() + delay.total_seconds()
        while not shutdown_event.is_set():
            remaining_seconds = deadline - asyncio.get_running_loop().time()
            if remaining_seconds <= 0:
                return True
            try:
                await asyncio.wait_for(
                    shutdown_event.wait(),
                    timeout=min(
                        remaining_seconds,
                        self.renew_interval.total_seconds(),
                    ),
                )
            except TimeoutError:
                if asyncio.get_running_loop().time() >= deadline:
                    return True
                if not await self._renew(
                    connection_id=connection_id,
                    lease=lease,
                ):
                    return False
        return False

    def _reconnect_delay(
        self,
        *,
        reason: str,
        attempt: int,
    ) -> datetime.timedelta:
        """Return bounded exponential backoff for one reconnect outcome."""
        base_delay = self.reconnect_delay
        if reason == "gateway_rate_limited":
            base_delay = max(base_delay, _RATE_LIMIT_RECONNECT_DELAY)
        return min(
            base_delay * 2 ** (attempt - 1),
            _MAX_RECONNECT_DELAY,
        )

    def _credentials(self, ciphertext: str | None) -> DiscordConnectionCredentials:
        if ciphertext is None:
            raise DiscordGatewayCredentialError("Discord credentials are unavailable.")
        try:
            credentials = self.credentials_codec.decrypt(ciphertext)
        except (InvalidToken, ValidationError) as error:
            raise DiscordGatewayCredentialError(
                "Discord credentials are invalid."
            ) from error
        if not isinstance(credentials, DiscordConnectionCredentials):
            raise DiscordGatewayCredentialError("Discord credentials are invalid.")
        return credentials


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)
