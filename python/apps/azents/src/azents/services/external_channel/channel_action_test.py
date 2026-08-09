"""Focused direct provider outcome tests for External Channel actions."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from azents.core.enums import (
    ExternalChannelActionMode,
    ExternalChannelAppMode,
    ExternalChannelDeliveryOperation,
    ExternalChannelProvider,
    ExternalChannelWorkStatus,
)
from azents.repos.external_channel.work_data import ChannelActionTransition
from azents.services.external_channel.channel_action import (
    ExternalChannelActionService,
    _provider_mutation_outcome,
)
from azents.services.external_channel.discord_delivery import DiscordDeliveryResult
from azents.services.external_channel.provider_effect import (
    ProviderOperationKey,
    ProviderTarget,
)
from azents.services.external_channel.slack_events import SlackControlMessageResult

_SESSION_URL = "https://azents.example/w/team/agents/agent-1/sessions/session-1"


def _target(
    *,
    provider: ExternalChannelProvider,
    operation: ExternalChannelDeliveryOperation,
) -> ProviderTarget:
    request_payload: dict[str, Any] = {
        "text": "",
        "conversation_scope": "parent_channel",
        "blocks": [{"type": "task_card"}],
        "embeds": [
            {
                "title": "Channel Work",
                "description": "◉ Agent is checking your message",
                "color": 0x5865F2,
            }
        ],
    }
    if provider is ExternalChannelProvider.SLACK:
        request_payload["channel_id"] = "C1"
        if operation is ExternalChannelDeliveryOperation.PROGRESS_UPDATE:
            request_payload["provider_message_key"] = "slack:C1:123.456"
    else:
        request_payload.update(
            {
                "guild_id": "111",
                "channel_id": "333",
            }
        )
        if operation is ExternalChannelDeliveryOperation.PROGRESS_UPDATE:
            request_payload["provider_message_key"] = "discord:111:555"
    return ProviderTarget(
        operation=operation,
        binding_id="binding-1",
        resource_id="resource-1",
        connection_id="connection-1",
        provider=provider,
        app_mode=ExternalChannelAppMode.SINGLE,
        encrypted_credentials="ciphertext",
        provider_tenant_id=(
            "T1" if provider is ExternalChannelProvider.SLACK else "111"
        ),
        capabilities=None,
        workspace_handle="team",
        agent_id="agent-1",
        agent_session_id="session-1",
        agent_name="Research Agent",
        agent_avatar=None,
        request_payload=request_payload,
    )


def _service(
    *,
    slack_client: object | None = None,
    discord_client: object | None = None,
) -> ExternalChannelActionService:
    return cast(
        ExternalChannelActionService,
        SimpleNamespace(
            config=SimpleNamespace(
                web_url="https://azents.example",
                avatar_cdn_base_url=None,
            ),
            slack_client=slack_client,
            discord_client=discord_client,
        ),
    )


def test_slack_result_normalizes_without_persistent_identifiers() -> None:
    outcome = _provider_mutation_outcome(
        SlackControlMessageResult(
            status="failed",
            provider_message_key=None,
            error_kind="provider_rejected",
            error_summary="The provider rejected the request.",
        )
    )

    assert outcome.status == "failed"
    assert outcome.provider_message_key is None
    assert outcome.error_kind == "provider_rejected"


def test_discord_ambiguity_remains_unknown() -> None:
    outcome = _provider_mutation_outcome(
        DiscordDeliveryResult(
            status="unknown",
            provider_message_key=None,
            error_kind="provider_timeout",
            error_summary="The provider outcome is unknown.",
        )
    )

    assert outcome.status == "unknown"
    assert outcome.error_kind == "provider_timeout"


@pytest.mark.asyncio
async def test_ignore_transition_completes_without_provider_execution() -> None:
    """An empty canonical effect plan returns empty outcomes without delivery."""
    session = SimpleNamespace(commit=AsyncMock())
    repository = SimpleNamespace(
        commit_direct_action=AsyncMock(
            return_value=ChannelActionTransition(
                binding_id="binding-1",
                work_id="work-1",
                work_status=ExternalChannelWorkStatus.FINISHED,
                state_revision=5,
                effects=(),
            )
        )
    )
    execute_direct_effect = AsyncMock()

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[object]:
        yield session

    service = cast(
        ExternalChannelActionService,
        SimpleNamespace(
            session_manager=session_manager,
            repository=repository,
            execute_direct_effect=execute_direct_effect,
        ),
    )

    result = await ExternalChannelActionService.execute(
        service,
        session_id="session-1",
        agent_id="agent-1",
        run_id="run-1",
        client_tool_call_id="call-ignore",
        binding_id="binding-1",
        mode=ExternalChannelActionMode.IGNORE,
        message=None,
        title=None,
        tasks=None,
        files=(),
        file_storage=None,
        authority=None,
        provider_delivery_service=None,
        resolve_runtime_target=None,
    )

    assert result.work_status is ExternalChannelWorkStatus.FINISHED
    assert result.outcomes == ()
    repository.commit_direct_action.assert_awaited_once()
    session.commit.assert_awaited_once()
    execute_direct_effect.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "method_name"),
    [
        (ExternalChannelDeliveryOperation.PROGRESS_CREATE, "post_blocks"),
        (ExternalChannelDeliveryOperation.PROGRESS_UPDATE, "update_message"),
    ],
)
async def test_slack_tracker_delivery_includes_session_navigation(
    operation: ExternalChannelDeliveryOperation,
    method_name: str,
) -> None:
    method = AsyncMock(
        return_value=SlackControlMessageResult(
            status="delivered",
            provider_message_key="slack:C1:123.456",
            error_kind=None,
            error_summary=None,
        )
    )
    slack_client = SimpleNamespace(
        post_blocks=method if method_name == "post_blocks" else AsyncMock(),
        update_message=method if method_name == "update_message" else AsyncMock(),
    )

    await ExternalChannelActionService._deliver_slack(
        _service(slack_client=slack_client),
        _target(provider=ExternalChannelProvider.SLACK, operation=operation),
        operation_key=ProviderOperationKey.from_seed("slack-progress"),
        bot_token="slack-secret",
        file_storage=None,
        agent_id=None,
        session_id=None,
        authority=None,
        provider_delivery_service=None,
        resolve_runtime_target=None,
    )

    call = method.await_args
    assert call is not None
    blocks = call.kwargs["blocks"]
    assert blocks[-1] == {
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "action_id": "view_azents_session",
                "text": {"type": "plain_text", "text": "View session"},
                "url": _SESSION_URL,
            }
        ],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "method_name"),
    [
        (ExternalChannelDeliveryOperation.PROGRESS_CREATE, "create_message"),
        (ExternalChannelDeliveryOperation.PROGRESS_UPDATE, "update_message"),
    ],
)
async def test_discord_tracker_delivery_includes_session_navigation(
    operation: ExternalChannelDeliveryOperation,
    method_name: str,
) -> None:
    method = AsyncMock(
        return_value=DiscordDeliveryResult(
            status="delivered",
            provider_message_key="discord:111:555",
            error_kind=None,
            error_summary=None,
        )
    )
    discord_client = SimpleNamespace(
        create_message=method if method_name == "create_message" else AsyncMock(),
        update_message=method if method_name == "update_message" else AsyncMock(),
    )

    await ExternalChannelActionService._deliver_discord(
        _service(discord_client=discord_client),
        _target(provider=ExternalChannelProvider.DISCORD, operation=operation),
        operation_key=ProviderOperationKey.from_seed("discord-progress"),
        bot_token="discord-secret",
        file_storage=None,
        agent_id=None,
        authority=None,
    )

    call = method.await_args
    assert call is not None
    assert call.kwargs["components"] == [
        {
            "type": 1,
            "components": [
                {
                    "type": 2,
                    "style": 5,
                    "label": "View session",
                    "url": _SESSION_URL,
                }
            ],
        }
    ]
