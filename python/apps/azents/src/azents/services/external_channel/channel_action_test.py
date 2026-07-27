"""Channel Action commit-before-delivery orchestration tests."""

import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast

import pytest
from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.enums import (
    ExchangeFileOrigin,
    ExchangeFileProvenanceKind,
    ExchangeFileStatus,
    ExternalChannelActionMode,
    ExternalChannelDeliveryOperation,
    ExternalChannelDeliveryStatus,
    ExternalChannelProvider,
    ExternalChannelWorkStatus,
)
from azents.core.external_channel_file import (
    ExternalChannelOutboundFileManifest,
    ExternalChannelOutboundFileSource,
)
from azents.rdb.session import SessionManager
from azents.repos.exchange_file.data import ExchangeFile
from azents.repos.external_channel.work import ExternalChannelWorkRepository
from azents.repos.external_channel.work_data import (
    ChannelActionCommit,
    ChannelDeliveryTarget,
    ChannelWorkDelivery,
)
from azents.services.exchange_file import ExchangeFileDownload, ExchangeFileService
from azents.services.external_channel.channel_action import (
    ExternalChannelActionService,
)
from azents.services.external_channel.credentials import ExternalChannelCredentialsCodec
from azents.services.external_channel.data import SlackConnectionCredentials
from azents.services.external_channel.discord_delivery import (
    DiscordDeliveryClient,
    DiscordDeliveryResult,
    DiscordOutboundFile,
)
from azents.services.external_channel.slack_events import (
    SlackControlMessageResult,
    SlackConversationClient,
    SlackOutboundFile,
)
from azents.services.file_storage import FileStorage
from azents.services.session_resource_authority import SessionResourceAuthority


def _at(second: int) -> datetime.datetime:
    return datetime.datetime(2026, 7, 22, 0, 0, second, tzinfo=datetime.UTC)


class _SessionDouble:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def commit(self) -> None:
        self.events.append("commit")


class _RepositoryDouble:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.recovery_delivery_ids: list[str | None] = []
        self.finished: list[
            tuple[ExternalChannelDeliveryStatus, str | None, str | None]
        ] = []
        self.target = ChannelDeliveryTarget(
            delivery_attempt_id="delivery-1",
            operation=ExternalChannelDeliveryOperation.REPLY,
            status=ExternalChannelDeliveryStatus.PENDING,
            binding_id="binding-1",
            connection_id="connection-1",
            provider=ExternalChannelProvider.SLACK,
            encrypted_credentials="ciphertext",
            provider_tenant_id="T1",
            capabilities=None,
            agent_name=None,
            agent_avatar=None,
            request_payload={
                "channel_id": "C1",
                "thread_ts": "1.000001",
                "text": "Reply",
            },
        )

    async def get_delivery_target(
        self,
        session: AsyncSession,
        *,
        delivery_attempt_id: str,
    ) -> ChannelDeliveryTarget | None:
        del session
        if delivery_attempt_id == "delivery-1":
            return self.target
        if delivery_attempt_id == "delivery-2":
            payload = dict(self.target.request_payload)
            payload.pop("provider_message_key", None)
            return self.target.model_copy(
                update={
                    "delivery_attempt_id": "delivery-2",
                    "operation": ExternalChannelDeliveryOperation.PROGRESS_CREATE,
                    "request_payload": payload,
                }
            )
        raise AssertionError("Unexpected delivery identity")

    async def start_delivery(
        self,
        session: AsyncSession,
        *,
        delivery_attempt_id: str,
        now: datetime.datetime,
    ) -> bool:
        del session, delivery_attempt_id, now
        self.events.append("start")
        return True

    async def finish_delivery(
        self,
        session: AsyncSession,
        *,
        delivery_attempt_id: str,
        status: ExternalChannelDeliveryStatus,
        provider_message_key: str | None,
        error_kind: str | None,
        error_summary: str | None,
        now: datetime.datetime,
    ) -> str | None:
        del session, delivery_attempt_id, error_summary, now
        self.events.append("finish")
        self.finished.append((status, provider_message_key, error_kind))
        return self.recovery_delivery_ids.pop(0) if self.recovery_delivery_ids else None

    async def recover_archive_cleanup(
        self,
        session: AsyncSession,
        *,
        current_delivery_ids: list[str],
        now: datetime.datetime,
    ) -> None:
        del session, now
        assert current_delivery_ids == ["delivery-1"]
        self.events.append("recover")

    async def list_archive_cleanup_ids(
        self,
        session: AsyncSession,
        *,
        delivery_ids: list[str],
    ) -> list[str]:
        del session
        assert delivery_ids == ["delivery-1"]
        return list(delivery_ids)


class _ExecutionRepositoryDouble(_RepositoryDouble):
    def __init__(
        self,
        events: list[str],
        committed: ChannelActionCommit,
    ) -> None:
        super().__init__(events)
        self.committed = committed
        self.skipped: list[tuple[str, str]] = []

    async def commit_action(
        self,
        session: AsyncSession,
        **_: object,
    ) -> ChannelActionCommit:
        del session
        self.events.append("commit-action")
        return self.committed

    async def skip_delivery(
        self,
        session: AsyncSession,
        *,
        delivery_attempt_id: str,
        error_kind: str,
        error_summary: str,
        now: datetime.datetime,
    ) -> bool:
        del session, error_summary, now
        self.events.append("skip")
        self.skipped.append((delivery_attempt_id, error_kind))
        return True

    async def complete_action(
        self,
        session: AsyncSession,
        *,
        action_id: str,
        now: datetime.datetime,
    ) -> ChannelActionCommit:
        del session, now
        assert action_id == self.committed.action_id
        self.events.append("complete-action")
        return self.committed


class _CredentialsCodec:
    def decrypt(self, encrypted: str) -> SlackConnectionCredentials:
        assert encrypted == "ciphertext"
        return SlackConnectionCredentials(
            bot_token="xoxb-secret",
            signing_secret="signing-secret",
            app_token=None,
        )


class _SlackClient:
    def __init__(
        self,
        events: list[str],
        result: SlackControlMessageResult | list[SlackControlMessageResult],
    ) -> None:
        self.events = events
        self.results = result if isinstance(result, list) else [result]
        self.bot_tokens: list[str] = []
        self.uploaded: list[tuple[str, bytes]] = []

    def _result(self) -> SlackControlMessageResult:
        if len(self.results) == 1:
            return self.results[0]
        return self.results.pop(0)

    async def post_message(self, **kwargs: str) -> SlackControlMessageResult:
        self.events.append("provider")
        self.bot_tokens.append(kwargs["bot_token"])
        assert kwargs["channel_id"] == "C1"
        assert kwargs["thread_ts"] == "1.000001"
        assert kwargs["markdown_text"] == "Reply"
        return self._result()

    async def post_file_message(self, **kwargs: object) -> SlackControlMessageResult:
        self.events.append("provider")
        self.bot_tokens.append(cast(str, kwargs["bot_token"]))
        assert kwargs["channel_id"] == "C1"
        assert kwargs["thread_ts"] == "1.000001"
        assert kwargs["markdown_text"] == "Reply"
        files = cast(list[SlackOutboundFile], kwargs["files"])
        for file in files:
            body = b"".join([chunk async for chunk in file.content()])
            assert len(body) == file.length
            self.uploaded.append((file.filename, body))
        return self._result()

    async def post_blocks(self, **kwargs: object) -> SlackControlMessageResult:
        self.events.append("provider")
        self.bot_tokens.append(cast(str, kwargs["bot_token"]))
        assert kwargs["channel_id"] == "C1"
        assert kwargs["thread_ts"] == "1.000001"
        assert kwargs["text"] == "Agent is working"
        return self._result()

    async def update_message(self, **kwargs: object) -> SlackControlMessageResult:
        self.events.append("provider")
        self.bot_tokens.append(cast(str, kwargs["bot_token"]))
        assert kwargs["channel_id"] == "C1"
        assert kwargs["message_ts"] == "2.000001"
        assert kwargs["text"] == "Agent is working"
        return self._result()

    async def delete_message(self, **kwargs: str) -> SlackControlMessageResult:
        self.events.append("provider")
        self.bot_tokens.append(kwargs["bot_token"])
        assert kwargs["channel_id"] == "C1"
        assert kwargs["message_ts"] == "2.000001"
        return self._result()


class _DiscordClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.uploaded: list[tuple[str, bytes]] = []

    async def ensure_thread(self, **kwargs: object) -> DiscordDeliveryResult:
        self.calls.append(("ensure_thread", kwargs))
        return DiscordDeliveryResult(
            status="delivered",
            provider_message_key=None,
            error_kind=None,
            error_summary=None,
        )

    async def create_message(self, **kwargs: object) -> DiscordDeliveryResult:
        self.calls.append(("create", kwargs))
        return DiscordDeliveryResult(
            status="delivered",
            provider_message_key="discord:111:555",
            error_kind=None,
            error_summary=None,
        )

    async def create_file_message(self, **kwargs: object) -> DiscordDeliveryResult:
        files = cast(tuple[DiscordOutboundFile, ...], kwargs["files"])
        for file in files:
            self.uploaded.append(
                (file.filename, b"".join([chunk async for chunk in file.content()]))
            )
        self.calls.append(("file", kwargs))
        return DiscordDeliveryResult(
            status="delivered",
            provider_message_key="discord:111:555",
            error_kind=None,
            error_summary=None,
        )

    async def update_message(self, **kwargs: object) -> DiscordDeliveryResult:
        self.calls.append(("update", kwargs))
        return DiscordDeliveryResult(
            status="delivered",
            provider_message_key="discord:111:555",
            error_kind=None,
            error_summary=None,
        )

    async def delete_message(self, **kwargs: object) -> DiscordDeliveryResult:
        self.calls.append(("delete", kwargs))
        return DiscordDeliveryResult(
            status="delivered",
            provider_message_key=None,
            error_kind=None,
            error_summary=None,
        )


class _RangedStorage:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.calls: list[tuple[str, str, int, int]] = []

    async def read_range(
        self,
        path: str,
        *,
        agent_id: str,
        offset: int,
        max_bytes: int,
    ) -> bytes:
        self.calls.append((path, agent_id, offset, max_bytes))
        return self.body[offset : offset + max_bytes]


class _ExchangeFileService:
    def __init__(self, result: Success[ExchangeFileDownload] | None = None) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    async def resolve_for_authority(
        self, **kwargs: object
    ) -> Success[ExchangeFileDownload]:
        self.calls.append(kwargs)
        if self.result is None:
            raise AssertionError("Exchange resolution was not expected")
        return self.result


@asynccontextmanager
async def _session_manager(
    events: list[str],
) -> AsyncGenerator[AsyncSession]:
    yield cast(AsyncSession, _SessionDouble(events))


def _service(
    events: list[str],
    repository: _RepositoryDouble,
    slack_client: _SlackClient,
    exchange_file_service: _ExchangeFileService | None = None,
    discord_client: _DiscordClient | None = None,
) -> ExternalChannelActionService:
    return ExternalChannelActionService(
        session_manager=cast(
            SessionManager[AsyncSession],
            lambda: _session_manager(events),
        ),
        repository=cast(ExternalChannelWorkRepository, repository),
        credentials_codec=cast(
            ExternalChannelCredentialsCodec,
            _CredentialsCodec(),
        ),
        slack_client=cast(SlackConversationClient, slack_client),
        discord_client=cast(DiscordDeliveryClient, discord_client or _DiscordClient()),
        exchange_file_service=cast(
            ExchangeFileService,
            exchange_file_service or _ExchangeFileService(),
        ),
        config=cast(Config, SimpleNamespace(avatar_cdn_base_url=None)),
    )


def _authority() -> SessionResourceAuthority:
    return SessionResourceAuthority(
        workspace_id="workspace-1",
        agent_id="agent-1",
        session_id="session-1",
        root_session_id="root-session-1",
        run_id="run-1",
        run_index=1,
        owner_generation=1,
    )


def _exchange_file() -> ExchangeFile:
    now = _at(1)
    return ExchangeFile(
        id="a" * 32,
        workspace_id="workspace-1",
        agent_id="agent-1",
        origin_type=ExchangeFileOrigin.ARTIFACT,
        status=ExchangeFileStatus.AVAILABLE,
        object_key="exchange/workspace-1/files/a/original",
        filename="generated.png",
        media_type="image/png",
        size_bytes=7,
        sha256="0" * 64,
        provenance_kind=ExchangeFileProvenanceKind.TOOL,
        source_user_id=None,
        source_agent_id="agent-1",
        source_run_id="run-1",
        source_tool_name="image_generation",
        source_provider=None,
        source_exchange_file_id=None,
        retention_root_session_id="root-session-1",
        retention_bound_at=now,
        preview_thumbnail_file_id=None,
        preview_thumbnail_uri=None,
        preview_title="generated.png",
        preview_summary=None,
        preview_thumbnail_media_type=None,
        preview_thumbnail_width=None,
        preview_thumbnail_height=None,
        preview_generated_at=None,
        expires_at=now + datetime.timedelta(days=7),
        expired_at=None,
        blob_deleted_at=None,
        created_at=now,
    )


@pytest.mark.asyncio
async def test_delivery_crosses_attempting_commit_before_provider_call() -> None:
    """The provider sees a call only after attempting is durably committed."""
    events: list[str] = []
    repository = _RepositoryDouble(events)
    slack_client = _SlackClient(
        events,
        SlackControlMessageResult(
            status="delivered",
            provider_message_key="slack:T1:C1:2.000001",
            error_kind=None,
            error_summary=None,
        ),
    )
    service = _service(events, repository, slack_client)

    await service.attempt_delivery("delivery-1")

    assert events == ["start", "commit", "provider", "finish", "commit"]
    assert repository.finished == [
        (
            ExternalChannelDeliveryStatus.DELIVERED,
            "slack:T1:C1:2.000001",
            None,
        )
    ]
    assert slack_client.bot_tokens == ["xoxb-secret"]


@pytest.mark.asyncio
async def test_prepared_delivery_survives_connection_secret_purge() -> None:
    """Disconnect cleanup uses the in-memory target captured before terminalization."""
    events: list[str] = []
    repository = _RepositoryDouble(events)
    slack_client = _SlackClient(
        events,
        SlackControlMessageResult(
            status="delivered",
            provider_message_key=None,
            error_kind=None,
            error_summary=None,
        ),
    )
    service = _service(events, repository, slack_client)

    target = await service.prepare_delivery("delivery-1")
    assert target is not None
    repository.target = repository.target.model_copy(
        update={
            "encrypted_credentials": None,
            "provider_tenant_id": None,
        }
    )

    await service.attempt_prepared_delivery(target)

    assert events == ["start", "commit", "provider", "finish", "commit"]
    assert slack_client.bot_tokens == ["xoxb-secret"]


@pytest.mark.asyncio
async def test_failed_delivery_is_terminal_and_not_reported_as_success() -> None:
    """A provider failure remains failed with its safe reason."""
    events: list[str] = []
    repository = _RepositoryDouble(events)
    service = _service(
        events,
        repository,
        _SlackClient(
            events,
            SlackControlMessageResult(
                status="failed",
                provider_message_key=None,
                error_kind="resource_unavailable",
                error_summary="Slack cannot post to the linked conversation.",
            ),
        ),
    )

    await service.attempt_delivery("delivery-1")

    assert repository.finished == [
        (ExternalChannelDeliveryStatus.FAILED, None, "resource_unavailable")
    ]
    assert events.count("provider") == 1


@pytest.mark.asyncio
async def test_discord_reply_delivery_uses_thread_target_and_agent_prefix() -> None:
    """Discord reply attempts retain durable ordering and shared-App attribution."""
    events: list[str] = []
    repository = _RepositoryDouble(events)
    repository.target = repository.target.model_copy(
        update={
            "provider": ExternalChannelProvider.DISCORD,
            "provider_tenant_id": "111",
            "agent_name": "Research * Agent",
            "request_payload": {
                "guild_id": "111",
                "channel_id": "333",
                "thread_parent_channel_id": "222",
                "thread_root_message_id": "333",
                "text": "Reply",
            },
        }
    )
    discord_client = _DiscordClient()
    service = _service(
        events,
        repository,
        _SlackClient(
            events,
            SlackControlMessageResult(
                status="delivered",
                provider_message_key=None,
                error_kind=None,
                error_summary=None,
            ),
        ),
        discord_client=discord_client,
    )

    await service.attempt_delivery("delivery-1")

    assert repository.finished == [
        (
            ExternalChannelDeliveryStatus.DELIVERED,
            "discord:111:555",
            None,
        )
    ]
    assert discord_client.calls == [
        (
            "ensure_thread",
            {
                "bot_token": "xoxb-secret",
                "parent_channel_id": "222",
                "root_message_id": "333",
            },
        ),
        (
            "create",
            {
                "bot_token": "xoxb-secret",
                "guild_id": "111",
                "channel_id": "333",
                "content": "**Research \\* Agent**\nReply",
                "delivery_attempt_id": "delivery-1",
            },
        ),
    ]


@pytest.mark.asyncio
async def test_discord_approval_control_delivery_uses_text_create() -> None:
    """Discord approval controls use the same fenced create-message delivery path."""
    events: list[str] = []
    repository = _RepositoryDouble(events)
    repository.target = repository.target.model_copy(
        update={
            "provider": ExternalChannelProvider.DISCORD,
            "provider_tenant_id": "111",
            "agent_name": None,
            "operation": ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
            "request_payload": {
                "guild_id": "111",
                "channel_id": "333",
                "thread_parent_channel_id": "222",
                "thread_root_message_id": "333",
                "text": (
                    "Approval is required. "
                    "[Review access](https://azents.example/request-1)"
                ),
            },
        }
    )
    discord_client = _DiscordClient()
    service = _service(
        events,
        repository,
        _SlackClient(
            events,
            SlackControlMessageResult(
                status="delivered",
                provider_message_key=None,
                error_kind=None,
                error_summary=None,
            ),
        ),
        discord_client=discord_client,
    )

    await service.attempt_delivery("delivery-1")

    assert repository.finished == [
        (
            ExternalChannelDeliveryStatus.DELIVERED,
            "discord:111:555",
            None,
        )
    ]
    assert discord_client.calls == [
        (
            "ensure_thread",
            {
                "bot_token": "xoxb-secret",
                "parent_channel_id": "222",
                "root_message_id": "333",
            },
        ),
        (
            "create",
            {
                "bot_token": "xoxb-secret",
                "guild_id": "111",
                "channel_id": "333",
                "content": (
                    "Approval is required. "
                    "[Review access](https://azents.example/request-1)"
                ),
                "delivery_attempt_id": "delivery-1",
            },
        ),
    ]


@pytest.mark.asyncio
async def test_discord_file_delivery_streams_the_current_runtime_source() -> None:
    """Discord multipart delivery reads only the bounded current Runtime source."""
    events: list[str] = []
    repository = _RepositoryDouble(events)
    repository.target = repository.target.model_copy(
        update={
            "provider": ExternalChannelProvider.DISCORD,
            "provider_tenant_id": "111",
            "request_payload": {
                "guild_id": "111",
                "channel_id": "333",
                "text": "Report",
                "files": [
                    ExternalChannelOutboundFileManifest(
                        path="/workspace/agent/report.txt",
                        filename="report.txt",
                        media_type="text/plain",
                        expected_size=6,
                    ).model_dump(mode="json")
                ],
            },
        }
    )
    discord_client = _DiscordClient()
    service = _service(
        events,
        repository,
        _SlackClient(
            events,
            SlackControlMessageResult(
                status="delivered",
                provider_message_key=None,
                error_kind=None,
                error_summary=None,
            ),
        ),
        discord_client=discord_client,
    )
    storage = _RangedStorage(b"report")

    await service.attempt_delivery(
        "delivery-1",
        file_storage=cast(FileStorage, storage),
        agent_id="agent-1",
    )

    assert discord_client.calls[0][0] == "file"
    assert discord_client.uploaded == [("report.txt", b"report")]
    assert storage.calls == [
        ("/workspace/agent/report.txt", "agent-1", 0, 6),
        ("/workspace/agent/report.txt", "agent-1", 6, 1),
    ]


@pytest.mark.asyncio
async def test_file_delivery_streams_only_from_the_immediate_run_source() -> None:
    """The post-commit attempt consumes the current run-scoped Runtime source."""
    events: list[str] = []
    repository = _RepositoryDouble(events)
    repository.target = repository.target.model_copy(
        update={
            "request_payload": {
                **repository.target.request_payload,
                "files": [
                    ExternalChannelOutboundFileManifest(
                        path="/workspace/agent/report.txt",
                        filename="report.txt",
                        media_type="text/plain",
                        expected_size=6,
                    ).model_dump(mode="json")
                ],
            }
        }
    )
    slack_client = _SlackClient(
        events,
        SlackControlMessageResult(
            status="delivered",
            provider_message_key=None,
            error_kind=None,
            error_summary=None,
        ),
    )
    storage = _RangedStorage(b"report")
    service = _service(events, repository, slack_client)

    await service.attempt_delivery(
        "delivery-1",
        file_storage=cast(FileStorage, storage),
        agent_id="agent-1",
    )

    assert events == ["start", "commit", "provider", "finish", "commit"]
    assert slack_client.uploaded == [("report.txt", b"report")]
    assert storage.calls == [
        ("/workspace/agent/report.txt", "agent-1", 0, 6),
        ("/workspace/agent/report.txt", "agent-1", 6, 1),
    ]


@pytest.mark.asyncio
async def test_exchange_file_delivery_revalidates_the_current_authority() -> None:
    """Post-commit Exchange delivery reads only the canonical execution source."""
    events: list[str] = []
    repository = _RepositoryDouble(events)
    exchange_file = _exchange_file()
    repository.target = repository.target.model_copy(
        update={
            "request_payload": {
                **repository.target.request_payload,
                "files": [
                    ExternalChannelOutboundFileManifest(
                        source=ExternalChannelOutboundFileSource.EXCHANGE,
                        path=exchange_file.uri,
                        filename=exchange_file.filename,
                        media_type=exchange_file.media_type,
                        expected_size=exchange_file.size_bytes,
                    ).model_dump(mode="json")
                ],
            }
        }
    )
    exchange_file_service = _ExchangeFileService(
        Success(ExchangeFileDownload(file=exchange_file, body=b"pngdata"))
    )
    slack_client = _SlackClient(
        events,
        SlackControlMessageResult(
            status="delivered",
            provider_message_key=None,
            error_kind=None,
            error_summary=None,
        ),
    )
    service = _service(
        events,
        repository,
        slack_client,
        exchange_file_service=exchange_file_service,
    )

    await service.attempt_delivery("delivery-1", authority=_authority())

    assert events == ["start", "commit", "provider", "finish", "commit"]
    assert slack_client.uploaded == [("generated.png", b"pngdata")]
    assert exchange_file_service.calls == [
        {"uri": exchange_file.uri, "authority": _authority()}
    ]


@pytest.mark.asyncio
async def test_recovered_exchange_delivery_without_authority_fails() -> None:
    """An Exchange source is never replayed without its execution authority."""
    events: list[str] = []
    repository = _RepositoryDouble(events)
    exchange_file = _exchange_file()
    repository.target = repository.target.model_copy(
        update={
            "request_payload": {
                **repository.target.request_payload,
                "files": [
                    ExternalChannelOutboundFileManifest(
                        source=ExternalChannelOutboundFileSource.EXCHANGE,
                        path=exchange_file.uri,
                        filename=exchange_file.filename,
                        media_type=exchange_file.media_type,
                        expected_size=exchange_file.size_bytes,
                    ).model_dump(mode="json")
                ],
            }
        }
    )
    service = _service(
        events,
        repository,
        _SlackClient(
            events,
            SlackControlMessageResult(
                status="delivered",
                provider_message_key=None,
                error_kind=None,
                error_summary=None,
            ),
        ),
    )

    await service.attempt_delivery("delivery-1")

    assert repository.finished == [
        (
            ExternalChannelDeliveryStatus.FAILED,
            None,
            "exchange_file_source_unavailable",
        )
    ]
    assert "provider" not in events


@pytest.mark.asyncio
async def test_recovered_file_delivery_without_run_source_fails_before_provider() -> (
    None
):
    """A durable file-bearing intent is not replayed without its original source."""
    events: list[str] = []
    repository = _RepositoryDouble(events)
    repository.target = repository.target.model_copy(
        update={
            "request_payload": {
                **repository.target.request_payload,
                "files": [
                    ExternalChannelOutboundFileManifest(
                        path="/workspace/agent/report.txt",
                        filename="report.txt",
                        media_type="text/plain",
                        expected_size=6,
                    ).model_dump(mode="json")
                ],
            }
        }
    )
    service = _service(
        events,
        repository,
        _SlackClient(
            events,
            SlackControlMessageResult(
                status="delivered",
                provider_message_key=None,
                error_kind=None,
                error_summary=None,
            ),
        ),
    )

    await service.attempt_delivery("delivery-1")

    assert repository.finished == [
        (
            ExternalChannelDeliveryStatus.FAILED,
            None,
            "runtime_file_source_unavailable",
        )
    ]
    assert "provider" not in events


@pytest.mark.asyncio
async def test_failed_control_message_delete_remains_a_terminal_outcome() -> None:
    """Approval cleanup failure is recorded after the decision-owned intent."""
    events: list[str] = []
    repository = _RepositoryDouble(events)
    repository.target = repository.target.model_copy(
        update={
            "operation": ExternalChannelDeliveryOperation.PROGRESS_DELETE,
            "binding_id": None,
            "request_payload": {
                "channel_id": "C1",
                "thread_ts": "1.000001",
                "provider_message_key": "slack:T1:C1:2.000001",
            },
        }
    )
    service = _service(
        events,
        repository,
        _SlackClient(
            events,
            SlackControlMessageResult(
                status="failed",
                provider_message_key=None,
                error_kind="message_not_found",
                error_summary="Slack could not delete the approval message.",
            ),
        ),
    )

    await service.attempt_delivery("delivery-1")

    assert repository.finished == [
        (ExternalChannelDeliveryStatus.FAILED, None, "message_not_found")
    ]
    assert events == ["start", "commit", "provider", "finish", "commit"]


@pytest.mark.asyncio
async def test_missing_activity_tracker_is_recreated_once() -> None:
    """A confirmed missing update target consumes one durable recreate intent."""
    events: list[str] = []
    repository = _RepositoryDouble(events)
    repository.recovery_delivery_ids = ["delivery-2", None]
    repository.target = repository.target.model_copy(
        update={
            "operation": ExternalChannelDeliveryOperation.PROGRESS_UPDATE,
            "request_payload": {
                "channel_id": "C1",
                "thread_ts": "1.000001",
                "provider_message_key": "slack:T1:C1:2.000001",
                "text": "Agent is working",
                "blocks": [],
            },
        }
    )
    service = _service(
        events,
        repository,
        _SlackClient(
            events,
            [
                SlackControlMessageResult(
                    status="failed",
                    provider_message_key=None,
                    error_kind="message_not_found",
                    error_summary="Slack no longer contains the Activity Tracker.",
                ),
                SlackControlMessageResult(
                    status="delivered",
                    provider_message_key="slack:T1:C1:3.000001",
                    error_kind=None,
                    error_summary=None,
                ),
            ],
        ),
    )

    await service.attempt_delivery("delivery-1")

    assert repository.finished == [
        (ExternalChannelDeliveryStatus.FAILED, None, "message_not_found"),
        (
            ExternalChannelDeliveryStatus.DELIVERED,
            "slack:T1:C1:3.000001",
            None,
        ),
    ]
    assert events == [
        "start",
        "commit",
        "provider",
        "finish",
        "commit",
        "start",
        "commit",
        "provider",
        "finish",
        "commit",
    ]


@pytest.mark.asyncio
async def test_recovered_failed_final_reply_skips_tracker_deletion() -> None:
    """A resumed finish action cannot delete the Tracker after reply failure."""
    events: list[str] = []
    committed = ChannelActionCommit(
        action_id="action-finish",
        binding_id="binding-1",
        work_id="work-1",
        work_status=ExternalChannelWorkStatus.FINISHED,
        state_revision=3,
        deliveries=[
            ChannelWorkDelivery(
                id="reply",
                operation=ExternalChannelDeliveryOperation.REPLY,
                status=ExternalChannelDeliveryStatus.FAILED,
                provider_message_key=None,
                error_kind="resource_unavailable",
                error_summary="Slack rejected the final reply.",
                created_at=_at(1),
                completed_at=_at(2),
            ),
            ChannelWorkDelivery(
                id="cleanup",
                operation=ExternalChannelDeliveryOperation.PROGRESS_DELETE,
                status=ExternalChannelDeliveryStatus.PENDING,
                provider_message_key="slack:T1:C1:2.000001",
                error_kind=None,
                error_summary=None,
                created_at=_at(1),
                completed_at=None,
            ),
        ],
    )
    repository = _ExecutionRepositoryDouble(events, committed)
    service = _service(
        events,
        repository,
        _SlackClient(
            events,
            SlackControlMessageResult(
                status="delivered",
                provider_message_key="slack:T1:C1:2.000001",
                error_kind=None,
                error_summary=None,
            ),
        ),
    )

    result = await service.execute(
        session_id="session-1",
        agent_id="agent-1",
        run_id="run-1",
        client_tool_call_id="call-finish",
        binding_id="binding-1",
        mode=ExternalChannelActionMode.FINISH,
        message="Final answer",
        title=None,
        tasks=None,
        files=(),
        file_storage=None,
    )

    assert result is committed
    assert repository.skipped == [
        ("cleanup", "final_reply_not_delivered"),
    ]
    assert "provider" not in events


@pytest.mark.asyncio
async def test_finish_without_a_final_reply_skips_tracker_deletion() -> None:
    """A FINISH action without a reply cannot remove the existing Tracker."""
    events: list[str] = []
    committed = ChannelActionCommit(
        action_id="action-finish",
        binding_id="binding-1",
        work_id="work-1",
        work_status=ExternalChannelWorkStatus.FINISHED,
        state_revision=3,
        deliveries=[
            ChannelWorkDelivery(
                id="cleanup",
                operation=ExternalChannelDeliveryOperation.PROGRESS_DELETE,
                status=ExternalChannelDeliveryStatus.PENDING,
                provider_message_key="slack:T1:C1:2.000001",
                error_kind=None,
                error_summary=None,
                created_at=_at(1),
                completed_at=None,
            ),
        ],
    )
    repository = _ExecutionRepositoryDouble(events, committed)
    service = _service(
        events,
        repository,
        _SlackClient(
            events,
            SlackControlMessageResult(
                status="delivered",
                provider_message_key="slack:T1:C1:2.000001",
                error_kind=None,
                error_summary=None,
            ),
        ),
    )

    await service.execute(
        session_id="session-1",
        agent_id="agent-1",
        run_id="run-1",
        client_tool_call_id="call-finish-without-reply",
        binding_id="binding-1",
        mode=ExternalChannelActionMode.FINISH,
        message=None,
        title=None,
        tasks=None,
        files=(),
        file_storage=None,
    )

    assert repository.skipped == [("cleanup", "final_reply_not_delivered")]
    assert "provider" not in events


@pytest.mark.asyncio
async def test_archive_cleanup_consumes_each_pending_intent_once() -> None:
    """Post-archive cleanup delegates each durable pending row to the same fence."""
    events: list[str] = []
    repository = _RepositoryDouble(events)
    service = _service(
        events,
        repository,
        _SlackClient(
            events,
            SlackControlMessageResult(
                status="delivered",
                provider_message_key="slack:T1:C1:2.000001",
                error_kind=None,
                error_summary=None,
            ),
        ),
    )

    count = await service.drain_archive_cleanup(["delivery-1"])

    assert count == 1
    assert events == [
        "recover",
        "commit",
        "start",
        "commit",
        "provider",
        "finish",
        "commit",
    ]


def test_action_commit_fixture_preserves_transparent_outcomes() -> None:
    """The service-facing commit record distinguishes failed from delivered."""
    commit = ChannelActionCommit(
        action_id="action-1",
        binding_id="binding-1",
        work_id="work-1",
        work_status=ExternalChannelWorkStatus.ACTIVE,
        state_revision=2,
        deliveries=[
            ChannelWorkDelivery(
                id="delivery-1",
                operation=ExternalChannelDeliveryOperation.REPLY,
                status=ExternalChannelDeliveryStatus.UNKNOWN,
                provider_message_key=None,
                error_kind="provider_ambiguous",
                error_summary="Slack delivery outcome is unknown.",
                created_at=_at(1),
                completed_at=_at(2),
            )
        ],
    )

    assert commit.deliveries[0].status is ExternalChannelDeliveryStatus.UNKNOWN
