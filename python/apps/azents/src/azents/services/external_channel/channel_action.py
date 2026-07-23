"""Atomic Channel Action orchestration and one-attempt provider delivery."""

import asyncio
import datetime
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Annotated, assert_never

import httpx
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelActionMode,
    ExternalChannelDeliveryOperation,
    ExternalChannelDeliveryStatus,
    ExternalChannelProvider,
    ExternalChannelWorkStatus,
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
from azents.services.external_channel.connection import (
    get_external_channel_credentials_codec,
)
from azents.services.external_channel.credentials import ExternalChannelCredentialsCodec
from azents.services.external_channel.slack_events import (
    SlackControlMessageResult,
    SlackConversationClient,
)


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
        tasks: Sequence[ChannelWorkTask] | None,
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
                tasks=tasks,
                now=datetime.datetime.now(datetime.UTC),
            )
            await session.commit()
        reply_delivered = (
            committed.work_status is not ExternalChannelWorkStatus.FINISHED
        )
        for delivery in committed.deliveries:
            if (
                delivery.operation is ExternalChannelDeliveryOperation.REPLY
                and delivery.status is not ExternalChannelDeliveryStatus.PENDING
            ):
                reply_delivered = (
                    delivery.status is ExternalChannelDeliveryStatus.DELIVERED
                )
            if delivery.status is ExternalChannelDeliveryStatus.PENDING:
                if (
                    delivery.operation
                    is ExternalChannelDeliveryOperation.PROGRESS_UPDATE
                    and committed.work_status is ExternalChannelWorkStatus.FINISHED
                    and not reply_delivered
                ):
                    async with self.session_manager() as session:
                        await self.repository.skip_delivery(
                            session,
                            delivery_attempt_id=delivery.id,
                            error_kind="final_reply_not_delivered",
                            error_summary=(
                                "Activity Tracker completion requires a delivered "
                                "final reply."
                            ),
                            now=datetime.datetime.now(datetime.UTC),
                        )
                        await session.commit()
                    continue
                outcome = await self.attempt_delivery(delivery.id)
                if delivery.operation is ExternalChannelDeliveryOperation.REPLY:
                    reply_delivered = outcome is ExternalChannelDeliveryStatus.DELIVERED
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

    async def attempt_delivery(
        self,
        delivery_attempt_id: str,
    ) -> ExternalChannelDeliveryStatus | None:
        """Attempt one pending provider operation without automatic retry."""
        target = await self.prepare_delivery(delivery_attempt_id)
        if target is None:
            return None
        return await self.attempt_prepared_delivery(target)

    async def attempt_prepared_delivery(
        self,
        target: ChannelDeliveryTarget,
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
            result = await self._deliver(target)
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
    ) -> SlackControlMessageResult:
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
                )
            case _ as unreachable:
                assert_never(unreachable)

    async def _deliver_slack(
        self,
        target: ChannelDeliveryTarget,
        *,
        bot_token: str,
    ) -> SlackControlMessageResult:
        payload = target.request_payload
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
                return await self.slack_client.post_message(
                    bot_token=bot_token,
                    tenant_id=tenant_id,
                    channel_id=channel_id,
                    thread_ts=thread_ts,
                    markdown_text=text,
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
                    text=text,
                    blocks=blocks,
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
                    text=text,
                    blocks=blocks,
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


def _invalid_payload() -> SlackControlMessageResult:
    return SlackControlMessageResult(
        status="failed",
        provider_message_key=None,
        error_kind="provider_payload_invalid",
        error_summary="The committed provider request is incomplete.",
    )


def _blocks(value: object) -> list[dict[str, object]] | None:
    """Validate one persisted Slack Block Kit list."""
    if not isinstance(value, list) or not all(
        isinstance(block, dict) for block in value
    ):
        return None
    return [block for block in value if isinstance(block, dict)]
