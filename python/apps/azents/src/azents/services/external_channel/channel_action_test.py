"""Focused direct provider outcome tests for External Channel actions."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
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
from azents.core.external_channel_file import (
    ExternalChannelOutboundFileManifest,
    ExternalChannelOutboundFileSource,
)
from azents.repos.external_channel.work_data import (
    ChannelActionEffectPlan,
    ChannelActionTransition,
)
from azents.services.external_channel.channel_action import (
    ExternalChannelActionService,
    _provider_mutation_outcome,
)
from azents.services.external_channel.discord_delivery import DiscordDeliveryResult
from azents.services.external_channel.discord_sdk import DiscordSDKUnavailable
from azents.services.external_channel.provider_effect import (
    ProviderEffectOutcome,
    ProviderOperationKey,
    ProviderTarget,
)
from azents.services.external_channel.slack_events import SlackControlMessageResult
from azents.services.session_resource_authority import SessionResourceAuthority

_SESSION_URL = "https://azents.example/w/team/agents/agent-1/sessions/session-1"


@dataclass
class _DiscordClientDelegate:
    open_error: Exception | None = None
    ensure_thread: AsyncMock = field(default_factory=AsyncMock)
    create_message: AsyncMock = field(default_factory=AsyncMock)
    create_file_message: AsyncMock = field(default_factory=AsyncMock)
    update_message: AsyncMock = field(default_factory=AsyncMock)
    delete_message: AsyncMock = field(default_factory=AsyncMock)


class _OpenableDiscordClient:
    def __init__(self, delegate: _DiscordClientDelegate) -> None:
        self.delegate = delegate
        self.opens = 0

    @asynccontextmanager
    async def open(
        self,
        *,
        bot_token: str,
    ) -> AsyncIterator["_OpenableDiscordClient"]:
        assert bot_token == "discord-secret"
        self.opens += 1
        if self.delegate.open_error is not None:
            raise self.delegate.open_error
        yield self

    async def ensure_thread(self, **values: object) -> DiscordDeliveryResult:
        return await self.delegate.ensure_thread(**values)

    async def create_message(self, **values: object) -> DiscordDeliveryResult:
        return await self.delegate.create_message(**values)

    async def create_file_message(self, **values: object) -> DiscordDeliveryResult:
        return await self.delegate.create_file_message(**values)

    async def update_message(self, **values: object) -> DiscordDeliveryResult:
        return await self.delegate.update_message(**values)

    async def delete_message(self, **values: object) -> DiscordDeliveryResult:
        return await self.delegate.delete_message(**values)


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


def _effect(
    operation: ExternalChannelDeliveryOperation,
    *,
    part: int = 0,
) -> ChannelActionEffectPlan:
    return cast(
        ChannelActionEffectPlan,
        SimpleNamespace(
            provider=SimpleNamespace(
                target=SimpleNamespace(operation=operation),
            ),
            part=part,
        ),
    )


def _service(
    *,
    slack_client: object | None = None,
    discord_client: _DiscordClientDelegate | None = None,
    exchange_file_service: object | None = None,
) -> ExternalChannelActionService:
    bound_discord_client: object | None = None
    if discord_client is not None:
        bound_discord_client = _OpenableDiscordClient(discord_client)
    return cast(
        ExternalChannelActionService,
        SimpleNamespace(
            config=SimpleNamespace(
                web_url="https://azents.example",
                avatar_cdn_base_url=None,
            ),
            slack_client=slack_client,
            discord_client=bound_discord_client,
            exchange_file_service=exchange_file_service,
        ),
    )


def _exchange_manifest() -> ExternalChannelOutboundFileManifest:
    return ExternalChannelOutboundFileManifest(
        source=ExternalChannelOutboundFileSource.EXCHANGE,
        path="exchange://exchange/workspace-1/files/file-1/original",
        filename="report.csv",
        media_type="text/csv",
        expected_size=42,
    )


def _authority() -> SessionResourceAuthority:
    return SessionResourceAuthority(
        workspace_id="workspace-1",
        agent_id="agent-1",
        session_id="session-1",
        root_session_id="session-1",
        run_id="run-1",
        run_index=1,
        owner_generation=1,
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
async def test_ignore_executes_tracker_deletion_without_final_reply() -> None:
    """Ignore does not apply finish's final-reply gate to Tracker cleanup."""
    session = SimpleNamespace(commit=AsyncMock())
    effect = _effect(ExternalChannelDeliveryOperation.PROGRESS_DELETE)
    repository = SimpleNamespace(
        commit_direct_action=AsyncMock(
            return_value=ChannelActionTransition(
                binding_id="binding-1",
                work_id="work-1",
                work_status=ExternalChannelWorkStatus.FINISHED,
                state_revision=5,
                effects=(effect,),
            )
        )
    )
    delivered = ProviderEffectOutcome(
        operation=ExternalChannelDeliveryOperation.PROGRESS_DELETE,
        part=0,
        status="delivered",
        reason=None,
        detail=None,
    )
    execute_direct_effect = AsyncMock(return_value=delivered)

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
    assert result.outcomes == (delivered,)
    repository.commit_direct_action.assert_awaited_once()
    session.commit.assert_awaited_once()
    execute_direct_effect.assert_awaited_once_with(
        effect,
        file_storage=None,
        agent_id="agent-1",
        session_id="session-1",
        authority=None,
        provider_delivery_service=None,
        resolve_runtime_target=None,
    )


@pytest.mark.asyncio
async def test_finish_keeps_tracker_when_final_reply_is_not_delivered() -> None:
    """Finish retains the Tracker cleanup gate when its required reply fails."""
    session = SimpleNamespace(commit=AsyncMock())
    reply = _effect(ExternalChannelDeliveryOperation.REPLY)
    delete = _effect(ExternalChannelDeliveryOperation.PROGRESS_DELETE)
    repository = SimpleNamespace(
        commit_direct_action=AsyncMock(
            return_value=ChannelActionTransition(
                binding_id="binding-1",
                work_id="work-1",
                work_status=ExternalChannelWorkStatus.FINISHED,
                state_revision=5,
                effects=(reply, delete),
            )
        )
    )
    failed_reply = ProviderEffectOutcome(
        operation=ExternalChannelDeliveryOperation.REPLY,
        part=0,
        status="failed",
        reason="provider_rejected",
        detail="The provider rejected the request.",
    )
    execute_direct_effect = AsyncMock(return_value=failed_reply)

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
        client_tool_call_id="call-finish",
        binding_id="binding-1",
        mode=ExternalChannelActionMode.FINISH,
        message="Done.",
        title=None,
        tasks=None,
        files=(),
        file_storage=None,
        authority=None,
        provider_delivery_service=None,
        resolve_runtime_target=None,
    )

    assert result.outcomes[0] is failed_reply
    assert result.outcomes[1].status == "not_attempted"
    assert result.outcomes[1].reason == "final_reply_not_delivered"
    execute_direct_effect.assert_awaited_once()


@pytest.mark.asyncio
async def test_slack_exchange_file_delivery_does_not_require_runtime_services() -> None:
    """Slack Exchange delivery bypasses every Runtime file dependency."""
    delivered = SlackControlMessageResult(
        status="delivered",
        provider_message_key="slack:C1:123.456",
        error_kind=None,
        error_summary=None,
    )
    post_file_message = AsyncMock(return_value=delivered)
    result = await ExternalChannelActionService._deliver_slack_files(
        _service(
            slack_client=SimpleNamespace(post_file_message=post_file_message),
            exchange_file_service=object(),
        ),
        bot_token="slack-secret",
        tenant_id="T1",
        channel_id="C1",
        thread_ts=None,
        markdown_text="Attached report.",
        files=(_exchange_manifest(),),
        operation_key=ProviderOperationKey.from_seed("slack-exchange"),
        agent_id="agent-1",
        session_id="session-1",
        authority=_authority(),
        provider_delivery_service=None,
        resolve_runtime_target=None,
    )

    assert result is delivered
    call = post_file_message.await_args
    assert call is not None
    assert call.kwargs["deadline_at"] is None
    assert len(call.kwargs["files"]) == 1


@pytest.mark.asyncio
async def test_discord_exchange_file_delivery_does_not_require_runtime_storage() -> (
    None
):
    """Discord Exchange delivery accepts a server-backed source without Runtime."""
    delivered = DiscordDeliveryResult(
        status="delivered",
        provider_message_key="discord:111:555",
        error_kind=None,
        error_summary=None,
    )
    create_file_message = AsyncMock(return_value=delivered)
    target = _target(
        provider=ExternalChannelProvider.DISCORD,
        operation=ExternalChannelDeliveryOperation.REPLY,
    )
    target.request_payload.pop("blocks")
    target.request_payload.pop("embeds")
    target.request_payload["files"] = [_exchange_manifest().model_dump(mode="json")]

    result = await ExternalChannelActionService._deliver_discord(
        _service(
            discord_client=_DiscordClientDelegate(
                create_file_message=create_file_message,
            ),
            exchange_file_service=object(),
        ),
        target,
        operation_key=ProviderOperationKey.from_seed("discord-exchange"),
        bot_token="discord-secret",
        file_storage=None,
        agent_id="agent-1",
        authority=_authority(),
    )

    assert result is delivered
    call = create_file_message.await_args
    assert call is not None
    assert len(call.kwargs["files"]) == 1


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
    discord_client = _DiscordClientDelegate(
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


@pytest.mark.asyncio
async def test_slack_terminal_thread_reply_enables_broadcast() -> None:
    """The Scheduled terminal flag reaches the exact-thread SDK call."""
    post_message = AsyncMock(
        return_value=SlackControlMessageResult(
            status="delivered",
            provider_message_key="slack:C1:123.456",
            error_kind=None,
            error_summary=None,
        )
    )
    target = _target(
        provider=ExternalChannelProvider.SLACK,
        operation=ExternalChannelDeliveryOperation.REPLY,
    )
    target.request_payload.update(
        {
            "conversation_scope": "thread",
            "thread_ts": "111.222",
            "reply_broadcast": True,
        }
    )
    target.request_payload.pop("blocks")
    target.request_payload.pop("embeds")

    result = await ExternalChannelActionService._deliver_slack(
        _service(slack_client=SimpleNamespace(post_message=post_message)),
        target,
        operation_key=ProviderOperationKey.from_seed("slack-terminal"),
        bot_token="slack-secret",
        file_storage=None,
        agent_id=None,
        session_id=None,
        authority=None,
        provider_delivery_service=None,
        resolve_runtime_target=None,
    )

    assert result.status == "delivered"
    post_call = post_message.await_args
    assert post_call is not None
    assert post_call.kwargs["reply_broadcast"] is True


@pytest.mark.asyncio
async def test_discord_terminal_thread_reply_forwards_to_exact_parent() -> None:
    """The Scheduled terminal flag reaches native exact-message forwarding."""
    create_message = AsyncMock(
        return_value=DiscordDeliveryResult(
            status="delivered",
            provider_message_key="discord:111:555",
            error_kind=None,
            error_summary=None,
        )
    )
    target = _target(
        provider=ExternalChannelProvider.DISCORD,
        operation=ExternalChannelDeliveryOperation.REPLY,
    )
    target.request_payload.update(
        {
            "conversation_scope": "thread",
            "channel_id": "444",
            "parent_channel_id": "222",
            "forward_to_parent": True,
        }
    )
    target.request_payload.pop("blocks")
    target.request_payload.pop("embeds")

    result = await ExternalChannelActionService._deliver_discord(
        _service(discord_client=_DiscordClientDelegate(create_message=create_message)),
        target,
        operation_key=ProviderOperationKey.from_seed("discord-terminal"),
        bot_token="discord-secret",
        file_storage=None,
        agent_id=None,
        authority=None,
    )

    assert result.status == "delivered"
    create_call = create_message.await_args
    assert create_call is not None
    assert create_call.kwargs["forward_to_parent"] is True
    assert create_call.kwargs["parent_channel_id"] == "222"


@pytest.mark.asyncio
async def test_discord_terminal_thread_files_forward_to_exact_parent() -> None:
    """Scheduled terminal files retain exact Thread native forwarding."""
    create_file_message = AsyncMock(
        return_value=DiscordDeliveryResult(
            status="delivered",
            provider_message_key="discord:111:555",
            error_kind=None,
            error_summary=None,
        )
    )
    target = _target(
        provider=ExternalChannelProvider.DISCORD,
        operation=ExternalChannelDeliveryOperation.REPLY,
    )
    target.request_payload.update(
        {
            "conversation_scope": "thread",
            "channel_id": "444",
            "parent_channel_id": "222",
            "forward_to_parent": True,
            "files": [
                {
                    "source": "exchange",
                    "path": "exchange://file-1",
                    "filename": "report.txt",
                    "media_type": "text/plain",
                    "expected_size": 12,
                }
            ],
        }
    )
    target.request_payload.pop("blocks")
    target.request_payload.pop("embeds")

    result = await ExternalChannelActionService._deliver_discord(
        _service(
            discord_client=_DiscordClientDelegate(
                create_file_message=create_file_message
            )
        ),
        target,
        operation_key=ProviderOperationKey.from_seed("discord-terminal-file"),
        bot_token="discord-secret",
        file_storage=None,
        agent_id=None,
        authority=cast(Any, object()),
    )

    assert result.status == "delivered"
    create_call = create_file_message.await_args
    assert create_call is not None
    assert create_call.kwargs["forward_to_parent"] is True
    assert create_call.kwargs["parent_channel_id"] == "222"


@pytest.mark.asyncio
async def test_discord_registration_accepts_bounded_embed_fields() -> None:
    """Scheduled registration fields reach the provider-bound message."""
    create_message = AsyncMock(
        return_value=DiscordDeliveryResult(
            status="delivered",
            provider_message_key="discord:111:555",
            error_kind=None,
            error_summary=None,
        )
    )
    target = _target(
        provider=ExternalChannelProvider.DISCORD,
        operation=ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
    )
    target.request_payload.update(
        {
            "control_kind": "scheduled_task_registration",
            "text": "Scheduled Task registered: Daily report",
            "task_id": "task-1",
            "delete_locator": "st1:d:task:binding:signature",
            "embeds": [
                {
                    "title": "Scheduled Task registered",
                    "color": 0x5865F2,
                    "fields": [{"name": "Schedule", "value": "At 2099-03-01"}],
                }
            ],
        }
    )
    target.request_payload.pop("blocks")

    result = await ExternalChannelActionService._deliver_discord(
        _service(discord_client=_DiscordClientDelegate(create_message=create_message)),
        target,
        operation_key=ProviderOperationKey.from_seed("discord-registration"),
        bot_token="discord-secret",
        file_storage=None,
        agent_id=None,
        authority=None,
    )

    assert result.status == "delivered"
    create_call = create_message.await_args
    assert create_call is not None
    assert create_call.kwargs["embeds"] == target.request_payload["embeds"]
    assert create_call.kwargs["components"] == [
        {
            "type": 1,
            "components": [
                {
                    "type": 2,
                    "style": 5,
                    "label": "Edit",
                    "url": (
                        "https://azents.example/w/team/agents/agent-1/"
                        "sessions/session-1?page=scheduled-tasks&"
                        "taskId=task-1&edit=1"
                    ),
                },
                {
                    "type": 2,
                    "style": 4,
                    "label": "Cancel",
                    "custom_id": "st1:d:task:binding:signature",
                },
            ],
        }
    ]


@pytest.mark.asyncio
async def test_discord_parent_file_delivery_does_not_open_sdk_session() -> None:
    """The multipart direct gap does not add an unnecessary Discord login."""
    create_file_message = AsyncMock(
        return_value=DiscordDeliveryResult(
            status="delivered",
            provider_message_key="discord:111:555",
            error_kind=None,
            error_summary=None,
        )
    )
    service = _service(
        discord_client=_DiscordClientDelegate(create_file_message=create_file_message)
    )
    target = _target(
        provider=ExternalChannelProvider.DISCORD,
        operation=ExternalChannelDeliveryOperation.REPLY,
    )
    target.request_payload["files"] = [
        {
            "source": "exchange",
            "path": "exchange://file-1",
            "filename": "report.txt",
            "media_type": "text/plain",
            "expected_size": 12,
        }
    ]
    target.request_payload.pop("embeds")

    result = await ExternalChannelActionService._deliver_discord(
        service,
        target,
        operation_key=ProviderOperationKey.from_seed("discord-file"),
        bot_token="discord-secret",
        file_storage=None,
        agent_id=None,
        authority=cast(Any, object()),
    )

    assert result.status == "delivered"
    assert cast(_OpenableDiscordClient, service.discord_client).opens == 0
    create_file_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_discord_thread_effect_reuses_one_sdk_session() -> None:
    """Thread provisioning and the adjacent message share one login."""
    ensure_thread = AsyncMock(
        return_value=DiscordDeliveryResult(
            status="delivered",
            provider_message_key="discord-thread:444",
            error_kind=None,
            error_summary=None,
        )
    )
    create_message = AsyncMock(
        return_value=DiscordDeliveryResult(
            status="delivered",
            provider_message_key="discord:111:555",
            error_kind=None,
            error_summary=None,
        )
    )
    service = _service(
        discord_client=_DiscordClientDelegate(
            ensure_thread=ensure_thread,
            create_message=create_message,
        )
    )
    target = _target(
        provider=ExternalChannelProvider.DISCORD,
        operation=ExternalChannelDeliveryOperation.REPLY,
    )
    target.request_payload.update(
        {
            "conversation_scope": "thread",
            "thread_parent_channel_id": "222",
            "thread_root_message_id": "333",
        }
    )

    result = await ExternalChannelActionService._deliver_discord(
        service,
        replace(target, resource_id=None),
        operation_key=ProviderOperationKey.from_seed("discord-thread"),
        bot_token="discord-secret",
        file_storage=None,
        agent_id=None,
        authority=None,
    )

    assert result.status == "delivered"
    assert cast(_OpenableDiscordClient, service.discord_client).opens == 1
    ensure_thread.assert_awaited_once()
    create_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_discord_thread_session_open_failure_is_an_unknown_outcome() -> None:
    """A workflow login failure retains the delivery error contract."""
    service = _service(
        discord_client=_DiscordClientDelegate(open_error=DiscordSDKUnavailable())
    )
    target = _target(
        provider=ExternalChannelProvider.DISCORD,
        operation=ExternalChannelDeliveryOperation.REPLY,
    )
    target.request_payload.update(
        {
            "conversation_scope": "thread",
            "thread_parent_channel_id": "222",
            "thread_root_message_id": "333",
        }
    )

    result = await ExternalChannelActionService._deliver_discord(
        service,
        replace(target, resource_id=None),
        operation_key=ProviderOperationKey.from_seed("discord-thread-open"),
        bot_token="discord-secret",
        file_storage=None,
        agent_id=None,
        authority=None,
    )

    assert result.status == "unknown"
    assert result.error_kind == "provider_ambiguous"
