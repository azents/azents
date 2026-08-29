"""Tests for the high-level discord.py Gateway integration boundary."""

import asyncio
import hashlib
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from azents.repos.external_channel.data import DiscordGatewayTypingTarget
from azents.services.external_channel import discord_gateway
from azents.services.external_channel.discord_events import DiscordGatewayMessageEvent
from azents.services.external_channel.discord_gateway import (
    DISCORD_GATEWAY_INTENTS,
    DiscordGatewayClient,
    DiscordGatewayCredentialError,
    DiscordGatewayError,
    DiscordGatewayTerminalError,
    _DiscordLibraryClient,
)

_CALLBACK_BASE_URL = "https://callbacks.example/"
_CALLBACK_SELECTOR = "opaque-selector"
_CALLBACK_SELECTOR_HASH = hashlib.sha256(_CALLBACK_SELECTOR.encode()).hexdigest()


def _guild(*, guild_id: int = 300) -> MagicMock:
    guild = MagicMock(spec=discord.Guild)
    guild.id = guild_id
    return guild


def _channel(*, channel_id: int = 200, guild_id: int = 300) -> MagicMock:
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = channel_id
    channel.guild = _guild(guild_id=guild_id)
    channel.name = "general"
    return channel


def _message(
    *,
    channel: MagicMock | None = None,
    guild_id: int = 300,
) -> MagicMock:
    resolved_channel = channel or _channel(guild_id=guild_id)
    message = MagicMock(spec=discord.Message)
    message.id = 100
    message.guild = resolved_channel.guild
    message.channel = resolved_channel
    message.content = "hello"
    message.created_at = discord.utils.utcnow()
    message.author = MagicMock(spec=discord.User)
    message.author.id = 400
    message.author.name = "participant"
    message.author.global_name = None
    message.author.bot = False
    message.author.system = False
    message.mentions = []
    message.role_mentions = []
    message.attachments = []
    message.embeds = []
    return message


def _library_client(
    *,
    handle_event: AsyncMock | None = None,
    handle_lifecycle: AsyncMock | None = None,
) -> _DiscordLibraryClient:
    return _DiscordLibraryClient(
        target_guild_id=300,
        interactions_callback_base_url=_CALLBACK_BASE_URL,
        interactions_callback_selector_hash=_CALLBACK_SELECTOR_HASH,
        connected_bot_user_id="900",
        handle_event=handle_event or AsyncMock(),
        handle_lifecycle=handle_lifecycle or AsyncMock(),
    )


def _typing_target(
    *,
    channel_id: str = "200",
    work_cycle_ids: tuple[str, ...] = ("work-1",),
) -> DiscordGatewayTypingTarget:
    return DiscordGatewayTypingTarget(
        guild_id="300",
        channel_id=channel_id,
        work_cycle_ids=work_cycle_ids,
    )


def _install_ready_gateway_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    release: asyncio.Event,
    messageable: MagicMock,
) -> list[tuple[int, int | None]]:
    partial_messageable_calls: list[tuple[int, int | None]] = []

    async def start(
        self: _DiscordLibraryClient,
        token: str,
        *,
        reconnect: bool = True,
    ) -> None:
        del token, reconnect
        await self.on_ready()
        await release.wait()

    async def close(self: _DiscordLibraryClient) -> None:
        del self

    def get_partial_messageable(
        self: _DiscordLibraryClient,
        channel_id: int,
        *,
        guild_id: int | None = None,
    ) -> MagicMock:
        del self
        partial_messageable_calls.append((channel_id, guild_id))
        return messageable

    monkeypatch.setattr(_DiscordLibraryClient, "start", start)
    monkeypatch.setattr(_DiscordLibraryClient, "close", close)
    monkeypatch.setattr(
        _DiscordLibraryClient,
        "get_partial_messageable",
        get_partial_messageable,
    )
    return partial_messageable_calls


def test_library_client_requests_required_intents() -> None:
    """Only Guild message and message-content events are requested."""
    client = _library_client()

    assert client.intents.value == DISCORD_GATEWAY_INTENTS
    assert client.intents.guilds is True
    assert client.intents.guild_messages is True
    assert client.intents.message_content is True
    assert client.intents.members is False


@pytest.mark.asyncio
async def test_setup_hook_accepts_exact_interaction_endpoint() -> None:
    """Gateway login accepts only the current callback selector authority."""
    client = _library_client()
    application = MagicMock(spec=discord.AppInfo)
    application.interactions_endpoint_url = (
        f"{_CALLBACK_BASE_URL}external-channel/v1/discord/interactions/"
        f"{_CALLBACK_SELECTOR}"
    )
    client._application = application

    await client.setup_hook()


@pytest.mark.asyncio
async def test_setup_hook_rejects_missing_interaction_endpoint() -> None:
    """Provider callback removal becomes a terminal reconnect requirement."""
    client = _library_client()
    application = MagicMock(spec=discord.AppInfo)
    application.interactions_endpoint_url = None
    client._application = application

    with pytest.raises(DiscordGatewayTerminalError) as raised:
        await client.setup_hook()

    assert raised.value.reason == "interaction_endpoint_drift"


@pytest.mark.asyncio
async def test_message_callback_emits_typed_sdk_event() -> None:
    """The public on_message callback forwards the SDK Message unchanged."""
    handler = AsyncMock()
    client = _library_client(handle_event=handler)
    channel = _channel()
    message = _message(channel=channel)

    await client.on_message(message)

    await_args = handler.await_args
    assert await_args is not None
    event = await_args.args[0]
    assert isinstance(event, DiscordGatewayMessageEvent)
    assert event.event_type == "message_create"
    assert event.guild_id == "300"
    assert event.channel_id == "200"
    assert event.message["id"] == "100"
    assert event.message["content"] == "hello"


@pytest.mark.asyncio
async def test_lifecycle_callbacks_emit_typed_sdk_state_in_order() -> None:
    """Ready, disconnect, and Resume use the serialized SDK callback boundary."""
    lifecycle = AsyncMock()
    client = _library_client(handle_lifecycle=lifecycle)

    await client.on_ready()
    await client.on_disconnect()
    await client.on_resumed()

    assert [call.args[0] for call in lifecycle.await_args_list] == [
        "ready",
        "disconnected",
        "resumed",
    ]


@pytest.mark.asyncio
async def test_cross_guild_callbacks_are_ignored() -> None:
    handler = AsyncMock()
    client = _library_client(handle_event=handler)

    await client.on_message(_message(guild_id=301))

    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_handler_failure_closes_client_and_is_retained() -> None:
    """Admission failures stop the SDK connection instead of being logged and lost."""
    error = DiscordGatewayError("admission failed")
    client = _library_client(handle_event=AsyncMock(side_effect=error))
    client.close = AsyncMock()

    await client.on_message(_message())

    assert client.event_error is error
    client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_lifecycle_failure_closes_client_and_is_retained() -> None:
    """Lease-fenced health failures stop the SDK lifecycle."""
    error = DiscordGatewayError("lease lost")
    client = _library_client(handle_lifecycle=AsyncMock(side_effect=error))
    client.close = AsyncMock()

    await client.on_ready()

    assert client.event_error is error
    client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_runner_uses_public_start_with_sdk_reconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Discovery, heartbeat, reconnect, and Resume stay inside Client.start."""
    started: list[tuple[str, bool]] = []

    async def start(
        self: _DiscordLibraryClient,
        token: str,
        *,
        reconnect: bool = True,
    ) -> None:
        del self
        started.append((token, reconnect))

    async def close(self: _DiscordLibraryClient) -> None:
        del self

    monkeypatch.setattr(_DiscordLibraryClient, "start", start)
    monkeypatch.setattr(_DiscordLibraryClient, "close", close)

    with pytest.raises(DiscordGatewayError, match="stopped unexpectedly"):
        await DiscordGatewayClient().run_connection(
            bot_token="redacted-token",
            target_guild_id="300",
            interactions_callback_base_url=_CALLBACK_BASE_URL,
            interactions_callback_selector_hash=_CALLBACK_SELECTOR_HASH,
            handle_event=AsyncMock(),
            handle_lifecycle=AsyncMock(),
            load_typing_targets=AsyncMock(return_value=()),
        )

    assert started == [("redacted-token", True)]


@pytest.mark.asyncio
async def test_runner_wraps_uncontrolled_callback_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Typed callback failures enter the manager's controlled gap path."""
    failure = RuntimeError("private failure detail")

    async def start(
        self: _DiscordLibraryClient,
        token: str,
        *,
        reconnect: bool = True,
    ) -> None:
        del token, reconnect
        self.event_error = failure

    async def close(self: _DiscordLibraryClient) -> None:
        del self

    monkeypatch.setattr(_DiscordLibraryClient, "start", start)
    monkeypatch.setattr(_DiscordLibraryClient, "close", close)

    with pytest.raises(
        DiscordGatewayError,
        match="typed callback processing failed",
    ) as raised:
        await DiscordGatewayClient().run_connection(
            bot_token="redacted-token",
            target_guild_id="300",
            interactions_callback_base_url=_CALLBACK_BASE_URL,
            interactions_callback_selector_hash=_CALLBACK_SELECTOR_HASH,
            handle_event=AsyncMock(),
            handle_lifecycle=AsyncMock(),
            load_typing_targets=AsyncMock(return_value=()),
        )

    assert raised.value.__cause__ is failure


@pytest.mark.asyncio
async def test_runner_preserves_controlled_callback_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lease and admission errors retain their controlled subtype."""
    failure = DiscordGatewayError("controlled failure")

    async def start(
        self: _DiscordLibraryClient,
        token: str,
        *,
        reconnect: bool = True,
    ) -> None:
        del token, reconnect
        self.event_error = failure

    async def close(self: _DiscordLibraryClient) -> None:
        del self

    monkeypatch.setattr(_DiscordLibraryClient, "start", start)
    monkeypatch.setattr(_DiscordLibraryClient, "close", close)

    with pytest.raises(DiscordGatewayError) as raised:
        await DiscordGatewayClient().run_connection(
            bot_token="redacted-token",
            target_guild_id="300",
            interactions_callback_base_url=_CALLBACK_BASE_URL,
            interactions_callback_selector_hash=_CALLBACK_SELECTOR_HASH,
            handle_event=AsyncMock(),
            handle_lifecycle=AsyncMock(),
            load_typing_targets=AsyncMock(return_value=()),
        )

    assert raised.value is failure


@pytest.mark.asyncio
async def test_runner_classifies_public_login_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def start(
        self: _DiscordLibraryClient,
        token: str,
        *,
        reconnect: bool = True,
    ) -> None:
        del self, token, reconnect
        raise discord.LoginFailure("rejected")

    async def close(self: _DiscordLibraryClient) -> None:
        del self

    monkeypatch.setattr(_DiscordLibraryClient, "start", start)
    monkeypatch.setattr(_DiscordLibraryClient, "close", close)

    with pytest.raises(DiscordGatewayCredentialError):
        await DiscordGatewayClient().run_connection(
            bot_token="redacted-token",
            target_guild_id="300",
            interactions_callback_base_url=_CALLBACK_BASE_URL,
            interactions_callback_selector_hash=_CALLBACK_SELECTOR_HASH,
            handle_event=AsyncMock(),
            handle_lifecycle=AsyncMock(),
            load_typing_targets=AsyncMock(return_value=()),
        )


@pytest.mark.asyncio
async def test_runner_preserves_terminal_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = DiscordGatewayTerminalError("gateway_connection_rejected")

    async def start(
        self: _DiscordLibraryClient,
        token: str,
        *,
        reconnect: bool = True,
    ) -> None:
        del self, token, reconnect
        raise failure

    async def close(self: _DiscordLibraryClient) -> None:
        del self

    monkeypatch.setattr(_DiscordLibraryClient, "start", start)
    monkeypatch.setattr(_DiscordLibraryClient, "close", close)

    with pytest.raises(DiscordGatewayTerminalError) as raised:
        await DiscordGatewayClient().run_connection(
            bot_token="redacted-token",
            target_guild_id="300",
            interactions_callback_base_url=_CALLBACK_BASE_URL,
            interactions_callback_selector_hash=_CALLBACK_SELECTOR_HASH,
            handle_event=AsyncMock(),
            handle_lifecycle=AsyncMock(),
            load_typing_targets=AsyncMock(return_value=()),
        )

    assert raised.value.reason == "gateway_connection_rejected"


@pytest.mark.asyncio
async def test_runner_rejects_non_numeric_guild_identity() -> None:
    with pytest.raises(DiscordGatewayError, match="Guild identity"):
        await DiscordGatewayClient().run_connection(
            bot_token="redacted-token",
            target_guild_id="not-a-snowflake",
            interactions_callback_base_url=_CALLBACK_BASE_URL,
            interactions_callback_selector_hash=_CALLBACK_SELECTOR_HASH,
            handle_event=AsyncMock(),
            handle_lifecycle=AsyncMock(),
            load_typing_targets=AsyncMock(return_value=()),
        )


@pytest.mark.asyncio
async def test_runner_starts_and_renews_typing_with_public_messageable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One active target renews through the public partial Messageable API."""
    first_typing = asyncio.Event()
    renewed_typing = asyncio.Event()
    release = asyncio.Event()
    typing_calls = 0
    messageable = MagicMock()

    async def typing() -> None:
        nonlocal typing_calls
        typing_calls += 1
        if typing_calls == 1:
            first_typing.set()
        if typing_calls == 2:
            renewed_typing.set()

    messageable.typing = typing
    partial_calls = _install_ready_gateway_client(
        monkeypatch,
        release=release,
        messageable=messageable,
    )
    monkeypatch.setattr(discord_gateway, "_TYPING_RENEW_INTERVAL_SECONDS", 0.001)

    task = asyncio.create_task(
        DiscordGatewayClient().run_connection(
            bot_token="redacted-token",
            target_guild_id="300",
            interactions_callback_base_url=_CALLBACK_BASE_URL,
            interactions_callback_selector_hash=_CALLBACK_SELECTOR_HASH,
            handle_event=AsyncMock(),
            handle_lifecycle=AsyncMock(),
            load_typing_targets=AsyncMock(return_value=(_typing_target(),)),
        )
    )

    await first_typing.wait()
    await renewed_typing.wait()

    assert partial_calls == [(200, 300)]
    assert typing_calls >= 2

    release.set()
    with pytest.raises(DiscordGatewayError, match="stopped unexpectedly"):
        await task


@pytest.mark.asyncio
async def test_runner_removes_typing_task_when_target_disappears(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Target removal cancels its outstanding renewal rather than waiting to expire."""
    typing_started = asyncio.Event()
    typing_cancelled = asyncio.Event()
    second_load = asyncio.Event()
    release = asyncio.Event()
    current_targets: tuple[DiscordGatewayTypingTarget, ...] = (_typing_target(),)
    load_count = 0
    messageable = MagicMock()

    async def typing() -> None:
        typing_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            typing_cancelled.set()
            raise

    async def load_typing_targets() -> tuple[DiscordGatewayTypingTarget, ...]:
        nonlocal load_count
        load_count += 1
        if load_count == 2:
            second_load.set()
        return current_targets

    messageable.typing = typing
    _install_ready_gateway_client(
        monkeypatch,
        release=release,
        messageable=messageable,
    )
    monkeypatch.setattr(discord_gateway, "_TYPING_RECONCILE_INTERVAL_SECONDS", 0.001)
    task = asyncio.create_task(
        DiscordGatewayClient().run_connection(
            bot_token="redacted-token",
            target_guild_id="300",
            interactions_callback_base_url=_CALLBACK_BASE_URL,
            interactions_callback_selector_hash=_CALLBACK_SELECTOR_HASH,
            handle_event=AsyncMock(),
            handle_lifecycle=AsyncMock(),
            load_typing_targets=load_typing_targets,
        )
    )

    await typing_started.wait()
    current_targets = ()
    await second_load.wait()
    await typing_cancelled.wait()
    assert not task.done()

    release.set()
    with pytest.raises(DiscordGatewayError, match="stopped unexpectedly"):
        await task


@pytest.mark.asyncio
async def test_runner_retains_one_typing_task_when_work_cycles_share_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Changing contributing Work cycles retains the existing channel task."""
    typing_started = asyncio.Event()
    typing_cancelled = asyncio.Event()
    second_load = asyncio.Event()
    release = asyncio.Event()
    current_targets: tuple[DiscordGatewayTypingTarget, ...] = (_typing_target(),)
    load_count = 0
    messageable = MagicMock()

    async def typing() -> None:
        typing_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            typing_cancelled.set()
            raise

    async def load_typing_targets() -> tuple[DiscordGatewayTypingTarget, ...]:
        nonlocal load_count
        load_count += 1
        if load_count == 2:
            second_load.set()
        return current_targets

    messageable.typing = typing
    partial_calls = _install_ready_gateway_client(
        monkeypatch,
        release=release,
        messageable=messageable,
    )
    monkeypatch.setattr(discord_gateway, "_TYPING_RECONCILE_INTERVAL_SECONDS", 0.001)
    task = asyncio.create_task(
        DiscordGatewayClient().run_connection(
            bot_token="redacted-token",
            target_guild_id="300",
            interactions_callback_base_url=_CALLBACK_BASE_URL,
            interactions_callback_selector_hash=_CALLBACK_SELECTOR_HASH,
            handle_event=AsyncMock(),
            handle_lifecycle=AsyncMock(),
            load_typing_targets=load_typing_targets,
        )
    )

    await typing_started.wait()
    current_targets = (_typing_target(work_cycle_ids=("work-1", "work-2")),)
    await second_load.wait()

    assert partial_calls == [(200, 300)]
    assert not typing_cancelled.is_set()

    release.set()
    with pytest.raises(DiscordGatewayError, match="stopped unexpectedly"):
        await task
    assert typing_cancelled.is_set()


@pytest.mark.asyncio
async def test_runner_stops_sdk_lifecycle_when_target_source_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fenced target-source failure closes the client and reaches the manager."""
    release = asyncio.Event()
    closed = asyncio.Event()
    failure = DiscordGatewayError("lease lost")

    async def start(
        self: _DiscordLibraryClient,
        token: str,
        *,
        reconnect: bool = True,
    ) -> None:
        del token, reconnect
        await self.on_ready()
        await release.wait()

    async def close(self: _DiscordLibraryClient) -> None:
        del self
        closed.set()
        release.set()

    async def load_typing_targets() -> tuple[DiscordGatewayTypingTarget, ...]:
        raise failure

    monkeypatch.setattr(_DiscordLibraryClient, "start", start)
    monkeypatch.setattr(_DiscordLibraryClient, "close", close)

    with pytest.raises(DiscordGatewayError) as raised:
        await DiscordGatewayClient().run_connection(
            bot_token="redacted-token",
            target_guild_id="300",
            interactions_callback_base_url=_CALLBACK_BASE_URL,
            interactions_callback_selector_hash=_CALLBACK_SELECTOR_HASH,
            handle_event=AsyncMock(),
            handle_lifecycle=AsyncMock(),
            load_typing_targets=load_typing_targets,
        )

    assert raised.value is failure
    assert closed.is_set()


@pytest.mark.asyncio
async def test_runner_isolates_provider_typing_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A temporary provider failure retries without terminating the Gateway."""
    provider_failure = asyncio.Event()
    provider_retried = asyncio.Event()
    release = asyncio.Event()
    keep_running = asyncio.Event()
    typing_attempts = 0
    messageable = MagicMock()

    async def typing() -> None:
        nonlocal typing_attempts
        typing_attempts += 1
        if typing_attempts == 1:
            provider_failure.set()
            raise OSError("provider transport unavailable")
        provider_retried.set()
        await keep_running.wait()

    messageable.typing = typing
    _install_ready_gateway_client(
        monkeypatch,
        release=release,
        messageable=messageable,
    )
    monkeypatch.setattr(discord_gateway, "_TYPING_RETRY_INTERVAL_SECONDS", 0.001)
    task = asyncio.create_task(
        DiscordGatewayClient().run_connection(
            bot_token="redacted-token",
            target_guild_id="300",
            interactions_callback_base_url=_CALLBACK_BASE_URL,
            interactions_callback_selector_hash=_CALLBACK_SELECTOR_HASH,
            handle_event=AsyncMock(),
            handle_lifecycle=AsyncMock(),
            load_typing_targets=AsyncMock(return_value=(_typing_target(),)),
        )
    )

    await provider_failure.wait()
    await provider_retried.wait()
    assert not task.done()

    release.set()
    with pytest.raises(DiscordGatewayError, match="stopped unexpectedly"):
        await task


@pytest.mark.asyncio
async def test_runner_cancels_typing_tasks_during_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SDK shutdown joins the typing renewal task before the runner returns."""
    typing_started = asyncio.Event()
    typing_cancelled = asyncio.Event()
    release = asyncio.Event()
    messageable = MagicMock()

    async def typing() -> None:
        typing_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            typing_cancelled.set()
            raise

    messageable.typing = typing
    _install_ready_gateway_client(
        monkeypatch,
        release=release,
        messageable=messageable,
    )
    task = asyncio.create_task(
        DiscordGatewayClient().run_connection(
            bot_token="redacted-token",
            target_guild_id="300",
            interactions_callback_base_url=_CALLBACK_BASE_URL,
            interactions_callback_selector_hash=_CALLBACK_SELECTOR_HASH,
            handle_event=AsyncMock(),
            handle_lifecycle=AsyncMock(),
            load_typing_targets=AsyncMock(return_value=(_typing_target(),)),
        )
    )

    await typing_started.wait()
    release.set()
    with pytest.raises(DiscordGatewayError, match="stopped unexpectedly"):
        await task
    assert typing_cancelled.is_set()
