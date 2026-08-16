"""Discord public SDK delivery and G2 multipart transport tests."""

import contextlib
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import cast

import httpx
import pytest

from azents.services.external_channel.discord_delivery import (
    DiscordDeliveryClient,
    DiscordDeliveryResult,
    DiscordFileMessageTransport,
    DiscordOutboundFile,
    DiscordOutboundFileContentError,
)
from azents.services.external_channel.discord_sdk import (
    DiscordSDKMessage,
    DiscordSDKPermissionDenied,
    DiscordSDKSession,
    DiscordSDKThread,
    DiscordSDKUnavailable,
)
from azents.services.external_channel.provider_effect import ProviderOperationKey


@dataclass
class _SDKSession:
    thread: DiscordSDKThread | None = None
    created_thread: DiscordSDKThread | None = None
    message: DiscordSDKMessage = field(
        default_factory=lambda: DiscordSDKMessage("555", "333", "111")
    )
    forwarded_message: DiscordSDKMessage = field(
        default_factory=lambda: DiscordSDKMessage("556", "222", "111")
    )
    create_thread_error: Exception | None = None
    forward_message_error: Exception | None = None
    calls: list[tuple[str, object]] = field(default_factory=list)

    async def fetch_root_thread(self, **values: object) -> DiscordSDKThread | None:
        self.calls.append(("fetch_root_thread", values))
        return self.thread

    async def create_thread(self, **values: object) -> DiscordSDKThread:
        self.calls.append(("create_thread", values))
        if self.create_thread_error is not None:
            self.thread = self.created_thread
            raise self.create_thread_error
        assert self.created_thread is not None
        return self.created_thread

    async def fetch_thread(self, **values: object) -> DiscordSDKThread:
        self.calls.append(("fetch_thread", values))
        assert self.thread is not None
        return self.thread

    async def update_thread_name(self, **values: object) -> DiscordSDKThread:
        self.calls.append(("update_thread_name", values))
        assert self.thread is not None
        name = values["name"]
        assert isinstance(name, str)
        return DiscordSDKThread(
            self.thread.thread_id,
            self.thread.parent_id,
            self.thread.guild_id,
            name,
        )

    async def create_message(self, **values: object) -> DiscordSDKMessage:
        self.calls.append(("create_message", values))
        return self.message

    async def forward_message(self, **values: object) -> DiscordSDKMessage:
        self.calls.append(("forward_message", values))
        if self.forward_message_error is not None:
            raise self.forward_message_error
        return self.forwarded_message

    async def update_message(self, **values: object) -> DiscordSDKMessage:
        self.calls.append(("update_message", values))
        return self.message

    async def delete_message(self, **values: object) -> None:
        self.calls.append(("delete_message", values))


@dataclass
class _SDKFactory:
    session: _SDKSession
    opens: int = 0

    @contextlib.asynccontextmanager
    async def open(self, *, bot_token: str) -> AsyncIterator[DiscordSDKSession]:
        assert bot_token == "discord-secret"
        self.opens += 1
        yield cast(DiscordSDKSession, self.session)


@dataclass
class _FileTransport:
    result: DiscordDeliveryResult = field(
        default_factory=lambda: DiscordDeliveryResult(
            "delivered", "discord:111:777", None, None
        )
    )
    calls: list[dict[str, object]] = field(default_factory=list)

    async def create_file_message(self, **values: object) -> DiscordDeliveryResult:
        self.calls.append(values)
        return self.result


def _client(session: _SDKSession) -> tuple[DiscordDeliveryClient, _FileTransport]:
    files = _FileTransport()
    return DiscordDeliveryClient(_SDKFactory(session), files), files


@pytest.mark.asyncio
async def test_create_message_forwards_nonce_and_rich_projection_to_sdk() -> None:
    """Text delivery uses one public SDK operation with the stable nonce."""
    session = _SDKSession()
    client, _ = _client(session)
    operation_key = ProviderOperationKey.from_seed("delivery-1")
    components: list[dict[str, object]] = [{"type": 1, "components": []}]
    embeds: list[dict[str, object]] = [{"description": "progress"}]

    result = await client.create_message(
        bot_token="discord-secret",
        guild_id="111",
        channel_id="333",
        content="Reply",
        operation_key=operation_key,
        components=components,
        embeds=embeds,
    )

    assert result.status == "delivered"
    assert result.provider_message_key == "discord:111:555"
    assert session.calls == [
        (
            "create_message",
            {
                "guild_id": "111",
                "channel_id": "333",
                "content": "Reply",
                "nonce": operation_key.value,
                "components": components,
                "embeds": embeds,
            },
        )
    ]


@pytest.mark.asyncio
async def test_create_message_can_forward_the_exact_created_message() -> None:
    """The opt-in flow creates first and forwards the typed SDK result second."""
    session = _SDKSession()
    client, _ = _client(session)
    operation_key = ProviderOperationKey.from_seed("terminal-part-1")

    result = await client.create_message(
        bot_token="discord-secret",
        guild_id="111",
        channel_id="333",
        content="Terminal result",
        operation_key=operation_key,
        forward_to_parent=True,
        parent_channel_id="222",
    )

    assert result == DiscordDeliveryResult(
        "delivered",
        "discord:111:555",
        None,
        None,
    )
    assert session.calls == [
        (
            "create_message",
            {
                "guild_id": "111",
                "channel_id": "333",
                "content": "Terminal result",
                "nonce": operation_key.value,
                "components": None,
                "embeds": None,
            },
        ),
        (
            "forward_message",
            {
                "message": session.message,
                "destination_channel_id": "222",
            },
        ),
    ]


@pytest.mark.asyncio
async def test_forward_failure_preserves_created_thread_message_identity() -> None:
    """Parent surfacing failure retains the successful Thread message key."""
    session = _SDKSession(
        forward_message_error=DiscordSDKUnavailable(),
    )
    client, _ = _client(session)

    result = await client.create_message(
        bot_token="discord-secret",
        guild_id="111",
        channel_id="333",
        content="Terminal result",
        operation_key=ProviderOperationKey.from_seed("terminal-part-2"),
        forward_to_parent=True,
        parent_channel_id="222",
    )

    assert result.status == "unknown"
    assert result.provider_message_key == "discord:111:555"
    assert result.error_kind == "provider_ambiguous"


@pytest.mark.asyncio
async def test_forward_permission_failure_keeps_classification_and_identity() -> None:
    """A native forward denial remains failed without hiding the Thread message."""
    session = _SDKSession(
        forward_message_error=DiscordSDKPermissionDenied(),
    )
    client, _ = _client(session)

    result = await client.create_message(
        bot_token="discord-secret",
        guild_id="111",
        channel_id="333",
        content="Terminal result",
        operation_key=ProviderOperationKey.from_seed("terminal-part-permission"),
        forward_to_parent=True,
        parent_channel_id="222",
    )

    assert result.status == "failed"
    assert result.provider_message_key == "discord:111:555"
    assert result.error_kind == "permission_denied"


@pytest.mark.asyncio
async def test_forward_requires_an_explicit_parent_before_create() -> None:
    """An incomplete forwarding payload cannot create the Thread message."""
    session = _SDKSession()
    client, _ = _client(session)

    result = await client.create_message(
        bot_token="discord-secret",
        guild_id="111",
        channel_id="333",
        content="Terminal result",
        operation_key=ProviderOperationKey.from_seed("terminal-part-3"),
        forward_to_parent=True,
    )

    assert result.status == "failed"
    assert result.error_kind == "provider_rejected"
    assert session.calls == []


@pytest.mark.asyncio
async def test_ensure_thread_creates_or_reuses_one_sdk_thread() -> None:
    """Thread provisioning reads once and creates only when absent."""
    created = DiscordSDKThread("444", "222", "111", "Azents")
    session = _SDKSession(created_thread=created)
    client, _ = _client(session)

    result = await client.ensure_thread(
        bot_token="discord-secret",
        guild_id="111",
        parent_channel_id="222",
        root_message_id="333",
        name=None,
    )

    assert result == DiscordDeliveryResult(
        "delivered", "discord-thread:444", None, None, "Azents"
    )
    assert [name for name, _ in session.calls] == ["fetch_root_thread", "create_thread"]

    session.calls.clear()
    session.thread = created
    reused = await client.ensure_thread(
        bot_token="discord-secret",
        guild_id="111",
        parent_channel_id="222",
        root_message_id="333",
        name=None,
    )
    assert reused.provider_message_key == "discord-thread:444"
    assert [name for name, _ in session.calls] == ["fetch_root_thread"]


@pytest.mark.asyncio
async def test_ensure_thread_reconciles_ambiguous_sdk_create_without_replay() -> None:
    """An ambiguous create performs one read reconciliation and no second create."""
    created = DiscordSDKThread("444", "222", "111", "Azents")
    session = _SDKSession(
        created_thread=created,
        create_thread_error=DiscordSDKUnavailable(),
    )
    client, _ = _client(session)

    result = await client.ensure_thread(
        bot_token="discord-secret",
        guild_id="111",
        parent_channel_id="222",
        root_message_id="333",
        name=None,
    )

    assert result.provider_message_key == "discord-thread:444"
    assert [name for name, _ in session.calls] == [
        "fetch_root_thread",
        "create_thread",
        "fetch_root_thread",
    ]


@pytest.mark.asyncio
async def test_thread_title_read_update_and_message_delete_use_sdk() -> None:
    """Title and exact message mutations remain one-attempt SDK operations."""
    session = _SDKSession(thread=DiscordSDKThread("444", "222", "111", "Old"))
    client, _ = _client(session)

    title = await client.read_thread_title(
        bot_token="discord-secret", guild_id="111", channel_id="444"
    )
    updated = await client.update_thread_title(
        bot_token="discord-secret",
        guild_id="111",
        channel_id="444",
        name="  Incident   response  ",
    )
    deleted = await client.delete_message(
        bot_token="discord-secret",
        guild_id="111",
        channel_id="333",
        message_id="555",
    )

    assert title.status == "present" and title.name == "Old"
    assert updated.status == "delivered"
    assert deleted.status == "delivered"
    assert [name for name, _ in session.calls] == [
        "fetch_thread",
        "update_thread_name",
        "delete_message",
    ]


@pytest.mark.asyncio
async def test_bound_delivery_workflow_reuses_one_sdk_factory_open() -> None:
    """Several delivery methods share one authenticated SDK factory lifecycle."""
    session = _SDKSession(thread=DiscordSDKThread("444", "222", "111", "Old"))
    factory = _SDKFactory(session)
    client = DiscordDeliveryClient(factory, _FileTransport())

    async with client.open(bot_token="discord-secret") as workflow:
        await workflow.read_thread_title(
            bot_token="discord-secret",
            guild_id="111",
            channel_id="444",
        )
        await workflow.create_message(
            bot_token="discord-secret",
            guild_id="111",
            channel_id="333",
            content="Reply",
            operation_key=ProviderOperationKey.from_seed("delivery-workflow"),
        )

    assert factory.opens == 1
    assert [name for name, _ in session.calls] == [
        "fetch_thread",
        "create_message",
    ]


@pytest.mark.asyncio
async def test_file_message_delegates_only_to_g2_transport() -> None:
    """Streaming file delivery bypasses the SDK only through exact gap G2."""
    session = _SDKSession()
    client, transport = _client(session)

    result = await client.create_file_message(
        bot_token="discord-secret",
        guild_id="111",
        channel_id="333",
        content="file",
        files=(),
        operation_key=ProviderOperationKey.from_seed("file-1"),
    )

    assert result.status == "delivered"
    assert session.calls == []
    assert transport.calls[0]["nonce"] == ProviderOperationKey.from_seed("file-1").value


@pytest.mark.asyncio
async def test_g2_multipart_stream_preserves_exact_length_and_nonce() -> None:
    """The approved direct gap sends exact-length streamed bytes once."""
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        body = await request.aread()
        assert request.headers["Content-Length"] == str(len(body))
        payload = body.split(b"\r\n\r\n", 1)[1].split(b"\r\n", 1)[0]
        assert json.loads(payload)["nonce"] == "nonce-1"
        assert b"abc" in body
        return httpx.Response(200, json={"id": "777", "channel_id": "333"})

    async def content() -> AsyncIterator[bytes]:
        yield b"abc"

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await DiscordFileMessageTransport(http).create_file_message(
            bot_token="discord-secret",
            guild_id="111",
            channel_id="333",
            content="file",
            files=(DiscordOutboundFile("a.txt", "text/plain", 3, content),),
            nonce="nonce-1",
        )

    assert result.provider_message_key == "discord:111:777"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_g2_midstream_source_failure_is_ambiguous() -> None:
    """A source failure after request start cannot be reported as no delivery."""

    async def handler(request: httpx.Request) -> httpx.Response:
        await request.aread()
        raise AssertionError("The stream failure should abort response handling.")

    async def content() -> AsyncIterator[bytes]:
        yield b"a"
        raise DiscordOutboundFileContentError

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await DiscordFileMessageTransport(http).create_file_message(
            bot_token="discord-secret",
            guild_id="111",
            channel_id="333",
            content="file",
            files=(DiscordOutboundFile("a.txt", "text/plain", 2, content),),
            nonce="nonce-1",
        )

    assert result.status == "unknown"
    assert result.error_kind == "provider_ambiguous"
