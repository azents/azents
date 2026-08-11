"""Explicit provider-to-Runtime External Channel file transfer."""

import asyncio
import datetime
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Annotated, Protocol, TypeGuard, assert_never

import grpc
import httpx
from azcommon.infra.s3.service import S3TransferCleanupRequired
from azcommon.uuid import uuid7
from azents_runtime_control.grpc_transfer_coordinator_client import (
    CoordinatorTransferFailure,
)
from fastapi import Depends
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import ExternalChannelProvider
from azents.core.external_channel_file import (
    EXTERNAL_CHANNEL_FILE_STREAM_CHUNK_BYTES,
    MAX_EXTERNAL_CHANNEL_FILES,
    MAX_EXTERNAL_CHANNEL_INBOUND_FILE_BYTES,
    ExternalChannelFileLocator,
    ExternalChannelFileMetadata,
    ExternalChannelOutboundFileManifest,
    ExternalChannelOutboundFileSource,
)
from azents.core.external_channel_file_system_setting import ExternalChannelFilesConfig
from azents.core.system_setting import SystemSettingSection
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.work import ExternalChannelWorkRepository
from azents.repos.external_channel.work_data import ExternalChannelFileAccessTarget
from azents.runtime.transfer.provider_source import (
    DeferredProviderServerToRuntimeSource,
    ProviderStagingStore,
)
from azents.runtime.transfer.server_to_runtime import (
    ServerToRuntimeSourceMetadata,
    ServerToRuntimeTarget,
    ServerToRuntimeTransferError,
    ServerToRuntimeTransferRequest,
)
from azents.services.exchange_file import (
    ExchangeFileDownload,
    ExchangeFileService,
    FileAccessDenied,
    FileExpired,
    FileNotFound,
    FileUnavailable,
    SessionNotFound,
    exchange_object_key_from_uri,
)
from azents.services.external_channel.connection import (
    get_external_channel_credentials_codec,
)
from azents.services.external_channel.credentials import ExternalChannelCredentialsCodec
from azents.services.external_channel.data import ExternalChannelCapabilitySnapshot
from azents.services.external_channel.discord_files import (
    DiscordAttachmentByteTransport,
    DiscordAttachmentDownloadInfo,
    DiscordChannelClient,
    DiscordFileCredentialsInvalid,
    DiscordFileNotFound,
    DiscordFilePermissionDenied,
    DiscordFileProviderError,
    DiscordFileTemporaryError,
    DiscordFileTooLarge,
)
from azents.services.external_channel.discord_sdk import (
    DiscordSDKClientFactory,
    get_discord_sdk_client_factory,
)
from azents.services.external_channel.slack_events import (
    SlackConversationClient,
    SlackExternalUploadTransport,
    SlackPrivateFileTransport,
    SlackProviderCredentialsInvalid,
    SlackProviderFileNotFound,
    SlackProviderFileTooLarge,
    SlackProviderPermissionDenied,
    SlackProviderRateLimited,
    SlackProviderRequestRejected,
    SlackProviderTemporaryError,
)
from azents.services.external_channel.slack_sdk_client import create_slack_web_client
from azents.services.file_storage import FileStorage, RangedFileStorage
from azents.services.runtime_storage_error import RuntimeStorageError
from azents.services.session_resource_authority import SessionResourceAuthority
from azents.services.session_storage import guess_media_type
from azents.services.system_setting.service import SystemSettingsService


class ExternalChannelFileTransferError(ValueError):
    """One requested External Channel file cannot be materialized safely."""


class ServerToRuntimeTransferExecutor(Protocol):
    """Backend-only terminal-success Runtime transfer capability."""

    async def transfer(self, request: ServerToRuntimeTransferRequest) -> None:
        """Deliver one complete source and await Runtime destination commit."""
        ...


@dataclass(frozen=True)
class ExternalChannelInboundStagingConfiguration:
    """Trusted configuration for deferred provider file staging."""

    s3_service: ProviderStagingStore
    workspace_bucket: str
    transfer_object_prefix: str
    stream_chunk_size: int
    multipart_part_size: int
    multipart_copy_threshold: int
    multipart_copy_part_size: int
    deadline_after: datetime.timedelta

    def __post_init__(self) -> None:
        """Reject incomplete or unbounded provider staging configuration."""
        if not self.workspace_bucket or not self.transfer_object_prefix.strip("/"):
            raise ValueError("External Channel transfer storage is required")
        if (
            min(
                self.stream_chunk_size,
                self.multipart_part_size,
                self.multipart_copy_threshold,
                self.multipart_copy_part_size,
            )
            <= 0
        ):
            raise ValueError("External Channel transfer byte bounds must be positive")
        if self.stream_chunk_size > self.multipart_part_size:
            raise ValueError(
                "External Channel stream chunk size exceeds multipart part size"
            )
        if self.deadline_after <= datetime.timedelta():
            raise ValueError("External Channel transfer deadline must be positive")


@dataclass(frozen=True)
class ExternalChannelFileDownloadResult:
    """Bounded successful provider-to-Runtime transfer result."""

    path: str
    filename: str
    media_type: str | None
    bytes_written: int


@dataclass(frozen=True)
class _DiscordAttachmentSource:
    """Validated current Discord attachment source."""

    filename: str
    download_url: str


async def get_slack_file_http_client() -> AsyncIterator[httpx.AsyncClient]:
    """Provide the bounded Slack file-read transport."""
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        yield client


def get_slack_file_client(
    http_client: Annotated[
        httpx.AsyncClient,
        Depends(get_slack_file_http_client),
    ],
) -> SlackConversationClient:
    """Provide the Slack file-read adapter."""
    return SlackConversationClient(
        web_client=create_slack_web_client(),
        private_file_transport=SlackPrivateFileTransport(http_client),
        external_upload_transport=SlackExternalUploadTransport(http_client),
    )


async def get_discord_file_http_client() -> AsyncIterator[httpx.AsyncClient]:
    """Provide the bounded Discord source-message and attachment transport."""
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
        yield client


def get_discord_file_client(
    sdk_factory: Annotated[
        DiscordSDKClientFactory,
        Depends(get_discord_sdk_client_factory),
    ],
    http_client: Annotated[
        httpx.AsyncClient,
        Depends(get_discord_file_http_client),
    ],
) -> DiscordChannelClient:
    """Provide the SDK metadata adapter and approved G3 byte transport."""
    return DiscordChannelClient(
        sdk_factory,
        DiscordAttachmentByteTransport(http_client),
    )


def get_unconfigured_external_channel_inbound_staging_configuration() -> (
    ExternalChannelInboundStagingConfiguration | None
):
    """Disable provider staging outside the Worker-owned transfer boundary."""
    return None


@dataclass
class ExternalChannelFileTransferService:
    """Authorize and materialize one selected provider file into the Runtime."""

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    repository: Annotated[
        ExternalChannelWorkRepository,
        Depends(ExternalChannelWorkRepository.create),
    ]
    credentials_codec: Annotated[
        ExternalChannelCredentialsCodec,
        Depends(get_external_channel_credentials_codec),
    ]
    slack_client: Annotated[
        SlackConversationClient,
        Depends(get_slack_file_client),
    ]
    discord_client: Annotated[
        DiscordChannelClient,
        Depends(get_discord_file_client),
    ]
    exchange_file_service: Annotated[
        ExchangeFileService,
        Depends(ExchangeFileService),
    ]
    system_settings: Annotated[
        SystemSettingsService,
        Depends(SystemSettingsService),
    ]
    inbound_staging_configuration: Annotated[
        ExternalChannelInboundStagingConfiguration | None,
        Depends(get_unconfigured_external_channel_inbound_staging_configuration),
    ] = None

    async def download(
        self,
        *,
        session_id: str,
        agent_id: str,
        operation_id: str,
        file: str,
        path: str,
        overwrite: bool,
        file_storage: FileStorage,
        transfer_service: ServerToRuntimeTransferExecutor | None,
        transfer_target: ServerToRuntimeTarget | None,
    ) -> ExternalChannelFileDownloadResult:
        """Stage one provider-authorized file and await Runtime destination commit."""
        locator = self._parse_locator(file)
        if not PurePosixPath(path).is_absolute():
            raise ExternalChannelFileTransferError(
                "Runtime destination path must be absolute."
            )
        async with self.session_manager() as session:
            target = await self.repository.get_active_file_access_target(
                session,
                session_id=session_id,
                agent_id=agent_id,
                binding_id=locator.binding_id,
            )
        if target is None:
            raise ExternalChannelFileTransferError(
                "External Channel binding is not active for this AgentSession."
            )
        if target.provider is not locator.provider:
            raise ExternalChannelFileTransferError(
                "External Channel file locator does not match its active provider."
            )
        capabilities = self._capabilities(target.capabilities)
        if not capabilities.download_files:
            raise ExternalChannelFileTransferError(
                "The active External Channel connection cannot download files."
            )
        if target.encrypted_credentials is None:
            raise ExternalChannelFileTransferError(
                "External Channel credentials are unavailable."
            )
        if not overwrite and await self._destination_exists(
            file_storage,
            path=path,
            agent_id=agent_id,
        ):
            raise ExternalChannelFileTransferError(
                f"File already exists: {path}. Set overwrite=true to replace it."
            )
        staging_configuration = self.inbound_staging_configuration
        if (
            transfer_service is None
            or transfer_target is None
            or staging_configuration is None
        ):
            raise ExternalChannelFileTransferError(
                "Runtime file transfer service is unavailable."
            )
        credentials = self.credentials_codec.decrypt(target.encrypted_credentials)
        resolved = await self.system_settings.resolve(
            SystemSettingSection.EXTERNAL_CHANNEL_FILES
        )
        if not isinstance(resolved.config, ExternalChannelFilesConfig):
            raise RuntimeError("Unexpected External Channel files settings model.")
        limit = min(
            resolved.config.inbound_max_file_bytes,
            MAX_EXTERNAL_CHANNEL_INBOUND_FILE_BYTES,
        )
        match target.provider:
            case ExternalChannelProvider.SLACK:
                return await self._download_slack(
                    bot_token=credentials.bot_token,
                    provider_file_id=locator.provider_file_id,
                    path=path,
                    overwrite=overwrite,
                    limit=limit,
                    agent_id=agent_id,
                    session_id=session_id,
                    operation_id=operation_id,
                    locator=locator,
                    target=target,
                    transfer_service=transfer_service,
                    transfer_target=transfer_target,
                    staging_configuration=staging_configuration,
                )
            case ExternalChannelProvider.DISCORD:
                guild_id = target.provider_tenant_id
                channel_id = locator.provider_channel_id
                message_id = locator.provider_message_id
                if (
                    not _discord_snowflake(guild_id)
                    or not _discord_snowflake(channel_id)
                    or not _discord_snowflake(message_id)
                ):
                    raise ExternalChannelFileTransferError(
                        "Discord attachment source is unavailable."
                    )
                return await self._download_discord(
                    bot_token=credentials.bot_token,
                    guild_id=guild_id,
                    source_identity=(channel_id, message_id),
                    provider_file_id=locator.provider_file_id,
                    path=path,
                    overwrite=overwrite,
                    limit=limit,
                    agent_id=agent_id,
                    session_id=session_id,
                    operation_id=operation_id,
                    locator=locator,
                    target=target,
                    transfer_service=transfer_service,
                    transfer_target=transfer_target,
                    staging_configuration=staging_configuration,
                )
            case _ as unreachable:
                assert_never(unreachable)

    async def _download_slack(
        self,
        *,
        bot_token: str,
        provider_file_id: str,
        path: str,
        overwrite: bool,
        limit: int,
        agent_id: str,
        session_id: str,
        operation_id: str,
        locator: ExternalChannelFileLocator,
        target: ExternalChannelFileAccessTarget,
        transfer_service: ServerToRuntimeTransferExecutor,
        transfer_target: ServerToRuntimeTarget,
        staging_configuration: ExternalChannelInboundStagingConfiguration,
    ) -> ExternalChannelFileDownloadResult:
        try:
            info = await self.slack_client.fetch_file_download_info(
                bot_token=bot_token,
                provider_file_id=provider_file_id,
            )
            metadata = info.metadata
            filename = _validate_slack_file_metadata(
                metadata=metadata,
                provider_file_id=provider_file_id,
            )
            private_url = info.private_url
            if private_url is None:
                raise ExternalChannelFileTransferError(
                    "Slack file metadata does not include a private download target."
                )
            transfer_size = await self.slack_client.fetch_private_file_content_length(
                bot_token=bot_token, private_url=private_url, max_bytes=limit
            )
            source = DeferredProviderServerToRuntimeSource(
                metadata=ServerToRuntimeSourceMetadata(
                    canonical_uri=(
                        f"external-channel://slack/{locator.binding_id}/"
                        f"{provider_file_id}"
                    ),
                    source_kind="external_channel_slack",
                    display_name=filename,
                    media_type=metadata.media_type or "application/octet-stream",
                    size=transfer_size,
                    sha256=None,
                    expires_at=None,
                ),
                open_stream=lambda *, maximum_chunk_size: (
                    self.slack_client.open_private_file_stream(
                        bot_token=bot_token,
                        private_url=private_url,
                        max_bytes=limit,
                        maximum_chunk_size=maximum_chunk_size,
                    )
                ),
                revalidate_authority=lambda: self._revalidate_slack_source(
                    session_id=session_id,
                    agent_id=agent_id,
                    locator=locator,
                    target=target,
                    bot_token=bot_token,
                    expected_metadata=metadata,
                ),
                s3_service=staging_configuration.s3_service,
                bucket=staging_configuration.workspace_bucket,
                transfer_object_prefix=staging_configuration.transfer_object_prefix,
                preparation_id_source=lambda: uuid7().hex,
                maximum_size=limit,
                stream_chunk_size=staging_configuration.stream_chunk_size,
                multipart_part_size=staging_configuration.multipart_part_size,
                multipart_copy_threshold=staging_configuration.multipart_copy_threshold,
                multipart_copy_part_size=(
                    staging_configuration.multipart_copy_part_size
                ),
            )
            await transfer_service.transfer(
                ServerToRuntimeTransferRequest(
                    source=source,
                    target=transfer_target,
                    agent_id=agent_id,
                    session_id=session_id,
                    operation_id=operation_id,
                    destination=path,
                    overwrite=overwrite,
                    product_maximum_size=limit,
                    provider_maximum_size=limit,
                    deadline_at=(
                        datetime.datetime.now(datetime.UTC)
                        + staging_configuration.deadline_after
                    ),
                )
            )
        except asyncio.CancelledError:
            raise
        except ExternalChannelFileTransferError:
            raise
        except (
            SlackProviderFileTooLarge,
            SlackProviderFileNotFound,
            SlackProviderPermissionDenied,
            SlackProviderCredentialsInvalid,
            SlackProviderRateLimited,
            SlackProviderRequestRejected,
            SlackProviderTemporaryError,
        ) as error:
            raise _map_slack_download_error(error, limit=limit) from None
        except ServerToRuntimeTransferError as error:
            raise ExternalChannelFileTransferError(
                _slack_transfer_error_message(error, path=path)
            ) from None
        except grpc.aio.AioRpcError:
            raise ExternalChannelFileTransferError(
                f"Failed to write the Runtime file: {path}."
            ) from None
        except PermissionError:
            raise ExternalChannelFileTransferError(
                f"Runtime destination is not writable: {path}."
            ) from None
        except FileExistsError:
            raise ExternalChannelFileTransferError(
                f"File already exists: {path}. Set overwrite=true to replace it."
            ) from None
        except RuntimeStorageError as error:
            raise ExternalChannelFileTransferError(
                f"Failed to write the Runtime file: {error.detail}"
            ) from None
        except S3TransferCleanupRequired:
            raise ExternalChannelFileTransferError(
                "Failed to stage the Slack file for Runtime transfer."
            ) from None
        except ValueError as error:
            message = str(error)
            if "exceeds" in message:
                raise ExternalChannelFileTransferError(
                    f"Slack file exceeds the configured inbound limit of {limit} bytes."
                ) from None
            if "size" in message or "hash" in message:
                raise ExternalChannelFileTransferError(
                    "Slack file body does not match the authenticated Content-Length."
                ) from None
            raise ExternalChannelFileTransferError(
                "Failed to write the Runtime file."
            ) from None
        except OSError:
            raise ExternalChannelFileTransferError(
                f"Failed to write the Runtime file: {path}."
            ) from None
        return ExternalChannelFileDownloadResult(
            path=path,
            filename=filename,
            media_type=metadata.media_type,
            bytes_written=transfer_size,
        )

    async def _download_discord(
        self,
        *,
        bot_token: str,
        guild_id: str,
        source_identity: tuple[str, str],
        provider_file_id: str,
        path: str,
        overwrite: bool,
        limit: int,
        agent_id: str,
        session_id: str,
        operation_id: str,
        locator: ExternalChannelFileLocator,
        target: ExternalChannelFileAccessTarget,
        transfer_service: ServerToRuntimeTransferExecutor,
        transfer_target: ServerToRuntimeTarget,
        staging_configuration: ExternalChannelInboundStagingConfiguration,
    ) -> ExternalChannelFileDownloadResult:
        """Stage one current Discord attachment without retaining its URL."""
        channel_id, message_id = source_identity
        try:
            info = await self.discord_client.fetch_attachment_download_info(
                bot_token=bot_token,
                guild_id=guild_id,
                channel_id=channel_id,
                message_id=message_id,
                attachment_id=provider_file_id,
            )
            attachment_source = _validate_discord_attachment_metadata(
                info=info,
                provider_file_id=provider_file_id,
            )
            filename = attachment_source.filename
            download_url = attachment_source.download_url
            metadata = info.metadata
            transfer_size = await self.discord_client.fetch_attachment_content_length(
                download_url=download_url, max_bytes=limit
            )
            source = DeferredProviderServerToRuntimeSource(
                metadata=ServerToRuntimeSourceMetadata(
                    canonical_uri=(
                        f"external-channel://discord/{locator.binding_id}/"
                        f"{provider_file_id}"
                    ),
                    source_kind="external_channel_discord",
                    display_name=filename,
                    media_type=metadata.media_type or "application/octet-stream",
                    size=transfer_size,
                    sha256=None,
                    expires_at=None,
                ),
                open_stream=lambda *, maximum_chunk_size: (
                    self.discord_client.open_attachment_stream(
                        download_url=download_url,
                        max_bytes=limit,
                        maximum_chunk_size=maximum_chunk_size,
                    )
                ),
                revalidate_authority=lambda: self._revalidate_discord_source(
                    session_id=session_id,
                    agent_id=agent_id,
                    locator=locator,
                    target=target,
                    bot_token=bot_token,
                    guild_id=guild_id,
                    source_identity=source_identity,
                    expected_metadata=metadata,
                ),
                s3_service=staging_configuration.s3_service,
                bucket=staging_configuration.workspace_bucket,
                transfer_object_prefix=staging_configuration.transfer_object_prefix,
                preparation_id_source=lambda: uuid7().hex,
                maximum_size=limit,
                stream_chunk_size=staging_configuration.stream_chunk_size,
                multipart_part_size=staging_configuration.multipart_part_size,
                multipart_copy_threshold=(
                    staging_configuration.multipart_copy_threshold
                ),
                multipart_copy_part_size=(
                    staging_configuration.multipart_copy_part_size
                ),
            )
            await transfer_service.transfer(
                ServerToRuntimeTransferRequest(
                    source=source,
                    target=transfer_target,
                    agent_id=agent_id,
                    session_id=session_id,
                    operation_id=operation_id,
                    destination=path,
                    overwrite=overwrite,
                    product_maximum_size=limit,
                    provider_maximum_size=limit,
                    deadline_at=(
                        datetime.datetime.now(datetime.UTC)
                        + staging_configuration.deadline_after
                    ),
                )
            )
        except asyncio.CancelledError:
            raise
        except ExternalChannelFileTransferError:
            raise
        except DiscordFileProviderError as error:
            raise _map_discord_download_error(error, limit=limit) from None
        except ServerToRuntimeTransferError as error:
            raise ExternalChannelFileTransferError(
                _discord_transfer_error_message(error, path=path)
            ) from None
        except grpc.aio.AioRpcError:
            raise ExternalChannelFileTransferError(
                f"Failed to write the Runtime file: {path}."
            ) from None
        except S3TransferCleanupRequired:
            raise ExternalChannelFileTransferError(
                "Failed to stage the Discord attachment for Runtime transfer."
            ) from None
        except RuntimeStorageError as error:
            raise ExternalChannelFileTransferError(
                f"Failed to write the Runtime file: {error.detail}"
            ) from None
        except ValueError as error:
            message = str(error)
            if "exceeds" in message:
                raise ExternalChannelFileTransferError(
                    "Discord attachment exceeds the configured inbound limit of "
                    f"{limit} bytes."
                ) from None
            if "size" in message or "hash" in message:
                raise ExternalChannelFileTransferError(
                    "Discord attachment body does not match the final Content-Length."
                ) from None
            raise ExternalChannelFileTransferError(
                "Failed to write the Runtime file."
            ) from None
        except OSError:
            raise ExternalChannelFileTransferError(
                f"Failed to write the Runtime file: {path}."
            ) from None
        return ExternalChannelFileDownloadResult(
            path=path,
            filename=filename,
            media_type=metadata.media_type,
            bytes_written=transfer_size,
        )

    async def _revalidate_discord_source(
        self,
        *,
        session_id: str,
        agent_id: str,
        locator: ExternalChannelFileLocator,
        target: ExternalChannelFileAccessTarget,
        bot_token: str,
        guild_id: str,
        source_identity: tuple[str, str],
        expected_metadata: ExternalChannelFileMetadata,
    ) -> bool:
        """Revalidate active Discord source authority before READY."""
        async with self.session_manager() as session:
            current = await self.repository.get_active_file_access_target(
                session,
                session_id=session_id,
                agent_id=agent_id,
                binding_id=locator.binding_id,
            )
        if current is None:
            raise ExternalChannelFileTransferError(
                "External Channel binding is not active for this AgentSession."
            )
        if current.provider is not locator.provider:
            raise ExternalChannelFileTransferError(
                "External Channel file locator does not match its active provider."
            )
        capabilities = self._capabilities(current.capabilities)
        if not capabilities.download_files or current.encrypted_credentials is None:
            raise ExternalChannelFileTransferError(
                "External Channel file authorization changed before transfer completed."
            )
        if current != target:
            raise ExternalChannelFileTransferError(
                "External Channel binding changed before file transfer completed."
            )
        if (
            locator.provider_channel_id,
            locator.provider_message_id,
        ) != source_identity:
            raise ExternalChannelFileTransferError(
                "Discord attachment source changed before transfer completed."
            )
        channel_id, message_id = source_identity
        info = await self.discord_client.fetch_attachment_download_info(
            bot_token=bot_token,
            guild_id=guild_id,
            channel_id=channel_id,
            message_id=message_id,
            attachment_id=locator.provider_file_id,
        )
        _validate_discord_attachment_metadata(
            info=info,
            provider_file_id=locator.provider_file_id,
        )
        if _metadata_without_declared_size(
            info.metadata
        ) != _metadata_without_declared_size(expected_metadata):
            raise ExternalChannelFileTransferError(
                "Discord attachment changed before transfer completed."
            )
        return True

    async def _revalidate_slack_source(
        self,
        *,
        session_id: str,
        agent_id: str,
        locator: ExternalChannelFileLocator,
        target: ExternalChannelFileAccessTarget,
        bot_token: str,
        expected_metadata: ExternalChannelFileMetadata,
    ) -> bool:
        """Revalidate active binding and current provider metadata before READY."""
        async with self.session_manager() as session:
            current = await self.repository.get_active_file_access_target(
                session,
                session_id=session_id,
                agent_id=agent_id,
                binding_id=locator.binding_id,
            )
        if current is None:
            raise ExternalChannelFileTransferError(
                "External Channel binding is not active for this AgentSession."
            )
        if current.provider is not locator.provider:
            raise ExternalChannelFileTransferError(
                "External Channel file locator does not match its active provider."
            )
        capabilities = self._capabilities(current.capabilities)
        if not capabilities.download_files or current.encrypted_credentials is None:
            raise ExternalChannelFileTransferError(
                "External Channel file authorization changed before transfer completed."
            )
        if current != target:
            raise ExternalChannelFileTransferError(
                "External Channel binding changed before file transfer completed."
            )
        info = await self.slack_client.fetch_file_download_info(
            bot_token=bot_token,
            provider_file_id=locator.provider_file_id,
        )
        _validate_slack_file_metadata(
            metadata=info.metadata,
            provider_file_id=locator.provider_file_id,
        )
        if _metadata_without_declared_size(
            info.metadata
        ) != _metadata_without_declared_size(expected_metadata):
            raise ExternalChannelFileTransferError(
                "Slack file changed before transfer completed."
            )
        return True

    async def prepare_outbound(
        self,
        *,
        session_id: str,
        agent_id: str,
        binding_id: str,
        paths: Sequence[str],
        file_storage: FileStorage | None,
        authority: SessionResourceAuthority | None = None,
    ) -> tuple[ExternalChannelOutboundFileManifest, ...]:
        """Validate one file-bearing reply before its durable action commit."""
        if not paths or len(paths) > MAX_EXTERNAL_CHANNEL_FILES:
            raise ExternalChannelFileTransferError(
                f"Outbound publication requires 1-{MAX_EXTERNAL_CHANNEL_FILES} files."
            )
        async with self.session_manager() as session:
            target = await self.repository.get_active_file_access_target(
                session,
                session_id=session_id,
                agent_id=agent_id,
                binding_id=binding_id,
            )
        if target is None:
            raise ExternalChannelFileTransferError(
                "External Channel binding is not active for this AgentSession."
            )
        capabilities = self._capabilities(target.capabilities)
        if not capabilities.upload_files:
            raise ExternalChannelFileTransferError(
                "The active External Channel connection cannot upload files."
            )
        resolved = await self.system_settings.resolve(
            SystemSettingSection.EXTERNAL_CHANNEL_FILES
        )
        if not isinstance(resolved.config, ExternalChannelFilesConfig):
            raise RuntimeError("Unexpected External Channel files settings model.")
        if file_storage is None and any(
            "://" not in path and PurePosixPath(path).is_absolute() for path in paths
        ):
            raise ExternalChannelFileTransferError(
                "Outbound Runtime file paths require Runtime file storage for this run."
            )
        manifests: list[ExternalChannelOutboundFileManifest] = []
        total_size = 0
        for path in paths:
            if path.startswith("exchange://"):
                if exchange_object_key_from_uri(path) is None:
                    raise ExternalChannelFileTransferError(
                        "Outbound Exchange file URI is invalid."
                    )
                if authority is None:
                    raise ExternalChannelFileTransferError(
                        "Exchange file publication requires execution authority."
                    )
                exchange = await _resolve_outbound_exchange_file(
                    exchange_file_service=self.exchange_file_service,
                    uri=path,
                    authority=authority,
                )
                size = exchange.file.size_bytes
                filename = exchange.file.filename
                media_type = exchange.file.media_type
                source = ExternalChannelOutboundFileSource.EXCHANGE
            else:
                if "://" in path or not PurePosixPath(path).is_absolute():
                    raise ExternalChannelFileTransferError(
                        "Every outbound Runtime file path must be absolute; Exchange "
                        "sources must use an exchange:// URI."
                    )
                if file_storage is None:
                    raise ExternalChannelFileTransferError(
                        "Runtime file storage is unavailable for this run."
                    )
                metadata = await self._stat_outbound(
                    file_storage,
                    path=path,
                    agent_id=agent_id,
                )
                if metadata.get("is_file") is not True:
                    raise ExternalChannelFileTransferError(
                        f"Outbound Runtime path is not a regular file: {path}."
                    )
                size = metadata.get("size")
                if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
                    raise ExternalChannelFileTransferError(
                        f"Outbound Runtime file has an invalid size: {path}."
                    )
                filename = PurePosixPath(path).name
                media_type = guess_media_type(filename)
                source = ExternalChannelOutboundFileSource.RUNTIME
            if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
                raise ExternalChannelFileTransferError(
                    f"Outbound file has an invalid size: {path}."
                )
            if size > resolved.config.outbound_max_file_bytes:
                raise ExternalChannelFileTransferError(
                    "Outbound file exceeds the configured per-file limit."
                )
            total_size += size
            if total_size > resolved.config.outbound_max_action_bytes:
                raise ExternalChannelFileTransferError(
                    "Outbound files exceed the configured action limit."
                )
            manifests.append(
                ExternalChannelOutboundFileManifest(
                    source=source,
                    path=path,
                    filename=filename,
                    media_type=media_type,
                    expected_size=size,
                )
            )
        return tuple(manifests)

    @staticmethod
    def _parse_locator(file: str) -> ExternalChannelFileLocator:
        try:
            return ExternalChannelFileLocator.parse(file)
        except ValueError as error:
            raise ExternalChannelFileTransferError(str(error)) from None

    @staticmethod
    def _capabilities(
        stored_capabilities: dict[str, object] | None,
    ) -> ExternalChannelCapabilitySnapshot:
        if stored_capabilities is None:
            raise ExternalChannelFileTransferError(
                "External Channel file capabilities are unavailable."
            )
        stored = dict(stored_capabilities)
        stored.setdefault("download_files", False)
        stored.setdefault("upload_files", False)
        try:
            return ExternalChannelCapabilitySnapshot.model_validate(stored)
        except ValidationError:
            raise ExternalChannelFileTransferError(
                "External Channel file capabilities are unavailable."
            ) from None

    @staticmethod
    async def _destination_exists(
        file_storage: FileStorage,
        *,
        path: str,
        agent_id: str,
    ) -> bool:
        try:
            return await file_storage.exists(path, agent_id=agent_id)
        except PermissionError:
            raise ExternalChannelFileTransferError(
                f"Runtime destination is not accessible: {path}."
            ) from None
        except RuntimeStorageError as error:
            raise ExternalChannelFileTransferError(
                f"Failed to check the Runtime destination: {error.detail}"
            ) from None
        except ValueError as error:
            raise ExternalChannelFileTransferError(str(error)) from None
        except OSError:
            raise ExternalChannelFileTransferError(
                f"Failed to check the Runtime destination: {path}."
            ) from None

    @staticmethod
    async def _stat_outbound(
        file_storage: FileStorage,
        *,
        path: str,
        agent_id: str,
    ) -> dict[str, object]:
        try:
            return await file_storage.stat(path, agent_id=agent_id)
        except FileNotFoundError:
            raise ExternalChannelFileTransferError(
                f"Outbound Runtime file does not exist: {path}."
            ) from None
        except PermissionError:
            raise ExternalChannelFileTransferError(
                f"Outbound Runtime file is not readable: {path}."
            ) from None
        except RuntimeStorageError as error:
            raise ExternalChannelFileTransferError(
                f"Failed to inspect the outbound Runtime file: {error.detail}"
            ) from None
        except ValueError as error:
            raise ExternalChannelFileTransferError(str(error)) from None
        except OSError:
            raise ExternalChannelFileTransferError(
                f"Failed to inspect the outbound Runtime file: {path}."
            ) from None


def _discord_snowflake(value: object) -> TypeGuard[str]:
    """Return whether a provider identifier is a non-blank Discord snowflake."""
    return isinstance(value, str) and value.isdigit()


def _validate_discord_attachment_metadata(
    *,
    info: DiscordAttachmentDownloadInfo,
    provider_file_id: str,
) -> _DiscordAttachmentSource:
    """Validate one current Discord attachment before source admission."""
    metadata = info.metadata
    if metadata.provider_file_id != provider_file_id:
        raise ExternalChannelFileTransferError(
            "Discord attachment metadata does not match the selected locator."
        )
    if not metadata.supported:
        reason = metadata.unsupported_reason
        raise ExternalChannelFileTransferError(
            "Discord attachment metadata is unsupported"
            + (f": {reason.value}." if reason is not None else ".")
        )
    filename = metadata.name
    if filename is None:
        raise ExternalChannelFileTransferError(
            "Discord attachment metadata does not include a filename."
        )
    download_url = info.download_url
    if download_url is None:
        raise ExternalChannelFileTransferError(
            "Discord attachment does not include a current download target."
        )
    return _DiscordAttachmentSource(
        filename=filename,
        download_url=download_url,
    )


def _map_discord_download_error(
    error: DiscordFileProviderError,
    *,
    limit: int,
) -> ExternalChannelFileTransferError:
    """Map Discord failures to the existing External Channel file contract."""
    match error:
        case DiscordFileTooLarge():
            return ExternalChannelFileTransferError(
                "Discord attachment exceeds the configured inbound limit of "
                f"{limit} bytes."
            )
        case DiscordFileNotFound():
            return ExternalChannelFileTransferError(
                "Discord no longer exposes the requested attachment."
            )
        case DiscordFilePermissionDenied():
            return ExternalChannelFileTransferError(
                "Discord denied access to the requested attachment."
            )
        case DiscordFileCredentialsInvalid():
            return ExternalChannelFileTransferError(
                "Discord rejected the active External Channel credential."
            )
        case DiscordFileTemporaryError():
            return ExternalChannelFileTransferError(
                "Discord attachment download is temporarily unavailable."
            )
        case _:
            return ExternalChannelFileTransferError(
                "Discord rejected the requested attachment."
            )


def _discord_transfer_error_message(
    error: ServerToRuntimeTransferError,
    *,
    path: str,
) -> str:
    """Map bounded Runtime transfer outcomes to Discord's established contract."""
    match error.failure:
        case CoordinatorTransferFailure.CANCELLED:
            return "Runtime file transfer was cancelled before destination commit."
        case CoordinatorTransferFailure.EXPIRED:
            return "Runtime file transfer did not complete before its deadline."
        case CoordinatorTransferFailure.INTEGRITY:
            return (
                "Discord attachment integrity verification failed before "
                "destination commit."
            )
        case CoordinatorTransferFailure.CONSUMER:
            return f"Runtime destination is not writable: {path}."
        case (
            CoordinatorTransferFailure.ADMISSION
            | CoordinatorTransferFailure.FENCED
            | CoordinatorTransferFailure.STREAM
            | None
        ):
            return f"Failed to write the Runtime file: {path}."
        case _:
            return f"Failed to write the Runtime file: {path}."


def _validate_slack_file_metadata(
    *,
    metadata: ExternalChannelFileMetadata,
    provider_file_id: str,
) -> str:
    """Validate one files.info response before source admission."""
    if metadata.provider_file_id != provider_file_id:
        raise ExternalChannelFileTransferError(
            "Slack file metadata does not match the selected locator."
        )
    if not metadata.supported:
        reason = metadata.unsupported_reason
        raise ExternalChannelFileTransferError(
            "Slack file mode is unsupported"
            + (f": {reason.value}." if reason is not None else ".")
        )
    filename = metadata.name or metadata.title
    if filename is None:
        raise ExternalChannelFileTransferError(
            "Slack file metadata does not include a filename."
        )
    return filename


def _metadata_without_declared_size(
    metadata: ExternalChannelFileMetadata,
) -> dict[str, object]:
    """Return provider file identity without advisory metadata size."""
    return metadata.model_dump(mode="python", exclude={"declared_size"})


def _map_slack_download_error(
    error: (
        SlackProviderFileTooLarge
        | SlackProviderFileNotFound
        | SlackProviderPermissionDenied
        | SlackProviderCredentialsInvalid
        | SlackProviderRateLimited
        | SlackProviderRequestRejected
        | SlackProviderTemporaryError
    ),
    *,
    limit: int,
) -> ExternalChannelFileTransferError:
    """Map provider failures to the existing External Channel file contract."""
    match error:
        case SlackProviderFileTooLarge():
            return ExternalChannelFileTransferError(
                f"Slack file exceeds the configured inbound limit of {limit} bytes."
            )
        case SlackProviderFileNotFound():
            return ExternalChannelFileTransferError(
                "Slack no longer exposes the requested file."
            )
        case SlackProviderPermissionDenied():
            return ExternalChannelFileTransferError(
                "Slack denied access to the requested file."
            )
        case SlackProviderCredentialsInvalid():
            return ExternalChannelFileTransferError(
                "Slack rejected the active External Channel credential."
            )
        case SlackProviderRateLimited():
            return ExternalChannelFileTransferError(
                "Slack rate limited the file download request."
            )
        case SlackProviderRequestRejected():
            return ExternalChannelFileTransferError(
                f"Slack rejected the file download ({error.error_code})."
            )
        case SlackProviderTemporaryError():
            return ExternalChannelFileTransferError(
                "Slack file download is temporarily unavailable."
            )
        case _ as unreachable:
            assert_never(unreachable)


def _slack_transfer_error_message(
    error: ServerToRuntimeTransferError,
    *,
    path: str,
) -> str:
    """Map bounded Runtime transfer outcomes to Slack's established contract."""
    match error.failure:
        case CoordinatorTransferFailure.CANCELLED:
            return "Runtime file transfer was cancelled before destination commit."
        case CoordinatorTransferFailure.EXPIRED:
            return "Runtime file transfer did not complete before its deadline."
        case CoordinatorTransferFailure.INTEGRITY:
            return "Slack file integrity verification failed before destination commit."
        case CoordinatorTransferFailure.CONSUMER:
            return f"Runtime destination is not writable: {path}."
        case (
            CoordinatorTransferFailure.ADMISSION
            | CoordinatorTransferFailure.FENCED
            | CoordinatorTransferFailure.STREAM
            | None
        ):
            return f"Failed to write the Runtime file: {path}."
        case _:
            return f"Failed to write the Runtime file: {path}."


async def iter_external_channel_outbound_file_chunks(
    *,
    file_storage: RangedFileStorage,
    manifest: ExternalChannelOutboundFileManifest,
    agent_id: str,
) -> AsyncIterator[bytes]:
    """Yield exactly one manifest's expected Runtime bytes in bounded chunks."""
    offset = 0
    while offset < manifest.expected_size:
        requested = min(
            EXTERNAL_CHANNEL_FILE_STREAM_CHUNK_BYTES,
            manifest.expected_size - offset,
        )
        chunk = await _read_outbound_range(
            file_storage,
            manifest=manifest,
            agent_id=agent_id,
            offset=offset,
            max_bytes=requested,
        )
        if not chunk:
            raise ExternalChannelFileTransferError(
                "Runtime file ended before its expected size."
            )
        if len(chunk) > requested:
            raise ExternalChannelFileTransferError(
                "Runtime file range exceeded the requested chunk size."
            )
        offset += len(chunk)
        yield chunk
    trailing = await _read_outbound_range(
        file_storage,
        manifest=manifest,
        agent_id=agent_id,
        offset=manifest.expected_size,
        max_bytes=1,
    )
    if trailing:
        raise ExternalChannelFileTransferError(
            "Runtime file grew after outbound preflight."
        )


async def _read_outbound_range(
    file_storage: RangedFileStorage,
    *,
    manifest: ExternalChannelOutboundFileManifest,
    agent_id: str,
    offset: int,
    max_bytes: int,
) -> bytes:
    try:
        return await file_storage.read_range(
            manifest.path,
            agent_id=agent_id,
            offset=offset,
            max_bytes=max_bytes,
        )
    except ExternalChannelFileTransferError:
        raise
    except FileNotFoundError:
        raise ExternalChannelFileTransferError(
            "Runtime file disappeared during outbound upload."
        ) from None
    except PermissionError:
        raise ExternalChannelFileTransferError(
            "Runtime file became unreadable during outbound upload."
        ) from None
    except RuntimeStorageError as error:
        raise ExternalChannelFileTransferError(
            f"Failed to read the outbound Runtime file: {error.detail}"
        ) from None
    except ValueError as error:
        raise ExternalChannelFileTransferError(str(error)) from None
    except OSError:
        raise ExternalChannelFileTransferError(
            "Failed to read the outbound Runtime file."
        ) from None


async def iter_external_channel_exchange_file_chunks(
    *,
    exchange_file_service: ExchangeFileService,
    manifest: ExternalChannelOutboundFileManifest,
    authority: SessionResourceAuthority,
) -> AsyncIterator[bytes]:
    """Resolve and yield one authorized Exchange source in bounded chunks."""
    if manifest.source is not ExternalChannelOutboundFileSource.EXCHANGE:
        raise ExternalChannelFileTransferError(
            "Outbound manifest does not describe an Exchange file."
        )
    resolved = await _resolve_outbound_exchange_file(
        exchange_file_service=exchange_file_service,
        uri=manifest.path,
        authority=authority,
    )
    if (
        resolved.file.filename != manifest.filename
        or resolved.file.media_type != manifest.media_type
        or resolved.file.size_bytes != manifest.expected_size
        or len(resolved.body) != manifest.expected_size
    ):
        raise ExternalChannelFileTransferError(
            "Exchange file changed after outbound preflight."
        )
    for offset in range(
        0, len(resolved.body), EXTERNAL_CHANNEL_FILE_STREAM_CHUNK_BYTES
    ):
        yield resolved.body[offset : offset + EXTERNAL_CHANNEL_FILE_STREAM_CHUNK_BYTES]


async def _resolve_outbound_exchange_file(
    *,
    exchange_file_service: ExchangeFileService,
    uri: str,
    authority: SessionResourceAuthority,
) -> ExchangeFileDownload:
    """Resolve one Exchange source with the current canonical authority."""
    result = await exchange_file_service.resolve_for_authority(
        uri=uri,
        authority=authority,
    )
    if result.failure:
        match result.error:
            case SessionNotFound() | FileNotFound():
                message = "Outbound Exchange file was not found."
            case FileAccessDenied():
                message = "Outbound Exchange file access is denied."
            case FileExpired():
                message = "Outbound Exchange file is no longer available."
            case FileUnavailable():
                message = "Outbound Exchange file content is unavailable."
            case _:
                assert_never(result.error)
        raise ExternalChannelFileTransferError(message)
    if len(result.value.body) != result.value.file.size_bytes:
        raise ExternalChannelFileTransferError(
            "Outbound Exchange file size does not match its metadata."
        )
    return result.value
