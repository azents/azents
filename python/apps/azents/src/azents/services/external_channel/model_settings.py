"""Provider-neutral orchestration for actor-private shared model settings."""

import datetime
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated, assert_never

import httpx
from fastapi import Depends

from azents.core.enums import ExternalChannelProvider
from azents.core.external_channel_provider_effect import ProviderOperationKey
from azents.core.external_model_settings import (
    ExternalModelActorContext,
    ExternalModelApplied,
    ExternalModelApplyResult,
    ExternalModelCancelResult,
    ExternalModelDraftSelection,
    ExternalModelEditorResult,
    ExternalModelNoticeOutcome,
    ExternalModelNoticePlan,
    ExternalModelTargetContext,
)
from azents.repos.external_channel.model_settings import (
    ExternalModelSettingsRepository,
)
from azents.services.external_channel.connection import (
    get_external_channel_credentials_codec,
)
from azents.services.external_channel.credentials import ExternalChannelCredentialsCodec
from azents.services.external_channel.discord_delivery import (
    DiscordDeliveryClient,
    DiscordFileMessageTransport,
)
from azents.services.external_channel.discord_sdk import (
    DiscordSDKClientFactory,
    get_discord_sdk_client_factory,
)
from azents.services.external_channel.slack_events import (
    SlackConversationClient,
    SlackExternalUploadTransport,
    SlackPrivateFileTransport,
)
from azents.services.external_channel.slack_sdk_client import create_slack_web_client


async def get_external_model_notice_http_client() -> AsyncIterator[httpx.AsyncClient]:
    """Provide bounded HTTP transport for the single notice attempt."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        yield client


def get_external_model_slack_client(
    http_client: Annotated[
        httpx.AsyncClient,
        Depends(get_external_model_notice_http_client),
    ],
) -> SlackConversationClient:
    """Build the supported Slack SDK-backed conversation client."""
    return SlackConversationClient(
        web_client=create_slack_web_client(),
        private_file_transport=SlackPrivateFileTransport(http_client),
        external_upload_transport=SlackExternalUploadTransport(http_client),
    )


def get_external_model_discord_client(
    sdk_factory: Annotated[
        DiscordSDKClientFactory,
        Depends(get_discord_sdk_client_factory),
    ],
    http_client: Annotated[
        httpx.AsyncClient,
        Depends(get_external_model_notice_http_client),
    ],
) -> DiscordDeliveryClient:
    """Build the supported Discord SDK-backed delivery client."""
    return DiscordDeliveryClient(
        sdk_factory,
        DiscordFileMessageTransport(http_client),
    )


@dataclass
class ExternalModelSettingsService:
    """Sequence completed draft transactions and one post-commit SDK notice."""

    repository: Annotated[
        ExternalModelSettingsRepository,
        Depends(ExternalModelSettingsRepository),
    ]
    credentials_codec: Annotated[
        ExternalChannelCredentialsCodec,
        Depends(get_external_channel_credentials_codec),
    ]
    slack_client: Annotated[
        SlackConversationClient,
        Depends(get_external_model_slack_client),
    ]
    discord_client: Annotated[
        DiscordDeliveryClient,
        Depends(get_external_model_discord_client),
    ]

    async def open_editor(
        self,
        *,
        actor: ExternalModelActorContext,
        target: ExternalModelTargetContext,
        owner_interaction_key: str,
        now: datetime.datetime,
        offset: int = 0,
        limit: int = 10,
    ) -> ExternalModelEditorResult:
        """Open or replay one authorized private draft."""
        return await self.repository.open_editor(
            actor=actor,
            target=target,
            owner_interaction_key=owner_interaction_key,
            now=now,
            offset=offset,
            limit=limit,
        )

    async def update_draft(
        self,
        *,
        actor: ExternalModelActorContext,
        draft_id: str,
        selection: ExternalModelDraftSelection,
        now: datetime.datetime,
        offset: int = 0,
        limit: int = 10,
    ) -> ExternalModelEditorResult:
        """Update private draft state without changing the shared Session."""
        return await self.repository.update_draft(
            actor=actor,
            draft_id=draft_id,
            selection=selection,
            now=now,
            offset=offset,
            limit=limit,
        )

    async def page_options(
        self,
        *,
        actor: ExternalModelActorContext,
        draft_id: str,
        now: datetime.datetime,
        offset: int,
        limit: int,
    ) -> ExternalModelEditorResult:
        """Return one current authorized option page for a live draft."""
        return await self.repository.page_options(
            actor=actor,
            draft_id=draft_id,
            now=now,
            offset=offset,
            limit=limit,
        )

    async def cancel_draft(
        self,
        *,
        actor: ExternalModelActorContext,
        draft_id: str,
        now: datetime.datetime,
    ) -> ExternalModelCancelResult:
        """Discard one actor-owned draft without a shared mutation."""
        return await self.repository.cancel_draft(
            actor=actor,
            draft_id=draft_id,
            now=now,
        )

    async def apply_draft(
        self,
        *,
        actor: ExternalModelActorContext,
        draft_id: str,
        expected_selection_fingerprint: str,
        apply_interaction_key: str,
        now: datetime.datetime,
    ) -> ExternalModelApplyResult:
        """Commit Apply, attempt its notice once, and report both outcomes."""
        commit = await self.repository.apply_draft(
            actor=actor,
            draft_id=draft_id,
            expected_selection_fingerprint=expected_selection_fingerprint,
            apply_interaction_key=apply_interaction_key,
            now=now,
        )
        result = commit.result
        if not isinstance(result, ExternalModelApplied) or not result.created:
            return result
        context = await self.repository.get_notice_delivery_context(
            mutation_id=result.mutation_id
        )
        if context is None:
            return result
        outcome, error_summary = await self._deliver_notice(
            actor=actor,
            plan=context.plan,
            encrypted_credentials=context.encrypted_credentials,
        )
        stored = await self.repository.record_notice_outcome(
            mutation_id=result.mutation_id,
            outcome=outcome,
            attempted_at=now,
            error_summary=error_summary,
        )
        return result.model_copy(update={"notice_outcome": stored})

    async def _deliver_notice(
        self,
        *,
        actor: ExternalModelActorContext,
        plan: ExternalModelNoticePlan,
        encrypted_credentials: str,
    ) -> tuple[ExternalModelNoticeOutcome, str | None]:
        credentials = self.credentials_codec.decrypt(encrypted_credentials)
        text = _notice_text(plan)
        match plan.provider:
            case ExternalChannelProvider.SLACK:
                delivered = await self.slack_client.post_message(
                    bot_token=credentials.bot_token,
                    tenant_id=actor.provider_tenant_id,
                    channel_id=plan.provider_conversation_id,
                    thread_ts=plan.provider_thread_id,
                    markdown_text=_slack_safe(text),
                    icon_url=None,
                )
            case ExternalChannelProvider.DISCORD:
                channel_id = plan.provider_thread_id
                if channel_id is None:
                    return (
                        ExternalModelNoticeOutcome.FAILED,
                        "Discord notice target is unavailable.",
                    )
                delivered = await self.discord_client.create_message(
                    bot_token=credentials.bot_token,
                    guild_id=plan.provider_conversation_id,
                    channel_id=channel_id,
                    content=_discord_safe(text),
                    operation_key=ProviderOperationKey.from_seed(plan.mutation_id),
                    suppress_notifications=False,
                    suppress_embeds=True,
                )
            case _ as unreachable:
                assert_never(unreachable)
        if delivered.status == "delivered":
            return ExternalModelNoticeOutcome.DELIVERED, None
        if delivered.status == "failed":
            return ExternalModelNoticeOutcome.FAILED, delivered.error_summary
        return ExternalModelNoticeOutcome.UNKNOWN, delivered.error_summary


def _notice_text(plan: ExternalModelNoticePlan) -> str:
    """Render committed public-safe values without Azents account state."""
    details = [f"model {plan.model_label} ({plan.model_display_name})"]
    if plan.reasoning_effort is not None:
        details.append(f"reasoning {plan.reasoning_effort.value}")
    if plan.enabled_execution_option_labels:
        details.append("execution " + ", ".join(plan.enabled_execution_option_labels))
    return (
        f"{plan.actor_display_name} changed the conversation "
        f"{'; '.join(details)}. New model calls use this setting; "
        "calls already started continue unchanged."
    )


def _slack_safe(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _discord_safe(value: str) -> str:
    escaped = value.replace("\\", "\\\\")
    for character in ("*", "_", "`", "~", "|", ">", "#", "@"):
        escaped = escaped.replace(character, f"\\{character}")
    return escaped
