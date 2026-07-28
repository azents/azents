"""Atomic Channel Action orchestration and one-attempt provider delivery."""

import asyncio
import datetime
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Annotated, assert_never, cast

import httpx
from fastapi import Depends
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.enums import (
    ExternalChannelActionMode,
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
    return SlackConversationClient(http_client)


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
            if (
                target is None
                or target.status is not ExternalChannelDeliveryStatus.PENDING
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
        )

    async def attempt_prepared_delivery(
        self,
        target: ChannelDeliveryTarget,
        *,
        file_storage: FileStorage | None = None,
        agent_id: str | None = None,
        authority: SessionResourceAuthority | None = None,
    ) -> ExternalChannelDeliveryStatus | None:
        """Attempt a target captured before connection credentials were purged."""
        if target.status is not ExternalChannelDeliveryStatus.PENDING:
            return None
        async with self.session_manager() as session:
            started = await self.repository.start_delivery(
                session,
                delivery_attempt_id=target.delivery_attempt_id,
                now=datetime.datetime.now(datetime.UTC),
            )
            await session.commit()
        if not started:
            return None
        try:
            result = await self._deliver(
                target,
                file_storage=file_storage,
                agent_id=agent_id,
                authority=authority,
            )
        except asyncio.CancelledError:
            await asyncio.shield(
                self._record_unknown_after_cancellation(target.delivery_attempt_id)
            )
            raise
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
        return ExternalChannelDeliveryStatus(result.status)

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

    async def _deliver(
        self,
        target: ChannelDeliveryTarget,
        *,
        file_storage: FileStorage | None,
        agent_id: str | None,
        authority: SessionResourceAuthority | None,
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
                if files:
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
                return await self.discord_client.create_message(
                    bot_token=bot_token,
                    guild_id=guild_id,
                    channel_id=delivery_channel_id,
                    content=_discord_agent_content(target, text),
                    delivery_attempt_id=target.delivery_attempt_id,
                )
            case ExternalChannelDeliveryOperation.PROGRESS_UPDATE:
                text = payload.get("text")
                message_id = _discord_provider_message_id(
                    payload.get("provider_message_key"),
                    guild_id=guild_id,
                )
                if not isinstance(text, str) or message_id is None:
                    return _discord_invalid_payload()
                return await self.discord_client.update_message(
                    bot_token=bot_token,
                    guild_id=guild_id,
                    channel_id=delivery_channel_id,
                    message_id=message_id,
                    content=_discord_agent_content(target, text),
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
                        return SlackControlMessageResult(
                            status="failed",
                            provider_message_key=None,
                            error_kind="runtime_file_source_unavailable",
                            error_summary=(
                                "The original Runtime file source is unavailable."
                            ),
                        )
                    if exchange_files and authority is None:
                        return SlackControlMessageResult(
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
                    source_agent_id = agent_id
                    return await self.slack_client.post_file_message(
                        bot_token=bot_token,
                        tenant_id=tenant_id,
                        channel_id=channel_id,
                        thread_ts=thread_ts,
                        markdown_text=prepend_agent_markdown(presentation, text),
                        files=[
                            SlackOutboundFile(
                                filename=file.filename,
                                length=file.expected_size,
                                content=lambda file=file: _slack_outbound_content(
                                    manifest=file,
                                    file_storage=ranged_storage,
                                    agent_id=source_agent_id,
                                    exchange_file_service=self.exchange_file_service,
                                    authority=authority,
                                ),
                            )
                            for file in files
                        ],
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
    name = normalize_slack_agent_name(target.agent_name)
    if name is None:
        return text
    escaped_name = name.replace("\\", "\\\\").replace("*", "\\*")
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


async def _slack_outbound_content(
    *,
    manifest: ExternalChannelOutboundFileManifest,
    file_storage: RangedFileStorage | None,
    agent_id: str | None,
    exchange_file_service: ExchangeFileService,
    authority: SessionResourceAuthority | None,
) -> AsyncIterator[bytes]:
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
