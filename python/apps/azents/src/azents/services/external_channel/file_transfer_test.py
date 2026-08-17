"""Explicit External Channel inbound file-transfer tests."""

import datetime
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, cast
from unittest.mock import AsyncMock

import grpc
import pytest
from azcommon.infra.s3.service import S3TransferCleanupRequired
from azcommon.result import Failure, Success
from azents_runtime_control.grpc_transfer_coordinator_client import (
    CoordinatorTransferFailure,
)
from fastapi import Depends
from fastapi.dependencies.utils import get_dependant
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExchangeFileOrigin,
    ExchangeFileProvenanceKind,
    ExchangeFileStatus,
    ExternalChannelProvider,
)
from azents.core.external_channel_file import (
    EXTERNAL_CHANNEL_FILE_STREAM_CHUNK_BYTES,
    ExternalChannelFileLocator,
    ExternalChannelFileMetadata,
    ExternalChannelFileUnsupportedReason,
    ExternalChannelOutboundFileManifest,
    ExternalChannelOutboundFileSource,
)
from azents.core.external_channel_file_system_setting import (
    ExternalChannelFilesConfig,
    ExternalChannelFilesSecrets,
)
from azents.core.system_setting import ResolvedSystemSetting, SystemSettingSection
from azents.engine.io.attachments import RuntimeAttachment
from azents.rdb.session import SessionManager
from azents.repos.exchange_file.data import ExchangeFile
from azents.repos.external_channel.work import ExternalChannelWorkRepository
from azents.repos.external_channel.work_data import (
    ExternalChannelFileAccessTarget,
)
from azents.runtime.transfer.provider_source import (
    DeferredProviderServerToRuntimeSource,
    ProviderByteStreamResponse,
    ProviderStagingStore,
)
from azents.runtime.transfer.server_to_runtime import (
    ServerToRuntimeTarget,
    ServerToRuntimeTransferError,
    ServerToRuntimeTransferRequest,
)
from azents.services.exchange_file import (
    ExchangeFileDownload,
    ExchangeFileService,
    FileAccessDenied,
)
from azents.services.external_channel.credentials import ExternalChannelCredentialsCodec
from azents.services.external_channel.data import SlackConnectionCredentials
from azents.services.external_channel.discord_files import (
    DiscordAttachmentDownloadInfo,
    DiscordChannelClient,
    DiscordFileCredentialsInvalid,
    DiscordFileNotFound,
    DiscordFilePermissionDenied,
    DiscordFileTemporaryError,
    DiscordFileTooLarge,
)
from azents.services.external_channel.file_transfer import (
    ExternalChannelFileDownloadResult,
    ExternalChannelFileTransferError,
    ExternalChannelFileTransferExecutionError,
    ExternalChannelFileTransferService,
    ExternalChannelInboundStagingConfiguration,
    ServerToRuntimeTransferExecutor,
    iter_external_channel_outbound_file_chunks,
)
from azents.services.external_channel.slack_events import (
    SlackConversationClient,
    SlackFileDownloadInfo,
    SlackProviderCredentialsInvalid,
    SlackProviderFileNotFound,
    SlackProviderFileTooLarge,
    SlackProviderPermissionDenied,
    SlackProviderTemporaryError,
)
from azents.services.file_storage import FileStorage, RangedFileStorage
from azents.services.session_resource_authority import SessionResourceAuthority
from azents.services.system_setting.service import SystemSettingsService

_NOW = datetime.datetime.now(datetime.UTC)


class _Repository:
    def __init__(
        self,
        target: ExternalChannelFileAccessTarget | None,
    ) -> None:
        self.target = target
        self.calls: list[tuple[str, str, str]] = []

    async def get_active_file_access_target(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        agent_id: str,
        binding_id: str,
    ) -> ExternalChannelFileAccessTarget | None:
        del session
        self.calls.append((session_id, agent_id, binding_id))
        return self.target


def test_file_transfer_dependency_graph_allows_unconfigured_inbound_staging() -> None:
    """Non-Worker graphs explicitly disable Worker-only provider staging."""

    def endpoint(
        service: Annotated[
            ExternalChannelFileTransferService,
            Depends(ExternalChannelFileTransferService),
        ],
    ) -> None:
        del service

    assert get_dependant(path="/", call=endpoint).dependencies


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
        *,
        info: SlackFileDownloadInfo | None = None,
        chunks: tuple[bytes, ...] = (b"content",),
        info_error: Exception | None = None,
        download_error: Exception | None = None,
        stream_error: Exception | None = None,
    ) -> None:
        self.info = info or _file_info()
        self.chunks = chunks
        self.info_error = info_error
        self.download_error = download_error
        self.stream_error = stream_error
        self.info_file_ids: list[str] = []
        self.stream_limits: list[tuple[int, int]] = []
        self.stream_opened = 0
        self.stream_closed = 0

    async def fetch_file_download_info(
        self,
        *,
        bot_token: str,
        provider_file_id: str,
    ) -> SlackFileDownloadInfo:
        assert bot_token == "xoxb-secret"
        self.info_file_ids.append(provider_file_id)
        if self.info_error is not None:
            raise self.info_error
        return self.info

    async def fetch_private_file_content_length(
        self, *, bot_token: str, private_url: str, max_bytes: int
    ) -> int:
        del bot_token, private_url
        size = sum(len(chunk) for chunk in self.chunks)
        if size > max_bytes:
            raise SlackProviderFileTooLarge("oversize")
        return size

    @asynccontextmanager
    async def open_private_file_stream(
        self,
        *,
        bot_token: str,
        private_url: str,
        max_bytes: int,
        maximum_chunk_size: int,
    ) -> AsyncGenerator[ProviderByteStreamResponse, None]:
        assert bot_token == "xoxb-secret"
        assert private_url == "https://files.slack.test/private/F123"
        self.stream_limits.append((max_bytes, maximum_chunk_size))
        if self.download_error is not None:
            raise self.download_error
        self.stream_opened += 1

        async def iterator() -> AsyncIterator[bytes]:
            for chunk in self.chunks:
                assert len(chunk) <= maximum_chunk_size
                yield chunk
            if self.stream_error is not None:
                raise self.stream_error

        try:
            yield ProviderByteStreamResponse(
                content_length=sum(len(chunk) for chunk in self.chunks),
                chunks=iterator(),
            )
        finally:
            self.stream_closed += 1


class _TransferService:
    """Capture terminal-success transfer requests without Runtime file writes."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.requests: list[ServerToRuntimeTransferRequest] = []

    async def transfer(self, request: ServerToRuntimeTransferRequest) -> None:
        self.requests.append(request)
        if self.error is not None:
            raise self.error


class _DiscordClient:
    def __init__(
        self,
        *,
        info: DiscordAttachmentDownloadInfo | None = None,
        chunks: tuple[bytes, ...] = (b"content",),
        info_error: Exception | None = None,
        download_error: Exception | None = None,
        stream_error: Exception | None = None,
    ) -> None:
        self.info = info or _discord_file_info()
        self.chunks = chunks
        self.info_error = info_error
        self.download_error = download_error
        self.stream_error = stream_error
        self.fetch_calls: list[tuple[str, str, str, str]] = []
        self.download_urls: list[str] = []
        self.stream_limits: list[tuple[int, int]] = []
        self.stream_opened = 0
        self.stream_closed = 0

    async def fetch_attachment_download_info(
        self,
        *,
        bot_token: str,
        guild_id: str,
        channel_id: str,
        message_id: str,
        attachment_id: str,
    ) -> DiscordAttachmentDownloadInfo:
        assert bot_token == "xoxb-secret"
        self.fetch_calls.append((guild_id, channel_id, message_id, attachment_id))
        if self.info_error is not None:
            raise self.info_error
        return self.info

    async def fetch_attachment_content_length(
        self, *, download_url: str, max_bytes: int
    ) -> int:
        del download_url
        size = sum(len(chunk) for chunk in self.chunks)
        if size > max_bytes:
            raise DiscordFileTooLarge("oversize")
        return size

    @asynccontextmanager
    async def open_attachment_stream(
        self,
        *,
        download_url: str,
        max_bytes: int,
        maximum_chunk_size: int,
    ) -> AsyncGenerator[ProviderByteStreamResponse, None]:
        self.download_urls.append(download_url)
        self.stream_limits.append((max_bytes, maximum_chunk_size))
        if self.download_error is not None:
            raise self.download_error
        self.stream_opened += 1

        async def iterator() -> AsyncIterator[bytes]:
            for chunk in self.chunks:
                assert len(chunk) <= maximum_chunk_size
                yield chunk
            if self.stream_error is not None:
                raise self.stream_error

        try:
            yield ProviderByteStreamResponse(
                content_length=sum(len(chunk) for chunk in self.chunks),
                chunks=iterator(),
            )
        finally:
            self.stream_closed += 1


class _SystemSettings:
    def __init__(
        self,
        inbound_limit: int = 100,
        outbound_file_limit: int = 100,
        outbound_action_limit: int = 100,
    ) -> None:
        self.inbound_limit = inbound_limit
        self.outbound_file_limit = outbound_file_limit
        self.outbound_action_limit = outbound_action_limit

    async def resolve(
        self,
        section: SystemSettingSection,
    ) -> ResolvedSystemSetting:
        assert section is SystemSettingSection.EXTERNAL_CHANNEL_FILES
        return ResolvedSystemSetting(
            section=section,
            schema_version=1,
            admin_version=0,
            config=ExternalChannelFilesConfig(
                inbound_max_file_bytes=self.inbound_limit,
                outbound_max_file_bytes=self.outbound_file_limit,
                outbound_max_action_bytes=self.outbound_action_limit,
            ),
            secrets=ExternalChannelFilesSecrets(),
            field_sources={},
            effective_generation="generation",
        )


class _FileStorage:
    def __init__(
        self,
        *,
        exists: bool = False,
        put_error: Exception | None = None,
        exists_error: Exception | None = None,
    ) -> None:
        self.existing = exists
        self.put_error = put_error
        self.exists_error = exists_error
        self.put_calls: list[tuple[str, bytes, str, str]] = []

    async def exists(self, path: str, *, agent_id: str) -> bool:
        assert path == "/workspace/agent/report.csv"
        assert agent_id == "agent-1"
        if self.exists_error is not None:
            raise self.exists_error
        return self.existing

    async def put(
        self,
        path: str,
        data: bytes,
        media_type: str = "",
        *,
        agent_id: str,
    ) -> RuntimeAttachment:
        if self.put_error is not None:
            raise self.put_error
        self.put_calls.append((path, data, media_type, agent_id))
        return RuntimeAttachment(
            uri=path,
            media_type=media_type,
            size=len(data),
            name="report.csv",
            text_preview=None,
        )


class _OutboundStorage:
    def __init__(
        self,
        files: dict[str, bytes],
        *,
        metadata: dict[str, dict[str, object]] | None = None,
    ) -> None:
        self.files = files
        default_metadata: dict[str, dict[str, object]] = {
            path: {"is_file": True, "size": len(body)} for path, body in files.items()
        }
        self.metadata = metadata if metadata is not None else default_metadata
        self.stat_calls: list[tuple[str, str]] = []
        self.read_calls: list[tuple[str, str, int, int]] = []

    async def stat(self, path: str, *, agent_id: str) -> dict[str, object]:
        self.stat_calls.append((path, agent_id))
        if path not in self.metadata:
            raise FileNotFoundError(path)
        return self.metadata[path]

    async def read_range(
        self,
        path: str,
        *,
        agent_id: str,
        offset: int,
        max_bytes: int,
    ) -> bytes:
        self.read_calls.append((path, agent_id, offset, max_bytes))
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path][offset : offset + max_bytes]


@asynccontextmanager
async def _session_manager() -> AsyncGenerator[AsyncSession]:
    yield cast(AsyncSession, object())


def _capabilities(
    *,
    provider: ExternalChannelProvider = ExternalChannelProvider.SLACK,
    download_files: bool = True,
    upload_files: bool = False,
) -> dict[str, object]:
    return {
        "provider": provider.value,
        "transport": "http",
        "inbound_events": True,
        "thread_history": True,
        "post_messages": True,
        "update_messages": True,
        "delete_messages": True,
        "download_files": download_files,
        "upload_files": upload_files,
    }


def _target(
    *,
    provider: ExternalChannelProvider = ExternalChannelProvider.SLACK,
    capabilities: dict[str, object] | None = None,
) -> ExternalChannelFileAccessTarget:
    return ExternalChannelFileAccessTarget(
        binding_id="binding-1",
        connection_id="connection-1",
        resource_id="resource-1",
        provider=provider,
        encrypted_credentials="ciphertext",
        provider_tenant_id="111",
        capabilities=(
            _capabilities(provider=provider) if capabilities is None else capabilities
        ),
        resource_labels=(
            {
                "provider": "discord",
                "guild_id": "111",
                "thread_id": "333",
                "parent_channel_id": "222",
            }
            if provider is ExternalChannelProvider.DISCORD
            else None
        ),
    )


def _file_info(
    *,
    provider_file_id: str = "F123",
    declared_size: int | None = 7,
    supported: bool = True,
) -> SlackFileDownloadInfo:
    return SlackFileDownloadInfo(
        metadata=ExternalChannelFileMetadata(
            provider=ExternalChannelProvider.SLACK,
            provider_file_id=provider_file_id,
            name="report.csv",
            title="Report",
            media_type="text/csv",
            declared_size=declared_size,
            mode="hosted",
            external=not supported,
            file_access=None,
            supported=supported,
            unsupported_reason=(
                None
                if supported
                else ExternalChannelFileUnsupportedReason.EXTERNAL_FILE
            ),
        ),
        private_url="https://files.slack.test/private/F123",
    )


def _discord_file_info(
    *,
    provider_file_id: str = "555",
    declared_size: int | None = 7,
    download_url: str
    | None = "https://cdn.discordapp.com/attachments/333/555/report.csv",
) -> DiscordAttachmentDownloadInfo:
    return DiscordAttachmentDownloadInfo(
        metadata=ExternalChannelFileMetadata(
            provider=ExternalChannelProvider.DISCORD,
            provider_file_id=provider_file_id,
            name="report.csv",
            title=None,
            media_type="text/csv",
            declared_size=declared_size,
            mode=None,
            external=False,
            file_access=None,
            supported=True,
            unsupported_reason=None,
        ),
        download_url=download_url,
    )


def _service(
    *,
    repository: _Repository,
    slack_client: _SlackClient,
    discord_client: _DiscordClient | None = None,
    settings: _SystemSettings | None = None,
    exchange_file_service: AsyncMock | None = None,
    staging_configuration: ExternalChannelInboundStagingConfiguration | None = None,
) -> ExternalChannelFileTransferService:
    return ExternalChannelFileTransferService(
        session_manager=cast(SessionManager[AsyncSession], _session_manager),
        repository=cast(ExternalChannelWorkRepository, repository),
        credentials_codec=cast(
            ExternalChannelCredentialsCodec,
            _CredentialsCodec(),
        ),
        slack_client=cast(SlackConversationClient, slack_client),
        discord_client=cast(DiscordChannelClient, discord_client or _DiscordClient()),
        exchange_file_service=cast(
            ExchangeFileService,
            exchange_file_service or AsyncMock(),
        ),
        system_settings=cast(
            SystemSettingsService,
            settings or _SystemSettings(),
        ),
        inbound_staging_configuration=(
            staging_configuration
            or ExternalChannelInboundStagingConfiguration(
                s3_service=cast(ProviderStagingStore, object()),
                workspace_bucket="workspace",
                transfer_object_prefix="runtime-transfer",
                stream_chunk_size=4,
                multipart_part_size=4,
                multipart_copy_threshold=4,
                multipart_copy_part_size=4,
                deadline_after=datetime.timedelta(minutes=5),
            )
        ),
    )


def _locator(provider_file_id: str = "F123") -> str:
    return ExternalChannelFileLocator(
        provider=ExternalChannelProvider.SLACK,
        binding_id="binding-1",
        provider_file_id=provider_file_id,
    ).encode()


def _discord_locator(provider_file_id: str = "555") -> str:
    return ExternalChannelFileLocator(
        provider=ExternalChannelProvider.DISCORD,
        binding_id="binding-1",
        provider_file_id=provider_file_id,
        provider_channel_id="333",
        provider_message_id="444",
    ).encode()


async def _download(
    service: ExternalChannelFileTransferService,
    *,
    transfer: _TransferService | None = None,
    session_id: str,
    agent_id: str,
    operation_id: str = "run-1",
    file: str,
    path: str,
    overwrite: bool,
    file_storage: FileStorage,
) -> ExternalChannelFileDownloadResult:
    """Invoke one inbound transfer with an explicit Runtime target."""
    executor = transfer or _TransferService()
    return await service.download(
        session_id=session_id,
        agent_id=agent_id,
        operation_id=operation_id,
        file=file,
        path=path,
        overwrite=overwrite,
        file_storage=file_storage,
        transfer_service=cast(ServerToRuntimeTransferExecutor, executor),
        transfer_target=ServerToRuntimeTarget(
            runtime_id="runtime-1",
            desired_generation=1,
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
        retention_bound_at=_NOW,
        preview_thumbnail_file_id=None,
        preview_thumbnail_uri=None,
        preview_title="generated.png",
        preview_summary=None,
        preview_thumbnail_media_type=None,
        preview_thumbnail_width=None,
        preview_thumbnail_height=None,
        preview_generated_at=None,
        expires_at=_NOW + datetime.timedelta(days=7),
        expired_at=None,
        blob_deleted_at=None,
        created_at=_NOW,
    )


@pytest.mark.asyncio
async def test_download_materializes_only_selected_current_provider_file() -> None:
    """The locator file ID is provider-authoritative within the active binding."""
    repository = _Repository(_target())
    slack_client = _SlackClient(
        info=_file_info(provider_file_id="F-MODIFIED"),
    )
    storage = _FileStorage()
    service = _service(repository=repository, slack_client=slack_client)
    transfer = _TransferService()

    result = await _download(
        service,
        transfer=transfer,
        session_id="session-1",
        agent_id="agent-1",
        file=_locator("F-MODIFIED"),
        path="/workspace/agent/report.csv",
        overwrite=False,
        file_storage=cast(FileStorage, storage),
    )

    assert result.path == "/workspace/agent/report.csv"
    assert result.filename == "report.csv"
    assert result.media_type == "text/csv"
    assert result.bytes_written == 7
    assert repository.calls == [("session-1", "agent-1", "binding-1")]
    assert slack_client.info_file_ids == ["F-MODIFIED"]
    assert slack_client.stream_opened == 0
    assert storage.put_calls == []
    request = transfer.requests[0]
    assert request.destination == "/workspace/agent/report.csv"
    assert request.source.metadata.size == 7


@pytest.mark.asyncio
async def test_inactive_binding_fails_before_provider_access() -> None:
    """An unrelated or inactive locator never reaches Slack."""
    slack_client = _SlackClient()
    service = _service(repository=_Repository(None), slack_client=slack_client)

    with pytest.raises(ExternalChannelFileTransferError, match="not active"):
        await _download(
            service,
            session_id="session-1",
            agent_id="agent-1",
            file=_locator(),
            path="/workspace/agent/report.csv",
            overwrite=False,
            file_storage=cast(FileStorage, _FileStorage()),
        )

    assert slack_client.info_file_ids == []


@pytest.mark.asyncio
async def test_relative_runtime_destination_is_rejected() -> None:
    """The provider is not contacted for a non-absolute Runtime path."""
    repository = _Repository(_target())
    slack_client = _SlackClient()
    service = _service(repository=repository, slack_client=slack_client)

    with pytest.raises(ExternalChannelFileTransferError, match="must be absolute"):
        await _download(
            service,
            session_id="session-1",
            agent_id="agent-1",
            file=_locator(),
            path="report.csv",
            overwrite=False,
            file_storage=cast(FileStorage, _FileStorage()),
        )

    assert repository.calls == []
    assert slack_client.info_file_ids == []


@pytest.mark.asyncio
async def test_missing_download_capability_fails_before_provider_access() -> None:
    """Text-capable connections without files:read reject only the file Tool."""
    slack_client = _SlackClient()
    service = _service(
        repository=_Repository(
            _target(capabilities=_capabilities(download_files=False))
        ),
        slack_client=slack_client,
    )

    with pytest.raises(ExternalChannelFileTransferError, match="cannot download"):
        await _download(
            service,
            session_id="session-1",
            agent_id="agent-1",
            file=_locator(),
            path="/workspace/agent/report.csv",
            overwrite=False,
            file_storage=cast(FileStorage, _FileStorage()),
        )

    assert slack_client.info_file_ids == []


@pytest.mark.asyncio
async def test_existing_destination_fails_before_provider_access() -> None:
    """Overwrite remains explicit and avoids an unnecessary provider read."""
    slack_client = _SlackClient()
    service = _service(repository=_Repository(_target()), slack_client=slack_client)

    with pytest.raises(ExternalChannelFileTransferError, match="already exists"):
        await _download(
            service,
            session_id="session-1",
            agent_id="agent-1",
            file=_locator(),
            path="/workspace/agent/report.csv",
            overwrite=False,
            file_storage=cast(FileStorage, _FileStorage(exists=True)),
        )

    assert slack_client.info_file_ids == []


@pytest.mark.asyncio
async def test_inaccessible_destination_fails_before_provider_access() -> None:
    """Destination read-only preflight retains the External Channel contract."""
    slack_client = _SlackClient()
    service = _service(repository=_Repository(_target()), slack_client=slack_client)

    with pytest.raises(ExternalChannelFileTransferError, match="not accessible"):
        await _download(
            service,
            session_id="session-1",
            agent_id="agent-1",
            file=_locator(),
            path="/workspace/agent/report.csv",
            overwrite=False,
            file_storage=cast(
                FileStorage,
                _FileStorage(exists_error=PermissionError("read-only")),
            ),
        )

    assert slack_client.info_file_ids == []


@pytest.mark.asyncio
async def test_explicit_overwrite_skips_existence_rejection() -> None:
    """Explicit overwrite permits the existing Runtime destination policy."""
    slack_client = _SlackClient()
    storage = _FileStorage(exists=True)
    service = _service(
        repository=_Repository(_target()),
        slack_client=slack_client,
    )

    transfer = _TransferService()
    result = await _download(
        service,
        transfer=transfer,
        session_id="session-1",
        agent_id="agent-1",
        file=_locator(),
        path="/workspace/agent/report.csv",
        overwrite=True,
        file_storage=cast(FileStorage, storage),
    )

    assert result.bytes_written == 7
    assert slack_client.info_file_ids == ["F123"]
    assert storage.put_calls == []
    assert transfer.requests[0].overwrite is True


@pytest.mark.asyncio
async def test_slack_metadata_size_does_not_gate_download_or_revalidation() -> None:
    """Only the authenticated final URL declares the Slack transfer size."""
    storage = _FileStorage()
    slack_client = _SlackClient(info=_file_info(declared_size=101))
    service = _service(
        repository=_Repository(_target()),
        slack_client=slack_client,
    )
    transfer = _TransferService()

    result = await _download(
        service,
        transfer=transfer,
        session_id="session-1",
        agent_id="agent-1",
        file=_locator(),
        path="/workspace/agent/report.csv",
        overwrite=False,
        file_storage=cast(FileStorage, storage),
    )

    assert result.bytes_written == 7
    assert transfer.requests[0].source.metadata.size == 7
    slack_client.info = _file_info(declared_size=None)
    source = transfer.requests[0].source
    assert isinstance(source, DeferredProviderServerToRuntimeSource)
    assert await source.revalidate_authority()
    assert storage.put_calls == []


@pytest.mark.asyncio
async def test_slack_final_length_limit_and_body_mismatch_never_write() -> None:
    """HEAD size and streamed bytes independently protect Runtime admission."""
    oversize_storage = _FileStorage()
    oversize_service = _service(
        repository=_Repository(_target()),
        slack_client=_SlackClient(chunks=(b"x" * 101,)),
    )
    with pytest.raises(ExternalChannelFileTransferError, match="100 bytes"):
        await _download(
            oversize_service,
            session_id="session-1",
            agent_id="agent-1",
            file=_locator(),
            path="/workspace/agent/report.csv",
            overwrite=False,
            file_storage=cast(FileStorage, oversize_storage),
        )

    mismatch_storage = _FileStorage()
    mismatch_service = _service(
        repository=_Repository(_target()),
        slack_client=_SlackClient(),
    )
    with pytest.raises(ExternalChannelFileTransferError, match="Content-Length"):
        await _download(
            mismatch_service,
            transfer=_TransferService(
                ValueError("Provider stream size does not match the manifest")
            ),
            session_id="session-1",
            agent_id="agent-1",
            file=_locator(),
            path="/workspace/agent/report.csv",
            overwrite=False,
            file_storage=cast(FileStorage, mismatch_storage),
        )

    assert oversize_storage.put_calls == []
    assert mismatch_storage.put_calls == []


@pytest.mark.asyncio
async def test_unsupported_or_missing_provider_file_never_writes_runtime() -> None:
    """Fail-closed Slack modes and deleted files remain controlled Tool failures."""
    unsupported_storage = _FileStorage()
    unsupported_service = _service(
        repository=_Repository(_target()),
        slack_client=_SlackClient(info=_file_info(supported=False)),
    )
    with pytest.raises(ExternalChannelFileTransferError, match="external_file"):
        await _download(
            unsupported_service,
            session_id="session-1",
            agent_id="agent-1",
            file=_locator(),
            path="/workspace/agent/report.csv",
            overwrite=False,
            file_storage=cast(FileStorage, unsupported_storage),
        )

    missing_storage = _FileStorage()
    missing_service = _service(
        repository=_Repository(_target()),
        slack_client=_SlackClient(info_error=SlackProviderFileNotFound("missing")),
    )
    with pytest.raises(ExternalChannelFileTransferError, match="no longer exposes"):
        await _download(
            missing_service,
            session_id="session-1",
            agent_id="agent-1",
            file=_locator(),
            path="/workspace/agent/report.csv",
            overwrite=False,
            file_storage=cast(FileStorage, missing_storage),
        )

    assert unsupported_storage.put_calls == []
    assert missing_storage.put_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider_error", "message"),
    [
        (
            SlackProviderPermissionDenied("denied"),
            "denied access",
        ),
        (
            SlackProviderCredentialsInvalid("revoked"),
            "rejected the active",
        ),
        (
            SlackProviderTemporaryError("temporary"),
            "temporarily unavailable",
        ),
    ],
)
async def test_provider_failures_are_controlled_without_runtime_write(
    provider_error: Exception,
    message: str,
) -> None:
    """Provider denial, revocation, and transport failures leave no destination."""
    storage = _FileStorage()
    service = _service(
        repository=_Repository(_target()),
        slack_client=_SlackClient(info_error=provider_error),
    )

    with pytest.raises(ExternalChannelFileTransferError, match=message):
        await _download(
            service,
            session_id="session-1",
            agent_id="agent-1",
            file=_locator(),
            path="/workspace/agent/report.csv",
            overwrite=False,
            file_storage=cast(FileStorage, storage),
        )

    assert storage.put_calls == []


@pytest.mark.asyncio
async def test_terminal_runtime_failure_is_not_reported_as_success() -> None:
    """A non-success terminal Runtime result never produces file success."""
    service = _service(
        repository=_Repository(_target()),
        slack_client=_SlackClient(),
    )

    with pytest.raises(
        ExternalChannelFileTransferExecutionError,
        match="Runtime file",
    ) as raised:
        await _download(
            service,
            transfer=_TransferService(
                ServerToRuntimeTransferError(
                    "Runtime transfer failed before destination commit"
                )
            ),
            session_id="session-1",
            agent_id="agent-1",
            file=_locator(),
            path="/workspace/agent/report.csv",
            overwrite=False,
            file_storage=cast(FileStorage, _FileStorage()),
        )

    assert raised.value.failure.stage == "runtime_transfer"
    assert raised.value.failure.cause == "ServerToRuntimeTransferError"
    assert raised.value.failure.detail == (
        "Runtime transfer failed before destination commit"
    )
    assert raised.value.failure.coordinator_failure is None


@pytest.mark.asyncio
async def test_runtime_grpc_transport_failure_is_controlled() -> None:
    """Do not expose coordinator transport details through file download."""
    metadata = grpc.aio.Metadata()
    service = _service(
        repository=_Repository(_target()),
        slack_client=_SlackClient(),
    )

    with pytest.raises(
        ExternalChannelFileTransferError,
        match="Failed to write the Runtime file: /workspace/agent/report.csv",
    ) as raised:
        await _download(
            service,
            transfer=_TransferService(
                grpc.aio.AioRpcError(
                    grpc.StatusCode.UNAVAILABLE,
                    metadata,
                    metadata,
                    "coordinator endpoint unavailable",
                    None,
                )
            ),
            session_id="session-1",
            agent_id="agent-1",
            file=_locator(),
            path="/workspace/agent/report.csv",
            overwrite=False,
            file_storage=cast(FileStorage, _FileStorage()),
        )

    assert "AioRpcError" not in str(raised.value)
    assert "coordinator endpoint unavailable" not in str(raised.value)
    assert isinstance(raised.value, ExternalChannelFileTransferExecutionError)
    assert raised.value.failure.stage == "runtime_transfer"
    assert raised.value.failure.cause == "AioRpcError"
    assert raised.value.failure.detail is None
    assert raised.value.failure.coordinator_failure is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "message"),
    [
        (
            ServerToRuntimeTransferError(
                "terminal cancellation",
                failure=CoordinatorTransferFailure.CANCELLED,
            ),
            "cancelled before destination commit",
        ),
        (
            ServerToRuntimeTransferError(
                "terminal deadline",
                failure=CoordinatorTransferFailure.EXPIRED,
            ),
            "did not complete before its deadline",
        ),
        (
            ServerToRuntimeTransferError(
                "terminal integrity",
                failure=CoordinatorTransferFailure.INTEGRITY,
            ),
            "integrity verification failed",
        ),
        (
            ServerToRuntimeTransferError(
                "terminal destination",
                failure=CoordinatorTransferFailure.CONSUMER,
            ),
            "destination is not writable",
        ),
        (
            S3TransferCleanupRequired(
                "bucket/internal-key must remain hidden",
                multipart_cleanup_required=True,
                completed_object_cleanup_required=False,
            ),
            "stage the Slack file",
        ),
    ],
)
async def test_inbound_staging_and_terminal_failures_remain_controlled(
    error: Exception,
    message: str,
) -> None:
    """Provider staging and terminal outcomes do not leak transfer internals."""
    service = _service(
        repository=_Repository(_target()),
        slack_client=_SlackClient(),
    )

    with pytest.raises(ExternalChannelFileTransferError, match=message) as raised:
        await _download(
            service,
            transfer=_TransferService(error),
            session_id="session-1",
            agent_id="agent-1",
            file=_locator(),
            path="/workspace/agent/report.csv",
            overwrite=False,
            file_storage=cast(FileStorage, _FileStorage()),
        )

    assert "bucket/internal-key" not in str(raised.value)
    assert isinstance(raised.value, ExternalChannelFileTransferExecutionError)
    if isinstance(error, ServerToRuntimeTransferError):
        assert raised.value.failure.stage == "runtime_transfer"
        assert raised.value.failure.cause == "ServerToRuntimeTransferError"
        assert raised.value.failure.detail == str(error)
        assert raised.value.failure.coordinator_failure is error.failure
    else:
        assert raised.value.failure.stage == "provider_staging_cleanup"
        assert raised.value.failure.cause == "S3TransferCleanupRequired"
        assert raised.value.failure.detail is None
        assert raised.value.failure.coordinator_failure is None


@pytest.mark.asyncio
async def test_discord_download_materializes_only_current_binding_attachment() -> None:
    """Discord uses the channel, message, and attachment IDs carried by the locator."""
    repository = _Repository(
        _target(provider=ExternalChannelProvider.DISCORD),
    )
    discord_client = _DiscordClient()
    storage = _FileStorage()
    service = _service(
        repository=repository,
        slack_client=_SlackClient(),
        discord_client=discord_client,
    )

    transfer = _TransferService()
    result = await _download(
        service,
        transfer=transfer,
        session_id="session-1",
        agent_id="agent-1",
        file=_discord_locator(),
        path="/workspace/agent/report.csv",
        overwrite=False,
        file_storage=cast(FileStorage, storage),
    )

    assert result.path == "/workspace/agent/report.csv"
    assert result.filename == "report.csv"
    assert result.media_type == "text/csv"
    assert result.bytes_written == 7
    assert discord_client.fetch_calls == [("111", "333", "444", "555")]
    assert discord_client.stream_opened == 0
    assert storage.put_calls == []
    request = transfer.requests[0]
    assert request.destination == "/workspace/agent/report.csv"
    assert request.source.metadata.canonical_uri == (
        "external-channel://discord/binding-1/555"
    )
    assert request.source.metadata.size == 7


@pytest.mark.asyncio
async def test_discord_capability_and_current_attachment_failures_never_write() -> None:
    """No source read occurs without capability; stale URLs and files stay no-write."""
    capability_repository = _Repository(
        _target(
            provider=ExternalChannelProvider.DISCORD,
            capabilities=_capabilities(
                provider=ExternalChannelProvider.DISCORD,
                download_files=False,
            ),
        ),
    )
    capability_client = _DiscordClient()
    capability_service = _service(
        repository=capability_repository,
        slack_client=_SlackClient(),
        discord_client=capability_client,
    )
    with pytest.raises(ExternalChannelFileTransferError, match="cannot download"):
        await _download(
            capability_service,
            session_id="session-1",
            agent_id="agent-1",
            file=_discord_locator(),
            path="/workspace/agent/report.csv",
            overwrite=False,
            file_storage=cast(FileStorage, _FileStorage()),
        )

    url_storage = _FileStorage()
    url_service = _service(
        repository=_Repository(
            _target(provider=ExternalChannelProvider.DISCORD),
        ),
        slack_client=_SlackClient(),
        discord_client=_DiscordClient(info=_discord_file_info(download_url=None)),
    )
    with pytest.raises(ExternalChannelFileTransferError, match="download target"):
        await _download(
            url_service,
            session_id="session-1",
            agent_id="agent-1",
            file=_discord_locator(),
            path="/workspace/agent/report.csv",
            overwrite=False,
            file_storage=cast(FileStorage, url_storage),
        )

    deleted_storage = _FileStorage()
    deleted_service = _service(
        repository=_Repository(
            _target(provider=ExternalChannelProvider.DISCORD),
        ),
        slack_client=_SlackClient(),
        discord_client=_DiscordClient(info_error=DiscordFileNotFound("deleted")),
    )
    with pytest.raises(ExternalChannelFileTransferError, match="no longer exposes"):
        await _download(
            deleted_service,
            session_id="session-1",
            agent_id="agent-1",
            file=_discord_locator(),
            path="/workspace/agent/report.csv",
            overwrite=False,
            file_storage=cast(FileStorage, deleted_storage),
        )

    assert capability_client.fetch_calls == []
    assert url_storage.put_calls == []
    assert deleted_storage.put_calls == []


@pytest.mark.asyncio
async def test_discord_metadata_size_does_not_gate_download_or_revalidation() -> None:
    """Only the final CDN URL declares the Discord transfer size."""
    storage = _FileStorage()
    discord_client = _DiscordClient(info=_discord_file_info(declared_size=101))
    service = _service(
        repository=_Repository(
            _target(provider=ExternalChannelProvider.DISCORD),
        ),
        slack_client=_SlackClient(),
        discord_client=discord_client,
    )
    transfer = _TransferService()

    result = await _download(
        service,
        transfer=transfer,
        session_id="session-1",
        agent_id="agent-1",
        file=_discord_locator(),
        path="/workspace/agent/report.csv",
        overwrite=False,
        file_storage=cast(FileStorage, storage),
    )

    assert result.bytes_written == 7
    assert transfer.requests[0].source.metadata.size == 7
    discord_client.info = _discord_file_info(declared_size=None)
    source = transfer.requests[0].source
    assert isinstance(source, DeferredProviderServerToRuntimeSource)
    assert await source.revalidate_authority()
    assert storage.put_calls == []


@pytest.mark.asyncio
async def test_discord_final_length_limit_and_body_mismatch_never_write() -> None:
    """HEAD size and streamed bytes independently protect Runtime admission."""
    oversize_storage = _FileStorage()
    oversize_service = _service(
        repository=_Repository(
            _target(provider=ExternalChannelProvider.DISCORD),
        ),
        slack_client=_SlackClient(),
        discord_client=_DiscordClient(chunks=(b"x" * 101,)),
    )
    with pytest.raises(ExternalChannelFileTransferError, match="100 bytes"):
        await _download(
            oversize_service,
            session_id="session-1",
            agent_id="agent-1",
            file=_discord_locator(),
            path="/workspace/agent/report.csv",
            overwrite=False,
            file_storage=cast(FileStorage, oversize_storage),
        )

    mismatch_storage = _FileStorage()
    mismatch_service = _service(
        repository=_Repository(
            _target(provider=ExternalChannelProvider.DISCORD),
        ),
        slack_client=_SlackClient(),
        discord_client=_DiscordClient(),
    )
    with pytest.raises(ExternalChannelFileTransferError, match="Content-Length"):
        await _download(
            mismatch_service,
            transfer=_TransferService(
                ValueError("Provider stream size does not match the manifest")
            ),
            session_id="session-1",
            agent_id="agent-1",
            file=_discord_locator(),
            path="/workspace/agent/report.csv",
            overwrite=False,
            file_storage=cast(FileStorage, mismatch_storage),
        )

    assert oversize_storage.put_calls == []
    assert mismatch_storage.put_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider_error", "message"),
    [
        (DiscordFilePermissionDenied("denied"), "denied access"),
        (DiscordFileCredentialsInvalid("invalid"), "rejected the active"),
        (DiscordFileTemporaryError("temporary"), "temporarily unavailable"),
    ],
)
async def test_discord_provider_failures_are_controlled_without_runtime_write(
    provider_error: Exception,
    message: str,
) -> None:
    """Provider errors do not report success or create a partial Runtime file."""
    storage = _FileStorage()
    service = _service(
        repository=_Repository(
            _target(provider=ExternalChannelProvider.DISCORD),
        ),
        slack_client=_SlackClient(),
        discord_client=_DiscordClient(info_error=provider_error),
    )

    with pytest.raises(ExternalChannelFileTransferError, match=message):
        await _download(
            service,
            session_id="session-1",
            agent_id="agent-1",
            file=_discord_locator(),
            path="/workspace/agent/report.csv",
            overwrite=False,
            file_storage=cast(FileStorage, storage),
        )

    assert storage.put_calls == []


@pytest.mark.asyncio
async def test_outbound_preflight_builds_only_bounded_runtime_manifests() -> None:
    """Preflight stats every source and persists no bytes or provider details."""
    storage = _OutboundStorage(
        {
            "/workspace/agent/report.csv": b"report",
            "/workspace/agent/chart.png": b"png",
        }
    )
    service = _service(
        repository=_Repository(_target(capabilities=_capabilities(upload_files=True))),
        slack_client=_SlackClient(),
        settings=_SystemSettings(
            outbound_file_limit=10,
            outbound_action_limit=10,
        ),
    )

    manifests = await service.prepare_outbound(
        session_id="session-1",
        agent_id="agent-1",
        binding_id="binding-1",
        paths=[
            "/workspace/agent/report.csv",
            "/workspace/agent/chart.png",
        ],
        file_storage=cast(FileStorage, storage),
    )

    assert [item.model_dump(mode="json") for item in manifests] == [
        {
            "source": "runtime",
            "path": "/workspace/agent/report.csv",
            "filename": "report.csv",
            "media_type": "text/csv",
            "expected_size": 6,
        },
        {
            "source": "runtime",
            "path": "/workspace/agent/chart.png",
            "filename": "chart.png",
            "media_type": "image/png",
            "expected_size": 3,
        },
    ]
    assert storage.stat_calls == [
        ("/workspace/agent/report.csv", "agent-1"),
        ("/workspace/agent/chart.png", "agent-1"),
    ]
    assert storage.read_calls == []


@pytest.mark.asyncio
async def test_outbound_preflight_supports_authorized_exchange_file() -> None:
    """Exchange publication shares file limits without managed Runtime storage."""
    exchange_file = _exchange_file()
    exchange_file_service = AsyncMock()
    exchange_file_service.resolve_for_authority.return_value = Success(
        ExchangeFileDownload(file=exchange_file, body=b"pngdata")
    )
    service = _service(
        repository=_Repository(_target(capabilities=_capabilities(upload_files=True))),
        slack_client=_SlackClient(),
        settings=_SystemSettings(
            outbound_file_limit=10,
            outbound_action_limit=10,
        ),
        exchange_file_service=exchange_file_service,
    )

    manifests = await service.prepare_outbound(
        session_id="session-1",
        agent_id="agent-1",
        binding_id="binding-1",
        paths=[exchange_file.uri],
        file_storage=None,
        authority=_authority(),
    )

    assert manifests == (
        ExternalChannelOutboundFileManifest(
            source=ExternalChannelOutboundFileSource.EXCHANGE,
            path=exchange_file.uri,
            filename="generated.png",
            media_type="image/png",
            expected_size=7,
        ),
    )
    exchange_file_service.resolve_for_authority.assert_awaited_once_with(
        uri=exchange_file.uri,
        authority=_authority(),
    )


@pytest.mark.asyncio
async def test_outbound_preflight_requires_runtime_storage_only_for_runtime_paths() -> (
    None
):
    """Runtime and mixed sources fail precisely when Runtime storage is absent."""
    exchange_file = _exchange_file()
    exchange_file_service = AsyncMock()
    exchange_file_service.resolve_for_authority.return_value = Success(
        ExchangeFileDownload(file=exchange_file, body=b"pngdata")
    )
    service = _service(
        repository=_Repository(_target(capabilities=_capabilities(upload_files=True))),
        slack_client=_SlackClient(),
        exchange_file_service=exchange_file_service,
    )

    for paths in (
        ["/workspace/agent/report.csv"],
        [exchange_file.uri, "/workspace/agent/report.csv"],
    ):
        with pytest.raises(
            ExternalChannelFileTransferError,
            match="require Runtime file storage",
        ):
            await service.prepare_outbound(
                session_id="session-1",
                agent_id="agent-1",
                binding_id="binding-1",
                paths=paths,
                file_storage=None,
                authority=_authority(),
            )
    exchange_file_service.resolve_for_authority.assert_not_awaited()


@pytest.mark.asyncio
async def test_outbound_preflight_rejects_unavailable_exchange_and_other_uris() -> None:
    """Only current-authority Exchange sources cross the outbound URI boundary."""
    exchange_file_service = AsyncMock()
    exchange_file_service.resolve_for_authority.return_value = Failure(
        FileAccessDenied()
    )
    service = _service(
        repository=_Repository(_target(capabilities=_capabilities(upload_files=True))),
        slack_client=_SlackClient(),
        exchange_file_service=exchange_file_service,
    )
    storage = _OutboundStorage({})

    with pytest.raises(ExternalChannelFileTransferError, match="access is denied"):
        await service.prepare_outbound(
            session_id="session-1",
            agent_id="agent-1",
            binding_id="binding-1",
            paths=["exchange://exchange/workspace-1/files/missing/original"],
            file_storage=cast(FileStorage, storage),
            authority=_authority(),
        )
    with pytest.raises(ExternalChannelFileTransferError, match="must be absolute"):
        await service.prepare_outbound(
            session_id="session-1",
            agent_id="agent-1",
            binding_id="binding-1",
            paths=["artifact://artifacts/workspace-1/file-1"],
            file_storage=cast(FileStorage, storage),
            authority=_authority(),
        )

    assert exchange_file_service.resolve_for_authority.await_count == 1


@pytest.mark.asyncio
async def test_outbound_preflight_fails_before_reading_unavailable_sources() -> None:
    """Capability, path, and aggregate checks happen without whole-file reads."""
    storage = _OutboundStorage(
        {
            "/workspace/agent/first.bin": b"123456",
            "/workspace/agent/second.bin": b"123456",
        }
    )
    unavailable = _service(
        repository=_Repository(_target()),
        slack_client=_SlackClient(),
    )
    with pytest.raises(ExternalChannelFileTransferError, match="cannot upload"):
        await unavailable.prepare_outbound(
            session_id="session-1",
            agent_id="agent-1",
            binding_id="binding-1",
            paths=["/workspace/agent/first.bin"],
            file_storage=cast(FileStorage, storage),
        )

    service = _service(
        repository=_Repository(_target(capabilities=_capabilities(upload_files=True))),
        slack_client=_SlackClient(),
        settings=_SystemSettings(
            outbound_file_limit=10,
            outbound_action_limit=10,
        ),
    )
    with pytest.raises(ExternalChannelFileTransferError, match="must be absolute"):
        await service.prepare_outbound(
            session_id="session-1",
            agent_id="agent-1",
            binding_id="binding-1",
            paths=["relative.bin"],
            file_storage=cast(FileStorage, storage),
        )
    with pytest.raises(ExternalChannelFileTransferError, match="action limit"):
        await service.prepare_outbound(
            session_id="session-1",
            agent_id="agent-1",
            binding_id="binding-1",
            paths=[
                "/workspace/agent/first.bin",
                "/workspace/agent/second.bin",
            ],
            file_storage=cast(FileStorage, storage),
        )

    assert storage.read_calls == []


@pytest.mark.asyncio
async def test_outbound_iterator_reads_ordered_exact_bounded_ranges() -> None:
    """Streaming uses 1 MiB ranges and verifies that the file did not grow."""
    body = b"a" * (EXTERNAL_CHANNEL_FILE_STREAM_CHUNK_BYTES + 3)
    storage = _OutboundStorage({"/workspace/agent/large.bin": body})
    manifest = ExternalChannelOutboundFileManifest(
        path="/workspace/agent/large.bin",
        filename="large.bin",
        media_type="application/octet-stream",
        expected_size=len(body),
    )

    chunks = [
        chunk
        async for chunk in iter_external_channel_outbound_file_chunks(
            file_storage=cast(RangedFileStorage, storage),
            manifest=manifest,
            agent_id="agent-1",
        )
    ]

    assert b"".join(chunks) == body
    assert [len(chunk) for chunk in chunks] == [
        EXTERNAL_CHANNEL_FILE_STREAM_CHUNK_BYTES,
        3,
    ]
    assert storage.read_calls == [
        (
            "/workspace/agent/large.bin",
            "agent-1",
            0,
            EXTERNAL_CHANNEL_FILE_STREAM_CHUNK_BYTES,
        ),
        (
            "/workspace/agent/large.bin",
            "agent-1",
            EXTERNAL_CHANNEL_FILE_STREAM_CHUNK_BYTES,
            3,
        ),
        (
            "/workspace/agent/large.bin",
            "agent-1",
            len(body),
            1,
        ),
    ]


@pytest.mark.asyncio
async def test_outbound_iterator_rejects_short_and_grown_runtime_files() -> None:
    """Preflight size remains authoritative throughout one upload attempt."""
    short = _OutboundStorage({"/workspace/agent/file.bin": b"short"})
    expected = ExternalChannelOutboundFileManifest(
        path="/workspace/agent/file.bin",
        filename="file.bin",
        media_type="application/octet-stream",
        expected_size=6,
    )
    with pytest.raises(ExternalChannelFileTransferError, match="ended before"):
        async for _ in iter_external_channel_outbound_file_chunks(
            file_storage=cast(RangedFileStorage, short),
            manifest=expected,
            agent_id="agent-1",
        ):
            pass

    grown = _OutboundStorage({"/workspace/agent/file.bin": b"grown!"})
    expected = expected.model_copy(update={"expected_size": 5})
    with pytest.raises(ExternalChannelFileTransferError, match="grew"):
        async for _ in iter_external_channel_outbound_file_chunks(
            file_storage=cast(RangedFileStorage, grown),
            manifest=expected,
            agent_id="agent-1",
        ):
            pass
