"""Closed Drive contracts separate resource metadata, content and permission effects."""

from datetime import datetime
from typing import Annotated, Literal, Self, TypedDict

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
    with_config,
)

from azents.services.google_workspace.extraction import ExtractionStatus
from azents.services.google_workspace.file_models import GoogleFileInput, MediaType
from azents.services.google_workspace.gmail_models import GmailMailbox

DriveId = Annotated[
    str, StringConstraints(min_length=1, max_length=512, pattern=r"^[A-Za-z0-9_-]+$")
]
DriveName = Annotated[
    str, StringConstraints(min_length=1, max_length=255, pattern=r"^[^\x00\r\n]+$")
]
DriveRole = Literal["reader", "commenter", "writer", "fileOrganizer", "organizer"]
PermissionType = Literal["user", "group", "domain", "anyone"]


class DriveInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class DriveFileIdInput(DriveInput):
    file_id: DriveId
    resource_key: DriveId | None


class DriveSearchInput(DriveInput):
    query: str | None = Field(
        max_length=8192,
        description=(
            "Google Drive search expression, not a URL or method. App-file grants "
            "remain Google-limited; a known file ID does not expand eligibility."
        ),
    )
    page_token: str | None = Field(max_length=8192)
    page_size: int = Field(ge=1, le=100, strict=True)
    corpora: Literal["user", "drive", "allDrives"]
    drive_id: DriveId | None
    order_by: (
        Literal[
            "name",
            "name desc",
            "modifiedTime",
            "modifiedTime desc",
            "createdTime",
            "createdTime desc",
            "folder,name",
        ]
        | None
    )

    @model_validator(mode="after")
    def validate_corpora(self) -> Self:
        if (self.corpora == "drive") != (self.drive_id is not None):
            raise ValueError("A shared-drive search needs exactly its drive ID.")
        return self


class DriveContentInput(DriveFileIdInput):
    follow_shortcuts: bool = Field(
        strict=True,
        description=(
            "Follow only the shortcut's target content with bounded traversal; "
            "never infer writability from target readability."
        ),
    )
    acknowledge_abuse: bool = Field(strict=True)


class DriveExportInput(DriveContentInput):
    export_media_type: MediaType


class DriveReadInput(DriveContentInput):
    export_media_type: MediaType | None
    character_limit: int = Field(ge=1, le=65536, strict=True)


class DriveCreateFileInput(DriveInput):
    name: DriveName
    parent_id: DriveId | None
    description: str | None = Field(max_length=65536)
    content: GoogleFileInput | None
    text: str | None = Field(max_length=1_000_000)
    media_type: MediaType

    @model_validator(mode="after")
    def validate_content(self) -> Self:
        if self.content is not None and self.text is not None:
            raise ValueError("Choose one canonical source file or inline UTF-8 text.")
        if self.media_type.startswith("application/vnd.google-apps."):
            raise ValueError(
                "Use an explicit Drive import operation for native formats."
            )
        if self.text is not None and not self.media_type.startswith("text/"):
            raise ValueError("Inline Drive text needs a text media type.")
        return self


class DriveCreateFolderInput(DriveInput):
    name: DriveName
    parent_id: DriveId | None
    description: str | None = Field(max_length=65536)


class DriveCopyInput(DriveContentInput):
    name: DriveName
    parent_id: DriveId | None


@with_config(ConfigDict(extra="forbid", hide_input_in_errors=True))
class DriveMetadataPatch(TypedDict, total=False):
    name: DriveName
    description: Annotated[str, Field(max_length=65536)]
    starred: Annotated[bool, Field(strict=True)]
    trashed: Annotated[bool, Field(strict=True)]


class DriveUpdateMetadataInput(DriveFileIdInput):
    changes: DriveMetadataPatch
    add_parent_id: DriveId | None
    remove_parent_ids: tuple[DriveId, ...] = Field(max_length=100)

    @model_validator(mode="after")
    def validate_change(self) -> Self:
        if (
            not self.changes
            and self.add_parent_id is None
            and not self.remove_parent_ids
        ):
            raise ValueError("Provide a metadata change or explicit parent move.")
        if self.add_parent_id in self.remove_parent_ids:
            raise ValueError("A parent cannot be added and removed together.")
        return self


class DriveUpdateContentInput(DriveContentInput):
    content: GoogleFileInput | None
    text: str | None = Field(max_length=1_000_000)
    media_type: MediaType

    @model_validator(mode="after")
    def validate_content(self) -> Self:
        if (self.content is None) == (self.text is None):
            raise ValueError(
                "Supply exactly one canonical file or inline text content."
            )
        if self.media_type.startswith("application/vnd.google-apps."):
            raise ValueError(
                "Native formats require an explicit import/export conversion."
            )
        if self.text is not None and not self.media_type.startswith("text/"):
            raise ValueError("Inline content needs a text media type.")
        return self


class DriveAppendInput(DriveContentInput):
    text: str = Field(min_length=1, max_length=1_000_000)
    position: Literal["append", "prepend"]


class DriveImportInput(DriveInput):
    name: DriveName
    parent_id: DriveId | None
    content: GoogleFileInput | None
    text: str | None = Field(max_length=1_000_000)
    source_format: Literal[
        "text",
        "html",
        "markdown",
        "csv",
        "tsv",
        "docx",
        "xlsx",
        "pptx",
        "odt",
        "ods",
        "odp",
        "rtf",
    ]

    @model_validator(mode="after")
    def validate_content(self) -> Self:
        if (self.content is None) == (self.text is None):
            raise ValueError(
                "Supply exactly one conversion source file or inline text."
            )
        if self.text is not None and self.source_format not in {
            "text",
            "html",
            "markdown",
            "csv",
            "tsv",
            "rtf",
        }:
            raise ValueError("Binary import formats require a canonical file source.")
        return self


class DrivePermissionListInput(DriveFileIdInput):
    page_token: str | None = Field(max_length=8192)
    page_size: int = Field(ge=1, le=100, strict=True)


class DrivePermissionIdInput(DriveFileIdInput):
    permission_id: DriveId


class DrivePermissionGrant(DriveInput):
    type: PermissionType
    role: DriveRole
    email: str | None = Field(max_length=320)
    domain: str | None = Field(max_length=253, pattern=r"^[A-Za-z0-9.-]+$")
    allow_file_discovery: bool | None = Field(strict=True)
    expiration_time: AwareDatetime | None

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        return (
            None
            if value is None
            else GmailMailbox(email=value, display_name=None).email
        )

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        if (self.type in {"user", "group"}) != (self.email is not None):
            raise ValueError("User/group sharing requires an email target only.")
        if (self.type == "domain") != (self.domain is not None):
            raise ValueError("Domain sharing requires a domain target only.")
        if self.allow_file_discovery is not None and self.type not in {
            "domain",
            "anyone",
        }:
            raise ValueError("File discovery applies only to domain/anyone access.")
        if self.expiration_time is not None and self.type not in {"user", "group"}:
            raise ValueError("Expiring access applies only to users and groups.")
        return self


class DriveCreatePermissionInput(DriveFileIdInput):
    grants: tuple[DrivePermissionGrant, ...] = Field(min_length=1, max_length=100)
    send_notification_email: bool = Field(strict=True)
    email_message: str | None = Field(max_length=8192)

    @model_validator(mode="after")
    def validate_notification(self) -> Self:
        if self.email_message is not None and not self.send_notification_email:
            raise ValueError("An invitation message requires email notification.")
        if self.email_message is not None and any(
            grant.type not in {"user", "group"} for grant in self.grants
        ):
            raise ValueError("Email invitation messages require user/group targets.")
        return self


@with_config(ConfigDict(extra="forbid", hide_input_in_errors=True))
class DrivePermissionPatch(TypedDict, total=False):
    role: DriveRole
    allow_file_discovery: Annotated[bool, Field(strict=True)]
    expiration_time: AwareDatetime


class DriveUpdatePermissionInput(DrivePermissionIdInput):
    changes: DrivePermissionPatch
    remove_expiration: bool = Field(strict=True)

    @model_validator(mode="after")
    def validate_change(self) -> Self:
        if not self.changes and not self.remove_expiration:
            raise ValueError("Provide a permission change or remove expiration.")
        if self.remove_expiration and "expiration_time" in self.changes:
            raise ValueError("Do not set and remove permission expiration together.")
        return self


class DriveTransferOwnershipInput(DriveFileIdInput):
    recipient_email: str = Field(max_length=320)
    move_to_new_owners_root: bool = Field(strict=True)

    @field_validator("recipient_email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return GmailMailbox(email=value, display_name=None).email


@with_config(ConfigDict(extra="forbid", hide_input_in_errors=True))
class DriveAccessPatch(TypedDict, total=False):
    writers_can_share: Annotated[bool, Field(strict=True)]
    copy_requires_writer_permission: Annotated[bool, Field(strict=True)]
    inherited_permissions_disabled: Annotated[bool, Field(strict=True)]
    restrict_download_for_readers: Annotated[bool, Field(strict=True)]
    restrict_download_for_writers: Annotated[bool, Field(strict=True)]


class DriveUpdateAccessInput(DriveFileIdInput):
    changes: DriveAccessPatch

    @model_validator(mode="after")
    def require_change(self) -> Self:
        if not self.changes:
            raise ValueError("Provide an explicit Drive access metadata change.")
        return self


class DriveProviderModel(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


class DriveCapabilities(DriveProviderModel):
    can_download: bool | None = Field(default=None, alias="canDownload")
    can_edit: bool | None = Field(default=None, alias="canEdit")
    can_modify_content: bool | None = Field(default=None, alias="canModifyContent")
    can_share: bool | None = Field(default=None, alias="canShare")
    can_copy: bool | None = Field(default=None, alias="canCopy")


class DriveShortcut(DriveProviderModel):
    target_id: DriveId = Field(alias="targetId")
    target_mime_type: str | None = Field(default=None, alias="targetMimeType")
    target_resource_key: DriveId | None = Field(default=None, alias="targetResourceKey")


class DriveDownloadRestriction(DriveProviderModel):
    restricted_for_readers: bool | None = Field(
        default=None, alias="restrictedForReaders"
    )
    restricted_for_writers: bool | None = Field(
        default=None, alias="restrictedForWriters"
    )


class DriveDownloadRestrictions(DriveProviderModel):
    item: DriveDownloadRestriction | None = Field(
        default=None, alias="itemDownloadRestriction"
    )
    effective: DriveDownloadRestriction | None = Field(
        default=None, alias="effectiveDownloadRestrictionWithContext"
    )


class DriveMetadata(DriveProviderModel):
    id: DriveId
    name: str | None = Field(default=None, max_length=4096)
    mime_type: str | None = Field(default=None, alias="mimeType")
    description: str | None = None
    size: int | None = Field(default=None, ge=0)
    sha256_checksum: str | None = Field(
        default=None, alias="sha256Checksum", pattern=r"^[0-9a-fA-F]{64}$"
    )
    version: str | None = None
    modified_time: datetime | None = Field(default=None, alias="modifiedTime")
    parents: tuple[DriveId, ...] | None = None
    drive_id: DriveId | None = Field(default=None, alias="driveId")
    owned_by_me: bool | None = Field(default=None, alias="ownedByMe")
    shared: bool | None = None
    app_authorized: bool | None = Field(default=None, alias="isAppAuthorized")
    starred: bool | None = None
    trashed: bool | None = None
    web_view_link: str | None = Field(default=None, alias="webViewLink")
    capabilities: DriveCapabilities | None = None
    shortcut: DriveShortcut | None = Field(default=None, alias="shortcutDetails")
    writers_can_share: bool | None = Field(default=None, alias="writersCanShare")
    copy_requires_writer_permission: bool | None = Field(
        default=None, alias="copyRequiresWriterPermission"
    )
    inherited_permissions_disabled: bool | None = Field(
        default=None, alias="inheritedPermissionsDisabled"
    )
    download_restrictions: DriveDownloadRestrictions | None = Field(
        default=None, alias="downloadRestrictions"
    )


class DriveFileListResult(DriveProviderModel):
    files: tuple[DriveMetadata, ...] = Field(default=(), max_length=100)
    next_page_token: str | None = Field(default=None, alias="nextPageToken")
    incomplete_search: bool = Field(default=False, alias="incompleteSearch")


class DrivePermissionDetail(DriveProviderModel):
    inherited: bool | None = None
    inherited_from: str | None = Field(default=None, alias="inheritedFrom")
    permission_type: str | None = Field(default=None, alias="permissionType")
    role: str | None = None


class DrivePermission(DriveProviderModel):
    id: DriveId
    type: str | None = None
    role: str | None = None
    email_address: str | None = Field(default=None, alias="emailAddress")
    domain: str | None = None
    allow_file_discovery: bool | None = Field(default=None, alias="allowFileDiscovery")
    expiration_time: datetime | None = Field(default=None, alias="expirationTime")
    pending_owner: bool | None = Field(default=None, alias="pendingOwner")
    permission_details: tuple[DrivePermissionDetail, ...] = Field(
        default=(), alias="permissionDetails"
    )


class DrivePermissionListResult(DriveProviderModel):
    permissions: tuple[DrivePermission, ...] = Field(default=(), max_length=100)
    next_page_token: str | None = Field(default=None, alias="nextPageToken")


class DriveCreatedPermissions(DriveProviderModel):
    file_id: str
    permissions: tuple[DrivePermission, ...]


class DriveLinkResult(DriveProviderModel):
    file_id: str
    web_view_link: str | None
    sharing_changed: Literal[False]


class DriveTransferResult(DriveProviderModel):
    requested_file_id: str
    resolved_file_id: str
    filename: str
    media_type: str
    size: int
    sha256: str
    exported: bool


class DriveReadResult(DriveTransferResult):
    text: str | None
    extraction_status: ExtractionStatus


class DriveMutationResult(DriveProviderModel):
    confirmed_id: str
