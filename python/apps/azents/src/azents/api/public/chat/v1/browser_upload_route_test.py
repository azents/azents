"""Chat direct browser upload route and metadata-only OpenAPI contracts."""

import datetime
from unittest.mock import Mock

import pytest
from azcommon.infra.s3.service import S3PresignedRequest
from azcommon.result import Failure, Success
from fastapi import HTTPException, Response
from fastapi.openapi.utils import get_openapi
from pydantic import ValidationError

from azents.api.public.chat.v1 import (
    finalize_file_upload_for_agent,
    prepare_file_upload_for_agent,
    router,
)
from azents.api.public.chat.v1.data import ChatUploadPrepareRequest
from azents.core.auth.deps import CurrentUser
from azents.core.enums import ExchangeFileOrigin, ExchangeFileStatus
from azents.core.exchange_upload import ExchangeUploadError
from azents.repos.exchange_file.data import ExchangeFile
from azents.services.exchange_file import ExchangeFileService, ExchangeUploadPreparation

_AGENT_ID = "0123456789abcdef0123456789abcdef"
_UPLOAD_ID = "abcdefabcdefabcdefabcdefabcdefab"
_USER_ID = "authenticated-user"
_NOW = datetime.datetime(2026, 9, 29, tzinfo=datetime.UTC)
_DIGEST = "a" * 64


def _request() -> ChatUploadPrepareRequest:
    """Build a valid upload manifest without caller ownership fields."""
    return ChatUploadPrepareRequest(
        filename="report.txt", media_type="text/plain", size=12, sha256=_DIGEST
    )


def _current_user() -> CurrentUser:
    """Use the authenticated requester rather than client-provided identity."""
    return CurrentUser(user_id=_USER_ID, session_id="auth-session")


def _published_file() -> ExchangeFile:
    """Create the bounded attachment value returned after publication."""
    return ExchangeFile(
        id="publication-1",
        workspace_id="workspace-1",
        agent_id=_AGENT_ID,
        origin_type=ExchangeFileOrigin.UPLOAD,
        status=ExchangeFileStatus.AVAILABLE,
        object_key="exchange/workspace-1/files/publication-1/original",
        filename="report.txt",
        media_type="text/plain",
        size_bytes=12,
        sha256=_DIGEST,
        retention_root_session_id=None,
        retention_bound_at=None,
        expires_at=_NOW + datetime.timedelta(days=7),
        created_at=_NOW,
    )


def test_chat_upload_routes_expose_only_json_control_and_no_raw_body() -> None:
    """Prepare is JSON-only; finalize has no upload body or storage selectors."""
    openapi = get_openapi(title="test", version="1", routes=router.routes)
    prepare = openapi["paths"]["/agents/{agent_id}/uploads"]["post"]
    finalize = openapi["paths"]["/agents/{agent_id}/uploads/{upload_id}/finalize"][
        "post"
    ]
    assert set(prepare["requestBody"]["content"]) == {"application/json"}
    assert "requestBody" not in finalize
    schemas = openapi["components"]["schemas"]
    request = schemas["ChatUploadPrepareRequest"]
    assert set(request["properties"]) == {"filename", "media_type", "size", "sha256"}
    assert set(request["required"]) == {"filename", "media_type", "size", "sha256"}
    assert request["properties"]["size"]["maximum"] == 128 * 1024 * 1024
    assert request["properties"]["size"]["minimum"] == 0
    assert set(schemas["ChatUploadPrepareResponse"]["properties"]) == {
        "upload_id",
        "put_url",
        "put_headers",
        "expires_at",
    }
    assert set(schemas["UploadResponse"]["properties"]) == {
        "attachment_id",
        "uri",
        "media_type",
        "size",
        "name",
    }
    for operation in (prepare, finalize):
        assert all(parameter["in"] == "path" for parameter in operation["parameters"])
        assert set(operation["responses"]["200"]["content"]) == {"application/json"}


async def test_prepare_forwards_requester_and_returns_transient_ticket() -> None:
    """A prepare ticket is never reported as an already published attachment."""
    service = Mock(spec=ExchangeFileService)
    ticket = S3PresignedRequest(
        method="PUT",
        url="https://objects.example/put?signature=secret",
        expires_at=_NOW + datetime.timedelta(minutes=5),
        headers={"content-type": "text/plain", "x-amz-checksum-sha256": "checksum"},
    )
    service.prepare_agent_browser_upload.return_value = Success(
        ExchangeUploadPreparation(upload_id=_UPLOAD_ID, request=ticket)
    )
    response = Response()
    result = await prepare_file_upload_for_agent(
        agent_id=_AGENT_ID,
        request=_request(),
        response=response,
        current_user=_current_user(),
        exchange_file_service=service,
    )
    service.prepare_agent_browser_upload.assert_awaited_once_with(
        agent_id=_AGENT_ID,
        user_id=_USER_ID,
        filename="report.txt",
        media_type="text/plain",
        size=12,
        sha256=_DIGEST,
    )
    assert result.model_dump() == {
        "upload_id": _UPLOAD_ID,
        "put_url": ticket.url,
        "put_headers": dict(ticket.headers),
        "expires_at": ticket.expires_at,
    }
    assert response.headers["cache-control"] == "no-store"
    assert "attachment_id" not in result.model_dump()
    assert "object_key" not in result.model_dump()
    assert "uri" not in result.model_dump()
    service.finalize_agent_browser_upload.assert_not_awaited()


async def test_finalize_returns_existing_attachment_contract_without_ticket() -> None:
    """Only trusted finalized metadata becomes a client attachment."""
    service = Mock(spec=ExchangeFileService)
    publication = _published_file()
    service.finalize_agent_browser_upload.return_value = Success(publication)
    result = await finalize_file_upload_for_agent(
        agent_id=_AGENT_ID,
        upload_id=_UPLOAD_ID,
        current_user=_current_user(),
        exchange_file_service=service,
    )
    service.finalize_agent_browser_upload.assert_awaited_once_with(
        agent_id=_AGENT_ID, user_id=_USER_ID, upload_id=_UPLOAD_ID
    )
    assert result.model_dump() == {
        "attachment_id": publication.id,
        "uri": publication.uri,
        "media_type": "text/plain",
        "size": 12,
        "name": "report.txt",
    }
    assert "put_url" not in result.model_dump()
    assert "object_key" not in result.model_dump()
    assert "upload_id" not in result.model_dump()


@pytest.mark.parametrize(
    ("error", "status", "detail"),
    [
        (ExchangeUploadError.NOT_FOUND, 404, "Upload or Agent not found."),
        (ExchangeUploadError.ACCESS_DENIED, 403, "Upload access denied."),
        (ExchangeUploadError.EXPIRED, 410, "Upload has expired."),
        (ExchangeUploadError.BUSY, 409, "Upload claim is unavailable."),
        (ExchangeUploadError.FENCED, 409, "Upload claim is unavailable."),
        (
            ExchangeUploadError.MANIFEST_MISMATCH,
            400,
            "Upload does not match its manifest.",
        ),
        (ExchangeUploadError.INVALID_REQUEST, 400, "Invalid upload manifest."),
    ],
)
@pytest.mark.parametrize("finalize", [False, True])
async def test_routes_map_bounded_errors_without_storage_diagnostics(
    error: ExchangeUploadError, status: int, detail: str, finalize: bool
) -> None:
    """Each failure retains its public status and fixed non-sensitive detail."""
    service = Mock(spec=ExchangeFileService)
    service.prepare_agent_browser_upload.return_value = Failure(error)
    service.finalize_agent_browser_upload.return_value = Failure(error)
    with pytest.raises(HTTPException) as caught:
        if finalize:
            await finalize_file_upload_for_agent(
                agent_id=_AGENT_ID,
                upload_id=_UPLOAD_ID,
                current_user=_current_user(),
                exchange_file_service=service,
            )
        else:
            await prepare_file_upload_for_agent(
                agent_id=_AGENT_ID,
                request=_request(),
                response=Response(),
                current_user=_current_user(),
                exchange_file_service=service,
            )
    assert caught.value.status_code == status
    assert caught.value.detail == detail


@pytest.mark.parametrize("agent_id", ["invalid", "../other", "A" * 32, "0" * 31])
async def test_prepare_rejects_invalid_agent_before_service(agent_id: str) -> None:
    """Malformed Agent identifiers cannot reach authorization or presigning."""
    service = Mock(spec=ExchangeFileService)
    with pytest.raises(HTTPException) as caught:
        await prepare_file_upload_for_agent(
            agent_id=agent_id,
            request=_request(),
            response=Response(),
            current_user=_current_user(),
            exchange_file_service=service,
        )
    assert caught.value.status_code == 400
    service.prepare_agent_browser_upload.assert_not_awaited()


@pytest.mark.parametrize(
    ("agent_id", "upload_id"),
    [
        ("invalid", _UPLOAD_ID),
        (_AGENT_ID, "invalid"),
        (_AGENT_ID, "A" * 32),
        (_AGENT_ID, "../upload"),
    ],
)
async def test_finalize_rejects_invalid_ids_before_service(
    agent_id: str,
    upload_id: str,
) -> None:
    """Both ownership selectors must be valid bounded hexadecimal identifiers."""
    service = Mock(spec=ExchangeFileService)
    with pytest.raises(HTTPException) as caught:
        await finalize_file_upload_for_agent(
            agent_id=agent_id,
            upload_id=upload_id,
            current_user=_current_user(),
            exchange_file_service=service,
        )
    assert caught.value.status_code == 400
    service.finalize_agent_browser_upload.assert_not_awaited()


@pytest.mark.parametrize("size", [-1, 128 * 1024 * 1024 + 1, True, "12", 1.5])
def test_prepare_model_rejects_out_of_range_or_noninteger_size(
    size: int | bool | str | float,
) -> None:
    """The JSON manifest rejects booleans and coercible non-integers."""
    with pytest.raises(ValidationError):
        ChatUploadPrepareRequest.model_validate(
            {
                "filename": "report.txt",
                "media_type": "text/plain",
                "size": size,
                "sha256": _DIGEST,
            }
        )


@pytest.mark.parametrize("digest", ["", "a" * 63, "a" * 65, "A" * 64, "g" * 64])
def test_prepare_model_requires_exact_lowercase_sha256(digest: str) -> None:
    """Malformed digests are rejected before service-side ticket issuance."""
    with pytest.raises(ValidationError):
        ChatUploadPrepareRequest(
            filename="report.txt", media_type="text/plain", size=12, sha256=digest
        )


@pytest.mark.parametrize(
    "media_type", ["", "text/plain\r", "text/plain\nInjected: yes"]
)
def test_prepare_model_rejects_header_injection(media_type: str) -> None:
    """Signed content-type values cannot contain a newline or be empty."""
    with pytest.raises(ValidationError):
        ChatUploadPrepareRequest(
            filename="report.txt", media_type=media_type, size=12, sha256=_DIGEST
        )


@pytest.mark.parametrize("size", [0, 128 * 1024 * 1024])
def test_prepare_model_accepts_zero_and_maximum_size(size: int) -> None:
    """Boundary sizes retain the declared 128 MiB upload contract."""
    request = ChatUploadPrepareRequest(
        filename="report.txt", media_type="text/plain", size=size, sha256=_DIGEST
    )
    assert request.size == size
