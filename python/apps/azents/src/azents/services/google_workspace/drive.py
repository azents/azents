"""Direct Drive SDK methods with bounded media and explicit resource boundaries."""

import dataclasses
import io
from codecs import BOM_UTF8
from collections.abc import Buffer
from typing import TYPE_CHECKING

import httplib2
from googleapiclient.http import HttpRequest, MediaIoBaseDownload, MediaIoBaseUpload

from azents.core.file_transfer import GENERAL_FILE_MAXIMUM_BYTES
from azents.core.google_oauth import GoogleOAuthError
from azents.services.google_workspace import drive_models as m
from azents.services.google_workspace.errors import (
    GoogleCompletedStep,
    GoogleWorkspacePartialError,
)
from azents.services.google_workspace.extraction import (
    GoogleExtractionLimits,
    extract_text,
)
from azents.services.google_workspace.file_models import (
    GoogleFileInput,
    GooglePreparedFile,
    GoogleWorkspaceOutput,
    safe_file_name,
)
from azents.services.google_workspace.transport import (
    GoogleEmptyResponse,
    GoogleSdkError,
    GoogleSdkSession,
)

if TYPE_CHECKING:
    from googleapiclient._apis.drive.v3.schemas import (
        DownloadRestriction,
        File,
        Permission,
    )

DRIVE_METADATA_FIELDS = (
    "id,name,mimeType,description,size,sha256Checksum,version,modifiedTime,parents,"
    "driveId,ownedByMe,shared,isAppAuthorized,starred,trashed,webViewLink,"
    "capabilities(canDownload,canEdit,canModifyContent,canShare,canCopy),"
    "shortcutDetails(targetId,targetMimeType,targetResourceKey),"
    "writersCanShare,copyRequiresWriterPermission,inheritedPermissionsDisabled,"
    "downloadRestrictions(itemDownloadRestriction,effectiveDownloadRestrictionWithContext)"
)
_PERMISSION_FIELDS = (
    "id,type,role,emailAddress,domain,allowFileDiscovery,expirationTime,pendingOwner,"
    "permissionDetails(inherited,inheritedFrom,permissionType,role)"
)
_FOLDER = "application/vnd.google-apps.folder"
_SHORTCUT = "application/vnd.google-apps.shortcut"
_NATIVE_PREFIX = "application/vnd.google-apps."
_EXPORTS: dict[str, tuple[str, ...]] = {
    _NATIVE_PREFIX + "document": (
        "text/plain",
        "text/html",
        "text/markdown",
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.oasis.opendocument.text",
        "application/rtf",
    ),
    _NATIVE_PREFIX + "spreadsheet": (
        "text/csv",
        "text/tab-separated-values",
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.oasis.opendocument.spreadsheet",
        "application/zip",
    ),
    _NATIVE_PREFIX + "presentation": (
        "text/plain",
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.oasis.opendocument.presentation",
        "image/jpeg",
        "image/png",
        "image/svg+xml",
    ),
    _NATIVE_PREFIX + "drawing": (
        "application/pdf",
        "image/jpeg",
        "image/png",
        "image/svg+xml",
    ),
}
_EXTENSIONS = {
    "text/plain": ".txt",
    "text/html": ".html",
    "text/markdown": ".md",
    "text/csv": ".csv",
    "text/tab-separated-values": ".tsv",
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": (
        ".pptx"
    ),
    "application/vnd.oasis.opendocument.text": ".odt",
    "application/vnd.oasis.opendocument.spreadsheet": ".ods",
    "application/vnd.oasis.opendocument.presentation": ".odp",
    "application/rtf": ".rtf",
    "application/zip": ".zip",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/svg+xml": ".svg",
}


@dataclasses.dataclass(frozen=True)
class _ResolvedFile:
    metadata: m.DriveMetadata
    resource_key: str | None
    etag: str | None


def _resource_key(
    request: HttpRequest, file_id: str, resource_key: str | None
) -> HttpRequest:
    if resource_key is not None:
        request.headers = {
            **(request.headers or {}),
            "X-Goog-Drive-Resource-Keys": file_id + "/" + resource_key,
        }
    return request


def _load_metadata(
    session: GoogleSdkSession, value: m.DriveFileIdInput
) -> _ResolvedFile:
    request = session.drive.files().get(
        fileId=value.file_id, supportsAllDrives=True, fields=DRIVE_METADATA_FIELDS
    )
    _resource_key(request, value.file_id, value.resource_key)
    etag: str | None = None

    def observed(response: httplib2.Response) -> None:
        nonlocal etag
        header = response.get("etag")
        if isinstance(header, str) and "\r" not in header and "\n" not in header:
            etag = header

    request.add_response_callback(observed)
    metadata = session.decode(m.DriveMetadata, request)
    if metadata.id != value.file_id:
        raise GoogleSdkError("file_identity_mismatch", dispatched=True, status=None)
    return _ResolvedFile(metadata, value.resource_key, etag)


def get_metadata(
    session: GoogleSdkSession, value: m.DriveFileIdInput
) -> m.DriveMetadata:
    return _load_metadata(session, value).metadata


def search_files(
    session: GoogleSdkSession, value: m.DriveSearchInput
) -> m.DriveFileListResult:
    request = session.drive.files().list(
        q=value.query,
        pageToken=value.page_token,
        pageSize=value.page_size,
        corpora=value.corpora,
        driveId=value.drive_id,
        orderBy=value.order_by,
        includeItemsFromAllDrives=True,
        supportsAllDrives=True,
        spaces="drive",
        fields=f"files({DRIVE_METADATA_FIELDS}),nextPageToken,incompleteSearch",
    )
    result = session.decode(m.DriveFileListResult, request)
    if len(result.files) > value.page_size:
        raise GoogleSdkError("provider_page_limit", dispatched=True, status=None)
    return result


def _resolve_content(
    session: GoogleSdkSession, value: m.DriveContentInput
) -> _ResolvedFile:
    current = _load_metadata(session, value)
    visited = {current.metadata.id}
    for _ in range(8):
        if current.metadata.mime_type != _SHORTCUT:
            return current
        if not value.follow_shortcuts:
            raise GoogleSdkError(
                "shortcut_requires_explicit_target", dispatched=True, status=None
            )
        shortcut = current.metadata.shortcut
        if shortcut is None or shortcut.target_id in visited:
            raise GoogleSdkError(
                "invalid_or_cyclic_shortcut", dispatched=True, status=None
            )
        visited.add(shortcut.target_id)
        current = _load_metadata(
            session,
            m.DriveFileIdInput(
                file_id=shortcut.target_id, resource_key=shortcut.target_resource_key
            ),
        )
    raise GoogleSdkError("shortcut_depth_limit", dispatched=True, status=None)


class _BoundedSink(io.BytesIO):
    def __init__(self, maximum: int) -> None:
        super().__init__()
        self.maximum = maximum

    def write(self, value: Buffer, /) -> int:
        raw = memoryview(value)
        if self.tell() + raw.nbytes > self.maximum:
            raise GoogleSdkError("file_receive_limit", dispatched=True, status=None)
        return super().write(value)


def _download(
    session: GoogleSdkSession,
    resolved: _ResolvedFile,
    value: m.DriveContentInput,
    *,
    export_media_type: str | None,
    maximum_bytes: int,
) -> GooglePreparedFile:
    maximum = min(maximum_bytes, GENERAL_FILE_MAXIMUM_BYTES)
    if maximum <= 0:
        raise ValueError("Drive file transfer requires a positive byte limit.")
    metadata = resolved.metadata
    if metadata.mime_type == _FOLDER:
        raise GoogleSdkError("folder_has_no_file_content", dispatched=True, status=None)
    if (
        metadata.capabilities is not None
        and metadata.capabilities.can_download is False
    ):
        raise GoogleSdkError("download_not_permitted", dispatched=True, status=None)
    exported = metadata.mime_type is not None and metadata.mime_type.startswith(
        _NATIVE_PREFIX
    )
    if exported:
        if export_media_type is None or export_media_type not in _EXPORTS.get(
            metadata.mime_type or "", ()
        ):
            raise GoogleSdkError(
                "unsupported_export_format", dispatched=True, status=None
            )
        media_type = export_media_type
        # Drive files.export has a separate documented 10MB export ceiling.
        maximum = min(maximum, 10 * 1024 * 1024)
        request = session.drive.files().export_media(
            fileId=metadata.id, mimeType=media_type
        )
    else:
        if export_media_type is not None:
            raise GoogleSdkError("not_a_native_export", dispatched=True, status=None)
        if metadata.size is not None and metadata.size > maximum:
            raise GoogleSdkError("file_receive_limit", dispatched=True, status=None)
        media_type = metadata.mime_type or "application/octet-stream"
        request = session.drive.files().get_media(
            fileId=metadata.id,
            supportsAllDrives=True,
            acknowledgeAbuse=value.acknowledge_abuse,
        )
    _resource_key(request, metadata.id, resolved.resource_key)
    if resolved.etag is not None:
        request.headers = {**(request.headers or {}), "If-Match": resolved.etag}
    with _BoundedSink(maximum) as sink:
        downloader = MediaIoBaseDownload(
            sink, request, chunksize=min(1024 * 1024, maximum)
        )
        for _ in range(maximum // (1024 * 1024) + 3):
            session.require_current()
            _, done = downloader.next_chunk(num_retries=0)
            if done:
                content = sink.getvalue()
                break
        else:
            raise GoogleSdkError("file_chunk_limit", dispatched=True, status=None)
    name = safe_file_name(metadata.name or "drive-file", fallback="drive-file")
    if exported:
        suffix = _EXTENSIONS.get(media_type, "")
        if suffix and not name.lower().endswith(suffix):
            name = name[: 255 - len(suffix)] + suffix
    file = GooglePreparedFile(name, media_type, content, (value.file_id, metadata.id))
    if not exported and (
        metadata.size is not None
        and file.size != metadata.size
        or metadata.sha256_checksum is not None
        and file.sha256 != metadata.sha256_checksum.lower()
    ):
        raise GoogleSdkError("file_integrity_mismatch", dispatched=True, status=None)
    return file


def _transfer_result(
    value: m.DriveContentInput, resolved: _ResolvedFile, file: GooglePreparedFile
) -> m.DriveTransferResult:
    return m.DriveTransferResult(
        requested_file_id=value.file_id,
        resolved_file_id=resolved.metadata.id,
        filename=file.filename,
        media_type=file.media_type,
        size=file.size,
        sha256=file.sha256,
        exported=bool(
            resolved.metadata.mime_type
            and resolved.metadata.mime_type.startswith(_NATIVE_PREFIX)
        ),
    )


def download_file(
    session: GoogleSdkSession, value: m.DriveContentInput, *, maximum_bytes: int
) -> GoogleWorkspaceOutput[m.DriveTransferResult]:
    resolved = _resolve_content(session, value)
    file = _download(
        session, resolved, value, export_media_type=None, maximum_bytes=maximum_bytes
    )
    return GoogleWorkspaceOutput(_transfer_result(value, resolved, file), (file,))


def export_file(
    session: GoogleSdkSession, value: m.DriveExportInput, *, maximum_bytes: int
) -> GoogleWorkspaceOutput[m.DriveTransferResult]:
    resolved = _resolve_content(session, value)
    file = _download(
        session,
        resolved,
        value,
        export_media_type=value.export_media_type,
        maximum_bytes=maximum_bytes,
    )
    return GoogleWorkspaceOutput(_transfer_result(value, resolved, file), (file,))


def read_content(
    session: GoogleSdkSession, value: m.DriveReadInput, *, maximum_bytes: int
) -> GoogleWorkspaceOutput[m.DriveReadResult]:
    resolved = _resolve_content(session, value)
    native = resolved.metadata.mime_type
    export_type = value.export_media_type
    if export_type is None and native in {
        _NATIVE_PREFIX + "document",
        _NATIVE_PREFIX + "presentation",
    }:
        export_type = "text/plain"
    if export_type is None and native == _NATIVE_PREFIX + "spreadsheet":
        export_type = "text/csv"
    file = _download(
        session,
        resolved,
        value,
        export_media_type=export_type,
        maximum_bytes=maximum_bytes,
    )
    extracted = extract_text(
        file,
        GoogleExtractionLimits(
            maximum_input_bytes=min(maximum_bytes, 16 * 1024 * 1024),
            maximum_expanded_bytes=64 * 1024 * 1024,
            maximum_pages=200,
            maximum_cells=50000,
            maximum_xml_nodes=100000,
            maximum_characters=value.character_limit,
        ),
        session.require_current,
    )
    result = m.DriveReadResult(
        **_transfer_result(value, resolved, file).model_dump(),
        text=extracted.text,
        extraction_status=extracted.status,
    )
    return GoogleWorkspaceOutput(result, (file,))


def get_link(session: GoogleSdkSession, value: m.DriveFileIdInput) -> m.DriveLinkResult:
    metadata = get_metadata(session, value)
    return m.DriveLinkResult(
        file_id=metadata.id, web_view_link=metadata.web_view_link, sharing_changed=False
    )


def _require_blob(metadata: m.DriveMetadata) -> None:
    if metadata.mime_type is None or metadata.mime_type.startswith(_NATIVE_PREFIX):
        raise GoogleSdkError(
            "content_requires_ordinary_file", dispatched=True, status=None
        )
    if (
        metadata.capabilities is not None
        and metadata.capabilities.can_modify_content is False
    ):
        raise GoogleSdkError(
            "content_write_not_permitted", dispatched=True, status=None
        )


def _prepared_content(
    content: GoogleFileInput | None,
    text: str | None,
    prepared: GooglePreparedFile | None,
    maximum_bytes: int,
) -> bytes:
    if (content is None) != (prepared is None):
        raise ValueError("Resolve and authorize the exact Drive input file first.")
    raw = (
        prepared.content
        if prepared is not None
        else (b"" if text is None else text.encode("utf-8"))
    )
    if maximum_bytes < 1 or len(raw) > min(maximum_bytes, GENERAL_FILE_MAXIMUM_BYTES):
        raise GoogleSdkError("file_upload_limit", dispatched=False, status=None)
    return raw


def create_file(
    session: GoogleSdkSession,
    value: m.DriveCreateFileInput,
    *,
    prepared: GooglePreparedFile | None,
    maximum_bytes: int,
) -> m.DriveMetadata:
    content = _prepared_content(value.content, value.text, prepared, maximum_bytes)
    body: File = {"name": value.name, "mimeType": value.media_type}
    if value.parent_id is not None:
        body["parents"] = [value.parent_id]
    if value.description is not None:
        body["description"] = value.description
    with io.BytesIO(content) as source:
        upload = MediaIoBaseUpload(
            source, mimetype=value.media_type, chunksize=1024 * 1024, resumable=True
        )
        return session.decode(
            m.DriveMetadata,
            session.drive.files().create(
                body=body,
                media_body=upload,
                supportsAllDrives=True,
                fields=DRIVE_METADATA_FIELDS,
            ),
        )


def create_folder(
    session: GoogleSdkSession, value: m.DriveCreateFolderInput
) -> m.DriveMetadata:
    body: File = {"name": value.name, "mimeType": _FOLDER}
    if value.parent_id is not None:
        body["parents"] = [value.parent_id]
    if value.description is not None:
        body["description"] = value.description
    return session.decode(
        m.DriveMetadata,
        session.drive.files().create(
            body=body, supportsAllDrives=True, fields=DRIVE_METADATA_FIELDS
        ),
    )


def copy_file(session: GoogleSdkSession, value: m.DriveCopyInput) -> m.DriveMetadata:
    resolved = (
        _resolve_content(session, value)
        if value.follow_shortcuts
        else _load_metadata(session, value)
    )
    if (
        resolved.metadata.capabilities is not None
        and resolved.metadata.capabilities.can_copy is False
    ):
        raise GoogleSdkError("copy_not_permitted", dispatched=True, status=None)
    body: File = {"name": value.name}
    if value.parent_id is not None:
        body["parents"] = [value.parent_id]
    request = session.drive.files().copy(
        fileId=resolved.metadata.id,
        body=body,
        supportsAllDrives=True,
        fields=DRIVE_METADATA_FIELDS,
    )
    _resource_key(request, resolved.metadata.id, resolved.resource_key)
    return session.decode(m.DriveMetadata, request)


def update_metadata(
    session: GoogleSdkSession, value: m.DriveUpdateMetadataInput
) -> m.DriveMetadata:
    # Metadata changes are always shortcut-local, unlike explicit content targets.
    body: File = {}
    changes = value.changes
    if "name" in changes:
        body["name"] = changes["name"]
    if "description" in changes:
        body["description"] = changes["description"]
    if "starred" in changes:
        body["starred"] = changes["starred"]
    if "trashed" in changes:
        body["trashed"] = changes["trashed"]
    request = session.drive.files().update(
        fileId=value.file_id,
        body=body,
        supportsAllDrives=True,
        addParents=value.add_parent_id,
        removeParents=",".join(value.remove_parent_ids) or None,
        fields=DRIVE_METADATA_FIELDS,
    )
    _resource_key(request, value.file_id, value.resource_key)
    return session.decode(m.DriveMetadata, request)


def _replace_blob(
    session: GoogleSdkSession,
    resolved: _ResolvedFile,
    content: bytes,
    media_type: str,
    *,
    require_etag: bool,
) -> m.DriveMetadata:
    if require_etag and resolved.etag is None:
        raise GoogleSdkError(
            "file_precondition_unavailable", dispatched=True, status=None
        )
    with io.BytesIO(content) as source:
        upload = MediaIoBaseUpload(
            source, mimetype=media_type, chunksize=1024 * 1024, resumable=True
        )
        body: File = {"mimeType": media_type}
        request = session.drive.files().update(
            fileId=resolved.metadata.id,
            body=body,
            media_body=upload,
            supportsAllDrives=True,
            fields=DRIVE_METADATA_FIELDS,
        )
        _resource_key(request, resolved.metadata.id, resolved.resource_key)
        if resolved.etag is not None:
            request.headers = {**(request.headers or {}), "If-Match": resolved.etag}
        return session.decode(m.DriveMetadata, request)


def update_content(
    session: GoogleSdkSession,
    value: m.DriveUpdateContentInput,
    *,
    prepared: GooglePreparedFile | None,
    maximum_bytes: int,
) -> m.DriveMetadata:
    content = _prepared_content(value.content, value.text, prepared, maximum_bytes)
    resolved = _resolve_content(session, value)
    _require_blob(resolved.metadata)
    return _replace_blob(
        session, resolved, content, value.media_type, require_etag=False
    )


def append_text(
    session: GoogleSdkSession, value: m.DriveAppendInput, *, maximum_bytes: int
) -> m.DriveMetadata:
    resolved = _resolve_content(session, value)
    _require_blob(resolved.metadata)
    media_type = resolved.metadata.mime_type
    if media_type is None or not media_type.startswith("text/"):
        raise GoogleSdkError("append_requires_utf8_text", dispatched=True, status=None)
    if resolved.etag is None:
        raise GoogleSdkError(
            "file_precondition_unavailable", dispatched=True, status=None
        )
    original = _download(
        session, resolved, value, export_media_type=None, maximum_bytes=maximum_bytes
    )
    try:
        original.content.decode("utf-8")
    except UnicodeDecodeError:
        raise GoogleSdkError(
            "append_requires_utf8_text", dispatched=True, status=None
        ) from None
    addition = value.text.encode("utf-8")
    if value.position == "append":
        content = original.content + addition
    elif original.content.startswith(BOM_UTF8):
        content = BOM_UTF8 + addition + original.content[len(BOM_UTF8) :]
    else:
        content = addition + original.content
    if len(content) > min(maximum_bytes, GENERAL_FILE_MAXIMUM_BYTES):
        raise GoogleSdkError("file_upload_limit", dispatched=True, status=None)
    return _replace_blob(session, resolved, content, media_type, require_etag=True)


def list_permissions(
    session: GoogleSdkSession, value: m.DrivePermissionListInput
) -> m.DrivePermissionListResult:
    request = session.drive.permissions().list(
        fileId=value.file_id,
        pageSize=value.page_size,
        pageToken=value.page_token,
        supportsAllDrives=True,
        fields=f"permissions({_PERMISSION_FIELDS}),nextPageToken",
    )
    _resource_key(request, value.file_id, value.resource_key)
    result = session.decode(m.DrivePermissionListResult, request)
    if len(result.permissions) > value.page_size:
        raise GoogleSdkError("provider_page_limit", dispatched=True, status=None)
    return result


def get_permission(
    session: GoogleSdkSession, value: m.DrivePermissionIdInput
) -> m.DrivePermission:
    request = session.drive.permissions().get(
        fileId=value.file_id,
        permissionId=value.permission_id,
        supportsAllDrives=True,
        fields=_PERMISSION_FIELDS,
    )
    _resource_key(request, value.file_id, value.resource_key)
    result = session.decode(m.DrivePermission, request)
    if result.id != value.permission_id:
        raise GoogleSdkError(
            "permission_identity_mismatch", dispatched=True, status=None
        )
    return result


def _permission_body(value: m.DrivePermissionGrant) -> "Permission":
    body: Permission = {"type": value.type, "role": value.role}
    if value.email is not None:
        body["emailAddress"] = value.email
    if value.domain is not None:
        body["domain"] = value.domain
    if value.allow_file_discovery is not None:
        body["allowFileDiscovery"] = value.allow_file_discovery
    if value.expiration_time is not None:
        body["expirationTime"] = value.expiration_time.isoformat()
    return body


def create_permissions(
    session: GoogleSdkSession, value: m.DriveCreatePermissionInput
) -> m.DriveCreatedPermissions:
    completed: list[m.DrivePermission] = []
    for index, grant in enumerate(value.grants):
        request = session.drive.permissions().create(
            fileId=value.file_id,
            body=_permission_body(grant),
            sendNotificationEmail=value.send_notification_email
            if grant.type in {"user", "group"}
            else None,
            emailMessage=value.email_message,
            supportsAllDrives=True,
            fields=_PERMISSION_FIELDS,
        )
        _resource_key(request, value.file_id, value.resource_key)
        try:
            completed.append(session.decode(m.DrivePermission, request))
        except (GoogleSdkError, GoogleOAuthError) as error:
            # Target ordinals avoid echoing sensitive recipient addresses.
            raise GoogleWorkspacePartialError(
                completed=tuple(
                    GoogleCompletedStep(
                        action="create_permission", resource_ids=(permission.id,)
                    )
                    for permission in completed
                ),
                unconfirmed_action="create_permission",
                remaining_ids=tuple(
                    str(ordinal) for ordinal in range(index, len(value.grants))
                ),
                cause_code=error.code,
                provider_error=error.provider_error
                if isinstance(error, GoogleSdkError)
                else None,
                status=error.status if isinstance(error, GoogleSdkError) else None,
                dispatched=bool(completed)
                or isinstance(error, GoogleSdkError)
                and error.dispatched,
            ) from None
    return m.DriveCreatedPermissions(
        file_id=value.file_id, permissions=tuple(completed)
    )


def update_permission(
    session: GoogleSdkSession, value: m.DriveUpdatePermissionInput
) -> m.DrivePermission:
    body: Permission = {}
    if "role" in value.changes:
        body["role"] = value.changes["role"]
    if "allow_file_discovery" in value.changes:
        body["allowFileDiscovery"] = value.changes["allow_file_discovery"]
    if "expiration_time" in value.changes:
        body["expirationTime"] = value.changes["expiration_time"].isoformat()
    request = session.drive.permissions().update(
        fileId=value.file_id,
        permissionId=value.permission_id,
        body=body,
        removeExpiration=value.remove_expiration,
        supportsAllDrives=True,
        fields=_PERMISSION_FIELDS,
    )
    _resource_key(request, value.file_id, value.resource_key)
    return session.decode(m.DrivePermission, request)


def delete_permission(
    session: GoogleSdkSession, value: m.DrivePermissionIdInput
) -> m.DriveMutationResult:
    request = session.drive.permissions().delete(
        fileId=value.file_id, permissionId=value.permission_id, supportsAllDrives=True
    )
    _resource_key(request, value.file_id, value.resource_key)
    session.decode(GoogleEmptyResponse, request)
    return m.DriveMutationResult(confirmed_id=value.permission_id)


def transfer_ownership(
    session: GoogleSdkSession, value: m.DriveTransferOwnershipInput
) -> m.DrivePermission:
    body: Permission = {
        "type": "user",
        "role": "owner",
        "emailAddress": value.recipient_email,
    }
    request = session.drive.permissions().create(
        fileId=value.file_id,
        body=body,
        transferOwnership=True,
        moveToNewOwnersRoot=value.move_to_new_owners_root,
        sendNotificationEmail=True,
        supportsAllDrives=True,
        fields=_PERMISSION_FIELDS,
    )
    _resource_key(request, value.file_id, value.resource_key)
    return session.decode(m.DrivePermission, request)


def update_access(
    session: GoogleSdkSession, value: m.DriveUpdateAccessInput
) -> m.DriveMetadata:
    body: File = {}
    changes = value.changes
    if "writers_can_share" in changes:
        body["writersCanShare"] = changes["writers_can_share"]
    if "copy_requires_writer_permission" in changes:
        body["copyRequiresWriterPermission"] = changes[
            "copy_requires_writer_permission"
        ]
    if "inherited_permissions_disabled" in changes:
        body["inheritedPermissionsDisabled"] = changes["inherited_permissions_disabled"]
    restriction: DownloadRestriction = {}
    if "restrict_download_for_readers" in changes:
        restriction["restrictedForReaders"] = changes["restrict_download_for_readers"]
    if "restrict_download_for_writers" in changes:
        restriction["restrictedForWriters"] = changes["restrict_download_for_writers"]
    if restriction:
        body["downloadRestrictions"] = {"itemDownloadRestriction": restriction}
    request = session.drive.files().update(
        fileId=value.file_id,
        body=body,
        supportsAllDrives=True,
        fields=DRIVE_METADATA_FIELDS,
    )
    _resource_key(request, value.file_id, value.resource_key)
    return session.decode(m.DriveMetadata, request)
