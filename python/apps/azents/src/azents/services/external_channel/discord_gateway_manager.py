"""Dedicated lease-fenced Discord Gateway worker service."""

import asyncio
import dataclasses
import datetime
import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import uuid4

import httpx
from cryptography.fernet import InvalidToken
from fastapi import Depends
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.crypto import CredentialCipher
from azents.core.deps import get_config, get_credential_cipher
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
from azents.services.external_channel.discord_endpoint import (
    discord_api_base_url,
    discord_gateway_url_allowed,
)
from azents.services.external_channel.discord_events import (
    project_discord_gateway_dispatch,
)
from azents.services.external_channel.discord_gateway import (
    DiscordGatewayCheckpoint,
    DiscordGatewayClient,
    DiscordGatewayConnectionResult,
    DiscordGatewayDispatch,
    DiscordGatewayError,
)

logger = logging.getLogger(__name__)
_POLL_INTERVAL = datetime.timedelta(seconds=5)
_LEASE_DURATION = datetime.timedelta(seconds=45)
_RENEW_INTERVAL = datetime.timedelta(seconds=15)
_RECONNECT_DELAY = datetime.timedelta(seconds=1)
_CHECKPOINT_VERSION = 1


class DiscordGatewayCredentialError(RuntimeError):
    """Persisted Discord credentials cannot establish a Gateway session."""


class DiscordGatewayLeaseLost(RuntimeError):
    """The current process no longer owns the authoritative Gateway lease."""


async def get_discord_gateway_http_client() -> AsyncIterator[httpx.AsyncClient]:
    """Provide the HTTP client used only for Discord Gateway endpoint discovery."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        yield client


@dataclasses.dataclass
class DiscordGatewayManagerService:
    """Own Discord Gateway sessions separately from the Agent Worker role."""

    config: Annotated[Config, Depends(get_config)]
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
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)]
    http_client: Annotated[
        httpx.AsyncClient,
        Depends(get_discord_gateway_http_client),
    ]
    manager_id: str = dataclasses.field(default_factory=lambda: uuid4().hex)
    gateway_client: DiscordGatewayClient = dataclasses.field(
        default_factory=DiscordGatewayClient
    )
    poll_interval: datetime.timedelta = _POLL_INTERVAL
    lease_duration: datetime.timedelta = _LEASE_DURATION
    renew_interval: datetime.timedelta = _RENEW_INTERVAL
    reconnect_delay: datetime.timedelta = _RECONNECT_DELAY

    async def run(self, shutdown_event: asyncio.Event) -> None:
        """Continuously claim configured Discord Gateway connections until shutdown."""
        if not self.config.external_channel_discord_enabled:
            await shutdown_event.wait()
            return
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
        try:
            configuration = await self._owned_configuration(
                connection_id=connection_id,
                lease=lease,
            )
            if configuration is None:
                return
            credentials = self._credentials(configuration.encrypted_credentials)
            if configuration.provider_tenant_id is None:
                raise DiscordGatewayCredentialError
            checkpoint = _decode_checkpoint(
                cipher=self.cipher,
                ciphertext=lease.encrypted_checkpoint,
                version=lease.checkpoint_version,
            )
            while not shutdown_event.is_set():
                endpoint_url = (
                    checkpoint.resume_gateway_url
                    if checkpoint is not None
                    else await self._discover_gateway_url(credentials.bot_token)
                )
                result = await self._run_connection_with_lease(
                    connection_id=connection_id,
                    lease=lease,
                    endpoint_url=endpoint_url,
                    bot_token=credentials.bot_token,
                    provider_app_id=configuration.provider_app_id,
                    target_guild_id=configuration.provider_tenant_id,
                    checkpoint=checkpoint,
                    shutdown_event=shutdown_event,
                )
                if result is None:
                    return
                checkpoint = result.checkpoint if result.can_resume else None
                if not await self._record_gap(
                    connection_id=connection_id,
                    lease=lease,
                    reason=result.reason,
                ):
                    return
                if not result.reconnect:
                    return
                await self._sleep_or_shutdown(shutdown_event)
        except asyncio.CancelledError:
            await asyncio.shield(
                self._release(connection_id=connection_id, lease=lease)
            )
            raise
        except (
            DiscordGatewayCredentialError,
            DiscordGatewayError,
            httpx.RequestError,
            OSError,
            InvalidToken,
            ValidationError,
        ):
            await self._record_gap(
                connection_id=connection_id,
                lease=lease,
                reason="gateway_transport_unavailable",
            )
        finally:
            await self._release(connection_id=connection_id, lease=lease)

    async def _run_connection_with_lease(
        self,
        *,
        connection_id: str,
        lease: ExternalChannelIngressLease,
        endpoint_url: str,
        bot_token: str,
        provider_app_id: str | None,
        target_guild_id: str,
        checkpoint: DiscordGatewayCheckpoint | None,
        shutdown_event: asyncio.Event,
    ) -> DiscordGatewayConnectionResult | None:
        async def persist_checkpoint(value: DiscordGatewayCheckpoint) -> None:
            persisted = await self._persist_checkpoint(
                connection_id=connection_id,
                lease=lease,
                checkpoint=value,
            )
            if not persisted:
                raise DiscordGatewayLeaseLost

        connection_task = asyncio.create_task(
            self.gateway_client.run_connection(
                endpoint_url=endpoint_url,
                bot_token=bot_token,
                checkpoint=checkpoint,
                persist_checkpoint=persist_checkpoint,
                handle_dispatch=lambda dispatch: self._admit_dispatch(
                    connection_id=connection_id,
                    lease=lease,
                    provider_app_id=provider_app_id,
                    target_guild_id=target_guild_id,
                    dispatch=dispatch,
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

    async def _persist_checkpoint(
        self,
        *,
        connection_id: str,
        lease: ExternalChannelIngressLease,
        checkpoint: DiscordGatewayCheckpoint,
    ) -> bool:
        now = _utc_now()
        encrypted_checkpoint = self.cipher.encrypt(
            json.dumps(dataclasses.asdict(checkpoint), separators=(",", ":"))
        )
        async with self.session_manager() as session:
            persisted = await self.repository.update_discord_gateway_checkpoint(
                session,
                connection_id=connection_id,
                lease_owner=self.manager_id,
                lease_generation=lease.lease_generation,
                now=now,
                encrypted_checkpoint=encrypted_checkpoint,
                checkpoint_version=_CHECKPOINT_VERSION,
                sequence=checkpoint.sequence,
            )
            await session.commit()
            return persisted

    async def _admit_dispatch(
        self,
        *,
        connection_id: str,
        lease: ExternalChannelIngressLease,
        provider_app_id: str | None,
        target_guild_id: str,
        dispatch: DiscordGatewayDispatch,
    ) -> bool:
        """Durably admit one supported message dispatch under the lease fence."""
        create = project_discord_gateway_dispatch(
            connection_id=connection_id,
            provider_app_id=provider_app_id,
            target_guild_id=target_guild_id,
            dispatch=dispatch,
            received_at=_utc_now(),
        )
        if create is None:
            return False
        admitted = await self._admit_event(
            connection_id=connection_id,
            lease=lease,
            create=create,
            dispatch=dispatch,
        )
        if not admitted:
            raise DiscordGatewayLeaseLost
        return True

    async def _admit_event(
        self,
        *,
        connection_id: str,
        lease: ExternalChannelIngressLease,
        create: ExternalChannelEventCreate,
        dispatch: DiscordGatewayDispatch,
    ) -> bool:
        """Commit canonical admission only while current authority remains fenced."""
        encrypted_checkpoint = self.cipher.encrypt(
            json.dumps(
                {
                    "session_id": dispatch.session_id,
                    "resume_gateway_url": dispatch.resume_gateway_url,
                    "sequence": dispatch.sequence,
                },
                separators=(",", ":"),
            )
        )
        async with self.session_manager() as session:
            admission = await self.repository.admit_discord_gateway_event(
                session,
                connection_id=connection_id,
                lease_owner=self.manager_id,
                lease_generation=lease.lease_generation,
                now=_utc_now(),
                create=create,
                encrypted_checkpoint=encrypted_checkpoint,
                checkpoint_version=_CHECKPOINT_VERSION,
                sequence=dispatch.sequence,
            )
            if admission is None:
                return False
            await session.commit()
            return True

    async def _discover_gateway_url(self, bot_token: str) -> str:
        response = await self.http_client.get(
            f"{discord_api_base_url()}/gateway/bot",
            headers={"Authorization": f"Bot {bot_token}"},
        )
        if response.status_code in {401, 403}:
            raise DiscordGatewayCredentialError
        if response.status_code == 429 or response.status_code >= 500:
            raise DiscordGatewayError("Discord Gateway discovery is unavailable.")
        try:
            payload: object = response.json()
        except ValueError as error:
            raise DiscordGatewayError(
                "Discord Gateway discovery returned invalid JSON."
            ) from error
        if not isinstance(payload, dict):
            raise DiscordGatewayError("Discord Gateway discovery returned an object.")
        endpoint_url = payload.get("url")
        if not isinstance(endpoint_url, str):
            raise DiscordGatewayError(
                "Discord Gateway discovery returned an invalid endpoint."
            )
        if not discord_gateway_url_allowed(endpoint_url):
            raise DiscordGatewayError(
                "Discord Gateway discovery returned an invalid endpoint."
            )
        return endpoint_url

    def _credentials(self, ciphertext: str | None) -> DiscordConnectionCredentials:
        if ciphertext is None:
            raise DiscordGatewayCredentialError
        credentials = self.credentials_codec.decrypt(ciphertext)
        if not isinstance(credentials, DiscordConnectionCredentials):
            raise DiscordGatewayCredentialError
        return credentials

    async def _sleep_or_shutdown(self, shutdown_event: asyncio.Event) -> None:
        try:
            await asyncio.wait_for(
                shutdown_event.wait(),
                timeout=self.reconnect_delay.total_seconds(),
            )
        except TimeoutError:
            return


def _decode_checkpoint(
    *,
    cipher: CredentialCipher,
    ciphertext: str | None,
    version: int | None,
) -> DiscordGatewayCheckpoint | None:
    """Decrypt and validate one persisted resumable Gateway checkpoint."""
    if ciphertext is None:
        return None
    if version != _CHECKPOINT_VERSION:
        raise DiscordGatewayError("Discord Gateway checkpoint version is unsupported.")
    try:
        value: object = json.loads(cipher.decrypt(ciphertext))
    except (ValueError, InvalidToken) as error:
        raise DiscordGatewayError("Discord Gateway checkpoint is invalid.") from error
    if not isinstance(value, dict):
        raise DiscordGatewayError("Discord Gateway checkpoint must be an object.")
    session_id = value.get("session_id")
    resume_gateway_url = value.get("resume_gateway_url")
    sequence = value.get("sequence")
    if (
        not isinstance(session_id, str)
        or not session_id
        or not isinstance(resume_gateway_url, str)
        or not discord_gateway_url_allowed(resume_gateway_url)
        or not isinstance(sequence, int)
        or isinstance(sequence, bool)
        or sequence < 0
    ):
        raise DiscordGatewayError("Discord Gateway checkpoint has invalid fields.")
    return DiscordGatewayCheckpoint(
        session_id=session_id,
        resume_gateway_url=resume_gateway_url,
        sequence=sequence,
    )


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)
