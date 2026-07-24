"""Explicit provider-to-Runtime External Channel file transfer."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Annotated, assert_never

import httpx
from fastapi import Depends
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import ExternalChannelProvider
from azents.core.external_channel_file import ExternalChannelFileLocator
from azents.core.external_channel_file_system_setting import ExternalChannelFilesConfig
from azents.core.system_setting import SystemSettingSection
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.work import ExternalChannelWorkRepository
from azents.services.external_channel.connection import (
    get_external_channel_credentials_codec,
)
from azents.services.external_channel.credentials import ExternalChannelCredentialsCodec
from azents.services.external_channel.data import ExternalChannelCapabilitySnapshot
from azents.services.external_channel.slack_events import (
    SlackConversationClient,
    SlackProviderCredentialsInvalid,
    SlackProviderFileNotFound,
    SlackProviderFileTooLarge,
    SlackProviderPermissionDenied,
    SlackProviderRateLimited,
    SlackProviderRequestRejected,
    SlackProviderTemporaryError,
)
from azents.services.file_storage import FileStorage
from azents.services.runtime_storage_error import RuntimeStorageError
from azents.services.system_setting.service import SystemSettingsService


class ExternalChannelFileTransferError(ValueError):
    """One requested External Channel file cannot be materialized safely."""


@dataclass(frozen=True)
class ExternalChannelFileDownloadResult:
    """Bounded successful provider-to-Runtime transfer result."""

    path: str
    filename: str
    media_type: str | None
    bytes_written: int


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
    return SlackConversationClient(http_client)


@dataclass
class ExternalChannelFileTransferService:
    """Authorize and materialize one selected provider file into the Runtime."""

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    repository: Annotated[
        ExternalChannelWorkRepository,
        Depends(ExternalChannelWorkRepository),
    ]
    credentials_codec: Annotated[
        ExternalChannelCredentialsCodec,
        Depends(get_external_channel_credentials_codec),
    ]
    slack_client: Annotated[
        SlackConversationClient,
        Depends(get_slack_file_client),
    ]
    system_settings: Annotated[
        SystemSettingsService,
        Depends(SystemSettingsService),
    ]

    async def download(
        self,
        *,
        session_id: str,
        agent_id: str,
        file: str,
        path: str,
        overwrite: bool,
        file_storage: FileStorage,
    ) -> ExternalChannelFileDownloadResult:
        """Download one provider-authorized file and write one complete Runtime file."""
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
        credentials = self.credentials_codec.decrypt(target.encrypted_credentials)
        resolved = await self.system_settings.resolve(
            SystemSettingSection.EXTERNAL_CHANNEL_FILES
        )
        if not isinstance(resolved.config, ExternalChannelFilesConfig):
            raise RuntimeError("Unexpected External Channel files settings model.")
        limit = resolved.config.inbound_max_file_bytes
        match target.provider:
            case ExternalChannelProvider.SLACK:
                return await self._download_slack(
                    bot_token=credentials.bot_token,
                    provider_file_id=locator.provider_file_id,
                    path=path,
                    limit=limit,
                    agent_id=agent_id,
                    file_storage=file_storage,
                )
            case _ as unreachable:
                assert_never(unreachable)

    async def _download_slack(
        self,
        *,
        bot_token: str,
        provider_file_id: str,
        path: str,
        limit: int,
        agent_id: str,
        file_storage: FileStorage,
    ) -> ExternalChannelFileDownloadResult:
        try:
            info = await self.slack_client.fetch_file_download_info(
                bot_token=bot_token,
                provider_file_id=provider_file_id,
            )
            metadata = info.metadata
            if not metadata.supported:
                reason = metadata.unsupported_reason
                raise ExternalChannelFileTransferError(
                    "Slack file mode is unsupported"
                    + (f": {reason.value}." if reason is not None else ".")
                )
            if metadata.declared_size is None:
                raise ExternalChannelFileTransferError(
                    "Slack file metadata does not include a valid size."
                )
            if metadata.declared_size > limit:
                raise ExternalChannelFileTransferError(
                    f"Slack file exceeds the configured inbound limit of {limit} bytes."
                )
            if info.private_url is None:
                raise ExternalChannelFileTransferError(
                    "Slack file metadata does not include a private download target."
                )
            body = await self.slack_client.download_private_file(
                bot_token=bot_token,
                private_url=info.private_url,
                max_bytes=limit,
            )
            if len(body) != metadata.declared_size:
                raise ExternalChannelFileTransferError(
                    "Slack file size does not match current provider metadata."
                )
        except ExternalChannelFileTransferError:
            raise
        except SlackProviderFileTooLarge:
            raise ExternalChannelFileTransferError(
                f"Slack file exceeds the configured inbound limit of {limit} bytes."
            ) from None
        except SlackProviderFileNotFound:
            raise ExternalChannelFileTransferError(
                "Slack no longer exposes the requested file."
            ) from None
        except SlackProviderPermissionDenied:
            raise ExternalChannelFileTransferError(
                "Slack denied access to the requested file."
            ) from None
        except SlackProviderCredentialsInvalid:
            raise ExternalChannelFileTransferError(
                "Slack rejected the active External Channel credential."
            ) from None
        except SlackProviderRateLimited:
            raise ExternalChannelFileTransferError(
                "Slack rate limited the file download request."
            ) from None
        except SlackProviderRequestRejected as error:
            raise ExternalChannelFileTransferError(
                f"Slack rejected the file download ({error.error_code})."
            ) from None
        except SlackProviderTemporaryError:
            raise ExternalChannelFileTransferError(
                "Slack file download is temporarily unavailable."
            ) from None
        filename = metadata.name or metadata.title
        if filename is None:
            raise ExternalChannelFileTransferError(
                "Slack file metadata does not include a filename."
            )
        try:
            attachment = await file_storage.put(
                path,
                body,
                metadata.media_type or "",
                agent_id=agent_id,
            )
        except PermissionError:
            raise ExternalChannelFileTransferError(
                f"Runtime destination is not writable: {path}."
            ) from None
        except RuntimeStorageError as error:
            raise ExternalChannelFileTransferError(
                f"Failed to write the Runtime file: {error.detail}"
            ) from None
        except ValueError as error:
            raise ExternalChannelFileTransferError(str(error)) from None
        except OSError:
            raise ExternalChannelFileTransferError(
                f"Failed to write the Runtime file: {path}."
            ) from None
        if attachment.size != len(body):
            raise ExternalChannelFileTransferError(
                "Runtime reported an incomplete file write."
            )
        return ExternalChannelFileDownloadResult(
            path=path,
            filename=filename,
            media_type=metadata.media_type,
            bytes_written=len(body),
        )

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
