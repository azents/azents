"""Native provider delivery of independently resolved navigation controls."""

from unittest.mock import AsyncMock

import httpx
import pytest

from azents.core.enums import ExternalChannelDeliveryOperation, ExternalChannelProvider
from azents.core.external_channel_navigation import ChannelNavigationLink
from azents.core.external_channel_provider_effect import ProviderOperationKey
from azents.repos.external_channel.work import _reply_parts
from azents.services.external_channel.channel_action import ExternalChannelActionService
from azents.services.external_channel.channel_action_test import (
    _DiscordClientDelegate,
    _service,
    _target,
)
from azents.services.external_channel.discord_delivery import DiscordDeliveryResult
from azents.services.external_channel.slack_events_test import _client


@pytest.mark.parametrize(
    "provider", [ExternalChannelProvider.DISCORD, ExternalChannelProvider.SLACK]
)
async def test_native_navigation_reaches_provider_with_application_path(
    provider: ExternalChannelProvider,
) -> None:
    target = _target(
        provider=provider, operation=ExternalChannelDeliveryOperation.REPLY
    )
    link = ChannelNavigationLink(
        label="Sales report", url="https://app.example/reports?month=10#chart"
    )
    parts = _reply_parts(
        provider=provider,
        labels={
            "guild_id": "111",
            "channel_id": "C1",
            "parent_channel_id": "333",
            "conversation_scope": "parent_channel",
        },
        text="Sales results",
        files=(),
        links=(link,),
    )
    target.request_payload.clear()
    target.request_payload.update(parts[0].payload)
    operation = ProviderOperationKey.from_seed("navigation-test")
    if provider is ExternalChannelProvider.DISCORD:
        delivered = DiscordDeliveryResult(
            status="delivered",
            provider_message_key="discord:111:555",
            error_kind=None,
            error_summary=None,
        )
        create = AsyncMock(return_value=delivered)
        result = await ExternalChannelActionService._deliver_discord(
            _service(discord_client=_DiscordClientDelegate(create_message=create)),
            target,
            operation_key=operation,
            bot_token="discord-secret",
            file_storage=None,
            agent_id="agent-1",
            authority=None,
        )
        assert result is delivered
        call = create.await_args
        assert call is not None
        assert call.kwargs["components"][0]["components"][0]["url"] == link.url
        assert call.kwargs["content"] == "Sales results"
    else:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, json={"ok": True, "ts": "1721600001.000100"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            result = await ExternalChannelActionService._deliver_slack(
                _service(slack_client=_client(http)),
                target,
                operation_key=operation,
                bot_token="xoxb-secret",
                file_storage=None,
                agent_id="agent-1",
                session_id="session-1",
                authority=None,
                provider_delivery_service=None,
                resolve_runtime_target=None,
            )
        assert result.status == "delivered"
        assert len(requests) == 1
        body = requests[0].content.decode()
        assert "blocks" in body
        assert "Sales report" in body or "Sales+report" in body
        assert "markdown_text" not in body
        assert "month" in body and "chart" in body
