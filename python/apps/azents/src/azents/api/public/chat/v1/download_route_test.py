"""Authenticated metadata-only browser-download redirect route tests."""

import datetime
from unittest.mock import AsyncMock, Mock

import pytest
from azcommon.result import Failure, Success
from fastapi import HTTPException
from fastapi.responses import RedirectResponse

from azents.api.public.chat.v1 import (
    delete_exchange_file,
    download_agent_workspace_file,
    download_exchange_file,
    read_agent_workspace_path,
)
from azents.core.auth.deps import CurrentUser
from azents.services.browser_file_download import BrowserFileDownloadTicket
from azents.services.chat.data import NotWorkspaceMember, SessionAccessDenied
from azents.services.chat.workspace import (
    AgentWorkspaceFileNotFound,
    AgentWorkspaceFileReadError,
    AgentWorkspaceFileService,
    AgentWorkspaceFileTooLarge,
)
from azents.services.exchange_file import (
    ExchangeFileService,
    FileAccessDenied,
    FileExpired,
    FileNotFound,
    FileTooLarge,
    FileUnavailable,
)

_AGENT_ID = "0123456789abcdef0123456789abcdef"
_CURRENT_USER = CurrentUser(user_id="user-1", session_id="auth-session")
_TICKET = BrowserFileDownloadTicket(
    url="https://objects.test/file?signature=redacted",
    expires_at=datetime.datetime(2026, 9, 29, tzinfo=datetime.UTC),
)


@pytest.mark.asyncio
async def test_workspace_download_returns_uncached_redirect_with_no_file_body() -> None:
    service = Mock(spec=AgentWorkspaceFileService)
    service.create_download_ticket = AsyncMock(return_value=Success(_TICKET))

    response = await download_agent_workspace_file(
        agent_id=_AGENT_ID,
        path="/workspace/agent/report.txt",
        current_user=_CURRENT_USER,
        workspace_service=service,
    )

    assert isinstance(response, RedirectResponse)
    assert response.status_code == 302
    assert response.body == b""
    assert response.headers["location"] == _TICKET.url
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    service.create_download_ticket.assert_awaited_once_with(
        agent_id=_AGENT_ID,
        user_id="user-1",
        raw_path="/workspace/agent/report.txt",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (NotWorkspaceMember(), 403),
        (SessionAccessDenied(), 403),
        (AgentWorkspaceFileNotFound(), 404),
        (AgentWorkspaceFileReadError(detail="transfer failed"), 400),
        (AgentWorkspaceFileTooLarge(size=134_217_729, limit=134_217_728), 413),
    ],
)
async def test_workspace_denial_returns_no_redirect(
    error: object, status_code: int
) -> None:
    service = Mock(spec=AgentWorkspaceFileService)
    service.create_download_ticket = AsyncMock(return_value=Failure(error))

    with pytest.raises(HTTPException) as raised:
        await download_agent_workspace_file(
            agent_id=_AGENT_ID,
            path="/workspace/agent/report.txt",
            current_user=_CURRENT_USER,
            workspace_service=service,
        )

    assert raised.value.status_code == status_code
    assert raised.value.headers is None


@pytest.mark.asyncio
async def test_workspace_download_size_error_describes_general_file_limit() -> None:
    service = Mock(spec=AgentWorkspaceFileService)
    service.create_download_ticket = AsyncMock(
        return_value=Failure(
            AgentWorkspaceFileTooLarge(size=134_217_729, limit=134_217_728)
        )
    )

    with pytest.raises(HTTPException) as raised:
        await download_agent_workspace_file(
            agent_id=_AGENT_ID,
            path="/workspace/agent/report.txt",
            current_user=_CURRENT_USER,
            workspace_service=service,
        )

    assert raised.value.status_code == 413
    assert raised.value.detail == "File exceeds 128 MiB."
    assert raised.value.headers is None


@pytest.mark.asyncio
async def test_workspace_preview_limit_remains_distinct_from_download_limit() -> None:
    service = Mock(spec=AgentWorkspaceFileService)
    service.read_path = AsyncMock(
        return_value=Failure(AgentWorkspaceFileTooLarge(size=65537, limit=65536))
    )

    with pytest.raises(HTTPException) as raised:
        await read_agent_workspace_path(
            agent_id=_AGENT_ID,
            path="/workspace/agent/report.txt",
            limit=65536,
            current_user=_CURRENT_USER,
            workspace_service=service,
        )

    assert raised.value.status_code == 413
    assert raised.value.detail == (
        "File is too large to preview. Size 65537 bytes exceeds "
        "the 65536 byte preview limit."
    )
    assert raised.value.headers is None


@pytest.mark.asyncio
@pytest.mark.parametrize("disposition", ["attachment", "inline"])
async def test_exchange_redirect_delegates_safe_disposition_to_service(
    disposition: str,
) -> None:
    service = Mock(spec=ExchangeFileService)
    service.create_download_ticket = AsyncMock(return_value=Success(_TICKET))

    response = await download_exchange_file(
        file_id="file-1",
        current_user=_CURRENT_USER,
        exchange_file_service=service,
        disposition="inline" if disposition == "inline" else "attachment",
    )

    assert response.status_code == 302
    assert response.body == b""
    assert response.headers["location"] == _TICKET.url
    assert response.headers["cache-control"] == "no-store"
    service.create_download_ticket.assert_awaited_once_with(
        file_id="file-1",
        user_id="user-1",
        inline=disposition == "inline",
    )
    assert response.headers["referrer-policy"] == "no-referrer"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (FileNotFound(), 404),
        (FileAccessDenied(), 403),
        (FileExpired(), 410),
        (FileUnavailable(), 410),
        (FileTooLarge(), 413),
    ],
)
async def test_exchange_denial_issues_no_capability(
    error: object, status_code: int
) -> None:
    service = Mock(spec=ExchangeFileService)
    service.create_download_ticket = AsyncMock(return_value=Failure(error))

    with pytest.raises(HTTPException) as raised:
        await download_exchange_file(
            file_id="file-1",
            current_user=_CURRENT_USER,
            exchange_file_service=service,
        )

    assert raised.value.status_code == status_code
    assert raised.value.headers is None


@pytest.mark.asyncio
async def test_exchange_delete_denial_forwards_requester_and_bounds_error() -> None:
    """DELETE forwards authenticated identity and returns no storage diagnostics."""
    current_user = CurrentUser(user_id="other-user", session_id="auth-session")
    service = Mock(spec=ExchangeFileService)
    service.delete = AsyncMock(return_value=Failure(FileAccessDenied()))

    with pytest.raises(HTTPException) as raised:
        await delete_exchange_file(
            file_id="file-1",
            current_user=current_user,
            exchange_file_service=service,
        )

    service.delete.assert_awaited_once_with(
        file_id="file-1", user_id=current_user.user_id
    )
    assert raised.value.status_code == 403
    assert raised.value.detail == "File access denied."
    assert raised.value.headers is None
