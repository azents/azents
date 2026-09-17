"""Public file-download route tests."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from pathlib import PurePosixPath
from unittest.mock import AsyncMock, Mock
from urllib.parse import quote

import pytest
from azcommon.result import Failure, Success
from fastapi import HTTPException

from azents.api.public.chat.v1 import (
    download_agent_workspace_file,
    download_exchange_file,
)
from azents.api.public.file_download import FileDownloadResponse
from azents.core.auth.deps import CurrentUser
from azents.repos.exchange_file.data import ExchangeFile
from azents.services.chat.data import (
    NotWorkspaceMember,
    SessionAccessDenied,
)
from azents.services.chat.workspace import (
    AgentWorkspaceFileNotFound,
    AgentWorkspaceFileReadError,
    AgentWorkspaceFileService,
    WorkspaceFileDownloadStream,
)
from azents.services.exchange_file import (
    ExchangeFileDownloadStream,
    ExchangeFileService,
    FileAccessDenied,
    FileExpired,
    FileNotFound,
    FileUnavailable,
)
from azents.services.file_download_stream import BoundedDownloadStream

_AGENT_ID = "0123456789abcdef0123456789abcdef"
_CURRENT_USER = CurrentUser(user_id="user-1", session_id="auth-session")


async def _make_stream(body: bytes = b"download") -> BoundedDownloadStream:
    """Create one bounded stream suitable for a response-only route test."""

    @asynccontextmanager
    async def source() -> AsyncGenerator[AsyncIterator[bytes], None]:
        async def chunks() -> AsyncIterator[bytes]:
            yield body

        yield chunks()

    source_context = source()
    source_iterator = await source_context.__aenter__()
    return BoundedDownloadStream(
        source_context=source_context,
        source_iterator=source_iterator,
        expected_size=len(body),
        expected_sha256=hashlib.sha256(body).hexdigest(),
        maximum_chunk_size=max(1, len(body)),
    )


@pytest.mark.asyncio
async def test_workspace_download_route_preserves_stream_headers() -> None:
    """Workspace route keeps the media type and UTF-8 filename metadata."""
    stream = await _make_stream()
    path = PurePosixPath("/workspace/agent/report.txt")
    service = Mock(spec=AgentWorkspaceFileService)
    service.open_download_file = AsyncMock(
        return_value=Success(
            WorkspaceFileDownloadStream(
                path=path,
                stream=stream,
                media_type="text/plain",
            )
        )
    )

    response = await download_agent_workspace_file(
        agent_id=_AGENT_ID,
        path=path.as_posix(),
        current_user=_CURRENT_USER,
        workspace_service=service,
    )

    assert isinstance(response, FileDownloadResponse)
    assert response.download_stream is stream
    assert response.media_type == "text/plain"
    assert response.headers["content-disposition"] == (
        "attachment; filename*=UTF-8''report.txt"
    )
    service.open_download_file.assert_awaited_once_with(
        agent_id=_AGENT_ID,
        user_id="user-1",
        raw_path=path.as_posix(),
    )
    await stream.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (NotWorkspaceMember(), 403),
        (SessionAccessDenied(), 403),
        (AgentWorkspaceFileNotFound(), 404),
        (AgentWorkspaceFileReadError(detail="transfer failed"), 400),
    ],
)
async def test_workspace_download_route_maps_authorization_and_read_errors(
    error: object,
    status_code: int,
) -> None:
    """Workspace service errors retain their existing HTTP status semantics."""
    service = Mock(spec=AgentWorkspaceFileService)
    service.open_download_file = AsyncMock(return_value=Failure(error))

    with pytest.raises(HTTPException) as raised:
        await download_agent_workspace_file(
            agent_id=_AGENT_ID,
            path="/workspace/agent/report.txt",
            current_user=_CURRENT_USER,
            workspace_service=service,
        )

    assert raised.value.status_code == status_code


@pytest.mark.asyncio
async def test_exchange_download_route_preserves_stream_headers() -> None:
    """Exchange route keeps the stored media type and encoded filename."""
    stream = await _make_stream()
    file = ExchangeFile.model_construct(
        filename="보고서.csv",
        media_type="text/csv",
    )
    service = Mock(spec=ExchangeFileService)
    service.open_download = AsyncMock(
        return_value=Success(
            ExchangeFileDownloadStream(
                file=file,
                stream=stream,
            )
        )
    )

    response = await download_exchange_file(
        file_id="file-1",
        current_user=_CURRENT_USER,
        exchange_file_service=service,
    )

    assert isinstance(response, FileDownloadResponse)
    assert response.download_stream is stream
    assert response.media_type == "text/csv"
    assert response.headers["content-disposition"] == (
        f"attachment; filename*=UTF-8''{quote(file.filename)}"
    )
    service.open_download.assert_awaited_once_with(
        file_id="file-1",
        user_id="user-1",
    )
    await stream.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (FileNotFound(), 404),
        (FileAccessDenied(), 403),
        (FileExpired(), 410),
        (FileUnavailable(), 410),
    ],
)
async def test_exchange_download_route_maps_access_and_storage_errors(
    error: object,
    status_code: int,
) -> None:
    """Exchange service errors retain authorization and storage HTTP semantics."""
    service = Mock(spec=ExchangeFileService)
    service.open_download = AsyncMock(return_value=Failure(error))

    with pytest.raises(HTTPException) as raised:
        await download_exchange_file(
            file_id="file-1",
            current_user=_CURRENT_USER,
            exchange_file_service=service,
        )

    assert raised.value.status_code == status_code
