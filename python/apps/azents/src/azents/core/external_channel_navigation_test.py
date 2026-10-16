"""Semantic channel action validation and provider reply lowering."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from azents.core.enums import ExternalChannelProvider
from azents.core.external_channel_file import ExternalChannelOutboundFileManifest
from azents.core.external_channel_navigation import (
    ChannelNavigationAction,
    ChannelNavigationContext,
    ChannelNavigationLink,
    validate_service_path,
)
from azents.engine.tools.external_channel import ChannelActionInput
from azents.repos.external_channel.work import _reply_parts
from azents.services.external_channel.channel_action import ExternalChannelActionService
from azents.services.runtime_web.service_url import SettingsRuntimeWebServiceUrlResolver
from azents.testing.types import require_instance

SERVICE = "a" * 32


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/reports/sales",
        "/reports/sales?period=month#chart",
        "/search?q=hello%20world",
        "/%ED%95%9C%EA%B8%80",
    ],
)
def test_service_paths_preserve_application_navigation(path: str) -> None:
    assert validate_service_path(path) == path


@pytest.mark.parametrize(
    "path",
    [
        "https://evil.example/x",
        "//evil.example/x",
        "relative",
        "/\\evil",
        "/%2f%2fevil",
        "/%252f%252fevil",
        "/x\nHost:evil",
        "/%0aevil",
        "/%5cevil",
    ],
)
def test_service_paths_cannot_escape_the_service(path: str) -> None:
    with pytest.raises(ValueError):
        validate_service_path(path)


@pytest.mark.parametrize(
    "action",
    [
        {"type": "browser", "service_id": SERVICE},
        {"type": "browser", "path": "/"},
        {"type": "browser", "label": "  "},
        {"type": "web_service"},
        {"type": "web_service", "service_id": SERVICE, "path": "//evil"},
        {"type": "browser", "tool_call_id": "call-1"},
    ],
)
def test_semantic_actions_reject_invalid_combinations(action: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        ChannelNavigationAction.model_validate(action)


@pytest.mark.parametrize("mode", ["continue", "request_input", "finish"])
def test_actions_work_with_each_publication_mode(mode: str) -> None:
    value = ChannelActionInput.model_validate(
        {
            "mode": mode,
            "binding": "binding",
            "message": "Please open",
            "actions": [{"type": "browser"}],
        }
    )
    assert value.actions == [ChannelNavigationAction(type="browser")]


@pytest.mark.parametrize(
    "payload",
    [
        {"mode": "ignore", "binding": "binding", "actions": [{"type": "browser"}]},
        {"mode": "continue", "binding": "binding", "actions": [{"type": "browser"}]},
        {
            "mode": "finish",
            "binding": "binding",
            "message": "Open",
            "actions": [{"type": "browser"}] * 6,
        },
    ],
)
def test_actions_require_a_message_and_bounded_publication(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        ChannelActionInput.model_validate(payload)


async def test_resolution_uses_scope_service_id_and_path_without_tool_results() -> None:
    operations = SimpleNamespace(
        navigation_context=AsyncMock(
            return_value=ChannelNavigationContext(
                workspace_handle="team",
                service_hosts={SERVICE: "apphost"},
            )
        )
    )
    service = require_instance(
        MagicMock(
            spec=ExternalChannelActionService,
            operations=operations,
            config=SimpleNamespace(web_url="https://azents.example"),
            navigation_urls=SettingsRuntimeWebServiceUrlResolver(
                enabled=True, service_suffix="apps.example"
            ),
        ),
        ExternalChannelActionService,
    )
    links = await ExternalChannelActionService.prepare_navigation(
        service,
        actions=[
            ChannelNavigationAction(type="browser"),
            ChannelNavigationAction(
                type="web_service",
                service_id=SERVICE,
                path="/reports?year=2026#summary",
                label="Report",
            ),
        ],
        session_id="session",
        agent_id="agent",
        binding_id="binding",
    )
    assert links == (
        ChannelNavigationLink(
            label="Open browser",
            url="https://azents.example/w/team/agents/agent/sessions/session?page=browser",
        ),
        ChannelNavigationLink(
            label="Report", url="https://apphost.apps.example/reports?year=2026#summary"
        ),
    )
    operations.navigation_context.assert_awaited_once_with(
        session_id="session",
        agent_id="agent",
        binding_id="binding",
        service_ids=[SERVICE],
    )


@pytest.mark.parametrize(
    "provider", [ExternalChannelProvider.DISCORD, ExternalChannelProvider.SLACK]
)
def test_reply_parts_attach_native_controls_without_changing_text(
    provider: ExternalChannelProvider,
) -> None:
    links = (ChannelNavigationLink(label="Open", url="https://azents.example/"),)
    parts = _reply_parts(
        provider=provider,
        labels={
            "guild_id": "1",
            "channel_id": "2",
            "parent_channel_id": "2",
            "conversation_scope": "parent_channel",
        },
        text="A useful result",
        files=(),
        links=links,
    )
    assert len(parts) == 1
    assert parts[0].payload["text"] == "A useful result"
    if provider is ExternalChannelProvider.DISCORD:
        assert parts[0].payload["components"] == [
            {
                "type": 1,
                "components": [
                    {
                        "type": 2,
                        "style": 5,
                        "label": "Open",
                        "url": "https://azents.example/",
                    },
                ],
            }
        ]
    else:
        blocks = parts[0].payload["blocks"]
        assert isinstance(blocks, list)
        assert blocks[-1]["elements"][0]["url"] == links[0].url


@pytest.mark.parametrize(
    "provider", [ExternalChannelProvider.DISCORD, ExternalChannelProvider.SLACK]
)
def test_long_messages_keep_controls_on_only_the_last_part(
    provider: ExternalChannelProvider,
) -> None:
    parts = _reply_parts(
        provider=provider,
        labels={
            "guild_id": "1",
            "channel_id": "2",
            "parent_channel_id": "2",
            "conversation_scope": "parent_channel",
        },
        text="A long result. " * 500,
        files=(),
        links=(ChannelNavigationLink(label="Open", url="https://azents.example/"),),
        slack_text_limit=2000,
    )
    assert len(parts) > 1
    key = "components" if provider is ExternalChannelProvider.DISCORD else "blocks"
    assert all(key not in part.payload for part in parts[:-1])
    assert key in parts[-1].payload


@pytest.mark.parametrize(
    "provider", [ExternalChannelProvider.DISCORD, ExternalChannelProvider.SLACK]
)
def test_file_replies_keep_files_and_append_native_navigation(
    provider: ExternalChannelProvider,
) -> None:
    manifest = ExternalChannelOutboundFileManifest(
        path="/tmp/report.txt",
        filename="report.txt",
        media_type="text/plain",
        expected_size=10,
    )
    parts = _reply_parts(
        provider=provider,
        labels={
            "guild_id": "1",
            "channel_id": "2",
            "parent_channel_id": "2",
            "conversation_scope": "parent_channel",
        },
        text="Report attached.",
        files=(manifest,),
        links=(ChannelNavigationLink(label="Open", url="https://azents.example/"),),
    )
    assert len(parts) == 2
    assert parts[0].payload["text"] == "Report attached."
    assert parts[0].payload["files"] == [manifest.model_dump(mode="json")]
    assert "files" not in parts[-1].payload
    key = "components" if provider is ExternalChannelProvider.DISCORD else "blocks"
    assert key in parts[-1].payload
