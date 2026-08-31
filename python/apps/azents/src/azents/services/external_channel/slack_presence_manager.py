"""Lease-owned Slack Work presence manager."""

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

from azents.core.config import Config, ExternalChannelGatewayLeaseConfig
from azents.core.deps import get_config
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import (
    ExternalChannelConnectionConfiguration,
    SlackWorkPresenceTarget,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.connection import (
    get_external_channel_credentials_codec,
)
from azents.services.external_channel.credentials import ExternalChannelCredentialsCodec
from azents.services.external_channel.data import SlackConnectionCredentials
from azents.services.external_channel.slack_presence import (
    SlackPresenceOutcome,
    SlackWorkPresenceClient,
)
from azents.services.external_channel.slack_sdk_client import create_slack_web_client

logger = logging.getLogger(__name__)
_POLL_INTERVAL = datetime.timedelta(seconds=5)
_LEASE_DURATION = datetime.timedelta(seconds=45)
_RENEW_INTERVAL = datetime.timedelta(seconds=15)
_RECONCILE_INTERVAL = datetime.timedelta(seconds=5)
_CHANNEL_REFRESH_INTERVAL = datetime.timedelta(seconds=90)

type SlackPresenceKey = tuple[str, str, str]


class SlackPresenceLeaseLost(RuntimeError):
    """The current process no longer owns Slack Work presence authority."""


class SlackPresenceCredentialError(RuntimeError):
    """Persisted Slack credentials cannot project Work presence."""


@dataclasses.dataclass(frozen=True)
class _ObservedPresence:
    """One successfully delivered process-local presence projection."""

    target: SlackWorkPresenceTarget
    delivered_at: datetime.datetime


def get_slack_work_presence_client() -> SlackWorkPresenceClient:
    """Create the public Slack SDK Work presence adapter."""
    return SlackWorkPresenceClient(create_slack_web_client())


@dataclasses.dataclass
class SlackWorkPresenceManagerService:
    """Reconcile canonical Channel Work onto Slack-native presence."""

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
    presence_client: Annotated[
        SlackWorkPresenceClient,
        Depends(get_slack_work_presence_client),
    ]
    manager_id: str = dataclasses.field(default_factory=lambda: uuid4().hex)
    poll_interval: datetime.timedelta = _POLL_INTERVAL
    lease_duration: datetime.timedelta = _LEASE_DURATION
    renew_interval: datetime.timedelta = _RENEW_INTERVAL
    reconcile_interval: datetime.timedelta = _RECONCILE_INTERVAL
    channel_refresh_interval: datetime.timedelta = _CHANNEL_REFRESH_INTERVAL
    config: Annotated[Config | None, Depends(get_config)] = None

    async def run(self, shutdown_event: asyncio.Event) -> None:
        """Continuously own all claimable Slack presence connections."""
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
                        logger.exception("Slack Work presence task failed")
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
                except TimeoutError:
                    continue
        finally:
            for task in tasks.values():
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks.values(), return_exceptions=True)

    async def _list_connection_ids(self) -> list[str]:
        async with self.session_manager() as session:
            return await self.repository.list_slack_presence_connection_ids(session)

    async def _run_owned_connection(
        self,
        *,
        connection_id: str,
        shutdown_event: asyncio.Event,
    ) -> None:
        configuration = await self._claim(connection_id)
        if configuration is None:
            return
        observed: dict[SlackPresenceKey, _ObservedPresence] = {}
        try:
            bot_token = self._credentials(configuration).bot_token
            try:
                await self._run_connection_with_lease(
                    connection_id=connection_id,
                    configuration_generation=configuration.configuration_generation,
                    bot_token=bot_token,
                    observed=observed,
                    shutdown_event=shutdown_event,
                )
            except asyncio.CancelledError:
                await asyncio.shield(
                    self._clear_if_owned(
                        connection_id=connection_id,
                        configuration_generation=(
                            configuration.configuration_generation
                        ),
                        bot_token=bot_token,
                        observed=observed,
                    )
                )
                raise
            except SlackPresenceLeaseLost:
                return
        except SlackPresenceCredentialError:
            logger.warning(
                "Slack Work presence credentials are unavailable",
                extra={
                    "provider": "slack",
                    "connection_id": connection_id,
                },
            )
        finally:
            await asyncio.shield(self._release(connection_id))

    async def _run_connection_with_lease(
        self,
        *,
        connection_id: str,
        configuration_generation: int,
        bot_token: str,
        observed: dict[SlackPresenceKey, _ObservedPresence],
        shutdown_event: asyncio.Event,
    ) -> None:
        reconcile_task = asyncio.create_task(
            self._reconcile_forever(
                connection_id=connection_id,
                configuration_generation=configuration_generation,
                bot_token=bot_token,
                observed=observed,
            )
        )
        renew_task = asyncio.create_task(
            self._renew_forever(
                connection_id=connection_id,
                configuration_generation=configuration_generation,
            )
        )
        shutdown_task = asyncio.create_task(shutdown_event.wait())
        try:
            done, _ = await asyncio.wait(
                (reconcile_task, renew_task, shutdown_task),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if shutdown_task in done:
                reconcile_task.cancel()
                renew_task.cancel()
                await asyncio.gather(
                    reconcile_task,
                    renew_task,
                    return_exceptions=True,
                )
                await self._clear_if_owned(
                    connection_id=connection_id,
                    configuration_generation=configuration_generation,
                    bot_token=bot_token,
                    observed=observed,
                )
                return
            if renew_task in done:
                renew_task.result()
                raise SlackPresenceLeaseLost(
                    "Slack Work presence renewal stopped unexpectedly."
                )
            reconcile_task.result()
            raise RuntimeError("Slack Work presence reconciliation stopped.")
        finally:
            for task in (reconcile_task, renew_task, shutdown_task):
                task.cancel()
            await asyncio.gather(
                reconcile_task,
                renew_task,
                shutdown_task,
                return_exceptions=True,
            )

    async def _renew_forever(
        self,
        *,
        connection_id: str,
        configuration_generation: int,
    ) -> None:
        while True:
            await asyncio.sleep(self._renew_interval().total_seconds())
            if not await self._renew(
                connection_id=connection_id,
                configuration_generation=configuration_generation,
            ):
                raise SlackPresenceLeaseLost("Slack Work presence authority is stale.")

    async def _reconcile_forever(
        self,
        *,
        connection_id: str,
        configuration_generation: int,
        bot_token: str,
        observed: dict[SlackPresenceKey, _ObservedPresence],
    ) -> None:
        while True:
            targets = await self._load_targets(
                connection_id=connection_id,
                configuration_generation=configuration_generation,
            )
            if targets is None:
                raise SlackPresenceLeaseLost(
                    "Slack Work presence projection authority is stale."
                )
            await self._reconcile(
                connection_id=connection_id,
                bot_token=bot_token,
                targets=targets,
                observed=observed,
                now=_utc_now(),
            )
            await asyncio.sleep(self.reconcile_interval.total_seconds())

    async def _reconcile(
        self,
        *,
        connection_id: str,
        bot_token: str,
        targets: tuple[SlackWorkPresenceTarget, ...],
        observed: dict[SlackPresenceKey, _ObservedPresence],
        now: datetime.datetime,
    ) -> None:
        desired = {_presence_key(target): target for target in targets}
        for key, current in tuple(observed.items()):
            if key in desired:
                continue
            if current.target.desired_state == "idle":
                del observed[key]
                continue
            outcome = await self._apply(
                connection_id=connection_id,
                bot_token=bot_token,
                target=_idle_target(current.target),
            )
            if outcome.status == "delivered":
                del observed[key]

        for key, target in desired.items():
            current = observed.get(key)
            if not self._should_apply(target=target, observed=current, now=now):
                continue
            outcome = await self._apply(
                connection_id=connection_id,
                bot_token=bot_token,
                target=target,
            )
            if outcome.status == "delivered":
                observed[key] = _ObservedPresence(
                    target=target,
                    delivered_at=now,
                )

    def _should_apply(
        self,
        *,
        target: SlackWorkPresenceTarget,
        observed: _ObservedPresence | None,
        now: datetime.datetime,
    ) -> bool:
        if observed is None or observed.target != target:
            return True
        return (
            target.kind == "channel_loading"
            and target.desired_state == "processing"
            and now - observed.delivered_at >= self.channel_refresh_interval
        )

    async def _apply(
        self,
        *,
        connection_id: str,
        bot_token: str,
        target: SlackWorkPresenceTarget,
    ) -> SlackPresenceOutcome:
        outcome = await self.presence_client.set_presence(
            bot_token=bot_token,
            target=target,
        )
        log = logger.info if outcome.status == "delivered" else logger.warning
        log(
            "Slack Work presence reconciliation completed",
            extra={
                "provider": "slack",
                "connection_id": connection_id,
                "presence_kind": target.kind,
                "desired_state": target.desired_state,
                "outcome_status": outcome.status,
                "error_kind": outcome.error_kind,
            },
        )
        return outcome

    async def _clear_if_owned(
        self,
        *,
        connection_id: str,
        configuration_generation: int,
        bot_token: str,
        observed: dict[SlackPresenceKey, _ObservedPresence],
    ) -> None:
        if not await self._renew(
            connection_id=connection_id,
            configuration_generation=configuration_generation,
        ):
            return
        for key, current in tuple(observed.items()):
            if current.target.desired_state == "idle":
                continue
            outcome = await self._apply(
                connection_id=connection_id,
                bot_token=bot_token,
                target=_idle_target(current.target),
            )
            if outcome.status == "delivered":
                del observed[key]

    async def _claim(
        self,
        connection_id: str,
    ) -> ExternalChannelConnectionConfiguration | None:
        now = _utc_now()
        async with self.session_manager() as session:
            configuration = await self.repository.claim_slack_presence_connection(
                session,
                connection_id=connection_id,
                lease_owner=self.manager_id,
                now=now,
                lease_until=now + self._lease_duration(),
            )
            await session.commit()
            return configuration

    async def _renew(
        self,
        *,
        connection_id: str,
        configuration_generation: int,
    ) -> bool:
        now = _utc_now()
        async with self.session_manager() as session:
            renewed = await self.repository.renew_slack_presence_lease(
                session,
                connection_id=connection_id,
                lease_owner=self.manager_id,
                required_configuration_generation=configuration_generation,
                now=now,
                lease_until=now + self._lease_duration(),
            )
            await session.commit()
            return renewed

    async def _release(self, connection_id: str) -> bool:
        async with self.session_manager() as session:
            released = await self.repository.release_slack_presence_lease(
                session,
                connection_id=connection_id,
                lease_owner=self.manager_id,
                now=_utc_now(),
            )
            await session.commit()
            return released

    async def _load_targets(
        self,
        *,
        connection_id: str,
        configuration_generation: int,
    ) -> tuple[SlackWorkPresenceTarget, ...] | None:
        async with self.session_manager() as session:
            return await self.repository.list_owned_slack_work_presence_targets(
                session,
                connection_id=connection_id,
                lease_owner=self.manager_id,
                required_configuration_generation=configuration_generation,
                now=_utc_now(),
            )

    def _credentials(
        self,
        configuration: ExternalChannelConnectionConfiguration,
    ) -> SlackConnectionCredentials:
        if configuration.encrypted_credentials is None:
            raise SlackPresenceCredentialError(
                "Slack Work presence credentials are unavailable."
            )
        try:
            credentials = self.credentials_codec.decrypt(
                configuration.encrypted_credentials
            )
        except (InvalidToken, ValidationError) as error:
            raise SlackPresenceCredentialError(
                "Slack Work presence credentials are invalid."
            ) from error
        if not isinstance(credentials, SlackConnectionCredentials):
            raise SlackPresenceCredentialError(
                "Slack Work presence credentials are invalid."
            )
        return credentials

    def _lease_override(self) -> ExternalChannelGatewayLeaseConfig | None:
        if self.config is None:
            return None
        override = self.config.testenv_external_channel_gateway_lease
        return (
            override
            if isinstance(override, ExternalChannelGatewayLeaseConfig)
            else None
        )

    def _lease_duration(self) -> datetime.timedelta:
        override = self._lease_override()
        return self.lease_duration if override is None else override.duration

    def _renew_interval(self) -> datetime.timedelta:
        override = self._lease_override()
        return self.renew_interval if override is None else override.renewal_interval


def _presence_key(target: SlackWorkPresenceTarget) -> SlackPresenceKey:
    return target.kind, target.channel_id, target.thread_ts


def _idle_target(target: SlackWorkPresenceTarget) -> SlackWorkPresenceTarget:
    return dataclasses.replace(
        target,
        desired_state="idle",
        initiator_user_id=None,
        status_text=None,
    )


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)
