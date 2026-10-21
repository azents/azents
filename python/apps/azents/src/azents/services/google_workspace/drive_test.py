"""Drive SDK routing, media integrity and permission tests with synthetic HTTP."""

import dataclasses
import hashlib
import io
import json
import zipfile
from collections.abc import Callable, Iterator

import httpx
import pytest
from pydantic import BaseModel, ValidationError
from pypdf import PdfWriter

from azents.core.google_oauth import GoogleOAuthError
from azents.core.google_policy import GoogleService
from azents.core.google_workspace_policy import GoogleWorkspaceOperation as Op
from azents.core.google_workspace_policy import drive_access, operation_permitted
from azents.services.google_workspace import drive
from azents.services.google_workspace import drive_models as m
from azents.services.google_workspace.drive_import import (
    import_file,
    validate_office_archive,
)
from azents.services.google_workspace.errors import GoogleWorkspacePartialError
from azents.services.google_workspace.file_models import (
    GooglePreparedFile,
)
from azents.services.google_workspace.transport import (
    GoogleSdkError,
    GoogleSdkLimits,
    GoogleSdkSession,
    GoogleWorkspaceSdk,
)


class _Stream(httpx.SyncByteStream):
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __iter__(self) -> Iterator[bytes]:
        yield self.body


@dataclasses.dataclass(frozen=True)
class _Reply:
    status: int
    payload: object
    headers: dict[str, str] = dataclasses.field(default_factory=dict)


async def _run[T](
    operation: Callable[[GoogleSdkSession], T],
    replies: tuple[_Reply, ...],
    requests: list[httpx.Request],
    *,
    before_request: Callable[[], None] = lambda: None,
) -> T:
    values = iter(replies)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        reply = next(values)
        raw = (
            reply.payload
            if isinstance(reply.payload, bytes)
            else json.dumps(reply.payload).encode()
        )
        if reply.status == 204:
            raw = b""
        return httpx.Response(
            reply.status,
            headers={"content-type": "application/json", **reply.headers},
            stream=_Stream(raw),
        )

    sdk = GoogleWorkspaceSdk(
        capacity=1,
        client_factory=lambda proxy, timeout: httpx.Client(
            transport=httpx.MockTransport(handler)
        ),
    )
    return await sdk.run(
        access_token="fixture",
        limits=GoogleSdkLimits(
            maximum_response_bytes=2 * 1024 * 1024,
            maximum_total_received_bytes=8 * 1024 * 1024,
            maximum_upload_bytes=2 * 1024 * 1024,
            timeout=5,
        ),
        proxy_url=None,
        before_request=before_request,
        operation=operation,
    )


def _metadata(
    *, file_id: str = "file", content: bytes = b"hello", mime_type: str = "text/plain"
) -> dict[str, object]:
    return {
        "id": file_id,
        "name": "file.txt",
        "mimeType": mime_type,
        "size": str(len(content)),
        "sha256Checksum": hashlib.sha256(content).hexdigest(),
        "capabilities": {
            "canDownload": True,
            "canModifyContent": True,
            "canShare": True,
        },
    }


def _content(file_id: str = "file", *, follow: bool = False) -> m.DriveContentInput:
    return m.DriveContentInput(
        file_id=file_id,
        resource_key=None,
        follow_shortcuts=follow,
        acknowledge_abuse=False,
    )


def _scope(name: str) -> str:
    return "https://www.googleapis.com/auth/" + name


def _gate(operation: Op, scopes: tuple[str, ...]) -> Callable[[], None]:
    def admit() -> None:
        if not operation_permitted(operation, (GoogleService.DRIVE,), scopes, ()):
            raise GoogleOAuthError(
                "capability_unavailable", "Google scope does not permit this request."
            )

    return admit


async def test_drive_search_preserves_shared_drive_pagination_and_incomplete_flag() -> (
    None
):
    requests: list[httpx.Request] = []
    value = m.DriveSearchInput(
        query="trashed = false",
        page_token="cursor",
        page_size=10,
        corpora="drive",
        drive_id="shared",
        order_by="modifiedTime desc",
    )
    result = await _run(
        lambda s: drive.search_files(s, value),
        (
            _Reply(
                200,
                {
                    "files": [_metadata()],
                    "nextPageToken": "next",
                    "incompleteSearch": True,
                },
            ),
        ),
        requests,
    )
    assert result.next_page_token == "next" and result.incomplete_search
    assert len(requests) == 1
    assert requests[0].url.params["corpora"] == "drive"
    assert requests[0].url.params["driveId"] == "shared"
    assert requests[0].url.params["includeItemsFromAllDrives"] == "true"
    assert requests[0].url.params["pageToken"] == "cursor"


@pytest.mark.parametrize(
    "corpora,drive_id", [("drive", None), ("user", "drive"), ("allDrives", "drive")]
)
def test_search_corpora_requires_exact_drive_context(
    corpora: str, drive_id: str | None
) -> None:
    with pytest.raises(ValidationError):
        m.DriveSearchInput.model_validate(
            {
                "query": None,
                "page_token": None,
                "page_size": 10,
                "corpora": corpora,
                "drive_id": drive_id,
                "order_by": None,
            }
        )


async def test_original_download_preserves_binary_hash_resource_key_and_etag() -> None:
    data = b"\x00\xfforiginal"
    requests: list[httpx.Request] = []
    value = m.DriveContentInput(
        file_id="file",
        resource_key="resource",
        follow_shortcuts=False,
        acknowledge_abuse=False,
    )
    result = await _run(
        lambda s: drive.download_file(s, value, maximum_bytes=1024),
        (
            _Reply(
                200,
                _metadata(content=data, mime_type="application/octet-stream"),
                {"etag": '"etag1"'},
            ),
            _Reply(200, data, {"content-length": str(len(data))}),
        ),
        requests,
    )
    assert result.files[0].content == data
    assert result.value.sha256 == hashlib.sha256(data).hexdigest()
    assert result.value.size == len(data)
    assert requests[1].headers["x-goog-drive-resource-keys"] == "file/resource"
    assert requests[1].headers["if-match"] == '"etag1"'
    assert requests[1].headers["range"].startswith("bytes=0-")
    assert "content" not in result.value.model_dump()


@pytest.mark.parametrize("corruption", ["size", "checksum"])
async def test_download_rejects_provider_length_or_hash_mismatch(
    corruption: str,
) -> None:
    metadata = _metadata(content=b"hello")
    if corruption == "size":
        metadata["size"] = "6"
    else:
        metadata["sha256Checksum"] = "0" * 64
    with pytest.raises(GoogleSdkError) as error:
        await _run(
            lambda s: drive.download_file(s, _content(), maximum_bytes=1024),
            (_Reply(200, metadata), _Reply(200, b"hello")),
            [],
        )
    assert error.value.code == "file_integrity_mismatch"


async def test_oversized_metadata_stops_before_media_download() -> None:
    requests: list[httpx.Request] = []
    with pytest.raises(GoogleSdkError) as error:
        await _run(
            lambda s: drive.download_file(s, _content(), maximum_bytes=4),
            (_Reply(200, _metadata()),),
            requests,
        )
    assert error.value.code == "file_receive_limit" and len(requests) == 1


async def test_media_ignoring_range_is_still_sink_bounded() -> None:
    metadata = _metadata()
    metadata.pop("size")
    metadata.pop("sha256Checksum")
    with pytest.raises(GoogleSdkError) as error:
        await _run(
            lambda s: drive.download_file(s, _content(), maximum_bytes=4),
            (_Reply(200, metadata), _Reply(200, b"unbounded body")),
            [],
        )
    assert error.value.code == "file_receive_limit"


async def test_shortcut_target_read_is_explicit_and_uses_target_resource_key() -> None:
    shortcut = {
        "id": "shortcut",
        "mimeType": "application/vnd.google-apps.shortcut",
        "shortcutDetails": {"targetId": "target", "targetResourceKey": "targetkey"},
    }
    requests: list[httpx.Request] = []
    result = await _run(
        lambda s: drive.download_file(
            s, _content("shortcut", follow=True), maximum_bytes=1024
        ),
        (
            _Reply(200, shortcut),
            _Reply(200, _metadata(file_id="target")),
            _Reply(200, b"hello"),
        ),
        requests,
    )
    assert (
        result.value.requested_file_id == "shortcut"
        and result.value.resolved_file_id == "target"
    )
    assert requests[1].headers["x-goog-drive-resource-keys"] == "target/targetkey"
    assert requests[2].url.path.endswith("/files/target")


async def test_shortcut_read_without_opt_in_performs_no_target_request() -> None:
    shortcut = {
        "id": "shortcut",
        "mimeType": "application/vnd.google-apps.shortcut",
        "shortcutDetails": {"targetId": "target"},
    }
    requests: list[httpx.Request] = []
    with pytest.raises(GoogleSdkError) as error:
        await _run(
            lambda s: drive.download_file(s, _content("shortcut"), maximum_bytes=1024),
            (_Reply(200, shortcut),),
            requests,
        )
    assert error.value.code == "shortcut_requires_explicit_target"
    assert len(requests) == 1


async def test_cyclic_shortcut_is_bounded() -> None:
    shortcut = {
        "id": "shortcut",
        "mimeType": "application/vnd.google-apps.shortcut",
        "shortcutDetails": {"targetId": "shortcut"},
    }
    requests: list[httpx.Request] = []
    with pytest.raises(GoogleSdkError) as error:
        await _run(
            lambda s: drive.download_file(
                s, _content("shortcut", follow=True), maximum_bytes=1024
            ),
            (_Reply(200, shortcut),),
            requests,
        )
    assert error.value.code == "invalid_or_cyclic_shortcut"
    assert len(requests) == 1


async def test_metadata_update_is_shortcut_local_and_presence_aware() -> None:
    requests: list[httpx.Request] = []
    value = m.DriveUpdateMetadataInput(
        file_id="shortcut",
        resource_key=None,
        changes={"description": "", "starred": False},
        add_parent_id="newparent",
        remove_parent_ids=("oldparent",),
    )
    await _run(
        lambda s: drive.update_metadata(s, value),
        (_Reply(200, {"id": "shortcut"}),),
        requests,
    )
    assert len(requests) == 1 and requests[0].method == "PATCH"
    assert requests[0].url.path.endswith("/files/shortcut")
    assert json.loads(requests[0].content) == {"description": "", "starred": False}
    assert requests[0].url.params["addParents"] == "newparent"
    assert requests[0].url.params["removeParents"] == "oldparent"


async def test_native_export_returns_original_export_bytes_and_concrete_format() -> (
    None
):
    requests: list[httpx.Request] = []
    value = m.DriveExportInput(
        file_id="doc",
        resource_key=None,
        follow_shortcuts=False,
        acknowledge_abuse=False,
        export_media_type="application/pdf",
    )
    result = await _run(
        lambda s: drive.export_file(s, value, maximum_bytes=1024),
        (
            _Reply(
                200,
                {
                    "id": "doc",
                    "name": "Project",
                    "mimeType": "application/vnd.google-apps.document",
                },
            ),
            _Reply(200, b"%PDF-fixture"),
        ),
        requests,
    )
    assert result.value.exported and result.files[0].content == b"%PDF-fixture"
    assert result.value.filename == "Project.pdf"
    assert requests[1].url.path.endswith("/files/doc/export")
    assert requests[1].url.params["mimeType"] == "application/pdf"


async def test_native_read_defaults_to_text_but_returns_explicit_preview() -> None:
    value = m.DriveReadInput(
        file_id="doc",
        resource_key=None,
        follow_shortcuts=False,
        acknowledge_abuse=False,
        export_media_type=None,
        character_limit=4,
    )
    result = await _run(
        lambda s: drive.read_content(s, value, maximum_bytes=1024),
        (
            _Reply(
                200,
                {
                    "id": "doc",
                    "mimeType": "application/vnd.google-apps.document",
                    "name": "Project",
                },
            ),
            _Reply(200, b"document body"),
        ),
        [],
    )
    assert result.value.text == "docu" and result.value.extraction_status == "truncated"
    assert result.files[0].content == b"document body"


async def test_native_file_download_requires_explicit_supported_export() -> None:
    requests: list[httpx.Request] = []
    with pytest.raises(GoogleSdkError) as error:
        await _run(
            lambda s: drive.download_file(s, _content("doc"), maximum_bytes=1024),
            (
                _Reply(
                    200,
                    {"id": "doc", "mimeType": "application/vnd.google-apps.document"},
                ),
            ),
            requests,
        )
    assert error.value.code == "unsupported_export_format" and len(requests) == 1


async def test_link_read_does_not_create_public_access() -> None:
    requests: list[httpx.Request] = []
    result = await _run(
        lambda s: drive.get_link(
            s, m.DriveFileIdInput(file_id="file", resource_key=None)
        ),
        (
            _Reply(
                200,
                {
                    "id": "file",
                    "webViewLink": "https://drive.google.com/file/d/file/view",
                    "shared": False,
                },
            ),
        ),
        requests,
    )
    assert not result.sharing_changed
    assert len(requests) == 1 and requests[0].method == "GET"


def _upload_replies(metadata: object) -> tuple[_Reply, ...]:
    return (
        _Reply(
            200,
            b"",
            {
                "location": "https://www.googleapis.com/upload/drive/v3/files?upload_id=fixture"
            },
        ),
        _Reply(200, metadata),
    )


async def test_file_create_uses_one_sdk_resumable_session_without_replay() -> None:
    value = m.DriveCreateFileInput(
        name="created.txt",
        parent_id="folder",
        description=None,
        content=None,
        text="new body",
        media_type="text/plain",
    )
    requests: list[httpx.Request] = []
    result = await _run(
        lambda s: drive.create_file(s, value, prepared=None, maximum_bytes=1024),
        _upload_replies({"id": "created"}),
        requests,
    )
    assert result.id == "created" and len(requests) == 2
    assert requests[0].method == "POST"
    assert requests[0].url.params["uploadType"] == "resumable"
    assert json.loads(requests[0].content) == {
        "name": "created.txt",
        "mimeType": "text/plain",
        "parents": ["folder"],
    }
    assert requests[1].method == "PUT" and requests[1].content == b"new body"


async def test_resumable_upload_failure_does_not_create_a_second_file() -> None:
    requests: list[httpx.Request] = []
    value = m.DriveCreateFileInput(
        name="file.txt",
        parent_id=None,
        description=None,
        content=None,
        text="body",
        media_type="text/plain",
    )
    with pytest.raises(GoogleSdkError) as error:
        await _run(
            lambda s: drive.create_file(s, value, prepared=None, maximum_bytes=1024),
            (
                _Reply(
                    200,
                    b"",
                    {
                        "location": "https://www.googleapis.com/upload/drive/v3/files?upload_id=fixture"
                    },
                ),
                _Reply(503, {"error": {"message": "private-body"}}),
            ),
            requests,
        )
    assert error.value.status == 503
    assert [r.method for r in requests] == ["POST", "PUT"]
    assert "private-body" not in str(error.value)


async def test_lowered_product_file_limit_precedes_upload_session_creation() -> None:
    value = m.DriveCreateFileInput(
        name="file.txt",
        parent_id=None,
        description=None,
        content=None,
        text="too much text",
        media_type="text/plain",
    )
    requests: list[httpx.Request] = []
    with pytest.raises(GoogleSdkError) as error:
        await _run(
            lambda s: drive.create_file(
                s,
                value,
                prepared=None,
                maximum_bytes=4,
            ),
            (),
            requests,
        )
    assert error.value.code == "file_upload_limit"
    assert not error.value.dispatched and not requests


async def test_cancelled_admission_between_upload_steps_sends_no_file_bytes() -> None:
    requests: list[httpx.Request] = []
    admissions = 0

    def admit() -> None:
        nonlocal admissions
        admissions += 1
        if admissions > 1:
            raise GoogleOAuthError("capability_unavailable", "Drive disabled.")

    value = m.DriveCreateFileInput(
        name="file.txt",
        parent_id=None,
        description=None,
        content=None,
        text="body",
        media_type="text/plain",
    )
    with pytest.raises(GoogleOAuthError):
        await _run(
            lambda s: drive.create_file(s, value, prepared=None, maximum_bytes=1024),
            (
                _Reply(
                    200,
                    b"",
                    {
                        "location": "https://www.googleapis.com/upload/drive/v3/files?upload_id=fixture"
                    },
                ),
            ),
            requests,
            before_request=admit,
        )
    assert len(requests) == 1 and requests[0].method == "POST"


async def test_content_update_targets_resolved_shortcut_content() -> None:
    value = m.DriveUpdateContentInput(
        file_id="shortcut",
        resource_key=None,
        follow_shortcuts=True,
        acknowledge_abuse=False,
        content=None,
        text="replacement",
        media_type="text/plain",
    )
    requests: list[httpx.Request] = []
    replies = (
        _Reply(
            200,
            {
                "id": "shortcut",
                "mimeType": "application/vnd.google-apps.shortcut",
                "shortcutDetails": {"targetId": "target"},
            },
        ),
        _Reply(200, _metadata(file_id="target"), {"etag": '"version"'}),
        *_upload_replies({"id": "target"}),
    )
    await _run(
        lambda s: drive.update_content(s, value, prepared=None, maximum_bytes=1024),
        replies,
        requests,
    )
    assert requests[2].url.path.endswith("/files/target")
    assert requests[2].headers["if-match"] == '"version"'
    assert requests[-1].content == b"replacement"


async def test_append_utf8_text_is_conditional_and_preserves_existing_bytes() -> None:
    value = m.DriveAppendInput(
        file_id="file",
        resource_key=None,
        follow_shortcuts=False,
        acknowledge_abuse=False,
        text=" world",
        position="append",
    )
    requests: list[httpx.Request] = []
    await _run(
        lambda s: drive.append_text(s, value, maximum_bytes=1024),
        (
            _Reply(200, _metadata(), {"etag": '"v1"'}),
            _Reply(200, b"hello"),
            *_upload_replies({"id": "file"}),
        ),
        requests,
    )
    assert requests[-1].content == b"hello world"
    assert requests[-2].headers["if-match"] == '"v1"'


async def test_append_without_etag_does_not_guess_current_version() -> None:
    requests: list[httpx.Request] = []
    value = m.DriveAppendInput(
        file_id="file",
        resource_key=None,
        follow_shortcuts=False,
        acknowledge_abuse=False,
        text="more",
        position="append",
    )
    with pytest.raises(GoogleSdkError) as error:
        await _run(
            lambda s: drive.append_text(s, value, maximum_bytes=1024),
            (_Reply(200, _metadata()),),
            requests,
        )
    assert error.value.code == "file_precondition_unavailable" and len(requests) == 1


async def test_native_content_replacement_is_not_lossless_structural_editing() -> None:
    requests: list[httpx.Request] = []
    value = m.DriveUpdateContentInput(
        file_id="doc",
        resource_key=None,
        follow_shortcuts=False,
        acknowledge_abuse=False,
        content=None,
        text="replacement",
        media_type="text/plain",
    )
    with pytest.raises(GoogleSdkError) as error:
        await _run(
            lambda s: drive.update_content(s, value, prepared=None, maximum_bytes=1024),
            (
                _Reply(
                    200,
                    {"id": "doc", "mimeType": "application/vnd.google-apps.document"},
                ),
            ),
            requests,
        )
    assert error.value.code == "content_requires_ordinary_file" and len(requests) == 1


async def test_metadata_scope_changes_access_fields_not_content_permissions() -> None:
    requests: list[httpx.Request] = []
    value = m.DriveUpdateAccessInput(
        file_id="file",
        resource_key=None,
        changes={"writers_can_share": False, "restrict_download_for_readers": True},
    )
    await _run(
        lambda s: drive.update_access(s, value),
        (_Reply(200, {"id": "file", "writersCanShare": False}),),
        requests,
        before_request=_gate(Op.DRIVE_UPDATE_ACCESS, (_scope("drive.metadata"),)),
    )
    assert json.loads(requests[0].content) == {
        "writersCanShare": False,
        "downloadRestrictions": {
            "itemDownloadRestriction": {"restrictedForReaders": True}
        },
    }
    assert not operation_permitted(
        Op.DRIVE_CREATE_PERMISSION,
        (GoogleService.DRIVE,),
        (_scope("drive.metadata"),),
        (),
    )
    assert not operation_permitted(
        Op.DRIVE_UPDATE_CONTENT, (GoogleService.DRIVE,), (_scope("drive.metadata"),), ()
    )


def test_mixed_readonly_and_app_file_grants_do_not_claim_whole_write() -> None:
    scopes = (_scope("drive.readonly"), _scope("drive.file"))
    extent = drive_access((GoogleService.DRIVE,), scopes)
    assert extent.whole_content_read and extent.app_file_write
    assert not extent.whole_content_write


async def test_readable_but_non_app_file_write_rejection_is_resource_local() -> None:
    requests: list[httpx.Request] = []
    value = m.DriveUpdateMetadataInput(
        file_id="readable",
        resource_key=None,
        changes={"name": "new"},
        add_parent_id=None,
        remove_parent_ids=(),
    )
    with pytest.raises(GoogleSdkError) as error:
        await _run(
            lambda s: drive.update_metadata(s, value),
            (_Reply(403, {"error": {"message": "not app eligible"}}),),
            requests,
            before_request=_gate(
                Op.DRIVE_UPDATE_METADATA,
                (_scope("drive.readonly"), _scope("drive.file")),
            ),
        )
    assert error.value.code == "resource_rejected" and error.value.status == 403
    assert len(requests) == 1


async def test_partial_sharing_keeps_confirmed_ids_without_recipient_content() -> None:
    grants = tuple(
        m.DrivePermissionGrant(
            type="user",
            role="reader",
            email=f"user{i}@example.com",
            domain=None,
            allow_file_discovery=None,
            expiration_time=None,
        )
        for i in range(3)
    )
    value = m.DriveCreatePermissionInput(
        file_id="file",
        resource_key=None,
        grants=grants,
        send_notification_email=True,
        email_message=None,
    )
    requests: list[httpx.Request] = []
    with pytest.raises(GoogleWorkspacePartialError) as error:
        await _run(
            lambda s: drive.create_permissions(s, value),
            (
                _Reply(200, {"id": "permission0", "type": "user", "role": "reader"}),
                _Reply(503, {"error": {"message": "provider-private-detail"}}),
            ),
            requests,
        )
    assert len(requests) == 2
    assert error.value.partial.completed[0].resource_ids == ("permission0",)
    assert error.value.partial.remaining_ids == ("1", "2")
    assert "user1@example.com" not in str(error.value)
    assert "provider-private-detail" not in str(error.value)


async def test_public_sharing_and_ownership_transfer_use_distinct_sdk_calls() -> None:
    requests: list[httpx.Request] = []
    grant = m.DrivePermissionGrant(
        type="anyone",
        role="reader",
        email=None,
        domain=None,
        allow_file_discovery=False,
        expiration_time=None,
    )
    await _run(
        lambda s: drive.create_permissions(
            s,
            m.DriveCreatePermissionInput(
                file_id="file",
                resource_key=None,
                grants=(grant,),
                send_notification_email=False,
                email_message=None,
            ),
        ),
        (_Reply(200, {"id": "public", "role": "reader", "type": "anyone"}),),
        requests,
    )
    assert json.loads(requests[0].content) == {
        "type": "anyone",
        "role": "reader",
        "allowFileDiscovery": False,
    }
    assert "transferOwnership" not in requests[0].url.params
    owner_requests: list[httpx.Request] = []
    await _run(
        lambda s: drive.transfer_ownership(
            s,
            m.DriveTransferOwnershipInput(
                file_id="file",
                resource_key=None,
                recipient_email="new-owner@example.com",
                move_to_new_owners_root=False,
            ),
        ),
        (_Reply(200, {"id": "newowner", "role": "owner"}),),
        owner_requests,
    )
    assert owner_requests[0].url.params["transferOwnership"] == "true"
    assert owner_requests[0].url.params["sendNotificationEmail"] == "true"
    assert json.loads(owner_requests[0].content)["role"] == "owner"


async def test_permissions_preserve_inherited_status_and_pagination() -> None:
    requests: list[httpx.Request] = []
    result = await _run(
        lambda s: drive.list_permissions(
            s,
            m.DrivePermissionListInput(
                file_id="file", resource_key=None, page_token=None, page_size=20
            ),
        ),
        (
            _Reply(
                200,
                {
                    "permissions": [
                        {
                            "id": "p",
                            "role": "reader",
                            "permissionDetails": [
                                {"inherited": True, "inheritedFrom": "parent"}
                            ],
                        }
                    ],
                    "nextPageToken": "next",
                },
            ),
        ),
        requests,
    )
    assert result.permissions[0].permission_details[0].inherited
    assert result.next_page_token == "next"
    assert requests[0].url.params["supportsAllDrives"] == "true"


@pytest.mark.parametrize(
    "kind,email,domain",
    [
        ("anyone", "user@example.com", None),
        ("domain", None, None),
        ("user", None, None),
        ("user", "a@example.com", "example.com"),
    ],
)
def test_permission_targets_are_validated_before_batch_effects(
    kind: str, email: str | None, domain: str | None
) -> None:
    with pytest.raises(ValidationError):
        m.DrivePermissionGrant.model_validate(
            {
                "type": kind,
                "role": "reader",
                "email": email,
                "domain": domain,
                "allow_file_discovery": None,
                "expiration_time": None,
            }
        )


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"role": "owner"},
        {"allow_file_discovery": "true"},
        {"expiration_time": None},
    ],
)
def test_permission_patch_is_presence_aware_and_ownership_is_not_smuggled(
    changes: object,
) -> None:
    with pytest.raises(ValidationError):
        m.DriveUpdatePermissionInput.model_validate(
            {
                "file_id": "file",
                "resource_key": None,
                "permission_id": "permission",
                "changes": changes,
                "remove_expiration": False,
            }
        )


async def test_import_markdown_renders_locally_and_uses_sdk_native_conversion() -> None:
    requests: list[httpx.Request] = []
    value = m.DriveImportInput(
        name="Document",
        parent_id=None,
        content=None,
        text="# Heading\n\nText **bold**.",
        source_format="markdown",
    )
    result = await _run(
        lambda s: import_file(
            s, value, target="document", prepared=None, maximum_bytes=1024
        ),
        _upload_replies(
            {"id": "converted", "mimeType": "application/vnd.google-apps.document"}
        ),
        requests,
    )
    assert result.id == "converted"
    assert (
        json.loads(requests[0].content)["mimeType"]
        == "application/vnd.google-apps.document"
    )
    assert requests[0].headers["x-upload-content-type"] == "text/html"
    assert b"<h1>Heading</h1>" in requests[1].content
    assert b"<strong>bold</strong>" in requests[1].content


async def test_unsupported_import_pair_fails_before_google_effect() -> None:
    requests: list[httpx.Request] = []
    value = m.DriveImportInput(
        name="Slides",
        parent_id=None,
        content=None,
        text="plain text",
        source_format="text",
    )
    with pytest.raises(GoogleSdkError) as error:
        await _run(
            lambda s: import_file(
                s, value, target="presentation", prepared=None, maximum_bytes=1024
            ),
            (),
            requests,
        )
    assert error.value.code == "unsupported_import_conversion"
    assert not requests


@pytest.mark.parametrize(
    "source_format,entry",
    [
        ("docx", "word/document.xml"),
        ("xlsx", "xl/workbook.xml"),
        ("pptx", "ppt/presentation.xml"),
    ],
)
async def test_office_import_preserves_original_archive_bytes(
    source_format: str, entry: str
) -> None:
    with io.BytesIO() as buffer:
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr(entry, "<document/>")
        data = buffer.getvalue()
    value = m.DriveImportInput.model_validate(
        {
            "name": "Imported",
            "parent_id": None,
            "content": {
                "source": "artifact://source",
                "filename": None,
                "media_type": None,
            },
            "text": None,
            "source_format": source_format,
        }
    )
    target = {"docx": "document", "xlsx": "spreadsheet", "pptx": "presentation"}[
        source_format
    ]
    requests: list[httpx.Request] = []

    def operation(session: GoogleSdkSession) -> m.DriveMetadata:
        prepared = GooglePreparedFile("input.zip", "application/zip", data, ())
        if target == "document":
            return import_file(
                session,
                value,
                target="document",
                prepared=prepared,
                maximum_bytes=10240,
            )
        if target == "spreadsheet":
            return import_file(
                session,
                value,
                target="spreadsheet",
                prepared=prepared,
                maximum_bytes=10240,
            )
        return import_file(
            session,
            value,
            target="presentation",
            prepared=prepared,
            maximum_bytes=10240,
        )

    await _run(operation, _upload_replies({"id": "converted"}), requests)
    assert requests[1].content == data


def test_office_import_rejects_archive_traversal_and_macros() -> None:
    for name in ("../outside.xml", "word/vbaProject.bin"):
        with io.BytesIO() as buffer:
            with zipfile.ZipFile(buffer, "w") as archive:
                archive.writestr("[Content_Types].xml", "<Types/>")
                archive.writestr("word/document.xml", "<document/>")
                archive.writestr(name, "data")
            data = buffer.getvalue()
        with pytest.raises(GoogleSdkError):
            validate_office_archive(data, "docx")


@pytest.mark.parametrize(
    "model",
    [
        m.DriveFileIdInput,
        m.DriveSearchInput,
        m.DriveContentInput,
        m.DriveExportInput,
        m.DriveReadInput,
        m.DriveCreateFileInput,
        m.DriveCreateFolderInput,
        m.DriveCopyInput,
        m.DriveUpdateMetadataInput,
        m.DriveUpdateContentInput,
        m.DriveAppendInput,
        m.DriveImportInput,
        m.DrivePermissionListInput,
        m.DrivePermissionIdInput,
        m.DriveCreatePermissionInput,
        m.DriveUpdatePermissionInput,
        m.DriveTransferOwnershipInput,
        m.DriveUpdateAccessInput,
    ],
)
def test_drive_tool_schemas_are_closed_top_level_objects(
    model: type[BaseModel],
) -> None:
    schema = model.model_json_schema()
    assert schema["type"] == "object" and schema["additionalProperties"] is False
    assert "oneOf" not in schema


async def test_folder_creation_uses_metadata_only_sdk_request() -> None:
    requests: list[httpx.Request] = []
    result = await _run(
        lambda s: drive.create_folder(
            s,
            m.DriveCreateFolderInput(
                name="Project",
                parent_id="parent",
                description="Project files",
            ),
        ),
        (
            _Reply(
                200, {"id": "created", "mimeType": "application/vnd.google-apps.folder"}
            ),
        ),
        requests,
    )
    assert result.id == "created" and len(requests) == 1
    assert requests[0].method == "POST"
    assert "uploadType" not in requests[0].url.params
    assert json.loads(requests[0].content) == {
        "name": "Project",
        "parents": ["parent"],
        "description": "Project files",
        "mimeType": "application/vnd.google-apps.folder",
    }


async def test_shortcut_copy_without_target_following_keeps_source_resource_local() -> (
    None
):
    requests: list[httpx.Request] = []
    value = m.DriveCopyInput(
        file_id="shortcut",
        resource_key=None,
        follow_shortcuts=False,
        acknowledge_abuse=False,
        name="Copied shortcut",
        parent_id=None,
    )
    result = await _run(
        lambda s: drive.copy_file(s, value),
        (
            _Reply(
                200,
                {
                    "id": "shortcut",
                    "mimeType": "application/vnd.google-apps.shortcut",
                    "shortcutDetails": {"targetId": "target"},
                },
            ),
            _Reply(200, {"id": "copied"}),
        ),
        requests,
    )
    assert result.id == "copied" and len(requests) == 2
    assert requests[1].url.path.endswith("/files/shortcut/copy")
    assert json.loads(requests[1].content) == {"name": "Copied shortcut"}


async def test_permission_get_and_update_keep_exact_permission_target() -> None:
    requests: list[httpx.Request] = []
    result = await _run(
        lambda s: drive.get_permission(
            s,
            m.DrivePermissionIdInput(
                file_id="file",
                resource_key=None,
                permission_id="permission",
            ),
        ),
        (
            _Reply(
                200,
                {
                    "id": "permission",
                    "role": "reader",
                    "permissionDetails": [
                        {"inherited": True, "inheritedFrom": "parent"}
                    ],
                },
            ),
        ),
        requests,
    )
    assert result.permission_details[0].inherited
    updated = await _run(
        lambda s: drive.update_permission(
            s,
            m.DriveUpdatePermissionInput(
                file_id="file",
                resource_key=None,
                permission_id="permission",
                changes={"role": "commenter"},
                remove_expiration=True,
            ),
        ),
        (_Reply(200, {"id": "permission", "role": "commenter"}),),
        requests,
    )
    assert updated.role == "commenter"
    assert requests[1].method == "PATCH"
    assert requests[1].url.path.endswith("/files/file/permissions/permission")
    assert json.loads(requests[1].content) == {"role": "commenter"}
    assert requests[1].url.params["removeExpiration"] == "true"


async def test_permission_delete_only_targets_explicit_local_permission() -> None:
    requests: list[httpx.Request] = []
    result = await _run(
        lambda s: drive.delete_permission(
            s,
            m.DrivePermissionIdInput(
                file_id="file",
                resource_key=None,
                permission_id="permission",
            ),
        ),
        (_Reply(204, None),),
        requests,
    )
    assert result.confirmed_id == "permission"
    assert len(requests) == 1 and requests[0].method == "DELETE"
    assert requests[0].url.path.endswith("/files/file/permissions/permission")


async def test_encrypted_pdf_read_keeps_original_download_without_text_claim() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("fixture-password")
    with io.BytesIO() as stream:
        writer.write(stream)
        data = stream.getvalue()
    result = await _run(
        lambda s: drive.read_content(
            s,
            m.DriveReadInput(
                file_id="file",
                resource_key=None,
                follow_shortcuts=False,
                acknowledge_abuse=False,
                export_media_type=None,
                character_limit=100,
            ),
            maximum_bytes=65536,
        ),
        (
            _Reply(200, _metadata(content=data, mime_type="application/pdf")),
            _Reply(200, data),
        ),
        [],
    )
    assert result.value.extraction_status == "encrypted"
    assert result.value.text is None and result.files[0].content == data
