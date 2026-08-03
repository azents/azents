"""Channel Action commit-before-delivery orchestration tests."""

import asyncio
import datetime
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
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
    ExternalChannelAppMode,
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
from azents.repos.external_channel.work import (
    DeliverySettlement,
    ExternalChannelWorkRepository,
    RuntimeProviderDeliveryCompletion,
)
from azents.repos.external_channel.work_data import (
    ChannelActionCommit,
    ChannelDeliveryTarget,
    ChannelWorkDelivery,
)
from azents.runtime.transfer.runtime_to_provider import (
    RuntimeToProviderDeliveryCapability,
    RuntimeToProviderRecovery,
    RuntimeToProviderRecoveryError,
    RuntimeToProviderSource,
    RuntimeToProviderTransferError,
)
from azents.runtime.transfer.server_to_runtime import ServerToRuntimeTarget
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
from azents.services.external_channel.discord_settings_scope import (
    build_discord_binding_settings_open_custom_id,
    build_discord_settings_custom_id,
)
from azents.services.external_channel.slack_events import (
    SlackControlMessageResult,
    SlackConversationClient,
    SlackOutboundFile,
)
from azents.services.external_channel.slack_settings import (
    SlackSettingsLocator,
    parse_slack_settings_locator,
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
        self.runtime_settlement_delivery_ids: list[str] = []
        self.finished: list[
            tuple[ExternalChannelDeliveryStatus, str | None, str | None]
        ] = []
        self.recorded_delivery_channels: list[tuple[str, str, str | None]] = []
        self.runtime_provider_states: list[tuple[str, dict[str, object]]] = []
        self.started_runtime_targets: list[object | None] = []
        self.settlement_accepted = True
        self.settlement_status: ExternalChannelDeliveryStatus | None = None
        self.target = ChannelDeliveryTarget(
            delivery_attempt_id="delivery-1",
            operation=ExternalChannelDeliveryOperation.REPLY,
            status=ExternalChannelDeliveryStatus.PENDING,
            binding_id="binding-1",
            resource_id=None,
            connection_id="connection-1",
            provider=ExternalChannelProvider.SLACK,
            app_mode=ExternalChannelAppMode.SINGLE,
            encrypted_credentials="ciphertext",
            provider_tenant_id="T1",
            capabilities=None,
            workspace_handle="workspace",
            agent_id="agent-1",
            agent_session_id="session-1",
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
        runtime_target: object | None,
    ) -> ChannelDeliveryTarget | None:
        del now
        self.events.append("start")
        self.started_runtime_targets.append(runtime_target)
        return await self.get_delivery_target(
            session,
            delivery_attempt_id=delivery_attempt_id,
        )

    async def start_captured_terminal_delivery(
        self,
        session: AsyncSession,
        *,
        target: ChannelDeliveryTarget,
        now: datetime.datetime,
    ) -> ChannelDeliveryTarget | None:
        del session, now
        self.events.append("start-captured")
        return target.model_copy(
            update={"status": ExternalChannelDeliveryStatus.ATTEMPTING}
        )

    async def record_runtime_provider_state(
        self,
        session: AsyncSession,
        *,
        delivery_attempt_id: str,
        state: str,
        recovery_payload: dict[str, object],
        provider_message_key: str | None,
    ) -> bool:
        del session, delivery_attempt_id, provider_message_key
        self.events.append(f"runtime-{state}")
        self.runtime_provider_states.append((state, recovery_payload))
        return True

    async def complete_runtime_provider_delivery(
        self,
        session: AsyncSession,
        *,
        delivery_attempt_id: str,
        recovery_payload: dict[str, object],
        provider_message_key: str | None,
        now: datetime.datetime,
    ) -> RuntimeProviderDeliveryCompletion:
        del session, delivery_attempt_id, now
        self.events.append("runtime-provider_completed")
        self.runtime_provider_states.append(("provider_completed", recovery_payload))
        self.finished.append(
            (ExternalChannelDeliveryStatus.DELIVERED, provider_message_key, None)
        )
        return RuntimeProviderDeliveryCompletion(
            accepted=True,
            recovery_delivery_id=None,
        )

    async def revalidate_runtime_delivery_authority(
        self,
        session: AsyncSession,
        *,
        delivery_attempt_id: str,
        runtime_target: object,
        provider_started: bool,
        now: datetime.datetime,
    ) -> bool:
        del session, delivery_attempt_id, runtime_target, now
        self.events.append(f"revalidate:{provider_started}")
        return True

    async def list_runtime_provider_settlement_delivery_ids(
        self,
        session: AsyncSession,
        *,
        limit: int,
    ) -> list[str]:
        del session
        return self.runtime_settlement_delivery_ids[:limit]

    async def complete_runtime_provider_recovery(
        self,
        session: AsyncSession,
        *,
        delivery_attempt_id: str,
        provider_message_key: str | None,
        now: datetime.datetime,
    ) -> str | None:
        del session, delivery_attempt_id, now
        self.events.append("recover-runtime")
        self.finished.append(
            (ExternalChannelDeliveryStatus.DELIVERED, provider_message_key, None)
        )
        return None

    async def skip_delivery(
        self,
        session: AsyncSession,
        *,
        delivery_attempt_id: str,
        error_kind: str,
        error_summary: str,
        now: datetime.datetime,
    ) -> bool:
        del session, delivery_attempt_id, error_summary, now
        self.events.append("skip")
        self.finished.append((ExternalChannelDeliveryStatus.FAILED, None, error_kind))
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

    async def settle_delivery(
        self,
        session: AsyncSession,
        *,
        delivery_attempt_id: str,
        status: ExternalChannelDeliveryStatus,
        provider_message_key: str | None,
        error_kind: str | None,
        error_summary: str | None,
        now: datetime.datetime,
    ) -> DeliverySettlement:
        recovery_delivery_id = await self.finish_delivery(
            session,
            delivery_attempt_id=delivery_attempt_id,
            status=status,
            provider_message_key=provider_message_key,
            error_kind=error_kind,
            error_summary=error_summary,
            now=now,
        )
        return DeliverySettlement(
            accepted=self.settlement_accepted,
            status=(
                self.settlement_status or status if self.settlement_accepted else None
            ),
            recovery_delivery_id=recovery_delivery_id,
        )

    async def record_discord_delivery_channel(
        self,
        _session: AsyncSession,
        *,
        resource_id: str,
        delivery_channel_id: str,
        initial_thread_title: str | None,
    ) -> str:
        self.recorded_delivery_channels.append(
            (resource_id, delivery_channel_id, initial_thread_title)
        )
        return delivery_channel_id

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
        before_provider_request = kwargs.get("before_provider_request")
        callback = (
            None
            if before_provider_request is None
            else cast(Callable[[], Awaitable[None]], before_provider_request)
        )
        for file in files:
            if callback is not None:
                await callback()
            body = b"".join([chunk async for chunk in file.content()])
            assert len(body) == file.length
            self.uploaded.append((file.filename, body))
            if callback is not None:
                await callback()
        if callback is not None:
            await callback()
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
            provider_message_key="discord-thread:444",
            error_kind=None,
            error_summary=None,
            created_thread_name="Research * Agent",
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


class _RuntimeProviderBatch:
    def __init__(
        self,
        bodies: tuple[bytes, ...],
        *,
        cleanup_fails: bool = False,
        settlement_fails: bool = False,
    ) -> None:
        self.bodies = bodies
        self.cleanup_fails = cleanup_fails
        self.settlement_fails = settlement_fails
        self.streamed: list[int] = []
        self.provider_completed_calls = 0
        self.acknowledgement_calls = 0
        self.abandon_calls = 0
        self.close_calls = 0
        self.deadline_at = _at(59)

    async def ensure_active(self) -> None:
        return None

    async def iter_source_chunks(self, source_index: int) -> AsyncIterator[bytes]:
        self.streamed.append(source_index)
        yield self.bodies[source_index]

    async def provider_completed(self) -> tuple[object, ...]:
        self.provider_completed_calls += 1
        assert sorted(self.streamed) == list(range(len(self.bodies)))
        return self.recovery_evidence()

    def recovery_evidence(self) -> tuple[RuntimeToProviderRecovery, ...]:
        return tuple(
            RuntimeToProviderRecovery(
                transfer_id=f"transfer-{index}",
                attempt_id=f"attempt-{index}",
                consumer_claim_id=f"claim-{index}",
                revision=1,
                runtime_id="runtime-1",
                desired_generation=1,
                operation_id=f"operation-{index}",
                session_id="session-1",
                agent_id="agent-1",
                deadline_at=self.deadline_at,
            )
            for index in range(len(self.bodies))
        )

    async def acknowledge_and_settle(self) -> None:
        self.acknowledgement_calls += 1
        if self.settlement_fails:
            raise RuntimeToProviderTransferError("settlement unavailable")

    async def abandon_or_cancel(self) -> None:
        self.abandon_calls += 1
        if self.cleanup_fails:
            raise RuntimeToProviderTransferError("cleanup failed")

    async def close(self) -> None:
        self.close_calls += 1


class _RuntimeProviderCapability:
    def __init__(
        self,
        bodies: dict[str, bytes],
        *,
        cleanup_fails: bool = False,
        settlement_fails: bool = False,
        recovery_error: RuntimeToProviderTransferError | None = None,
    ) -> None:
        self.bodies = bodies
        self.cleanup_fails = cleanup_fails
        self.settlement_fails = settlement_fails
        self.recovery_error = recovery_error
        self.requests: list[dict[str, object]] = []
        self.batches: list[_RuntimeProviderBatch] = []
        self.recoveries: list[tuple[RuntimeToProviderRecovery, ...]] = []
        self.target = ServerToRuntimeTarget(
            runtime_id="runtime-1",
            desired_generation=1,
        )

    async def prepare(self, **kwargs: object) -> _RuntimeProviderBatch:
        self.requests.append(kwargs)
        sources = cast(tuple[RuntimeToProviderSource, ...], kwargs["sources"])
        batch = _RuntimeProviderBatch(
            tuple(self.bodies[source.runtime_path] for source in sources),
            cleanup_fails=self.cleanup_fails,
            settlement_fails=self.settlement_fails,
        )
        self.batches.append(batch)
        return batch

    async def recover(
        self,
        *,
        recoveries: tuple[RuntimeToProviderRecovery, ...],
    ) -> None:
        self.recoveries.append(recoveries)
        if self.recovery_error is not None:
            raise self.recovery_error


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
        config=cast(
            Config,
            SimpleNamespace(
                avatar_cdn_base_url=None,
                web_url="https://azents.example",
                auth=SimpleNamespace(
                    jwt=SimpleNamespace(secret_key="test-signing-secret")
                ),
            ),
        ),
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
async def test_prepared_delivery_revalidates_secret_before_provider() -> None:
    """A credential revoked after preparation cannot reach the provider."""
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

    assert events == ["start", "commit", "finish", "commit"]
    assert slack_client.bot_tokens == []
    assert repository.finished == [
        (ExternalChannelDeliveryStatus.FAILED, None, "credentials_missing")
    ]


@pytest.mark.asyncio
async def test_captured_terminal_delivery_uses_pre_purge_provider_target() -> None:
    """Terminal cleanup reaches the provider with the captured credential snapshot."""
    events: list[str] = []
    repository = _RepositoryDouble(events)
    repository.target = repository.target.model_copy(
        update={
            "operation": ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
            "agent_name": "Research Agent",
            "request_payload": {
                "control_kind": "session_presence",
                "presence_state": "left",
                "tenant_id": "T1",
                "channel_id": "C1",
                "thread_ts": "1.000001",
            },
        }
    )

    class _CapturedTerminalSlackClient(_SlackClient):
        async def post_blocks(self, **kwargs: object) -> SlackControlMessageResult:
            self.events.append("provider")
            self.bot_tokens.append(cast(str, kwargs["bot_token"]))
            assert kwargs["channel_id"] == "C1"
            assert kwargs["thread_ts"] == "1.000001"
            assert kwargs["text"] == "Research Agent left this conversation."
            return self._result()

    slack_client = _CapturedTerminalSlackClient(
        events,
        SlackControlMessageResult(
            status="delivered",
            provider_message_key="1721600100.000001",
            error_kind=None,
            error_summary=None,
        ),
    )
    service = _service(events, repository, slack_client)

    result = await service.attempt_captured_terminal_delivery(repository.target)

    assert result is ExternalChannelDeliveryStatus.DELIVERED
    assert events == ["start-captured", "commit", "provider", "finish", "commit"]
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
async def test_provider_control_returns_revalidated_settlement_status() -> None:
    """The service reports a conservative post-provider authority result."""
    events: list[str] = []
    repository = _RepositoryDouble(events)
    repository.settlement_status = ExternalChannelDeliveryStatus.UNKNOWN
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

    result = await service.attempt_delivery("delivery-1")

    assert result is ExternalChannelDeliveryStatus.UNKNOWN
    assert events == ["start", "commit", "provider", "finish", "commit"]


@pytest.mark.asyncio
async def test_delivery_returns_none_when_final_settlement_loses_attempt() -> None:
    """A superseded final settlement cannot report an uncommitted provider result."""
    events: list[str] = []
    repository = _RepositoryDouble(events)
    repository.settlement_accepted = False
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

    result = await service.attempt_delivery("delivery-1")

    assert result is None
    assert events == ["start", "commit", "provider", "finish", "commit"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("app_mode", "expected_content"),
    [
        (ExternalChannelAppMode.MULTI, "**Research \\* Agent**\nReply"),
        (ExternalChannelAppMode.SINGLE, "Reply"),
    ],
)
async def test_discord_reply_agent_prefix_follows_app_mode(
    app_mode: ExternalChannelAppMode,
    expected_content: str,
) -> None:
    """Discord adds Agent attribution only for shared multi-app delivery."""
    events: list[str] = []
    repository = _RepositoryDouble(events)
    repository.target = repository.target.model_copy(
        update={
            "provider": ExternalChannelProvider.DISCORD,
            "provider_tenant_id": "111",
            "resource_id": "resource-1",
            "app_mode": app_mode,
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
                "name": "Research * Agent",
            },
        ),
        (
            "create",
            {
                "bot_token": "xoxb-secret",
                "guild_id": "111",
                "channel_id": "444",
                "content": expected_content,
                "delivery_attempt_id": "delivery-1",
            },
        ),
    ]
    assert repository.recorded_delivery_channels == [
        ("resource-1", "444", "Research * Agent")
    ]


@pytest.mark.asyncio
async def test_discord_parent_reply_posts_directly_without_thread_provisioning() -> (
    None
):
    """A parent Resource never asks Discord to provision a reply thread."""
    events: list[str] = []
    repository = _RepositoryDouble(events)
    repository.target = repository.target.model_copy(
        update={
            "provider": ExternalChannelProvider.DISCORD,
            "provider_tenant_id": "111",
            "resource_id": "resource-1",
            "request_payload": {
                "guild_id": "111",
                "channel_id": "222",
                "conversation_scope": "parent_channel",
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

    result = await service.attempt_delivery("delivery-1")

    assert result is ExternalChannelDeliveryStatus.DELIVERED
    assert discord_client.calls == [
        (
            "create",
            {
                "bot_token": "xoxb-secret",
                "guild_id": "111",
                "channel_id": "222",
                "content": "Reply",
                "delivery_attempt_id": "delivery-1",
            },
        )
    ]
    assert repository.recorded_delivery_channels == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("app_mode", "expected_content"),
    [
        (ExternalChannelAppMode.SINGLE, ""),
        (ExternalChannelAppMode.MULTI, "**Research \\* Agent**"),
    ],
)
async def test_discord_progress_update_sends_tracker_embed(
    app_mode: ExternalChannelAppMode,
    expected_content: str,
) -> None:
    """A Tracker update keeps Multi App attribution outside its current Embed."""
    events: list[str] = []
    repository = _RepositoryDouble(events)
    repository.target = repository.target.model_copy(
        update={
            "provider": ExternalChannelProvider.DISCORD,
            "provider_tenant_id": "111",
            "app_mode": app_mode,
            "agent_name": "Research * Agent",
            "operation": ExternalChannelDeliveryOperation.PROGRESS_UPDATE,
            "request_payload": {
                "guild_id": "111",
                "channel_id": "333",
                "provider_message_key": "discord:111:555",
                "text": "",
                "embeds": [
                    {
                        "title": "Plan",
                        "description": "**0/1 complete**\n◉ Inspect the issue",
                        "color": 0x5865F2,
                    }
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
            "update",
            {
                "bot_token": "xoxb-secret",
                "guild_id": "111",
                "channel_id": "333",
                "message_id": "555",
                "content": expected_content,
                "embeds": [
                    {
                        "title": "Plan",
                        "description": "**0/1 complete**\n◉ Inspect the issue",
                        "color": 0x5865F2,
                    }
                ],
            },
        )
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
                "name": None,
            },
        ),
        (
            "create",
            {
                "bot_token": "xoxb-secret",
                "guild_id": "111",
                "channel_id": "444",
                "content": (
                    "Approval is required. "
                    "[Review access](https://azents.example/request-1)"
                ),
                "delivery_attempt_id": "delivery-1",
            },
        ),
    ]


@pytest.mark.asyncio
async def test_slack_selector_control_uses_interaction_identity() -> None:
    """A committed selector control carries only its retained interaction ID."""
    events: list[str] = []
    repository = _RepositoryDouble(events)
    repository.target = repository.target.model_copy(
        update={
            "operation": ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
            "request_payload": {
                "control_kind": "agent_selector",
                "tenant_id": "T1",
                "channel_id": "C1",
                "thread_ts": "1.000001",
                "selector_interaction_id": "selector-1",
            },
        }
    )

    class _SelectorSlackClient(_SlackClient):
        async def post_blocks(self, **kwargs: object) -> SlackControlMessageResult:
            self.events.append("provider")
            blocks = cast(list[dict[str, object]], kwargs["blocks"])
            actions = cast(list[dict[str, object]], blocks[1]["elements"])
            assert actions[0]["value"] == "selector-1"
            assert "conversation_admission_id" not in repository.target.request_payload
            return self._result()

    service = _service(
        events,
        repository,
        _SelectorSlackClient(
            events,
            SlackControlMessageResult(
                status="delivered",
                provider_message_key="slack:T1:C1:2.000001",
                error_kind=None,
                error_summary=None,
            ),
        ),
    )

    await service.attempt_delivery("delivery-1")

    assert repository.finished == [
        (
            ExternalChannelDeliveryStatus.DELIVERED,
            "slack:T1:C1:2.000001",
            None,
        )
    ]


@pytest.mark.asyncio
async def test_slack_session_presence_control_replaces_open_session() -> None:
    """A committed Slack binding presence is delivered as copy plus navigation."""
    events: list[str] = []
    repository = _RepositoryDouble(events)
    repository.target = repository.target.model_copy(
        update={
            "operation": ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
            "agent_name": "Research Agent",
            "request_payload": {
                "control_kind": "session_presence",
                "presence_state": "joined",
                "tenant_id": "T1",
                "channel_id": "C1",
                "thread_ts": "1.000001",
            },
        }
    )

    class _SessionPresenceSlackClient(_SlackClient):
        async def post_blocks(self, **kwargs: object) -> SlackControlMessageResult:
            self.events.append("provider")
            self.bot_tokens.append(cast(str, kwargs["bot_token"]))
            assert kwargs["channel_id"] == "C1"
            assert kwargs["thread_ts"] == "1.000001"
            assert kwargs["text"] == "Research Agent joined this conversation."
            assert kwargs["blocks"] == [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*Research Agent* joined this conversation.",
                    },
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "action_id": "view_azents_session",
                            "text": {
                                "type": "plain_text",
                                "text": "View session",
                            },
                            "url": (
                                "https://azents.example/w/workspace/agents/agent-1/"
                                "sessions/session-1"
                            ),
                        }
                    ],
                },
            ]
            assert kwargs["icon_url"] is None
            return self._result()

    service = _service(
        events,
        repository,
        _SessionPresenceSlackClient(
            events,
            SlackControlMessageResult(
                status="delivered",
                provider_message_key="slack:T1:C1:2.000001",
                error_kind=None,
                error_summary=None,
            ),
        ),
    )

    result = await service.attempt_delivery("delivery-1")

    assert result is ExternalChannelDeliveryStatus.DELIVERED
    assert events == ["start", "commit", "provider", "finish", "commit"]


@pytest.mark.asyncio
async def test_slack_setup_required_control_opens_parent_location_settings() -> None:
    """A new unconfigured mention receives one parent-scoped setup action."""
    events: list[str] = []
    repository = _RepositoryDouble(events)
    repository.target = repository.target.model_copy(
        update={
            "operation": ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
            "binding_id": None,
            "resource_id": "source-resource-1",
            "agent_name": "Research Agent",
            "request_payload": {
                "control_kind": "setup_required",
                "control_version": 2,
                "setup_claim_id": "claim-1",
                "claim_generation": 1,
                "source_revision": 1,
                "tenant_id": "T1",
                "channel_id": "C1",
                "thread_ts": "1.000001",
            },
        }
    )

    class _SetupSlackClient(_SlackClient):
        async def post_blocks(self, **kwargs: object) -> SlackControlMessageResult:
            self.events.append("provider")
            blocks = cast(list[dict[str, object]], kwargs["blocks"])
            assert kwargs["text"] == (
                "Choose where Research Agent should answer this conversation."
            )
            actions = cast(list[dict[str, object]], blocks[1]["elements"])
            assert actions[0]["text"] == {
                "type": "plain_text",
                "text": "Choose conversation location",
            }
            value = actions[0]["value"]
            assert isinstance(value, str)
            assert parse_slack_settings_locator(
                metadata=value,
                secret="test-signing-secret",
            ) == SlackSettingsLocator(
                connection_id="connection-1",
                provider_parent_channel_id="C1",
                resource_id=None,
                binding_id=None,
            )
            return self._result()

    service = _service(
        events,
        repository,
        _SetupSlackClient(
            events,
            SlackControlMessageResult(
                status="delivered",
                provider_message_key="slack:T1:C1:2.000001",
                error_kind=None,
                error_summary=None,
            ),
        ),
    )

    result = await service.attempt_delivery("delivery-1")

    assert result is ExternalChannelDeliveryStatus.DELIVERED
    assert events == ["start", "commit", "provider", "finish", "commit"]


@pytest.mark.asyncio
async def test_slack_existing_binding_settings_are_exposed_on_demand() -> None:
    """An eligible mention can expose settings without replaying joined presence."""
    events: list[str] = []
    repository = _RepositoryDouble(events)
    repository.target = repository.target.model_copy(
        update={
            "operation": ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
            "resource_id": "resource-1",
            "agent_name": "Research Agent",
            "request_payload": {
                "control_kind": "binding_settings_on_demand",
                "control_version": 3,
                "tenant_id": "T1",
                "channel_id": "C1",
                "thread_ts": "1.000001",
            },
        }
    )

    class _SettingsSlackClient(_SlackClient):
        async def post_blocks(self, **kwargs: object) -> SlackControlMessageResult:
            self.events.append("provider")
            assert kwargs["text"] == "Conversation settings for Research Agent."
            blocks = cast(list[dict[str, object]], kwargs["blocks"])
            assert "joined" not in str(blocks)
            actions = cast(list[dict[str, object]], blocks[1]["elements"])
            value = actions[0]["value"]
            assert isinstance(value, str)
            assert parse_slack_settings_locator(
                metadata=value,
                secret="test-signing-secret",
            ) == SlackSettingsLocator(
                connection_id="connection-1",
                provider_parent_channel_id="C1",
                resource_id="resource-1",
                binding_id="binding-1",
            )
            return self._result()

    service = _service(
        events,
        repository,
        _SettingsSlackClient(
            events,
            SlackControlMessageResult(
                status="delivered",
                provider_message_key="slack:T1:C1:2.000001",
                error_kind=None,
                error_summary=None,
            ),
        ),
    )

    result = await service.attempt_delivery("delivery-1")

    assert result is ExternalChannelDeliveryStatus.DELIVERED
    assert events == ["start", "commit", "provider", "finish", "commit"]


@pytest.mark.asyncio
async def test_legacy_binding_settings_delivery_never_reaches_slack() -> None:
    """A pending rollout-era intent is terminalized without provider I/O."""
    events: list[str] = []
    repository = _RepositoryDouble(events)
    repository.target = repository.target.model_copy(
        update={
            "operation": ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
            "resource_id": "resource-1",
            "agent_name": "Research Agent",
            "request_payload": {
                "control_kind": "binding_settings_available",
                "control_version": 2,
                "tenant_id": "T1",
                "channel_id": "C1",
                "thread_ts": "1.000001",
            },
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

    result = await service.attempt_delivery("delivery-1")

    assert result is ExternalChannelDeliveryStatus.FAILED
    assert events == ["start", "commit", "finish", "commit"]
    assert repository.finished == [
        (ExternalChannelDeliveryStatus.FAILED, None, "provider_payload_invalid")
    ]


@pytest.mark.asyncio
async def test_discord_session_presence_control_uses_signed_settings_action() -> None:
    """A joined Discord binding presence contains a signed settings action."""
    events: list[str] = []
    repository = _RepositoryDouble(events)
    repository.target = repository.target.model_copy(
        update={
            "provider": ExternalChannelProvider.DISCORD,
            "provider_tenant_id": "111",
            "operation": ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
            "agent_name": "Research Agent",
            "request_payload": {
                "control_kind": "session_presence",
                "presence_state": "joined",
                "guild_id": "111",
                "channel_id": "333",
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

    result = await service.attempt_delivery("delivery-1")

    assert result is ExternalChannelDeliveryStatus.DELIVERED
    assert discord_client.calls == [
        (
            "create",
            {
                "bot_token": "xoxb-secret",
                "guild_id": "111",
                "channel_id": "333",
                "content": "",
                "delivery_attempt_id": "delivery-1",
                "components": [
                    {
                        "type": 1,
                        "components": [
                            {
                                "type": 2,
                                "style": 5,
                                "label": "View session",
                                "url": (
                                    "https://azents.example/w/workspace/agents/"
                                    "agent-1/sessions/session-1"
                                ),
                            },
                            {
                                "type": 2,
                                "style": 2,
                                "label": "Conversation settings",
                                "custom_id": (
                                    build_discord_binding_settings_open_custom_id(
                                        secret="test-signing-secret",
                                        binding_id="binding-1",
                                    )
                                ),
                            },
                        ],
                    }
                ],
                "embeds": [
                    {
                        "description": "**Research Agent** joined this conversation.",
                        "color": 0x57F287,
                    }
                ],
            },
        )
    ]


@pytest.mark.asyncio
async def test_discord_setup_required_control_uses_claim_fenced_choices() -> None:
    """A new unconfigured mention receives two claim-fenced location choices."""
    events: list[str] = []
    repository = _RepositoryDouble(events)
    repository.target = repository.target.model_copy(
        update={
            "provider": ExternalChannelProvider.DISCORD,
            "provider_tenant_id": "111",
            "operation": ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
            "binding_id": None,
            "resource_id": "source-resource-1",
            "agent_name": "Research Agent",
            "request_payload": {
                "control_kind": "setup_required",
                "control_version": 2,
                "setup_claim_id": "claim-1",
                "claim_generation": 2,
                "source_revision": 4,
                "guild_id": "111",
                "channel_id": "333",
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

    result = await service.attempt_delivery("delivery-1")

    assert result is ExternalChannelDeliveryStatus.DELIVERED
    create = discord_client.calls[0][1]
    components = cast(list[dict[str, object]], create["components"])
    actions = cast(list[dict[str, object]], components[0]["components"])
    assert [action["label"] for action in actions] == [
        "Answer in this channel",
        "Answer in threads",
    ]
    assert actions[0]["custom_id"] == build_discord_settings_custom_id(
        secret="test-signing-secret",
        action="setup_channel",
        origin_interaction_id="claim-1",
        setup_claim_id="claim-1",
        claim_generation=2,
        source_revision=4,
    )
    assert actions[1]["custom_id"] == build_discord_settings_custom_id(
        secret="test-signing-secret",
        action="setup_threads",
        origin_interaction_id="claim-1",
        setup_claim_id="claim-1",
        claim_generation=2,
        source_revision=4,
    )


@pytest.mark.asyncio
async def test_discord_existing_binding_settings_are_exposed_on_demand() -> None:
    """An eligible mention can expose settings without replaying joined presence."""
    events: list[str] = []
    repository = _RepositoryDouble(events)
    repository.target = repository.target.model_copy(
        update={
            "provider": ExternalChannelProvider.DISCORD,
            "provider_tenant_id": "111",
            "operation": ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
            "resource_id": "resource-1",
            "agent_name": "Research Agent",
            "request_payload": {
                "control_kind": "binding_settings_on_demand",
                "control_version": 3,
                "guild_id": "111",
                "channel_id": "333",
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

    result = await service.attempt_delivery("delivery-1")

    assert result is ExternalChannelDeliveryStatus.DELIVERED
    create = discord_client.calls[0][1]
    embeds = cast(list[dict[str, object]], create["embeds"])
    assert "joined" not in str(embeds)
    components = cast(list[dict[str, object]], create["components"])
    actions = cast(list[dict[str, object]], components[0]["components"])
    assert actions == [
        {
            "type": 2,
            "style": 2,
            "label": "Conversation settings",
            "custom_id": build_discord_binding_settings_open_custom_id(
                secret="test-signing-secret",
                binding_id="binding-1",
            ),
        }
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
    capability = _RuntimeProviderCapability({})

    await service.attempt_delivery(
        "delivery-1",
        file_storage=cast(FileStorage, storage),
        agent_id="agent-1",
        provider_delivery_capability=cast(
            RuntimeToProviderDeliveryCapability,
            capability,
        ),
    )

    assert discord_client.calls[0][0] == "file"
    assert discord_client.uploaded == [("report.txt", b"report")]
    assert repository.started_runtime_targets == [capability.target]
    assert capability.requests == []
    assert storage.calls == [
        ("/workspace/agent/report.txt", "agent-1", 0, 6),
        ("/workspace/agent/report.txt", "agent-1", 6, 1),
    ]


@pytest.mark.asyncio
async def test_runtime_file_delivery_uses_verified_provider_stream() -> None:
    """The post-commit attempt streams one verified Runtime upload to Slack."""
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
    capability = _RuntimeProviderCapability({"/workspace/agent/report.txt": b"report"})
    exchange_file_service = _ExchangeFileService()
    service = _service(
        events,
        repository,
        slack_client,
        exchange_file_service=exchange_file_service,
    )

    await service.attempt_delivery(
        "delivery-1",
        provider_delivery_capability=cast(
            RuntimeToProviderDeliveryCapability,
            capability,
        ),
    )

    assert events[:2] == ["start", "commit"]
    assert events[-1] == "commit"
    assert "runtime-provider_completed" in events
    assert events.count("provider") == 1
    assert [state for state, _ in repository.runtime_provider_states] == [
        "prepared",
        "provider_started",
        "provider_completed",
        "settled",
    ]
    assert slack_client.uploaded == [("report.txt", b"report")]
    assert len(capability.requests) == 1
    request = capability.requests[0]
    assert request["operation_id"] == "external-channel-delivery:delivery-1"
    assert request["batch_id"] == "delivery-1"
    assert request["sources"] == (
        RuntimeToProviderSource(
            runtime_path="/workspace/agent/report.txt",
            filename="report.txt",
            media_type="text/plain",
            expected_size=6,
        ),
    )
    assert callable(request["before_source_admission"])
    assert capability.batches[0].provider_completed_calls == 1
    assert capability.batches[0].acknowledgement_calls == 1
    assert capability.batches[0].abandon_calls == 0
    assert exchange_file_service.calls == []


@pytest.mark.asyncio
async def test_runtime_file_provider_failure_abandons_unacknowledged_batch() -> None:
    """A confirmed Slack failure releases every unacknowledged Runtime claim."""
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
    capability = _RuntimeProviderCapability({"/workspace/agent/report.txt": b"report"})
    service = _service(
        events,
        repository,
        _SlackClient(
            events,
            SlackControlMessageResult(
                status="failed",
                provider_message_key=None,
                error_kind="provider_rejected",
                error_summary="Slack rejected the external file upload.",
            ),
        ),
    )

    await service.attempt_delivery(
        "delivery-1",
        provider_delivery_capability=cast(
            RuntimeToProviderDeliveryCapability,
            capability,
        ),
    )

    assert capability.batches[0].provider_completed_calls == 0
    assert capability.batches[0].acknowledgement_calls == 0
    assert capability.batches[0].abandon_calls == 1
    assert repository.finished == [
        (ExternalChannelDeliveryStatus.FAILED, None, "provider_rejected")
    ]


@pytest.mark.asyncio
async def test_runtime_file_failed_delivery_cleanup_unknown() -> None:
    """A failed Slack result remains unknown until Runtime cleanup is confirmed."""
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
    capability = _RuntimeProviderCapability(
        {"/workspace/agent/report.txt": b"report"},
        cleanup_fails=True,
    )
    service = _service(
        events,
        repository,
        _SlackClient(
            events,
            SlackControlMessageResult(
                status="failed",
                provider_message_key=None,
                error_kind="provider_rejected",
                error_summary="Slack rejected the external file upload.",
            ),
        ),
    )

    await service.attempt_delivery(
        "delivery-1",
        provider_delivery_capability=cast(
            RuntimeToProviderDeliveryCapability,
            capability,
        ),
    )

    assert capability.batches[0].abandon_calls == 1
    assert repository.finished == [
        (
            ExternalChannelDeliveryStatus.UNKNOWN,
            None,
            "runtime_transfer_cleanup_unknown",
        )
    ]


@pytest.mark.asyncio
async def test_runtime_file_provider_ambiguity_retains_batch_for_expiry() -> None:
    """An ambiguous provider outcome never abandons or replays Runtime bytes."""
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
    capability = _RuntimeProviderCapability({"/workspace/agent/report.txt": b"report"})
    service = _service(
        events,
        repository,
        _SlackClient(
            events,
            SlackControlMessageResult(
                status="unknown",
                provider_message_key=None,
                error_kind="provider_ambiguous",
                error_summary="Slack file upload outcome is unknown.",
            ),
        ),
    )

    await service.attempt_delivery(
        "delivery-1",
        provider_delivery_capability=cast(
            RuntimeToProviderDeliveryCapability,
            capability,
        ),
    )

    assert capability.batches[0].provider_completed_calls == 0
    assert capability.batches[0].acknowledgement_calls == 0
    assert capability.batches[0].abandon_calls == 0
    assert repository.finished == [
        (ExternalChannelDeliveryStatus.UNKNOWN, None, "provider_ambiguous")
    ]


@pytest.mark.asyncio
async def test_runtime_provider_completion_stays_delivered_when_settlement_fails() -> (
    None
):
    """Confirmed Slack completion remains delivered while exact cleanup is pending."""
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
    capability = _RuntimeProviderCapability(
        {"/workspace/agent/report.txt": b"report"},
        settlement_fails=True,
    )
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

    result = await service.attempt_delivery(
        "delivery-1",
        provider_delivery_capability=cast(
            RuntimeToProviderDeliveryCapability,
            capability,
        ),
    )

    assert result is ExternalChannelDeliveryStatus.DELIVERED
    assert events.count("provider") == 1
    assert repository.finished == [
        (
            ExternalChannelDeliveryStatus.DELIVERED,
            "slack:T1:C1:2.000001",
            None,
        )
    ]
    assert capability.batches[0].acknowledgement_calls == 1


@pytest.mark.asyncio
async def test_runtime_provider_started_cancellation_closes_batch_without_replay() -> (
    None
):
    """Cancellation after request ownership persists stops renewal but keeps claims."""
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
    capability = _RuntimeProviderCapability({"/workspace/agent/report.txt": b"report"})

    class _CancellingSlackClient(_SlackClient):
        async def post_file_message(
            self, **kwargs: object
        ) -> SlackControlMessageResult:
            callback = cast(
                Callable[[], Awaitable[None]], kwargs["before_provider_request"]
            )
            await callback()
            raise asyncio.CancelledError

    service = _service(
        events,
        repository,
        _CancellingSlackClient(
            events,
            SlackControlMessageResult(
                status="unknown",
                provider_message_key=None,
                error_kind="provider_ambiguous",
                error_summary="Slack file upload outcome is unknown.",
            ),
        ),
    )

    with pytest.raises(asyncio.CancelledError):
        await service.attempt_delivery(
            "delivery-1",
            provider_delivery_capability=cast(
                RuntimeToProviderDeliveryCapability,
                capability,
            ),
        )

    assert capability.batches[0].close_calls >= 1
    assert capability.batches[0].abandon_calls == 0
    assert [state for state, _ in repository.runtime_provider_states] == [
        "prepared",
        "provider_started",
    ]


@pytest.mark.asyncio
async def test_runtime_provider_authority_revocation_after_upload_is_unknown() -> None:
    """Authority loss after a Slack upload begins never becomes not-attempted."""
    events: list[str] = []

    class _RevokingRepository(_RepositoryDouble):
        async def revalidate_runtime_delivery_authority(
            self,
            session: AsyncSession,
            *,
            delivery_attempt_id: str,
            runtime_target: object,
            provider_started: bool,
            now: datetime.datetime,
        ) -> bool:
            del session, delivery_attempt_id, runtime_target, now
            self.events.append(f"revalidate:{provider_started}")
            return not provider_started

    repository = _RevokingRepository(events)
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
    capability = _RuntimeProviderCapability({"/workspace/agent/report.txt": b"report"})
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

    result = await service.attempt_delivery(
        "delivery-1",
        provider_delivery_capability=cast(
            RuntimeToProviderDeliveryCapability,
            capability,
        ),
    )

    assert result is ExternalChannelDeliveryStatus.UNKNOWN
    assert slack_client.uploaded == [("report.txt", b"report")]
    assert events.count("revalidate:False") == 1
    assert events.count("revalidate:True") == 1
    assert repository.finished == [
        (
            ExternalChannelDeliveryStatus.UNKNOWN,
            None,
            "runtime_transfer_ambiguous",
        )
    ]
    assert capability.batches[0].abandon_calls == 0
    assert capability.batches[0].close_calls >= 1


@pytest.mark.asyncio
async def test_runtime_completion_recovery_settles_without_slack_replay() -> None:
    """A persisted Slack success invokes only exact Runtime settlement recovery."""
    events: list[str] = []
    repository = _RepositoryDouble(events)
    repository.target = repository.target.model_copy(
        update={
            "status": ExternalChannelDeliveryStatus.UNKNOWN,
            "request_payload": {
                **repository.target.request_payload,
                "runtime_provider_recovery": {
                    "state": "provider_completed",
                    "provider_message_key": "slack:T1:C1:2.000001",
                    "claims": [
                        {
                            "transfer_id": "transfer-1",
                            "attempt_id": "attempt-1",
                            "consumer_claim_id": "claim-1",
                            "revision": 1,
                            "runtime_id": "runtime-1",
                            "desired_generation": 1,
                            "operation_id": "operation-1",
                            "session_id": "session-1",
                            "agent_id": "agent-1",
                            "deadline_at": _at(59).isoformat(),
                        }
                    ],
                },
            },
        }
    )
    capability = _RuntimeProviderCapability({})
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

    result = await service.attempt_delivery(
        "delivery-1",
        provider_delivery_capability=cast(
            RuntimeToProviderDeliveryCapability,
            capability,
        ),
    )

    assert result is ExternalChannelDeliveryStatus.DELIVERED
    assert capability.requests == []
    assert len(capability.recoveries) == 1
    assert "provider" not in events
    assert repository.finished == [
        (
            ExternalChannelDeliveryStatus.DELIVERED,
            "slack:T1:C1:2.000001",
            None,
        )
    ]


@pytest.mark.asyncio
async def test_runtime_settlement_recovery_persists_advanced_claim_revision() -> None:
    """A failed exact recovery retains its observed claim revision."""
    events: list[str] = []
    repository = _RepositoryDouble(events)
    repository.target = repository.target.model_copy(
        update={
            "status": ExternalChannelDeliveryStatus.DELIVERED,
            "request_payload": {
                **repository.target.request_payload,
                "runtime_provider_recovery": {
                    "state": "provider_completed",
                    "provider_message_key": "slack:T1:C1:2.000001",
                    "claims": [
                        {
                            "transfer_id": "transfer-1",
                            "attempt_id": "attempt-1",
                            "consumer_claim_id": "claim-1",
                            "revision": 1,
                            "runtime_id": "runtime-1",
                            "desired_generation": 1,
                            "operation_id": "operation-1",
                            "session_id": "session-1",
                            "agent_id": "agent-1",
                            "deadline_at": _at(59).isoformat(),
                        }
                    ],
                },
            },
        }
    )
    advanced_recoveries = (
        RuntimeToProviderRecovery(
            transfer_id="transfer-1",
            attempt_id="attempt-1",
            consumer_claim_id="claim-1",
            revision=2,
            runtime_id="runtime-1",
            desired_generation=1,
            operation_id="operation-1",
            session_id="session-1",
            agent_id="agent-1",
            deadline_at=_at(59),
        ),
    )
    capability = _RuntimeProviderCapability(
        {},
        recovery_error=RuntimeToProviderRecoveryError(
            "settlement pending",
            recoveries=advanced_recoveries,
        ),
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

    result = await service.attempt_delivery(
        "delivery-1",
        provider_delivery_capability=cast(
            RuntimeToProviderDeliveryCapability,
            capability,
        ),
    )

    assert result is ExternalChannelDeliveryStatus.DELIVERED
    assert capability.requests == []
    assert capability.recoveries == [
        (
            RuntimeToProviderRecovery(
                transfer_id="transfer-1",
                attempt_id="attempt-1",
                consumer_claim_id="claim-1",
                revision=1,
                runtime_id="runtime-1",
                desired_generation=1,
                operation_id="operation-1",
                session_id="session-1",
                agent_id="agent-1",
                deadline_at=_at(59),
            ),
        )
    ]
    assert repository.runtime_provider_states == [
        (
            "provider_completed",
            {
                "claims": [
                    {
                        "transfer_id": "transfer-1",
                        "attempt_id": "attempt-1",
                        "consumer_claim_id": "claim-1",
                        "revision": 2,
                        "runtime_id": "runtime-1",
                        "desired_generation": 1,
                        "operation_id": "operation-1",
                        "session_id": "session-1",
                        "agent_id": "agent-1",
                        "deadline_at": _at(59).isoformat(),
                    }
                ],
                "provider_message_key": "slack:T1:C1:2.000001",
            },
        )
    ]
    assert "provider" not in events


@pytest.mark.asyncio
async def test_runtime_settlement_drain_recovers_completed_delivery_without_slack() -> (
    None
):
    """The durable drain settles only persisted provider completion claims."""
    events: list[str] = []
    repository = _RepositoryDouble(events)
    repository.runtime_settlement_delivery_ids = ["delivery-1"]
    repository.target = repository.target.model_copy(
        update={
            "status": ExternalChannelDeliveryStatus.DELIVERED,
            "request_payload": {
                **repository.target.request_payload,
                "runtime_provider_recovery": {
                    "state": "provider_completed",
                    "provider_message_key": "slack:T1:C1:2.000001",
                    "claims": [
                        {
                            "transfer_id": "transfer-1",
                            "attempt_id": "attempt-1",
                            "consumer_claim_id": "claim-1",
                            "revision": 1,
                            "runtime_id": "runtime-1",
                            "desired_generation": 1,
                            "operation_id": "operation-1",
                            "session_id": "session-1",
                            "agent_id": "agent-1",
                            "deadline_at": _at(59).isoformat(),
                        }
                    ],
                },
            },
        }
    )
    capability = _RuntimeProviderCapability({})
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

    recovered = await service.drain_runtime_provider_settlements(
        provider_delivery_capability=cast(
            RuntimeToProviderDeliveryCapability,
            capability,
        ),
    )

    assert recovered == 1
    assert capability.requests == []
    assert len(capability.recoveries) == 1
    assert "provider" not in events
    assert [state for state, _ in repository.runtime_provider_states] == ["settled"]


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
