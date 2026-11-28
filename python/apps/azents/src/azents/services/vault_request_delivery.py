"""One-shot provider publication and known-message settlement for Vault requests."""

import datetime
from dataclasses import dataclass
from typing import Annotated
from urllib.parse import urlencode

from fastapi import Depends

from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.enums import ExternalChannelProvider
from azents.core.external_channel_provider_effect import ProviderOperationKey
from azents.core.external_channel_session_presence import (
    build_external_channel_session_url,
)
from azents.repos.vault_request_delivery import (
    VaultDeliveryReceipt,
    VaultDeliveryTarget,
    VaultRequestDeliveryRepository,
)
from azents.services.external_channel.channel_action import (
    get_discord_delivery_client,
    get_slack_delivery_client,
)
from azents.services.external_channel.connection import (
    get_external_channel_credentials_codec,
)
from azents.services.external_channel.credentials import ExternalChannelCredentialsCodec
from azents.services.external_channel.discord_delivery import DiscordDeliveryClient
from azents.services.external_channel.slack_events import SlackConversationClient
from azents.services.vault_request_presentation import (
    render_discord_vault_request,
    render_slack_vault_request,
)


def _message_id(target: VaultDeliveryTarget, message_key: str) -> str | None:
    """Decode only the message identity confirmed by the exact adapter target."""
    if target.provider is ExternalChannelProvider.DISCORD:
        prefix = f"discord:{target.tenant_id}:"
    else:
        prefix = f"slack:{target.tenant_id}:{target.channel_id}:"
    if not message_key.startswith(prefix):
        return None
    suffix = message_key[len(prefix) :]
    if target.provider is ExternalChannelProvider.DISCORD:
        return suffix if suffix.isascii() and suffix.isdigit() else None
    seconds, separator, micros = suffix.partition(".")
    return (
        suffix
        if separator
        and seconds.isascii()
        and seconds.isdigit()
        and micros.isascii()
        and micros.isdigit()
        else None
    )


@dataclass(frozen=True)
class VaultRequestDeliveryService:
    """Claim, revalidate and attempt effects without coupling to Channel Work."""

    repository: Annotated[
        VaultRequestDeliveryRepository, Depends(VaultRequestDeliveryRepository)
    ]
    config: Annotated[Config, Depends(get_config)]
    credentials_codec: Annotated[
        ExternalChannelCredentialsCodec, Depends(get_external_channel_credentials_codec)
    ]
    discord_client: Annotated[
        DiscordDeliveryClient, Depends(get_discord_delivery_client)
    ]
    slack_client: Annotated[SlackConversationClient, Depends(get_slack_delivery_client)]

    async def reconcile(
        self, *, deadline: datetime.datetime, limit: int
    ) -> dict[str, int]:
        """Run bounded terminal edits and creates; report only safe counters."""
        summary = {"delivered": 0, "failed": 0, "unknown": 0, "skipped": 0}
        for terminal in (True, False):
            for _ in range(limit):
                if datetime.datetime.now(datetime.UTC) >= deadline:
                    return summary
                request_id = await self.repository.claim(terminal=terminal)
                if request_id is None:
                    break
                target = await self.repository.read_target(
                    request_id, terminal=terminal
                )
                if target is None:
                    summary["skipped"] += 1
                    continue
                if terminal:
                    outcome = await self._edit(target)
                else:
                    outcome = await self._post(request_id, target)
                summary[outcome] += 1
        return summary

    async def _post(self, request_id: str, target: VaultDeliveryTarget) -> str:
        url = build_external_channel_session_url(
            self.config.web_url,
            target.workspace_handle,
            target.agent_id,
            target.session_id,
        )
        if url is None:
            return "skipped"
        url = f"{url}?{urlencode({'vaultRequest': request_id})}"
        token = self.credentials_codec.decrypt(target.encrypted_credentials).bot_token
        if target.provider is ExternalChannelProvider.DISCORD:
            content = render_discord_vault_request(
                purpose=target.purpose,
                labels=target.field_labels,
                status=target.status,
                url=url,
            )
            result = await self.discord_client.create_message(
                bot_token=token,
                guild_id=target.tenant_id,
                channel_id=target.channel_id,
                content="",
                operation_key=ProviderOperationKey.from_seed(f"vault:{request_id}"),
                suppress_notifications=True,
                suppress_embeds=False,
                embeds=content.embeds,
                components=content.components,
            )
        else:
            slack = render_slack_vault_request(
                purpose=target.purpose,
                labels=target.field_labels,
                status=target.status,
                url=url,
            )
            result = await self.slack_client.post_blocks(
                bot_token=token,
                tenant_id=target.tenant_id,
                channel_id=target.channel_id,
                thread_ts=None,
                text=slack.text,
                blocks=slack.blocks,
                icon_url=None,
            )
        if result.status != "delivered":
            return result.status
        key = result.provider_message_key
        if key is None or _message_id(target, key) is None:
            return "unknown"
        await self.repository.record_receipt(
            request_id,
            VaultDeliveryReceipt(
                connection_id=target.connection_id,
                provider=target.provider,
                tenant_id=target.tenant_id,
                app_id=target.app_id,
                bot_id=target.bot_id,
                channel_id=target.channel_id,
                provider_message_key=key,
            ),
        )
        return "delivered"

    async def _edit(self, target: VaultDeliveryTarget) -> str:
        if target.receipt is None:
            return "skipped"
        message_id = _message_id(target, target.receipt.provider_message_key)
        if message_id is None:
            return "skipped"
        token = self.credentials_codec.decrypt(target.encrypted_credentials).bot_token
        if target.provider is ExternalChannelProvider.DISCORD:
            content = render_discord_vault_request(
                purpose=target.purpose,
                labels=target.field_labels,
                status=target.status,
                url=None,
            )
            result = await self.discord_client.update_message(
                bot_token=token,
                guild_id=target.tenant_id,
                channel_id=target.channel_id,
                message_id=message_id,
                content="",
                suppress_embeds=False,
                components=content.components,
                embeds=content.embeds,
            )
        else:
            slack = render_slack_vault_request(
                purpose=target.purpose,
                labels=target.field_labels,
                status=target.status,
                url=None,
            )
            result = await self.slack_client.update_message(
                bot_token=token,
                tenant_id=target.tenant_id,
                channel_id=target.channel_id,
                message_ts=message_id,
                text=slack.text,
                blocks=slack.blocks,
                literal_text=True,
            )
        return result.status
