"""Durable lease owner for Slack Socket Mode connections."""

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
from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelConnectionStatus,
    ExternalChannelIngressProfile,
    ExternalChannelInteractionStatus,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import (
    ExternalChannelConnectionConfiguration,
    ExternalChannelTrigger,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.admission import ExternalChannelAdmissionService
from azents.services.external_channel.connection import (
    get_external_channel_credentials_codec,
)
from azents.services.external_channel.connection_revocation import (
    ExternalChannelConnectionRevocationService,
)
from azents.services.external_channel.credentials import ExternalChannelCredentialsCodec
from azents.services.external_channel.data import SlackConnectionCredentials
from azents.services.external_channel.ingestion import (
    ExternalChannelIngressAuthority,
    ExternalChannelIngressAuthorityKind,
)
from azents.services.external_channel.interaction import (
    ExternalChannelInteractionHandoff,
    ExternalChannelInteractionProcessor,
)
from azents.services.external_channel.shortcut_source import (
    ExternalChannelShortcutSourceService,
)
from azents.services.external_channel.slack_events import SlackConnectionRevocation
from azents.services.external_channel.slack_http import (
    SlackInteractionCallback,
    slack_event_is_normal_message_ingress,
)
from azents.services.external_channel.slack_sdk_client import create_slack_web_client
from azents.services.external_channel.slack_socket import (
    SlackSocketConnectionResult,
    SlackSocketError,
    SlackSocketInvalidEnvelope,
    SlackSocketModeRunner,
    SlackSocketRetryableIngestion,
)
from azents.services.external_channel.transport_ingestion import (
    ExternalChannelTransportIngestionService,
    external_channel_transport_deadline,
    transport_outcome_acknowledgeable,
)

_DEFAULT_POLL_INTERVAL = datetime.timedelta(seconds=5)
_DEFAULT_LEASE_DURATION = datetime.timedelta(seconds=45)
_DEFAULT_RENEW_INTERVAL = datetime.timedelta(seconds=15)
logger = logging.getLogger(__name__)


class SlackSocketCredentialError(RuntimeError):
    """Persisted Socket Mode credentials cannot establish a connection."""


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
    interaction_processor: Annotated[
        ExternalChannelInteractionProcessor,
        Depends(ExternalChannelInteractionProcessor),
    ]
    shortcut_source_service: Annotated[
        ExternalChannelShortcutSourceService,
        Depends(ExternalChannelShortcutSourceService),
    ]
    transport_ingestion_service: Annotated[
        ExternalChannelTransportIngestionService,
        Depends(ExternalChannelTransportIngestionService),
    ]
    revocation_service: Annotated[
        ExternalChannelConnectionRevocationService,
        Depends(ExternalChannelConnectionRevocationService),
    ]
    manager_id: str = dataclasses.field(default_factory=lambda: uuid4().hex)
    poll_interval: datetime.timedelta = _DEFAULT_POLL_INTERVAL
    lease_duration: datetime.timedelta = _DEFAULT_LEASE_DURATION
    renew_interval: datetime.timedelta = _DEFAULT_RENEW_INTERVAL
    config: Annotated[Config | None, Depends(get_config)] = None

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
                        logger.exception("Slack Socket connection manager task failed")
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
            web_client = create_slack_web_client()

            async def admit_owned(event: ExternalChannelTrigger) -> object:
                return await self._handle_owned_event(
                    connection_id=connection_id,
                    configuration=configuration,
                    event=event,
                )

            async def admit_owned_interaction(
                callback: SlackInteractionCallback,
                shortcut_source_event: ExternalChannelTrigger | None,
            ) -> ExternalChannelInteractionHandoff | None:
                if (
                    callback.app_id != configuration.provider_app_id
                    or callback.tenant_id != configuration.provider_tenant_id
                    or not await self._owned_active(connection_id)
                ):
                    raise SlackSocketInvalidEnvelope(
                        "Slack Socket connection is no longer authorized."
                    )
                selector_supported = (
                    configuration.app_mode is ExternalChannelAppMode.MULTI
                    and callback.requires_selector_processing()
                )
                if not selector_supported:
                    shortcut_source_event = None
                admission = await self.admission_service.admit_interaction(
                    create=callback.interaction_create(
                        connection_id=connection_id,
                        transport=configuration.transport,
                    ),
                    principal=callback.principal_create(),
                )
                if shortcut_source_event is not None:
                    await self.shortcut_source_service.ensure(
                        shortcut_source_event=shortcut_source_event,
                        interaction_id=admission.interaction.id,
                        now=_utc_now(),
                    )
                claim = (
                    await self.admission_service.begin_interaction_provider_mutation(
                        interaction_id=admission.interaction.id,
                        now=_utc_now(),
                    )
                    if selector_supported
                    else None
                )
                if not selector_supported:
                    await self.admission_service.finish_interaction_provider_mutation(
                        interaction_id=admission.interaction.id,
                        status=ExternalChannelInteractionStatus.REJECTED,
                        error_kind="interaction_unsupported",
                        error_summary=(
                            "Slack interaction is outside the supported selector flow."
                        ),
                    )
                return (
                    ExternalChannelInteractionHandoff(
                        interaction_id=claim.interaction.id,
                        trigger_id=callback.trigger_id,
                        selector_admission_id=callback.selector_admission_id,
                        selector_metadata=callback.selector_metadata,
                        selected_route_id=callback.selected_route_id,
                        selector_navigation=callback.selector_navigation,
                        selector_search=callback.selector_search,
                        selector_view_id=callback.selector_view_id,
                        selector_view_hash=callback.selector_view_hash,
                    )
                    if (claim is not None and claim.claimed)
                    else None
                )

            def schedule_owned_interaction(
                handoff: ExternalChannelInteractionHandoff,
            ) -> None:
                task = asyncio.create_task(
                    self.admission_service.run_interaction_provider_mutation(
                        handoff=handoff,
                        callback=self.interaction_processor.process,
                    )
                )
                task.add_done_callback(_log_interaction_task_failure)

            async def report_active() -> None:
                if not await self._mark_active(connection_id):
                    raise SlackSocketInvalidEnvelope(
                        "Slack Socket connection is no longer authorized."
                    )

            async def report_gap(reason: str) -> None:
                if not await self._record_gap(connection_id, reason):
                    raise SlackSocketInvalidEnvelope(
                        "Slack Socket connection is no longer authorized."
                    )

            client = SlackSocketModeRunner(
                web_client=web_client,
                admit_event=admit_owned,
                admit_interaction=admit_owned_interaction,
                schedule_interaction=schedule_owned_interaction,
                report_active=report_active,
                report_gap=report_gap,
            )
            try:
                result = await self._run_connection_with_lease(
                    client=client,
                    connection_id=connection_id,
                    app_token=credentials.app_token,
                    shutdown_event=shutdown_event,
                )
            except SlackSocketRetryableIngestion:
                await self._release(
                    connection_id,
                    reason="socket_ingestion_retryable",
                    status=ExternalChannelConnectionStatus.DEGRADED,
                )
                return
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
            await self._release(
                connection_id,
                reason=result.reason,
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
        except SlackSocketCredentialError:
            await self._release(
                connection_id,
                reason="socket_credentials_invalid",
                status=ExternalChannelConnectionStatus.RECONNECT_REQUIRED,
            )
        except SlackSocketError, OSError:
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

    async def _handle_owned_event(
        self,
        *,
        connection_id: str,
        configuration: ExternalChannelConnectionConfiguration,
        event: ExternalChannelTrigger,
    ) -> object:
        """Complete one normal or revocation event under the current lease."""
        if (
            event.provider_app_id != configuration.provider_app_id
            or event.provider_tenant_id != configuration.provider_tenant_id
            or not await self._owned_active(connection_id)
        ):
            raise SlackSocketInvalidEnvelope(
                "Slack Socket connection is no longer authorized."
            )
        if self._message_ingress_quiesced(event):
            raise SlackSocketInvalidEnvelope(
                "Slack message ingress is temporarily quiesced."
            )
        result = await self.transport_ingestion_service.ingest_slack_event(
            event=event,
            authority=ExternalChannelIngressAuthority(
                kind=ExternalChannelIngressAuthorityKind.LEASE,
                ingress_profile=ExternalChannelIngressProfile.SLACK_SOCKET,
                configuration_generation=configuration.configuration_generation,
                lease_owner=self.manager_id,
                lease_generation=None,
            ),
            deadline=external_channel_transport_deadline(event.received_at),
        )
        if result is None:
            return event
        if isinstance(result, SlackConnectionRevocation):
            changed = await self.revocation_service.apply(
                connection_id=connection_id,
                revocation=result,
                required_configuration_generation=(
                    configuration.configuration_generation
                ),
                required_socket_lease_owner=self.manager_id,
                now=event.received_at,
            )
            if not changed:
                raise SlackSocketInvalidEnvelope(
                    "Slack Socket connection is no longer authorized."
                )
            return result
        if not transport_outcome_acknowledgeable(result):
            raise SlackSocketRetryableIngestion(
                "Slack Socket message ingestion is temporarily unavailable."
            )
        return result

    def _message_ingress_quiesced(
        self,
        event: ExternalChannelTrigger,
    ) -> bool:
        """Return whether normal Socket message admission is temporarily blocked."""
        return (
            self.config is not None
            and self.config.external_channel_conversation.quiesce.slack_socket
            and slack_event_is_normal_message_ingress(event)
        )

    async def _run_connection_with_lease(
        self,
        *,
        client: SlackSocketModeRunner,
        connection_id: str,
        app_token: str,
        shutdown_event: asyncio.Event,
    ) -> SlackSocketConnectionResult | None:
        connection_task = asyncio.create_task(
            client.run_connection(
                connection_id=connection_id,
                app_token=app_token,
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
                released = await self.repository.mark_connection_reconnect_required(
                    session,
                    connection_id=connection_id,
                    reason=reason,
                    now=now,
                    required_configuration_generation=None,
                    required_socket_lease_owner=self.manager_id,
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


def _required_ciphertext(
    configuration: ExternalChannelConnectionConfiguration,
) -> str:
    if configuration.encrypted_credentials is None:
        raise RuntimeError("Socket Mode credentials are not configured.")
    return configuration.encrypted_credentials


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _log_interaction_task_failure(task: asyncio.Task[None]) -> None:
    """Observe an already-terminalized handoff task without exposing triggers."""
    try:
        task.result()
    except asyncio.CancelledError:
        return
    except Exception:
        logger.exception("Slack interaction handoff task failed")
