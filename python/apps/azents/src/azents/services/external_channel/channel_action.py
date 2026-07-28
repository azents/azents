"""Atomic Channel Action orchestration and one-attempt provider delivery."""

import asyncio
import datetime
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Annotated, assert_never, cast
from urllib.parse import urlparse

import httpx
from fastapi import Depends
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.enums import (
    ExternalChannelActionMode,
    ExternalChannelAppMode,
    ExternalChannelDeliveryOperation,
    ExternalChannelDeliveryStatus,
    ExternalChannelProvider,
    ExternalChannelWorkStatus,
)
from azents.core.external_channel_file import (
    MAX_EXTERNAL_CHANNEL_FILES,
    ExternalChannelOutboundFileManifest,
    ExternalChannelOutboundFileSource,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.work import ExternalChannelWorkRepository
from azents.repos.external_channel.work_data import (
    ChannelActionCommit,
    ChannelDeliveryTarget,
    ChannelWorkSnapshot,
    ChannelWorkTask,
)
from azents.runtime.transfer.runtime_to_provider import (
    RuntimeToProviderBatch,
    RuntimeToProviderCleanupError,
    RuntimeToProviderDeliveryCapability,
    RuntimeToProviderRecovery,
    RuntimeToProviderRecoveryError,
    RuntimeToProviderSource,
    RuntimeToProviderTransferError,
)
from azents.services.exchange_file import ExchangeFileService
from azents.services.external_channel.connection import (
    get_external_channel_credentials_codec,
)
from azents.services.external_channel.credentials import ExternalChannelCredentialsCodec
from azents.services.external_channel.discord_delivery import (
    DiscordDeliveryClient,
    DiscordDeliveryResult,
    DiscordOutboundFile,
    DiscordOutboundFileContentError,
)
from azents.services.external_channel.file_transfer import (
    ExternalChannelFileTransferError,
    iter_external_channel_exchange_file_chunks,
    iter_external_channel_outbound_file_chunks,
)
from azents.services.external_channel.presentation import (
    normalize_slack_agent_name,
    prepend_agent_blocks,
    prepend_agent_fallback,
    prepend_agent_markdown,
    resolve_slack_agent_presentation,
)
from azents.services.external_channel.slack_events import (
    SlackControlMessageResult,
    SlackConversationClient,
    SlackOutboundFile,
    SlackOutboundFileContentError,
)
from azents.services.external_channel.slack_sdk_client import create_slack_web_client
from azents.services.file_storage import FileStorage, RangedFileStorage
from azents.services.session_resource_authority import SessionResourceAuthority


async def get_slack_delivery_http_client() -> AsyncIterator[httpx.AsyncClient]:
    """Provide the bounded outbound Slack mutation transport."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        yield client


def get_slack_delivery_client(
    http_client: Annotated[
        httpx.AsyncClient,
        Depends(get_slack_delivery_http_client),
    ],
) -> SlackConversationClient:
    """Provide the Slack Channel Action adapter."""
    return SlackConversationClient(
        web_client=create_slack_web_client(),
        http_client=http_client,
    )


async def get_discord_delivery_http_client() -> AsyncIterator[httpx.AsyncClient]:
    """Provide a bounded HTTP client for Discord message delivery."""
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
        yield client


def get_discord_delivery_client(
    http_client: Annotated[
        httpx.AsyncClient,
        Depends(get_discord_delivery_http_client),
    ],
) -> DiscordDeliveryClient:
    """Provide the Discord Channel Action adapter."""
    return DiscordDeliveryClient(http_client)


@dataclass
class ExternalChannelActionService:
    """Commit Channel Work before attempting provider operations once."""

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    repository: Annotated[
        ExternalChannelWorkRepository,
        Depends(ExternalChannelWorkRepository),
    ]
    credentials_codec: Annotated[
        ExternalChannelCredentialsCodec,
        Depends(get_external_channel_credentials_codec),
    ]
    slack_client: Annotated[
        SlackConversationClient,
        Depends(get_slack_delivery_client),
    ]
    discord_client: Annotated[
        DiscordDeliveryClient,
        Depends(get_discord_delivery_client),
    ]
    exchange_file_service: Annotated[
        ExchangeFileService,
        Depends(ExchangeFileService),
    ]
    config: Annotated[Config, Depends(get_config)]

    async def has_active_binding(self, *, session_id: str, agent_id: str) -> bool:
        """Return whether the tool should be exposed for this root Session."""
        async with self.session_manager() as session:
            return await self.repository.has_active_binding(
                session,
                session_id=session_id,
                agent_id=agent_id,
            )

    async def snapshot(
        self,
        *,
        session_id: str,
        agent_id: str,
    ) -> list[ChannelWorkSnapshot]:
        """Load the canonical active-work snapshot."""
        async with self.session_manager() as session:
            return await self.repository.list_active_work(
                session,
                session_id=session_id,
                agent_id=agent_id,
            )

    async def find_existing_action(
        self,
        *,
        session_id: str,
        client_tool_call_id: str,
    ) -> tuple[ChannelActionCommit, dict[str, object]] | None:
        """Resolve a duplicate Tool call before touching its Runtime sources."""
        async with self.session_manager() as session:
            return await self.repository.find_action_by_client_tool_call(
                session,
                session_id=session_id,
                client_tool_call_id=client_tool_call_id,
            )

    async def execute(
        self,
        *,
        session_id: str,
        agent_id: str,
        run_id: str,
        client_tool_call_id: str,
        binding_id: str,
        mode: ExternalChannelActionMode,
        message: str | None,
        title: str | None,
        tasks: Sequence[ChannelWorkTask] | None,
        files: Sequence[ExternalChannelOutboundFileManifest],
        file_storage: FileStorage | None,
        authority: SessionResourceAuthority | None = None,
        provider_delivery_capability: RuntimeToProviderDeliveryCapability | None = None,
    ) -> ChannelActionCommit:
        """Commit canonical state, then attempt every provider intent once."""
        async with self.session_manager() as session:
            committed = await self.repository.commit_action(
                session,
                session_id=session_id,
                agent_id=agent_id,
                run_id=run_id,
                client_tool_call_id=client_tool_call_id,
                binding_id=binding_id,
                mode=mode,
                message=message,
                title=title,
                tasks=tasks,
                files=files,
                now=datetime.datetime.now(datetime.UTC),
            )
            await session.commit()
        reply_delivered = (
            committed.work_status is not ExternalChannelWorkStatus.FINISHED
            or any(
                delivery.operation is ExternalChannelDeliveryOperation.REPLY
                for delivery in committed.deliveries
            )
        )
        for delivery in committed.deliveries:
            if (
                delivery.operation is ExternalChannelDeliveryOperation.REPLY
                and delivery.status is not ExternalChannelDeliveryStatus.PENDING
            ):
                reply_delivered = (
                    reply_delivered
                    and delivery.status is ExternalChannelDeliveryStatus.DELIVERED
                )
            if delivery.status is ExternalChannelDeliveryStatus.PENDING:
                if (
                    delivery.operation
                    is ExternalChannelDeliveryOperation.PROGRESS_DELETE
                    and committed.work_status is ExternalChannelWorkStatus.FINISHED
                    and not reply_delivered
                ):
                    async with self.session_manager() as session:
                        await self.repository.skip_delivery(
                            session,
                            delivery_attempt_id=delivery.id,
                            error_kind="final_reply_not_delivered",
                            error_summary=(
                                "Activity Tracker cleanup requires a delivered "
                                "final reply."
                            ),
                            now=datetime.datetime.now(datetime.UTC),
                        )
                        await session.commit()
                    continue
                outcome = await self.attempt_delivery(
                    delivery.id,
                    file_storage=file_storage,
                    agent_id=agent_id,
                    authority=authority,
                    provider_delivery_capability=provider_delivery_capability,
                )
                if delivery.operation is ExternalChannelDeliveryOperation.REPLY:
                    reply_delivered = (
                        reply_delivered
                        and outcome is ExternalChannelDeliveryStatus.DELIVERED
                    )
        async with self.session_manager() as session:
            result = await self.repository.complete_action(
                session,
                action_id=committed.action_id,
                now=datetime.datetime.now(datetime.UTC),
            )
            await session.commit()
            return result

    async def prepare_delivery(
        self,
        delivery_attempt_id: str,
    ) -> ChannelDeliveryTarget | None:
        """Load one pending provider target before its connection is terminalized."""
        async with self.session_manager() as session:
            target = await self.repository.get_delivery_target(
                session,
                delivery_attempt_id=delivery_attempt_id,
            )
            if target is None or target.status not in {
                ExternalChannelDeliveryStatus.PENDING,
                ExternalChannelDeliveryStatus.ATTEMPTING,
                ExternalChannelDeliveryStatus.UNKNOWN,
                ExternalChannelDeliveryStatus.DELIVERED,
            }:
                return None
            if (
                target.status is ExternalChannelDeliveryStatus.DELIVERED
                and _completed_runtime_recoveries(target.request_payload) is None
            ):
                return None
            return target

    async def prepare_delivery_in_session(
        self,
        session: AsyncSession,
        delivery_attempt_id: str,
    ) -> ChannelDeliveryTarget | None:
        """Capture a pending target before the caller purges connection secrets."""
        target = await self.repository.get_delivery_target(
            session,
            delivery_attempt_id=delivery_attempt_id,
        )
        if target is None or target.status is not ExternalChannelDeliveryStatus.PENDING:
            return None
        return target

    async def attempt_delivery(
        self,
        delivery_attempt_id: str,
        *,
        file_storage: FileStorage | None = None,
        agent_id: str | None = None,
        authority: SessionResourceAuthority | None = None,
        provider_delivery_capability: RuntimeToProviderDeliveryCapability | None = None,
    ) -> ExternalChannelDeliveryStatus | None:
        """Attempt one pending provider operation without automatic retry."""
        target = await self.prepare_delivery(delivery_attempt_id)
        if target is None:
            return None
        return await self.attempt_prepared_delivery(
            target,
            file_storage=file_storage,
            agent_id=agent_id,
            authority=authority,
            provider_delivery_capability=provider_delivery_capability,
        )

    async def attempt_prepared_delivery(
        self,
        target: ChannelDeliveryTarget,
        *,
        file_storage: FileStorage | None = None,
        agent_id: str | None = None,
        authority: SessionResourceAuthority | None = None,
        provider_delivery_capability: RuntimeToProviderDeliveryCapability | None = None,
    ) -> ExternalChannelDeliveryStatus | None:
        """Attempt one current target or settle its prior provider completion."""
        runtime_provider_transfer = _uses_runtime_provider_transfer(target)
        completed_recoveries = (
            _completed_runtime_recoveries(target.request_payload)
            if target.provider is ExternalChannelProvider.SLACK
            else None
        )
        if completed_recoveries is not None:
            return await self._recover_completed_runtime_delivery(
                target,
                recoveries=completed_recoveries,
                provider_delivery_capability=provider_delivery_capability,
            )
        if target.status is not ExternalChannelDeliveryStatus.PENDING:
            return None
        if runtime_provider_transfer:
            if provider_delivery_capability is None:
                async with self.session_manager() as session:
                    await self.repository.skip_delivery(
                        session,
                        delivery_attempt_id=target.delivery_attempt_id,
                        error_kind="runtime_file_source_unavailable",
                        error_summary=(
                            "The original Runtime file source is unavailable."
                        ),
                        now=datetime.datetime.now(datetime.UTC),
                    )
                    await session.commit()
                return ExternalChannelDeliveryStatus.FAILED
        async with self.session_manager() as session:
            started = await self.repository.start_delivery(
                session,
                delivery_attempt_id=target.delivery_attempt_id,
                now=datetime.datetime.now(datetime.UTC),
                runtime_target=(
                    provider_delivery_capability.target
                    if runtime_provider_transfer
                    and provider_delivery_capability is not None
                    else None
                ),
            )
            await session.commit()
        if started is None:
            return None
        try:
            result = await self._deliver(
                started,
                file_storage=file_storage,
                agent_id=agent_id,
                authority=authority,
                provider_delivery_capability=provider_delivery_capability,
            )
        except asyncio.CancelledError:
            await asyncio.shield(
                self._record_unknown_after_cancellation(target.delivery_attempt_id)
            )
            raise
        recovery_delivery_id = None
        started_runtime_provider_transfer = _uses_runtime_provider_transfer(started)
        if not (result.status == "delivered" and started_runtime_provider_transfer):
            async with self.session_manager() as session:
                recovery_delivery_id = await self.repository.finish_delivery(
                    session,
                    delivery_attempt_id=target.delivery_attempt_id,
                    status=ExternalChannelDeliveryStatus(result.status),
                    provider_message_key=result.provider_message_key,
                    error_kind=result.error_kind,
                    error_summary=result.error_summary,
                    now=datetime.datetime.now(datetime.UTC),
                )
                await session.commit()
        if recovery_delivery_id is not None:
            await self.attempt_delivery(recovery_delivery_id)
        if started_runtime_provider_transfer:
            await self.recover_runtime_provider_settlement(
                target.delivery_attempt_id,
                provider_delivery_capability=provider_delivery_capability,
            )
        return ExternalChannelDeliveryStatus(result.status)

    async def drain_runtime_provider_settlements(
        self,
        *,
        provider_delivery_capability: RuntimeToProviderDeliveryCapability | None,
        limit: int = 20,
    ) -> int:
        """Recover bounded provider-completed claims without provider mutation."""
        if provider_delivery_capability is None:
            return 0
        async with self.session_manager() as session:
            delivery_attempt_ids = (
                await self.repository.list_runtime_provider_settlement_delivery_ids(
                    session,
                    limit=limit,
                )
            )
        recovered = 0
        for delivery_attempt_id in delivery_attempt_ids:
            status = await self.recover_runtime_provider_settlement(
                delivery_attempt_id,
                provider_delivery_capability=provider_delivery_capability,
            )
            if status is ExternalChannelDeliveryStatus.DELIVERED:
                recovered += 1
        return recovered

    async def recover_runtime_provider_settlement(
        self,
        delivery_attempt_id: str,
        *,
        provider_delivery_capability: RuntimeToProviderDeliveryCapability | None,
    ) -> ExternalChannelDeliveryStatus | None:
        """Recover exact Runtime settlement without replaying a provider request."""
        target = await self.prepare_delivery(delivery_attempt_id)
        if target is None or target.provider is not ExternalChannelProvider.SLACK:
            return None
        recoveries = _completed_runtime_recoveries(target.request_payload)
        if recoveries is None or provider_delivery_capability is None:
            return None
        return await self._recover_completed_runtime_delivery(
            target,
            recoveries=recoveries,
            provider_delivery_capability=provider_delivery_capability,
        )

    async def _recover_completed_runtime_delivery(
        self,
        target: ChannelDeliveryTarget,
        *,
        recoveries: tuple[RuntimeToProviderRecovery, ...],
        provider_delivery_capability: RuntimeToProviderDeliveryCapability | None,
    ) -> ExternalChannelDeliveryStatus | None:
        """Settle a persisted Slack completion without another provider request."""
        if provider_delivery_capability is None:
            return None
        try:
            await provider_delivery_capability.recover(recoveries=recoveries)
        except asyncio.CancelledError:
            raise
        except RuntimeToProviderRecoveryError as error:
            await self._record_runtime_provider_state(
                delivery_attempt_id=target.delivery_attempt_id,
                state="provider_completed",
                recoveries=error.recoveries,
                provider_message_key=_runtime_provider_message_key(
                    target.request_payload
                ),
            )
            return target.status
        except RuntimeToProviderTransferError:
            return target.status
        if target.status is ExternalChannelDeliveryStatus.DELIVERED:
            await self._record_runtime_provider_state(
                delivery_attempt_id=target.delivery_attempt_id,
                state="settled",
                recoveries=recoveries,
                provider_message_key=_runtime_provider_message_key(
                    target.request_payload
                ),
            )
            return ExternalChannelDeliveryStatus.DELIVERED
        provider_message_key = _runtime_provider_message_key(target.request_payload)
        async with self.session_manager() as session:
            recovery_delivery_id = (
                await self.repository.complete_runtime_provider_recovery(
                    session,
                    delivery_attempt_id=target.delivery_attempt_id,
                    provider_message_key=provider_message_key,
                    now=datetime.datetime.now(datetime.UTC),
                )
            )
            await session.commit()
        if recovery_delivery_id is not None:
            await self.attempt_delivery(recovery_delivery_id)
        return ExternalChannelDeliveryStatus.DELIVERED

    async def drain_archive_cleanup(
        self,
        delivery_ids: Sequence[str],
    ) -> int:
        """Attempt current archive intents and recover older rows conservatively."""
        async with self.session_manager() as session:
            await self.repository.recover_archive_cleanup(
                session,
                current_delivery_ids=delivery_ids,
                now=datetime.datetime.now(datetime.UTC),
            )
            pending_ids = await self.repository.list_archive_cleanup_ids(
                session,
                delivery_ids=delivery_ids,
            )
            await session.commit()
        for delivery_id in pending_ids:
            await self.attempt_delivery(delivery_id)
        return len(pending_ids)

    async def _record_unknown_after_cancellation(
        self,
        delivery_attempt_id: str,
    ) -> None:
        async with self.session_manager() as session:
            await self.repository.finish_delivery(
                session,
                delivery_attempt_id=delivery_attempt_id,
                status=ExternalChannelDeliveryStatus.UNKNOWN,
                provider_message_key=None,
                error_kind="execution_cancelled",
                error_summary=(
                    "Provider delivery outcome is unknown after cancellation."
                ),
                now=datetime.datetime.now(datetime.UTC),
            )
            await session.commit()

    async def _record_runtime_provider_state(
        self,
        *,
        delivery_attempt_id: str,
        state: str,
        recoveries: tuple[RuntimeToProviderRecovery, ...],
        provider_message_key: str | None,
    ) -> bool:
        """Persist exact Runtime claim ownership before another state boundary."""
        async with self.session_manager() as session:
            recorded = await self.repository.record_runtime_provider_state(
                session,
                delivery_attempt_id=delivery_attempt_id,
                state=state,
                recovery_payload={
                    "claims": [
                        _runtime_provider_recovery_payload(recovery)
                        for recovery in recoveries
                    ],
                    "provider_message_key": provider_message_key,
                },
                provider_message_key=provider_message_key,
            )
            await session.commit()
            return recorded

    async def _complete_runtime_provider_delivery(
        self,
        *,
        delivery_attempt_id: str,
        recoveries: tuple[RuntimeToProviderRecovery, ...],
        provider_message_key: str | None,
    ) -> bool:
        """Atomically publish confirmed provider success before Runtime cleanup."""
        async with self.session_manager() as session:
            completion = await self.repository.complete_runtime_provider_delivery(
                session,
                delivery_attempt_id=delivery_attempt_id,
                recovery_payload={
                    "claims": [
                        _runtime_provider_recovery_payload(recovery)
                        for recovery in recoveries
                    ],
                    "provider_message_key": provider_message_key,
                },
                provider_message_key=provider_message_key,
                now=datetime.datetime.now(datetime.UTC),
            )
            await session.commit()
        if completion.recovery_delivery_id is not None:
            await self.attempt_delivery(completion.recovery_delivery_id)
        return completion.accepted

    async def _revalidate_runtime_delivery_authority(
        self,
        *,
        delivery_attempt_id: str,
        provider_delivery_capability: RuntimeToProviderDeliveryCapability,
        provider_started: bool,
    ) -> None:
        """Fence Runtime admission and provider mutation against current authority."""
        async with self.session_manager() as session:
            current = await self.repository.revalidate_runtime_delivery_authority(
                session,
                delivery_attempt_id=delivery_attempt_id,
                runtime_target=provider_delivery_capability.target,
                provider_started=provider_started,
                now=datetime.datetime.now(datetime.UTC),
            )
            await session.commit()
        if not current:
            raise RuntimeToProviderTransferError(
                "Runtime provider delivery authority is no longer current"
            )

    async def _deliver(
        self,
        target: ChannelDeliveryTarget,
        *,
        file_storage: FileStorage | None,
        agent_id: str | None,
        authority: SessionResourceAuthority | None,
        provider_delivery_capability: RuntimeToProviderDeliveryCapability | None,
    ) -> SlackControlMessageResult | DiscordDeliveryResult:
        if target.encrypted_credentials is None:
            return SlackControlMessageResult(
                status="failed",
                provider_message_key=None,
                error_kind="credentials_missing",
                error_summary="External Channel credentials are unavailable.",
            )
        credentials = self.credentials_codec.decrypt(target.encrypted_credentials)
        match target.provider:
            case ExternalChannelProvider.SLACK:
                return await self._deliver_slack(
                    target,
                    bot_token=credentials.bot_token,
                    file_storage=file_storage,
                    agent_id=agent_id,
                    authority=authority,
                    provider_delivery_capability=provider_delivery_capability,
                )
            case ExternalChannelProvider.DISCORD:
                return await self._deliver_discord(
                    target,
                    bot_token=credentials.bot_token,
                    file_storage=file_storage,
                    agent_id=agent_id,
                    authority=authority,
                )
            case _ as unreachable:
                assert_never(unreachable)

    async def _deliver_discord(
        self,
        target: ChannelDeliveryTarget,
        *,
        bot_token: str,
        file_storage: FileStorage | None,
        agent_id: str | None,
        authority: SessionResourceAuthority | None,
    ) -> DiscordDeliveryResult:
        """Deliver one Discord text, multipart file, or control mutation."""
        payload = target.request_payload
        guild_id = payload.get("guild_id")
        channel_id = payload.get("channel_id")
        if (
            not isinstance(guild_id, str)
            or not guild_id.isdigit()
            or target.provider_tenant_id != guild_id
            or not isinstance(channel_id, str)
            or not channel_id.isdigit()
        ):
            return _discord_invalid_payload()
        files = _outbound_files(payload.get("files"))
        if files is None:
            return _discord_invalid_payload()
        delivery_channel_id = channel_id
        parent_channel_id = payload.get("thread_parent_channel_id")
        root_message_id = payload.get("thread_root_message_id")
        if parent_channel_id is not None or root_message_id is not None:
            if (
                not isinstance(parent_channel_id, str)
                or not parent_channel_id.isdigit()
                or not isinstance(root_message_id, str)
                or root_message_id != channel_id
            ):
                return _discord_invalid_payload()
            thread = await self.discord_client.ensure_thread(
                bot_token=bot_token,
                parent_channel_id=parent_channel_id,
                root_message_id=root_message_id,
            )
            if thread.status != "delivered":
                return thread
            resolved_thread_id = _discord_thread_channel_id(thread.provider_message_key)
            if resolved_thread_id is None:
                return _discord_invalid_payload()
            delivery_channel_id = resolved_thread_id
            if target.resource_id is not None:
                await self._record_discord_delivery_channel(
                    resource_id=target.resource_id,
                    delivery_channel_id=resolved_thread_id,
                )
        match target.operation:
            case (
                ExternalChannelDeliveryOperation.REPLY
                | ExternalChannelDeliveryOperation.PROGRESS_CREATE
                | ExternalChannelDeliveryOperation.CONTROL_MESSAGE
            ):
                text = payload.get("text")
                if not isinstance(text, str):
                    return _discord_invalid_payload()
                components = _discord_components(payload.get("components"))
                if payload.get("components") is not None and components is None:
                    return _discord_invalid_payload()
                embeds = _discord_embeds(payload.get("embeds"))
                if payload.get("embeds") is not None and embeds is None:
                    return _discord_invalid_payload()
                if files:
                    if components is not None or embeds is not None:
                        return _discord_invalid_payload()
                    runtime_files = [
                        file
                        for file in files
                        if file.source is ExternalChannelOutboundFileSource.RUNTIME
                    ]
                    exchange_files = [
                        file
                        for file in files
                        if file.source is ExternalChannelOutboundFileSource.EXCHANGE
                    ]
                    if runtime_files and (
                        file_storage is None
                        or agent_id is None
                        or not callable(getattr(file_storage, "read_range", None))
                    ):
                        return DiscordDeliveryResult(
                            status="failed",
                            provider_message_key=None,
                            error_kind="runtime_file_source_unavailable",
                            error_summary=(
                                "The original Runtime file source is unavailable."
                            ),
                        )
                    if exchange_files and authority is None:
                        return DiscordDeliveryResult(
                            status="failed",
                            provider_message_key=None,
                            error_kind="exchange_file_source_unavailable",
                            error_summary=(
                                "The original Exchange file source is unavailable."
                            ),
                        )
                    ranged_storage = (
                        None
                        if file_storage is None
                        else cast(RangedFileStorage, file_storage)
                    )
                    return await self.discord_client.create_file_message(
                        bot_token=bot_token,
                        guild_id=guild_id,
                        channel_id=delivery_channel_id,
                        content=_discord_agent_content(target, text),
                        files=tuple(
                            DiscordOutboundFile(
                                filename=file.filename,
                                media_type=file.media_type,
                                length=file.expected_size,
                                content=lambda file=file: _discord_outbound_content(
                                    manifest=file,
                                    file_storage=ranged_storage,
                                    agent_id=agent_id,
                                    exchange_file_service=self.exchange_file_service,
                                    authority=authority,
                                ),
                            )
                            for file in files
                        ),
                        delivery_attempt_id=target.delivery_attempt_id,
                    )
                if components is None and embeds is None:
                    return await self.discord_client.create_message(
                        bot_token=bot_token,
                        guild_id=guild_id,
                        channel_id=delivery_channel_id,
                        content=_discord_agent_content(target, text),
                        delivery_attempt_id=target.delivery_attempt_id,
                    )
                return await self.discord_client.create_message(
                    bot_token=bot_token,
                    guild_id=guild_id,
                    channel_id=delivery_channel_id,
                    content=_discord_agent_content(target, text),
                    delivery_attempt_id=target.delivery_attempt_id,
                    components=components,
                    embeds=embeds,
                )
            case ExternalChannelDeliveryOperation.PROGRESS_UPDATE:
                text = payload.get("text")
                embeds = _discord_embeds(payload.get("embeds"))
                message_id = _discord_provider_message_id(
                    payload.get("provider_message_key"),
                    guild_id=guild_id,
                )
                if not isinstance(text, str) or embeds is None or message_id is None:
                    return _discord_invalid_payload()
                return await self.discord_client.update_message(
                    bot_token=bot_token,
                    guild_id=guild_id,
                    channel_id=delivery_channel_id,
                    message_id=message_id,
                    content=_discord_agent_content(target, text),
                    embeds=embeds,
                )
            case ExternalChannelDeliveryOperation.PROGRESS_DELETE:
                message_id = _discord_provider_message_id(
                    payload.get("provider_message_key"),
                    guild_id=guild_id,
                )
                if message_id is None:
                    return _discord_invalid_payload()
                return await self.discord_client.delete_message(
                    bot_token=bot_token,
                    channel_id=delivery_channel_id,
                    message_id=message_id,
                )
            case _ as unreachable:
                assert_never(unreachable)

    async def _record_discord_delivery_channel(
        self,
        *,
        resource_id: str,
        delivery_channel_id: str,
    ) -> None:
        """Persist a provisioned Discord thread outside the provider mutation."""
        async with self.session_manager() as session:
            await self.repository.record_discord_delivery_channel(
                session,
                resource_id=resource_id,
                delivery_channel_id=delivery_channel_id,
            )
            await session.commit()

    async def _deliver_slack(
        self,
        target: ChannelDeliveryTarget,
        *,
        bot_token: str,
        file_storage: FileStorage | None,
        agent_id: str | None,
        authority: SessionResourceAuthority | None,
        provider_delivery_capability: RuntimeToProviderDeliveryCapability | None,
    ) -> SlackControlMessageResult:
        payload = target.request_payload
        presentation = resolve_slack_agent_presentation(
            target,
            avatar_cdn_base_url=self.config.avatar_cdn_base_url,
        )
        tenant_id = target.provider_tenant_id
        channel_id = payload.get("channel_id")
        thread_ts = payload.get("thread_ts")
        if (
            not isinstance(tenant_id, str)
            or not tenant_id
            or not isinstance(channel_id, str)
            or not isinstance(thread_ts, str)
        ):
            return SlackControlMessageResult(
                status="failed",
                provider_message_key=None,
                error_kind="provider_target_invalid",
                error_summary="Slack delivery target is incomplete.",
            )
        match target.operation:
            case ExternalChannelDeliveryOperation.REPLY:
                text = payload.get("text")
                if not isinstance(text, str):
                    return _invalid_payload()
                files = _outbound_files(payload.get("files"))
                if files is None:
                    return _invalid_payload()
                if files:
                    del file_storage, agent_id
                    return await self._deliver_slack_files(
                        bot_token=bot_token,
                        tenant_id=tenant_id,
                        channel_id=channel_id,
                        thread_ts=thread_ts,
                        markdown_text=prepend_agent_markdown(presentation, text),
                        files=files,
                        delivery_attempt_id=target.delivery_attempt_id,
                        authority=authority,
                        provider_delivery_capability=provider_delivery_capability,
                    )
                return await self.slack_client.post_message(
                    bot_token=bot_token,
                    tenant_id=tenant_id,
                    channel_id=channel_id,
                    thread_ts=thread_ts,
                    markdown_text=prepend_agent_markdown(presentation, text),
                    icon_url=(None if presentation is None else presentation.icon_url),
                )
            case ExternalChannelDeliveryOperation.PROGRESS_CREATE:
                text = payload.get("text")
                blocks = _blocks(payload.get("blocks"))
                if not isinstance(text, str) or blocks is None:
                    return _invalid_payload()
                return await self.slack_client.post_blocks(
                    bot_token=bot_token,
                    tenant_id=tenant_id,
                    channel_id=channel_id,
                    thread_ts=thread_ts,
                    text=prepend_agent_fallback(presentation, text),
                    blocks=prepend_agent_blocks(presentation, blocks),
                    icon_url=(None if presentation is None else presentation.icon_url),
                )
            case ExternalChannelDeliveryOperation.PROGRESS_UPDATE:
                text = payload.get("text")
                blocks = _blocks(payload.get("blocks"))
                message_ts = _provider_message_ts(payload.get("provider_message_key"))
                if not isinstance(text, str) or blocks is None or message_ts is None:
                    return _invalid_payload()
                return await self.slack_client.update_message(
                    bot_token=bot_token,
                    tenant_id=tenant_id,
                    channel_id=channel_id,
                    message_ts=message_ts,
                    text=prepend_agent_fallback(presentation, text),
                    blocks=prepend_agent_blocks(presentation, blocks),
                )
            case ExternalChannelDeliveryOperation.PROGRESS_DELETE:
                message_ts = _provider_message_ts(payload.get("provider_message_key"))
                if message_ts is None:
                    return _invalid_payload()
                return await self.slack_client.delete_message(
                    bot_token=bot_token,
                    tenant_id=tenant_id,
                    channel_id=channel_id,
                    message_ts=message_ts,
                )
            case ExternalChannelDeliveryOperation.CONTROL_MESSAGE:
                return _invalid_payload()
            case _ as unreachable:
                assert_never(unreachable)

    async def _deliver_slack_files(
        self,
        *,
        bot_token: str,
        tenant_id: str,
        channel_id: str,
        thread_ts: str,
        markdown_text: str,
        files: tuple[ExternalChannelOutboundFileManifest, ...],
        delivery_attempt_id: str,
        authority: SessionResourceAuthority | None,
        provider_delivery_capability: RuntimeToProviderDeliveryCapability | None,
    ) -> SlackControlMessageResult:
        """Stream one Runtime batch and Exchange sources through one Slack completion.

        The Runtime claims remain held until Slack's one completion result.
        """
        runtime_sources = tuple(
            RuntimeToProviderSource(
                runtime_path=file.path,
                filename=file.filename,
                media_type=file.media_type,
                expected_size=file.expected_size,
            )
            for file in files
            if file.source is ExternalChannelOutboundFileSource.RUNTIME
        )
        batch: RuntimeToProviderBatch | None = None
        claim_recoveries: tuple[RuntimeToProviderRecovery, ...] = ()
        if runtime_sources:
            if provider_delivery_capability is None:
                return SlackControlMessageResult(
                    status="failed",
                    provider_message_key=None,
                    error_kind="runtime_file_source_unavailable",
                    error_summary="The original Runtime file source is unavailable.",
                )
            try:

                async def before_source_admission() -> None:
                    await self._revalidate_runtime_delivery_authority(
                        delivery_attempt_id=delivery_attempt_id,
                        provider_delivery_capability=provider_delivery_capability,
                        provider_started=False,
                    )

                batch = await provider_delivery_capability.prepare(
                    operation_id=f"external-channel-delivery:{delivery_attempt_id}",
                    batch_id=delivery_attempt_id,
                    sources=runtime_sources,
                    before_source_admission=before_source_admission,
                )
                await batch.ensure_active()
                claim_recoveries = batch.recovery_evidence()
                recorded = await self._record_runtime_provider_state(
                    delivery_attempt_id=delivery_attempt_id,
                    state="prepared",
                    recoveries=claim_recoveries,
                    provider_message_key=None,
                )
                if not recorded:
                    await batch.abandon_or_cancel()
                    return SlackControlMessageResult(
                        status="failed",
                        provider_message_key=None,
                        error_kind="runtime_file_source_unavailable",
                        error_summary=(
                            "The Runtime file delivery is no longer eligible."
                        ),
                    )
            except asyncio.CancelledError:
                if batch is not None:
                    await asyncio.shield(batch.close())
                    await asyncio.shield(batch.abandon_or_cancel())
                raise
            except RuntimeToProviderCleanupError:
                return SlackControlMessageResult(
                    status="unknown",
                    provider_message_key=None,
                    error_kind="runtime_transfer_cleanup_unknown",
                    error_summary="Runtime file delivery cleanup is not confirmed.",
                )
            except RuntimeToProviderTransferError:
                if batch is not None:
                    try:
                        await batch.abandon_or_cancel()
                    except RuntimeToProviderTransferError:
                        return SlackControlMessageResult(
                            status="unknown",
                            provider_message_key=None,
                            error_kind="runtime_transfer_cleanup_unknown",
                            error_summary=(
                                "Runtime file delivery cleanup is not confirmed."
                            ),
                        )
                return SlackControlMessageResult(
                    status="failed",
                    provider_message_key=None,
                    error_kind="runtime_file_source_unavailable",
                    error_summary="The original Runtime file source is unavailable.",
                )
        if (
            any(
                file.source is ExternalChannelOutboundFileSource.EXCHANGE
                for file in files
            )
            and authority is None
        ):
            if batch is not None:
                try:
                    await batch.abandon_or_cancel()
                except RuntimeToProviderCleanupError:
                    return SlackControlMessageResult(
                        status="unknown",
                        provider_message_key=None,
                        error_kind="runtime_transfer_cleanup_unknown",
                        error_summary=(
                            "Runtime file delivery cleanup is not confirmed."
                        ),
                    )
            return SlackControlMessageResult(
                status="failed",
                provider_message_key=None,
                error_kind="exchange_file_source_unavailable",
                error_summary="The original Exchange file source is unavailable.",
            )

        provider_started = False

        async def before_provider_request() -> None:
            nonlocal provider_started
            if batch is not None:
                assert provider_delivery_capability is not None
                await self._revalidate_runtime_delivery_authority(
                    delivery_attempt_id=delivery_attempt_id,
                    provider_delivery_capability=provider_delivery_capability,
                    provider_started=provider_started,
                )
                await batch.ensure_active()
                if not provider_started:
                    recorded = await self._record_runtime_provider_state(
                        delivery_attempt_id=delivery_attempt_id,
                        state="provider_started",
                        recoveries=claim_recoveries,
                        provider_message_key=None,
                    )
                    if not recorded:
                        raise RuntimeToProviderTransferError(
                            "Runtime provider claim ownership was not persisted"
                        )
            provider_started = True

        runtime_index = 0
        outbound_files: list[SlackOutboundFile] = []
        for file in files:
            if file.source is ExternalChannelOutboundFileSource.RUNTIME:
                source_index = runtime_index
                runtime_index += 1
                assert batch is not None
                outbound_files.append(
                    SlackOutboundFile(
                        filename=file.filename,
                        length=file.expected_size,
                        content=lambda source_index=source_index: (
                            _slack_runtime_provider_content(
                                batch=batch,
                                source_index=source_index,
                            )
                        ),
                    )
                )
            else:
                outbound_files.append(
                    SlackOutboundFile(
                        filename=file.filename,
                        length=file.expected_size,
                        content=lambda file=file: _slack_exchange_outbound_content(
                            manifest=file,
                            exchange_file_service=self.exchange_file_service,
                            authority=authority,
                        ),
                    )
                )
        try:
            result = await self.slack_client.post_file_message(
                bot_token=bot_token,
                tenant_id=tenant_id,
                channel_id=channel_id,
                thread_ts=thread_ts,
                markdown_text=markdown_text,
                files=outbound_files,
                before_provider_request=before_provider_request,
                deadline_at=batch.deadline_at if batch is not None else None,
            )
        except asyncio.CancelledError:
            if batch is not None:
                await asyncio.shield(batch.close())
                if not provider_started:
                    await asyncio.shield(batch.abandon_or_cancel())
            raise
        except RuntimeToProviderTransferError:
            if batch is not None and not provider_started:
                try:
                    await batch.close()
                    await batch.abandon_or_cancel()
                except RuntimeToProviderCleanupError:
                    return SlackControlMessageResult(
                        status="unknown",
                        provider_message_key=None,
                        error_kind="runtime_transfer_cleanup_unknown",
                        error_summary=(
                            "Runtime file delivery cleanup is not confirmed."
                        ),
                    )
                return SlackControlMessageResult(
                    status="failed",
                    provider_message_key=None,
                    error_kind="runtime_file_source_unavailable",
                    error_summary="The original Runtime file source is unavailable.",
                )
            if batch is not None:
                await batch.close()
            return SlackControlMessageResult(
                status="unknown",
                provider_message_key=None,
                error_kind="runtime_transfer_ambiguous",
                error_summary="Runtime file delivery outcome is unknown.",
            )
        if batch is None:
            return result
        if result.status == "delivered":
            try:
                recoveries = await batch.provider_completed()
                completed = await self._complete_runtime_provider_delivery(
                    delivery_attempt_id=delivery_attempt_id,
                    recoveries=recoveries,
                    provider_message_key=result.provider_message_key,
                )
                if not completed:
                    await batch.close()
                    return SlackControlMessageResult(
                        status="unknown",
                        provider_message_key=None,
                        error_kind="runtime_provider_completion_unrecorded",
                        error_summary=(
                            "Slack accepted the file reply, but the provider "
                            "completion could not be recorded."
                        ),
                    )
                await batch.acknowledge_and_settle()
                await self._record_runtime_provider_state(
                    delivery_attempt_id=delivery_attempt_id,
                    state="settled",
                    recoveries=recoveries,
                    provider_message_key=result.provider_message_key,
                )
            except asyncio.CancelledError:
                await asyncio.shield(batch.close())
                raise
            except RuntimeToProviderTransferError:
                await batch.close()
                return result
            return result
        if result.status == "failed":
            try:
                await batch.close()
                await batch.abandon_or_cancel()
            except asyncio.CancelledError:
                raise
            except RuntimeToProviderTransferError:
                return SlackControlMessageResult(
                    status="unknown",
                    provider_message_key=None,
                    error_kind="runtime_transfer_cleanup_unknown",
                    error_summary="Runtime file delivery cleanup is not confirmed.",
                )
        await batch.close()
        return result


def _has_runtime_outbound_source(payload: dict[str, object]) -> bool:
    """Return whether one persisted delivery requires a Runtime upload."""
    files = payload.get("files")
    return isinstance(files, list) and any(
        isinstance(file, dict) and file.get("source", "runtime") == "runtime"
        for file in files
    )


def _uses_runtime_provider_transfer(target: ChannelDeliveryTarget) -> bool:
    """Return whether Slack delivery requires the trusted Runtime transfer path."""
    return (
        target.provider is ExternalChannelProvider.SLACK
        and _has_runtime_outbound_source(target.request_payload)
    )


def _runtime_provider_recovery_payload(
    recovery: RuntimeToProviderRecovery,
) -> dict[str, object]:
    """Serialize exact internal claim correlation for durable recovery."""
    return {
        "transfer_id": recovery.transfer_id,
        "attempt_id": recovery.attempt_id,
        "consumer_claim_id": recovery.consumer_claim_id,
        "revision": recovery.revision,
        "runtime_id": recovery.runtime_id,
        "desired_generation": recovery.desired_generation,
        "operation_id": recovery.operation_id,
        "session_id": recovery.session_id,
        "agent_id": recovery.agent_id,
        "deadline_at": recovery.deadline_at.isoformat(),
    }


def _completed_runtime_recoveries(
    payload: dict[str, object],
) -> tuple[RuntimeToProviderRecovery, ...] | None:
    """Parse only the durable completion state that permits no provider replay."""
    recovery = payload.get("runtime_provider_recovery")
    if not isinstance(recovery, dict) or recovery.get("state") != "provider_completed":
        return None
    claims = recovery.get("claims")
    if not isinstance(claims, list) or not claims:
        return None
    parsed: list[RuntimeToProviderRecovery] = []
    for claim in claims:
        if not isinstance(claim, dict):
            return None
        try:
            transfer_id = _required_recovery_string(claim, "transfer_id")
            attempt_id = _required_recovery_string(claim, "attempt_id")
            consumer_claim_id = _required_recovery_string(claim, "consumer_claim_id")
            runtime_id = _required_recovery_string(claim, "runtime_id")
            operation_id = _required_recovery_string(claim, "operation_id")
            session_id = _required_recovery_string(claim, "session_id")
            agent_id = _required_recovery_string(claim, "agent_id")
            revision = claim["revision"]
            desired_generation = claim["desired_generation"]
            deadline_value = _required_recovery_string(claim, "deadline_at")
        except KeyError, ValueError:
            return None
        if (
            not isinstance(revision, int)
            or not isinstance(desired_generation, int)
            or revision < 0
            or desired_generation < 0
        ):
            return None
        try:
            deadline_at = datetime.datetime.fromisoformat(deadline_value)
        except ValueError:
            return None
        if deadline_at.tzinfo is None:
            return None
        parsed.append(
            RuntimeToProviderRecovery(
                transfer_id=transfer_id,
                attempt_id=attempt_id,
                consumer_claim_id=consumer_claim_id,
                revision=revision,
                runtime_id=runtime_id,
                desired_generation=desired_generation,
                operation_id=operation_id,
                session_id=session_id,
                agent_id=agent_id,
                deadline_at=deadline_at,
            )
        )
    return tuple(parsed)


def _runtime_provider_message_key(payload: dict[str, object]) -> str | None:
    """Return the provider key retained with a durable Runtime completion."""
    recovery = payload.get("runtime_provider_recovery")
    if not isinstance(recovery, dict):
        return None
    value = recovery.get("provider_message_key")
    return value if isinstance(value, str) and value else None


def _required_recovery_string(value: dict[str, object], key: str) -> str:
    """Read one non-empty durable recovery identifier."""
    result = value[key]
    if not isinstance(result, str) or not result:
        raise ValueError("Runtime provider recovery identifier is invalid")
    return result


def _provider_message_ts(value: object) -> str | None:
    if not isinstance(value, str) or ":" not in value:
        return None
    message_ts = value.rsplit(":", 1)[-1]
    return message_ts or None


def _discord_thread_channel_id(value: object) -> str | None:
    """Extract one validated Discord thread channel from a transient result."""
    if not isinstance(value, str):
        return None
    prefix = "discord-thread:"
    thread_id = value.removeprefix(prefix)
    if thread_id == value or not thread_id.isdigit():
        return None
    return thread_id


def _discord_provider_message_id(
    value: object,
    *,
    guild_id: str,
) -> str | None:
    """Extract an exact message snowflake from one canonical Discord key."""
    if not isinstance(value, str):
        return None
    provider, separator, remainder = value.partition(":")
    if provider != "discord" or not separator:
        return None
    message_guild_id, separator, message_id = remainder.partition(":")
    if not separator or message_guild_id != guild_id or not message_id.isdigit():
        return None
    return message_id


def _discord_agent_content(target: ChannelDeliveryTarget, text: str) -> str:
    """Prefix visible Discord text with a safely rendered current Agent name."""
    if target.app_mode is not ExternalChannelAppMode.MULTI:
        return text
    name = normalize_slack_agent_name(target.agent_name)
    if name is None:
        return text
    escaped_name = name.replace("\\", "\\\\").replace("*", "\\*")
    if not text:
        return f"**{escaped_name}**"
    return f"**{escaped_name}**\n{text}"


def _invalid_payload() -> SlackControlMessageResult:
    return SlackControlMessageResult(
        status="failed",
        provider_message_key=None,
        error_kind="provider_payload_invalid",
        error_summary="The committed provider request is incomplete.",
    )


def _discord_invalid_payload() -> DiscordDeliveryResult:
    return DiscordDeliveryResult(
        status="failed",
        provider_message_key=None,
        error_kind="provider_payload_invalid",
        error_summary="The committed Discord provider request is incomplete.",
    )


def _outbound_files(
    value: object,
) -> tuple[ExternalChannelOutboundFileManifest, ...] | None:
    if value is None:
        return ()
    if (
        not isinstance(value, list)
        or not value
        or len(value) > MAX_EXTERNAL_CHANNEL_FILES
    ):
        return None
    try:
        files = tuple(
            ExternalChannelOutboundFileManifest.model_validate(item) for item in value
        )
    except ValidationError:
        return None
    if any(PurePosixPath(file.filename).name != file.filename for file in files):
        return None
    return files


async def _slack_runtime_provider_content(
    *,
    batch: RuntimeToProviderBatch,
    source_index: int,
) -> AsyncIterator[bytes]:
    """Map one trusted Runtime batch stream to Slack's content error boundary."""
    try:
        async for chunk in batch.iter_source_chunks(source_index):
            yield chunk
    except RuntimeToProviderTransferError as error:
        raise SlackOutboundFileContentError from error


async def _slack_exchange_outbound_content(
    *,
    manifest: ExternalChannelOutboundFileManifest,
    exchange_file_service: ExchangeFileService,
    authority: SessionResourceAuthority | None,
) -> AsyncIterator[bytes]:
    """Map one authorized Exchange stream to Slack's content error boundary."""
    try:
        if authority is None:
            raise ExternalChannelFileTransferError(
                "Exchange file source is unavailable."
            )
        async for chunk in iter_external_channel_exchange_file_chunks(
            exchange_file_service=exchange_file_service,
            manifest=manifest,
            authority=authority,
        ):
            yield chunk
    except ExternalChannelFileTransferError as error:
        raise SlackOutboundFileContentError from error


async def _discord_outbound_content(
    *,
    manifest: ExternalChannelOutboundFileManifest,
    file_storage: RangedFileStorage | None,
    agent_id: str | None,
    exchange_file_service: ExchangeFileService,
    authority: SessionResourceAuthority | None,
) -> AsyncIterator[bytes]:
    """Yield one current source once for a Discord multipart request."""
    try:
        match manifest.source:
            case ExternalChannelOutboundFileSource.RUNTIME:
                if file_storage is None or agent_id is None:
                    raise ExternalChannelFileTransferError(
                        "Runtime file source is unavailable."
                    )
                async for chunk in iter_external_channel_outbound_file_chunks(
                    file_storage=file_storage,
                    manifest=manifest,
                    agent_id=agent_id,
                ):
                    yield chunk
            case ExternalChannelOutboundFileSource.EXCHANGE:
                if authority is None:
                    raise ExternalChannelFileTransferError(
                        "Exchange file source is unavailable."
                    )
                async for chunk in iter_external_channel_exchange_file_chunks(
                    exchange_file_service=exchange_file_service,
                    manifest=manifest,
                    authority=authority,
                ):
                    yield chunk
            case _ as unreachable:
                assert_never(unreachable)
    except ExternalChannelFileTransferError as error:
        raise DiscordOutboundFileContentError from error


def _blocks(value: object) -> list[dict[str, object]] | None:
    """Validate one persisted Slack Block Kit list."""
    if not isinstance(value, list) or not all(
        isinstance(block, dict) for block in value
    ):
        return None
    return [block for block in value if isinstance(block, dict)]


def _discord_components(value: object) -> list[dict[str, object]] | None:
    """Validate one bounded Discord component payload."""
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > 5:
        return None
    rows: list[dict[str, object]] = []
    for row in value:
        if (
            not isinstance(row, dict)
            or row.get("type") != 1
            or set(row) != {"type", "components"}
            or not isinstance(row.get("components"), list)
            or not row["components"]
            or len(row["components"]) > 5
        ):
            return None
        components = row["components"]
        if not all(_discord_button(component) for component in components):
            return None
        rows.append(row)
    return rows


def _discord_button(value: object) -> bool:
    """Permit the generated Button forms without accepting raw provider JSON."""
    if not isinstance(value, dict) or value.get("type") != 2:
        return False
    label = value.get("label")
    style = value.get("style")
    if (
        not isinstance(label, str)
        or not label
        or len(label) > 80
        or not isinstance(style, int)
        or style not in {1, 2, 3, 4, 5}
    ):
        return False
    if style == 5:
        url = value.get("url")
        parsed = urlparse(url) if isinstance(url, str) else None
        return (
            set(value) == {"type", "style", "label", "url"}
            and parsed is not None
            and parsed.scheme in {"http", "https"}
            and bool(parsed.netloc)
        )
    custom_id = value.get("custom_id")
    return (
        set(value) == {"type", "style", "label", "custom_id"}
        and isinstance(custom_id, str)
        and bool(custom_id)
        and len(custom_id) <= 100
    )


def _discord_embeds(value: object) -> list[dict[str, object]] | None:
    """Validate the generated bounded Embed subset persisted for delivery."""
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > 10:
        return None
    embeds: list[dict[str, object]] = []
    for embed in value:
        if not isinstance(embed, dict) or set(embed) - {
            "title",
            "description",
            "color",
        }:
            return None
        title = embed.get("title")
        description = embed.get("description")
        color = embed.get("color")
        if (
            not isinstance(title, str)
            or not title
            or len(title) > 256
            or not isinstance(description, str)
            or not description
            or len(description) > 4_096
            or not isinstance(color, int)
            or not 0 <= color <= 0xFFFFFF
            or len(title) + len(description) > 6_000
        ):
            return None
        embeds.append(embed)
    return embeds
