"""Explicit External Channel inbound file-transfer tests."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import ExternalChannelProvider
from azents.core.external_channel_file import (
    ExternalChannelFileLocator,
    ExternalChannelFileMetadata,
    ExternalChannelFileUnsupportedReason,
)
from azents.core.external_channel_file_system_setting import (
    ExternalChannelFilesConfig,
    ExternalChannelFilesSecrets,
)
from azents.core.system_setting import ResolvedSystemSetting, SystemSettingSection
from azents.engine.io.attachments import RuntimeAttachment
from azents.rdb.session import SessionManager
from azents.repos.external_channel.work import ExternalChannelWorkRepository
from azents.repos.external_channel.work_data import ExternalChannelFileAccessTarget
from azents.services.external_channel.credentials import ExternalChannelCredentialsCodec
from azents.services.external_channel.data import SlackConnectionCredentials
from azents.services.external_channel.file_transfer import (
    ExternalChannelFileTransferError,
    ExternalChannelFileTransferService,
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
from azents.services.file_storage import FileStorage
from azents.services.system_setting.service import SystemSettingsService


class _Repository:
    def __init__(self, target: ExternalChannelFileAccessTarget | None) -> None:
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
        body: bytes = b"content",
        info_error: Exception | None = None,
        download_error: Exception | None = None,
    ) -> None:
        self.info = info or _file_info()
        self.body = body
        self.info_error = info_error
        self.download_error = download_error
        self.info_file_ids: list[str] = []
        self.download_limits: list[int] = []

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

    async def download_private_file(
        self,
        *,
        bot_token: str,
        private_url: str,
        max_bytes: int,
    ) -> bytes:
        assert bot_token == "xoxb-secret"
        assert private_url == "https://files.slack.test/private/F123"
        self.download_limits.append(max_bytes)
        if self.download_error is not None:
            raise self.download_error
        return self.body


class _SystemSettings:
    def __init__(self, inbound_limit: int = 100) -> None:
        self.inbound_limit = inbound_limit

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
                outbound_max_file_bytes=100,
                outbound_max_action_bytes=100,
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
    ) -> None:
        self.existing = exists
        self.put_error = put_error
        self.put_calls: list[tuple[str, bytes, str, str]] = []

    async def exists(self, path: str, *, agent_id: str) -> bool:
        assert path == "/workspace/agent/report.csv"
        assert agent_id == "agent-1"
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


@asynccontextmanager
async def _session_manager() -> AsyncGenerator[AsyncSession]:
    yield cast(AsyncSession, object())


def _capabilities(*, download_files: bool = True) -> dict[str, object]:
    return {
        "provider": "slack",
        "transport": "http",
        "inbound_events": True,
        "thread_history": True,
        "post_messages": True,
        "update_messages": True,
        "delete_messages": True,
        "download_files": download_files,
        "upload_files": False,
    }


def _target(
    *,
    capabilities: dict[str, object] | None = None,
) -> ExternalChannelFileAccessTarget:
    return ExternalChannelFileAccessTarget(
        binding_id="binding-1",
        connection_id="connection-1",
        provider=ExternalChannelProvider.SLACK,
        encrypted_credentials="ciphertext",
        capabilities=_capabilities() if capabilities is None else capabilities,
    )


def _file_info(
    *,
    provider_file_id: str = "F123",
    declared_size: int = 7,
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


def _service(
    *,
    repository: _Repository,
    slack_client: _SlackClient,
    settings: _SystemSettings | None = None,
) -> ExternalChannelFileTransferService:
    return ExternalChannelFileTransferService(
        session_manager=cast(SessionManager[AsyncSession], _session_manager),
        repository=cast(ExternalChannelWorkRepository, repository),
        credentials_codec=cast(
            ExternalChannelCredentialsCodec,
            _CredentialsCodec(),
        ),
        slack_client=cast(SlackConversationClient, slack_client),
        system_settings=cast(
            SystemSettingsService,
            settings or _SystemSettings(),
        ),
    )


def _locator(provider_file_id: str = "F123") -> str:
    return ExternalChannelFileLocator(
        provider=ExternalChannelProvider.SLACK,
        binding_id="binding-1",
        provider_file_id=provider_file_id,
    ).encode()


@pytest.mark.asyncio
async def test_download_materializes_only_selected_current_provider_file() -> None:
    """The locator file ID is provider-authoritative within the active binding."""
    repository = _Repository(_target())
    slack_client = _SlackClient(
        info=_file_info(provider_file_id="F-MODIFIED"),
        body=b"content",
    )
    storage = _FileStorage()
    service = _service(repository=repository, slack_client=slack_client)

    result = await service.download(
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
    assert slack_client.download_limits == [100]
    assert storage.put_calls == [
        (
            "/workspace/agent/report.csv",
            b"content",
            "text/csv",
            "agent-1",
        )
    ]


@pytest.mark.asyncio
async def test_inactive_binding_fails_before_provider_access() -> None:
    """An unrelated or inactive locator never reaches Slack."""
    slack_client = _SlackClient()
    service = _service(repository=_Repository(None), slack_client=slack_client)

    with pytest.raises(ExternalChannelFileTransferError, match="not active"):
        await service.download(
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
        await service.download(
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
        await service.download(
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
        await service.download(
            session_id="session-1",
            agent_id="agent-1",
            file=_locator(),
            path="/workspace/agent/report.csv",
            overwrite=False,
            file_storage=cast(FileStorage, _FileStorage(exists=True)),
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

    result = await service.download(
        session_id="session-1",
        agent_id="agent-1",
        file=_locator(),
        path="/workspace/agent/report.csv",
        overwrite=True,
        file_storage=cast(FileStorage, storage),
    )

    assert result.bytes_written == 7
    assert slack_client.info_file_ids == ["F123"]
    assert len(storage.put_calls) == 1


@pytest.mark.asyncio
async def test_declared_and_actual_oversize_never_write_runtime_file() -> None:
    """Provider metadata and actual bytes independently enforce the effective limit."""
    declared_storage = _FileStorage()
    declared_service = _service(
        repository=_Repository(_target()),
        slack_client=_SlackClient(info=_file_info(declared_size=101)),
    )

    with pytest.raises(ExternalChannelFileTransferError, match="100 bytes"):
        await declared_service.download(
            session_id="session-1",
            agent_id="agent-1",
            file=_locator(),
            path="/workspace/agent/report.csv",
            overwrite=False,
            file_storage=cast(FileStorage, declared_storage),
        )

    actual_storage = _FileStorage()
    actual_service = _service(
        repository=_Repository(_target()),
        slack_client=_SlackClient(download_error=SlackProviderFileTooLarge("oversize")),
    )
    with pytest.raises(ExternalChannelFileTransferError, match="100 bytes"):
        await actual_service.download(
            session_id="session-1",
            agent_id="agent-1",
            file=_locator(),
            path="/workspace/agent/report.csv",
            overwrite=False,
            file_storage=cast(FileStorage, actual_storage),
        )

    assert declared_storage.put_calls == []
    assert actual_storage.put_calls == []


@pytest.mark.asyncio
async def test_provider_size_mismatch_never_writes_runtime_file() -> None:
    """A short complete response is not reported as the declared Slack file."""
    storage = _FileStorage()
    service = _service(
        repository=_Repository(_target()),
        slack_client=_SlackClient(
            info=_file_info(declared_size=8),
            body=b"short",
        ),
    )

    with pytest.raises(ExternalChannelFileTransferError, match="does not match"):
        await service.download(
            session_id="session-1",
            agent_id="agent-1",
            file=_locator(),
            path="/workspace/agent/report.csv",
            overwrite=False,
            file_storage=cast(FileStorage, storage),
        )

    assert storage.put_calls == []


@pytest.mark.asyncio
async def test_unsupported_or_missing_provider_file_never_writes_runtime() -> None:
    """Fail-closed Slack modes and deleted files remain controlled Tool failures."""
    unsupported_storage = _FileStorage()
    unsupported_service = _service(
        repository=_Repository(_target()),
        slack_client=_SlackClient(info=_file_info(supported=False)),
    )
    with pytest.raises(ExternalChannelFileTransferError, match="external_file"):
        await unsupported_service.download(
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
        await missing_service.download(
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
        await service.download(
            session_id="session-1",
            agent_id="agent-1",
            file=_locator(),
            path="/workspace/agent/report.csv",
            overwrite=False,
            file_storage=cast(FileStorage, storage),
        )

    assert storage.put_calls == []


@pytest.mark.asyncio
async def test_runtime_write_failure_is_not_reported_as_success() -> None:
    """A complete provider response still fails when the Runtime write fails."""
    service = _service(
        repository=_Repository(_target()),
        slack_client=_SlackClient(),
    )

    with pytest.raises(ExternalChannelFileTransferError, match="Runtime file"):
        await service.download(
            session_id="session-1",
            agent_id="agent-1",
            file=_locator(),
            path="/workspace/agent/report.csv",
            overwrite=False,
            file_storage=cast(
                FileStorage,
                _FileStorage(put_error=OSError("write failed")),
            ),
        )
