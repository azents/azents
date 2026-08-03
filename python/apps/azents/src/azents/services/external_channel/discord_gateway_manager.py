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
from azents.core.enums import ExternalChannelIngressProfile
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import (
    ExternalChannelConnectionConfiguration,
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
    DiscordGatewayCredentialError,
    DiscordGatewayError,
    DiscordGatewayIntentsError,
    DiscordGatewayLifecycleState,
    DiscordGatewayMessageEvent,
    DiscordGatewayRunner,
    DiscordGatewayTerminalError,
)
from azents.services.external_channel.ingestion import (
    ExternalChannelIngestionOutcome,
    ExternalChannelIngestionReason,
    ExternalChannelIngressAuthority,
    ExternalChannelIngressAuthorityKind,
)
from azents.services.external_channel.provider_control import (
    ExternalChannelProviderControlService,
    get_external_channel_provider_control_service,
)
from azents.services.external_channel.transport_ingestion import (
    ExternalChannelTransportIngestionService,
    external_channel_transport_deadline,
    transport_outcome_acknowledgeable,
)

logger = logging.getLogger(__name__)
_POLL_INTERVAL = datetime.timedelta(seconds=5)
_LEASE_DURATION = datetime.timedelta(seconds=45)
_RENEW_INTERVAL = datetime.timedelta(seconds=15)
_EVENT_RETRY_DELAY_SECONDS = 1.0


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
        Depends(ExternalChannelRepository.create),
    ]
    credentials_codec: Annotated[
        ExternalChannelCredentialsCodec,
        Depends(get_external_channel_credentials_codec),
    ]
    transport_ingestion_service: Annotated[
        ExternalChannelTransportIngestionService,
        Depends(ExternalChannelTransportIngestionService),
    ]
    provider_control: Annotated[
        ExternalChannelProviderControlService,
        Depends(get_external_channel_provider_control_service),
    ]
    control_tasks: set[asyncio.Task[object]] = dataclasses.field(
        default_factory=set,
        init=False,
        repr=False,
    )
    manager_id: str = dataclasses.field(default_factory=lambda: uuid4().hex)
    gateway_client: Annotated[
        DiscordGatewayRunner,
        Depends(get_discord_gateway_client),
    ] = dataclasses.field(default_factory=DiscordGatewayClient)
    poll_interval: datetime.timedelta = _POLL_INTERVAL
    lease_duration: datetime.timedelta = _LEASE_DURATION
    renew_interval: datetime.timedelta = _RENEW_INTERVAL
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
                        logger.exception("Discord Gateway task failed")
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
            await self._run_connection_with_lease(
                connection_id=connection_id,
                lease=lease,
                bot_token=credentials.bot_token,
                provider_app_id=configuration.provider_app_id,
                target_guild_id=configuration.provider_tenant_id,
                connected_bot_user_id=configuration.provider_bot_user_id,
                configuration_generation=configuration.configuration_generation,
                shutdown_event=shutdown_event,
            )
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
        except DiscordGatewayTerminalError as error:
            await self._mark_reconnect_required(
                connection_id=connection_id,
                lease=lease,
                reason=error.reason,
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
        connected_bot_user_id: str | None,
        configuration_generation: int,
        shutdown_event: asyncio.Event,
    ) -> None:
        connection_task = asyncio.create_task(
            self.gateway_client.run_connection(
                bot_token=bot_token,
                target_guild_id=target_guild_id,
                handle_event=lambda event: self._admit_gateway_event(
                    connection_id=connection_id,
                    lease=lease,
                    provider_app_id=provider_app_id,
                    target_guild_id=target_guild_id,
                    connected_bot_user_id=connected_bot_user_id,
                    configuration_generation=configuration_generation,
                    event=event,
                ),
                handle_lifecycle=lambda state: self._handle_gateway_lifecycle(
                    connection_id=connection_id,
                    lease=lease,
                    state=state,
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
                    connection_task.result()
                    raise DiscordGatewayError(
                        "Discord Gateway client stopped unexpectedly."
                    )
                if shutdown_task in done or not await self._renew(
                    connection_id=connection_id,
                    lease=lease,
                ):
                    connection_task.cancel()
                    await asyncio.gather(connection_task, return_exceptions=True)
                    return
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

    async def _mark_active(
        self,
        *,
        connection_id: str,
        lease: ExternalChannelIngressLease,
    ) -> bool:
        async with self.session_manager() as session:
            active = await self.repository.mark_discord_gateway_active(
                session,
                connection_id=connection_id,
                lease_owner=self.manager_id,
                lease_generation=lease.lease_generation,
                now=_utc_now(),
            )
            await session.commit()
            return active

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
        connected_bot_user_id: str | None,
        configuration_generation: int,
        event: DiscordGatewayMessageEvent,
    ) -> None:
        """Synchronously hand off one typed high-level discord.py create event."""
        if (
            self.config is not None
            and self.config.external_channel_conversation.quiesce.discord_gateway
            and event.event_type == "message_create"
        ):
            raise DiscordGatewayError(
                "Discord message ingress is temporarily quiesced."
            )
        if event.event_type != "message_create":
            return
        received_at = _utc_now()
        create = project_discord_gateway_event(
            connection_id=connection_id,
            provider_app_id=provider_app_id,
            target_guild_id=target_guild_id,
            connected_bot_user_id=connected_bot_user_id,
            event=event,
            received_at=received_at,
        )
        if create is None:
            return
        authority = ExternalChannelIngressAuthority(
            kind=ExternalChannelIngressAuthorityKind.LEASE,
            ingress_profile=ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP,
            configuration_generation=configuration_generation,
            lease_owner=self.manager_id,
            lease_generation=lease.lease_generation,
        )
        deadline = external_channel_transport_deadline(received_at)
        while True:
            outcome = await self.transport_ingestion_service.ingest_discord_event(
                event=create,
                authority=authority,
                deadline=deadline,
            )
            if outcome is None:
                return
            if transport_outcome_acknowledgeable(outcome):
                self._schedule_control_plans(outcome)
                return
            if outcome.reason is ExternalChannelIngestionReason.INGRESS_AUTHORITY_STALE:
                raise DiscordGatewayLeaseLost(
                    "Discord Gateway ingestion authority is stale."
                )
            remaining_seconds = deadline.remaining_seconds()
            if remaining_seconds <= 0:
                raise DiscordGatewayError(
                    "Discord message ingestion remained unavailable."
                )
            await asyncio.sleep(min(_EVENT_RETRY_DELAY_SECONDS, remaining_seconds))

    def _schedule_control_plans(
        self,
        outcome: ExternalChannelIngestionOutcome,
    ) -> None:
        """Run direct controls after canonical Gateway admission."""
        for plan in outcome.control_plans:
            task = asyncio.create_task(self.provider_control.attempt(plan))
            self.control_tasks.add(task)
            task.add_done_callback(self.control_tasks.discard)
            task.add_done_callback(_log_provider_control_task_failure)

    async def _handle_gateway_lifecycle(
        self,
        *,
        connection_id: str,
        lease: ExternalChannelIngressLease,
        state: DiscordGatewayLifecycleState,
    ) -> None:
        """Project typed SDK connection state through the current lease fence."""
        if state == "disconnected":
            changed = await self._record_gap(
                connection_id=connection_id,
                lease=lease,
                reason="gateway_disconnected",
            )
        else:
            changed = await self._mark_active(
                connection_id=connection_id,
                lease=lease,
            )
        if not changed:
            raise DiscordGatewayLeaseLost(
                "Discord Gateway lifecycle authority is stale."
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


def _log_provider_control_task_failure(
    task: asyncio.Task[object],
) -> None:
    """Observe one direct control task without exposing provider payloads."""
    try:
        task.result()
    except asyncio.CancelledError:
        return
    except Exception:
        logger.exception("Discord provider control task failed")
