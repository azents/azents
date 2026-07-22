"""Durable lease owner for Slack Socket Mode connections."""

import asyncio
import dataclasses
import datetime
import logging
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import uuid4

import httpx
from cryptography.fernet import InvalidToken
from fastapi import Depends
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import ExternalChannelConnectionStatus
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import (
    ExternalChannelConnectionConfiguration,
    ExternalChannelEventCreate,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.admission import ExternalChannelAdmissionService
from azents.services.external_channel.connection import (
    get_external_channel_credentials_codec,
)
from azents.services.external_channel.credentials import ExternalChannelCredentialsCodec
from azents.services.external_channel.data import SlackConnectionCredentials
from azents.services.external_channel.slack_socket import (
    SlackSocketConnectionResult,
    SlackSocketError,
    SlackSocketInvalidEnvelope,
    SlackSocketModeClient,
    SlackSocketReconnectRequired,
    SlackSocketWebAPIClient,
)

_DEFAULT_POLL_INTERVAL = datetime.timedelta(seconds=5)
_DEFAULT_LEASE_DURATION = datetime.timedelta(seconds=45)
_DEFAULT_RENEW_INTERVAL = datetime.timedelta(seconds=15)
_DEFAULT_RECONNECT_DELAY = datetime.timedelta(seconds=1)
logger = logging.getLogger(__name__)


class SlackSocketCredentialError(RuntimeError):
    """Persisted Socket Mode credentials cannot establish a connection."""


async def get_slack_socket_http_client() -> AsyncIterator[httpx.AsyncClient]:
    """Provide the shared HTTP client used to open Socket Mode endpoints."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        yield client


@dataclasses.dataclass
class SlackSocketManagerService:
    """Own multiple Slack sockets in Agent Worker processes with DB fencing."""

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
    admission_service: Annotated[
        ExternalChannelAdmissionService,
        Depends(ExternalChannelAdmissionService),
    ]
    http_client: Annotated[
        httpx.AsyncClient,
        Depends(get_slack_socket_http_client),
    ]
    manager_id: str = dataclasses.field(default_factory=lambda: uuid4().hex)
    poll_interval: datetime.timedelta = _DEFAULT_POLL_INTERVAL
    lease_duration: datetime.timedelta = _DEFAULT_LEASE_DURATION
    renew_interval: datetime.timedelta = _DEFAULT_RENEW_INTERVAL
    reconnect_delay: datetime.timedelta = _DEFAULT_RECONNECT_DELAY

    async def run(self, shutdown_event: asyncio.Event) -> None:
        """Continuously own all claimable Socket Mode connections until shutdown."""
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
                            "Slack Socket connection manager task failed",
                            extra={"connection_id": connection_id},
                        )
                for connection_id in await self._list_connection_ids():
                    if connection_id in tasks:
                        continue
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
                except asyncio.TimeoutError:
                    continue
        finally:
            for task in tasks.values():
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks.values(), return_exceptions=True)

    async def _list_connection_ids(self) -> list[str]:
        async with self.session_manager() as session:
            return await self.repository.list_socket_connection_ids(session)

    async def _run_owned_connection(
        self,
        *,
        connection_id: str,
        shutdown_event: asyncio.Event,
    ) -> None:
        configuration = await self._claim(connection_id)
        if configuration is None:
            return
        try:
            try:
                credentials = self.credentials_codec.decrypt(
                    _required_ciphertext(configuration)
                )
            except (RuntimeError, InvalidToken, ValidationError) as error:
                raise SlackSocketCredentialError from error
            if not isinstance(credentials, SlackConnectionCredentials):
                raise SlackSocketCredentialError
            if credentials.app_token is None:
                raise SlackSocketCredentialError
            web_api_client = SlackSocketWebAPIClient(self.http_client)

            async def admit_owned(event: ExternalChannelEventCreate) -> object:
                if (
                    event.provider_app_id != configuration.provider_app_id
                    or event.provider_tenant_id != configuration.provider_tenant_id
                    or not await self._owned_active(connection_id)
                ):
                    raise SlackSocketInvalidEnvelope(
                        "Slack Socket connection is no longer authorized."
                    )
                return await self.admission_service.admit(event)

            client = SlackSocketModeClient(
                web_api_client=web_api_client,
                admit_event=admit_owned,
                reconnect_delay_seconds=self.reconnect_delay.total_seconds(),
            )
            while not shutdown_event.is_set():
                opened = await web_api_client.open_connection(
                    app_token=credentials.app_token
                )
                if not await self._mark_active(connection_id):
                    return
                result = await self._run_connection_with_lease(
                    client=client,
                    connection_id=connection_id,
                    endpoint_url=opened.url,
                    shutdown_event=shutdown_event,
                )
                if result is None:
                    await self._release(
                        connection_id,
                        reason="socket_manager_shutdown",
                        status=ExternalChannelConnectionStatus.DEGRADED,
                    )
                    return
                if not result.reconnect:
                    await self._release(
                        connection_id,
                        reason=result.reason,
                        status=ExternalChannelConnectionStatus.RECONNECT_REQUIRED,
                    )
                    return
                if not await self._record_gap(connection_id, result.reason):
                    return
                await self._sleep_or_shutdown(shutdown_event)
            await self._release(
                connection_id,
                reason="socket_manager_shutdown",
                status=ExternalChannelConnectionStatus.DEGRADED,
            )
        except asyncio.CancelledError:
            await asyncio.shield(
                self._release(
                    connection_id,
                    reason="socket_manager_shutdown",
                    status=ExternalChannelConnectionStatus.DEGRADED,
                )
            )
            raise
        except SlackSocketReconnectRequired:
            await self._release(
                connection_id,
                reason="socket_credentials_rejected",
                status=ExternalChannelConnectionStatus.RECONNECT_REQUIRED,
            )
        except SlackSocketCredentialError:
            await self._release(
                connection_id,
                reason="socket_credentials_invalid",
                status=ExternalChannelConnectionStatus.RECONNECT_REQUIRED,
            )
        except SlackSocketError, httpx.RequestError, OSError:
            await self._release(
                connection_id,
                reason="socket_transport_unavailable",
                status=ExternalChannelConnectionStatus.DEGRADED,
            )

    async def _owned_active(self, connection_id: str) -> bool:
        async with self.session_manager() as session:
            connection = await self.repository.socket_connection_owned_active(
                session,
                connection_id=connection_id,
                lease_owner=self.manager_id,
                now=_utc_now(),
            )
            return connection is not None

    async def _run_connection_with_lease(
        self,
        *,
        client: SlackSocketModeClient,
        connection_id: str,
        endpoint_url: str,
        shutdown_event: asyncio.Event,
    ) -> SlackSocketConnectionResult | None:
        connection_task = asyncio.create_task(
            client.run_connection(
                connection_id=connection_id,
                endpoint_url=endpoint_url,
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
                if shutdown_task in done:
                    connection_task.cancel()
                    await asyncio.gather(connection_task, return_exceptions=True)
                    return None
                if not await self._renew(connection_id):
                    connection_task.cancel()
                    await asyncio.gather(connection_task, return_exceptions=True)
                    return None
        finally:
            shutdown_task.cancel()
            await asyncio.gather(shutdown_task, return_exceptions=True)

    async def _claim(
        self,
        connection_id: str,
    ) -> ExternalChannelConnectionConfiguration | None:
        now = _utc_now()
        async with self.session_manager() as session:
            configuration = await self.repository.claim_socket_connection(
                session,
                connection_id=connection_id,
                lease_owner=self.manager_id,
                now=now,
                lease_until=now + self.lease_duration,
            )
            await session.commit()
            return configuration

    async def _renew(self, connection_id: str) -> bool:
        now = _utc_now()
        async with self.session_manager() as session:
            renewed = await self.repository.renew_socket_connection_lease(
                session,
                connection_id=connection_id,
                lease_owner=self.manager_id,
                now=now,
                lease_until=now + self.lease_duration,
            )
            await session.commit()
            return renewed

    async def _mark_active(self, connection_id: str) -> bool:
        async with self.session_manager() as session:
            active = await self.repository.mark_socket_connection_active(
                session,
                connection_id=connection_id,
                lease_owner=self.manager_id,
                now=_utc_now(),
            )
            await session.commit()
            return active

    async def _record_gap(self, connection_id: str, reason: str) -> bool:
        async with self.session_manager() as session:
            recorded = await self.repository.record_socket_connection_gap(
                session,
                connection_id=connection_id,
                lease_owner=self.manager_id,
                now=_utc_now(),
                gap_reason=reason,
            )
            await session.commit()
            return recorded

    async def _release(
        self,
        connection_id: str,
        *,
        reason: str,
        status: ExternalChannelConnectionStatus,
    ) -> bool:
        async with self.session_manager() as session:
            now = _utc_now()
            if status is ExternalChannelConnectionStatus.RECONNECT_REQUIRED:
                released = (
                    await self.repository.terminate_connection_for_provider_event(
                        session,
                        connection_id=connection_id,
                        status=status,
                        reason=reason,
                        now=now,
                        required_socket_lease_owner=self.manager_id,
                    )
                )
            else:
                released = await self.repository.release_socket_connection_lease(
                    session,
                    connection_id=connection_id,
                    lease_owner=self.manager_id,
                    now=now,
                    gap_reason=reason,
                    gap_status=status,
                )
            await session.commit()
            return released

    async def _sleep_or_shutdown(self, shutdown_event: asyncio.Event) -> None:
        try:
            await asyncio.wait_for(
                shutdown_event.wait(),
                timeout=self.reconnect_delay.total_seconds(),
            )
        except asyncio.TimeoutError:
            return


def _required_ciphertext(
    configuration: ExternalChannelConnectionConfiguration,
) -> str:
    if configuration.encrypted_credentials is None:
        raise RuntimeError("Socket Mode credentials are not configured.")
    return configuration.encrypted_credentials


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)
