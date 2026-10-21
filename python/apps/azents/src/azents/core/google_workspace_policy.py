"""Direct Workspace contracts authorized by actual grants, not request intent."""

import dataclasses
import enum
from types import MappingProxyType
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from azents.core.google_policy import GoogleService

_SCOPE_PREFIX = "https://www.googleapis.com/auth/"
_FULL_MAIL = "https://mail.google.com/"
IDENTITY_SCOPES = frozenset({"openid", "email"})


def _scope(name: str) -> str:
    return _FULL_MAIL if name == "mail" else _SCOPE_PREFIX + name


# Only supported Workspace access requests belong here. Actual receipt evidence is
# retained verbatim elsewhere, including unknown scopes; it is not request input.
REQUEST_SCOPE_SERVICES = MappingProxyType(
    {
        **{
            _scope(name): GoogleService.GMAIL
            for name in (
                "mail",
                "gmail.readonly",
                "gmail.modify",
                "gmail.compose",
                "gmail.send",
                "gmail.labels",
                "gmail.metadata",
                "gmail.settings.basic",
            )
        },
        **{
            _scope(name): GoogleService.CALENDAR
            for name in (
                "calendar",
                "calendar.readonly",
                "calendar.events",
                "calendar.events.readonly",
                "calendar.events.freebusy",
                "calendar.freebusy",
                "calendar.events.owned",
                "calendar.events.owned.readonly",
                "calendar.events.public.readonly",
                "calendar.app.created",
                "calendar.calendars",
                "calendar.calendarlist",
                "calendar.calendarlist.readonly",
            )
        },
        **{
            _scope(name): GoogleService.DRIVE
            for name in (
                "drive",
                "drive.readonly",
                "drive.file",
                "drive.metadata",
                "drive.metadata.readonly",
            )
        },
    }
)


class GoogleWorkspaceConfig(BaseModel):
    """Saved local switches and future OAuth intent, never an action ceiling."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    services: tuple[GoogleService, ...]
    oauth_request_scopes: tuple[str, ...]
    timeout: float = Field(gt=0, le=300, allow_inf_nan=False, strict=True)

    @field_validator("services")
    @classmethod
    def canonical_services(
        cls, value: tuple[GoogleService, ...]
    ) -> tuple[GoogleService, ...]:
        return tuple(sorted(set(value)))

    @field_validator("oauth_request_scopes")
    @classmethod
    def canonical_scopes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(
            scope not in REQUEST_SCOPE_SERVICES and scope not in IDENTITY_SCOPES
            for scope in value
        ):
            raise ValueError("Unsupported Google OAuth request scope.")
        return tuple(sorted(set(value) | IDENTITY_SCOPES))


class GoogleWorkspaceConnectInput(GoogleWorkspaceConfig):
    """Consent request only includes scopes belonging to requested services."""

    @model_validator(mode="after")
    def validate_request(self) -> Self:
        if not self.services:
            raise ValueError("Select at least one Google service.")
        if any(
            REQUEST_SCOPE_SERVICES[scope] not in self.services
            for scope in self.oauth_request_scopes
            if scope not in IDENTITY_SCOPES
        ):
            raise ValueError("Google request scope belongs to a disabled service.")
        return self


class GoogleWorkspaceFinalSettings(GoogleWorkspaceConfig):
    """Reviewed publication settings without secret or scanner acknowledgement."""

    name: str | None = Field(max_length=255)
    slug: str | None
    description: str | None
    prompt: str | None
    enabled: bool = Field(strict=True)
    always_expose_tools: bool = Field(strict=True)


@dataclasses.dataclass(frozen=True)
class GoogleMethodPolicy:
    """Closed SDK method identity and explicit sufficient scope alternatives."""

    method: str
    sufficient: tuple[frozenset[str], ...]

    def permits(self, scopes: frozenset[str]) -> bool:
        return any(alternative <= scopes for alternative in self.sufficient)


class GoogleWorkspaceOperation(enum.StrEnum):
    """Supported direct operations; this is not a provider-method executor."""

    GMAIL_SEARCH_MESSAGES = "gmail_search_messages"
    GMAIL_GET_MESSAGE = "gmail_get_message"
    GMAIL_BATCH_GET_MESSAGES = "gmail_batch_get_messages"
    GMAIL_SEARCH_THREADS = "gmail_search_threads"
    GMAIL_GET_THREAD = "gmail_get_thread"
    GMAIL_DOWNLOAD_ATTACHMENT = "gmail_download_attachment"
    GMAIL_LIST_LABELS = "gmail_list_labels"
    GMAIL_GET_LABEL = "gmail_get_label"
    GMAIL_CREATE_LABEL = "gmail_create_label"
    GMAIL_UPDATE_LABEL = "gmail_update_label"
    GMAIL_DELETE_LABEL = "gmail_delete_label"
    GMAIL_LIST_DRAFTS = "gmail_list_drafts"
    GMAIL_GET_DRAFT = "gmail_get_draft"
    GMAIL_CREATE_DRAFT = "gmail_create_draft"
    GMAIL_UPDATE_DRAFT = "gmail_update_draft"
    GMAIL_DELETE_DRAFT = "gmail_delete_draft"
    GMAIL_SEND_DRAFT = "gmail_send_draft"
    GMAIL_SEND_MESSAGE = "gmail_send_message"
    # Internal sender prerequisite, not a model-facing alias administration tool.
    GMAIL_GET_SEND_AS = "gmail_get_send_as"
    GMAIL_REPLY_MESSAGE = "gmail_reply_message"
    GMAIL_FORWARD_MESSAGE = "gmail_forward_message"
    GMAIL_MODIFY_MESSAGE = "gmail_modify_message"
    GMAIL_BATCH_MODIFY_MESSAGES = "gmail_batch_modify_messages"
    GMAIL_MODIFY_THREAD = "gmail_modify_thread"
    GMAIL_TRASH_MESSAGE = "gmail_trash_message"
    GMAIL_UNTRASH_MESSAGE = "gmail_untrash_message"
    GMAIL_TRASH_THREAD = "gmail_trash_thread"
    GMAIL_UNTRASH_THREAD = "gmail_untrash_thread"
    GMAIL_LIST_FILTERS = "gmail_list_filters"
    GMAIL_GET_FILTER = "gmail_get_filter"
    GMAIL_CREATE_FILTER = "gmail_create_filter"
    GMAIL_DELETE_FILTER = "gmail_delete_filter"
    GMAIL_REPLACE_FILTER = "gmail_replace_filter"
    GMAIL_APPLY_FILTER = "gmail_apply_filter"
    GMAIL_PREVIEW_FILTER = "gmail_preview_filter"
    CALENDAR_LIST_CALENDARS = "calendar_list_calendars"
    CALENDAR_LIST_EVENTS = "calendar_list_events"
    CALENDAR_GET_EVENT = "calendar_get_event"
    CALENDAR_LIST_INSTANCES = "calendar_list_instances"
    CALENDAR_QUERY_FREEBUSY = "calendar_query_freebusy"
    CALENDAR_SUGGEST_TIME = "calendar_suggest_time"
    CALENDAR_CREATE_EVENT = "calendar_create_event"
    CALENDAR_UPDATE_EVENT = "calendar_update_event"
    CALENDAR_DELETE_EVENT = "calendar_delete_event"
    CALENDAR_RESPOND_EVENT = "calendar_respond_event"
    CALENDAR_LIST_STATUS_EVENTS = "calendar_list_status_events"
    CALENDAR_CREATE_STATUS_EVENT = "calendar_create_status_event"
    CALENDAR_UPDATE_STATUS_EVENT = "calendar_update_status_event"
    CALENDAR_DELETE_STATUS_EVENT = "calendar_delete_status_event"
    CALENDAR_CREATE_CALENDAR = "calendar_create_calendar"
    DRIVE_SEARCH_FILES = "drive_search_files"
    DRIVE_GET_METADATA = "drive_get_metadata"
    DRIVE_READ_CONTENT = "drive_read_content"
    DRIVE_DOWNLOAD_FILE = "drive_download_file"
    DRIVE_EXPORT_FILE = "drive_export_file"
    DRIVE_GET_LINK = "drive_get_link"
    DRIVE_LIST_PERMISSIONS = "drive_list_permissions"
    DRIVE_GET_PERMISSION = "drive_get_permission"
    DRIVE_CREATE_FILE = "drive_create_file"
    DRIVE_CREATE_FOLDER = "drive_create_folder"
    DRIVE_COPY_FILE = "drive_copy_file"
    DRIVE_UPDATE_METADATA = "drive_update_metadata"
    DRIVE_UPDATE_CONTENT = "drive_update_content"
    DRIVE_APPEND_TEXT = "drive_append_text"
    DRIVE_IMPORT_DOCUMENT = "drive_import_document"
    DRIVE_IMPORT_SPREADSHEET = "drive_import_spreadsheet"
    DRIVE_IMPORT_PRESENTATION = "drive_import_presentation"
    DRIVE_CREATE_PERMISSION = "drive_create_permission"
    DRIVE_UPDATE_PERMISSION = "drive_update_permission"
    DRIVE_DELETE_PERMISSION = "drive_delete_permission"
    DRIVE_TRANSFER_OWNERSHIP = "drive_transfer_ownership"
    DRIVE_UPDATE_ACCESS = "drive_update_access"


def _method(method: str, *scopes: str) -> GoogleMethodPolicy:
    return GoogleMethodPolicy(
        method, tuple(frozenset({_scope(scope)}) for scope in scopes)
    )


# Scope sets deliberately describe the supported body/metadata contract, not every
# scope appearing in discovery. Add-on scopes, appdata/photos/Meet-only access and
# availability-only event bodies do not satisfy these ordinary Workspace tools.
_GMAIL_READ = ("mail", "gmail.readonly", "gmail.modify")
_GMAIL_DRAFT_READ = (*_GMAIL_READ, "gmail.compose")
_GMAIL_DRAFT_WRITE = ("mail", "gmail.compose", "gmail.modify")
_GMAIL_LABEL_READ = (*_GMAIL_READ, "gmail.labels", "gmail.metadata")
_GMAIL_LABEL_WRITE = ("mail", "gmail.labels", "gmail.modify")
_GMAIL_SETTINGS_READ = (*_GMAIL_READ, "gmail.settings.basic")
_GMAIL_MODIFY = ("mail", "gmail.modify")
_CALENDAR_EVENTS_READ = (
    "calendar",
    "calendar.readonly",
    "calendar.events",
    "calendar.events.readonly",
    "calendar.app.created",
    "calendar.events.owned",
    "calendar.events.owned.readonly",
    "calendar.events.public.readonly",
)
_CALENDAR_EVENTS_WRITE = (
    "calendar",
    "calendar.events",
    "calendar.events.owned",
    "calendar.app.created",
)
_DRIVE_CONTENT = ("drive", "drive.readonly", "drive.file")
_DRIVE_METADATA = (*_DRIVE_CONTENT, "drive.metadata", "drive.metadata.readonly")
_DRIVE_WRITE = ("drive", "drive.file")


@dataclasses.dataclass(frozen=True)
class GoogleOperationPolicy:
    """Every SDK prerequisite must be satisfied; scopes never grant resource ACLs."""

    operation: GoogleWorkspaceOperation
    service: GoogleService
    methods: tuple[GoogleMethodPolicy, ...]

    def permits(self, scopes: frozenset[str]) -> bool:
        return all(method.permits(scopes) for method in self.methods)


def _policies(
    service: GoogleService,
    method: GoogleMethodPolicy,
    *operations: GoogleWorkspaceOperation,
) -> tuple[GoogleOperationPolicy, ...]:
    return tuple(
        GoogleOperationPolicy(operation, service, (method,)) for operation in operations
    )


# Exact SDK method IDs are review evidence and adapter contracts, never callable
# attribute paths supplied by the Agent. Adapters dispatch closed typed operations.
_O = GoogleWorkspaceOperation
_G = GoogleService.GMAIL
_C = GoogleService.CALENDAR
_D = GoogleService.DRIVE
_POLICIES = (
    *_policies(
        _G, _method("gmail.users.messages.list", *_GMAIL_READ), _O.GMAIL_SEARCH_MESSAGES
    ),
    *(
        GoogleOperationPolicy(
            operation,
            _G,
            (
                _method("gmail.users.messages.get", *_GMAIL_READ),
                _method("gmail.users.messages.attachments.get", *_GMAIL_READ),
            ),
        )
        for operation in (_O.GMAIL_GET_MESSAGE, _O.GMAIL_BATCH_GET_MESSAGES)
    ),
    *_policies(
        _G, _method("gmail.users.threads.list", *_GMAIL_READ), _O.GMAIL_SEARCH_THREADS
    ),
    GoogleOperationPolicy(
        _O.GMAIL_GET_THREAD,
        _G,
        (
            _method("gmail.users.threads.get", *_GMAIL_READ),
            _method("gmail.users.messages.attachments.get", *_GMAIL_READ),
        ),
    ),
    GoogleOperationPolicy(
        _O.GMAIL_DOWNLOAD_ATTACHMENT,
        _G,
        (
            _method("gmail.users.messages.get", *_GMAIL_READ),
            _method("gmail.users.messages.attachments.get", *_GMAIL_READ),
        ),
    ),
    *_policies(
        _G, _method("gmail.users.labels.list", *_GMAIL_LABEL_READ), _O.GMAIL_LIST_LABELS
    ),
    *_policies(
        _G, _method("gmail.users.labels.get", *_GMAIL_LABEL_READ), _O.GMAIL_GET_LABEL
    ),
    *_policies(
        _G,
        _method("gmail.users.labels.create", *_GMAIL_LABEL_WRITE),
        _O.GMAIL_CREATE_LABEL,
    ),
    *_policies(
        _G,
        _method("gmail.users.labels.patch", *_GMAIL_LABEL_WRITE),
        _O.GMAIL_UPDATE_LABEL,
    ),
    *_policies(
        _G,
        _method("gmail.users.labels.delete", *_GMAIL_LABEL_WRITE),
        _O.GMAIL_DELETE_LABEL,
    ),
    *_policies(
        _G, _method("gmail.users.drafts.list", *_GMAIL_DRAFT_READ), _O.GMAIL_LIST_DRAFTS
    ),
    *_policies(
        _G, _method("gmail.users.drafts.get", *_GMAIL_DRAFT_READ), _O.GMAIL_GET_DRAFT
    ),
    *_policies(
        _G,
        _method("gmail.users.drafts.create", *_GMAIL_DRAFT_WRITE),
        _O.GMAIL_CREATE_DRAFT,
    ),
    *_policies(
        _G,
        _method("gmail.users.drafts.update", *_GMAIL_DRAFT_WRITE),
        _O.GMAIL_UPDATE_DRAFT,
    ),
    *_policies(
        _G,
        _method("gmail.users.drafts.delete", *_GMAIL_DRAFT_WRITE),
        _O.GMAIL_DELETE_DRAFT,
    ),
    *_policies(
        _G, _method("gmail.users.drafts.send", *_GMAIL_DRAFT_WRITE), _O.GMAIL_SEND_DRAFT
    ),
    *_policies(
        _G,
        _method("gmail.users.messages.send", *_GMAIL_DRAFT_WRITE, "gmail.send"),
        _O.GMAIL_SEND_MESSAGE,
    ),
    *_policies(
        _G,
        _method("gmail.users.settings.sendAs.get", *_GMAIL_SETTINGS_READ),
        _O.GMAIL_GET_SEND_AS,
    ),
    *(
        GoogleOperationPolicy(
            operation,
            _G,
            (
                _method("gmail.users.messages.get", *_GMAIL_READ),
                _method("gmail.users.messages.send", *_GMAIL_DRAFT_WRITE, "gmail.send"),
            ),
        )
        for operation in (_O.GMAIL_REPLY_MESSAGE, _O.GMAIL_FORWARD_MESSAGE)
    ),
    *_policies(
        _G,
        _method("gmail.users.messages.modify", *_GMAIL_MODIFY),
        _O.GMAIL_MODIFY_MESSAGE,
    ),
    *_policies(
        _G,
        _method("gmail.users.messages.batchModify", *_GMAIL_MODIFY),
        _O.GMAIL_BATCH_MODIFY_MESSAGES,
    ),
    *_policies(
        _G,
        _method("gmail.users.threads.modify", *_GMAIL_MODIFY),
        _O.GMAIL_MODIFY_THREAD,
    ),
    *_policies(
        _G,
        _method("gmail.users.messages.trash", *_GMAIL_MODIFY),
        _O.GMAIL_TRASH_MESSAGE,
    ),
    *_policies(
        _G,
        _method("gmail.users.messages.untrash", *_GMAIL_MODIFY),
        _O.GMAIL_UNTRASH_MESSAGE,
    ),
    *_policies(
        _G, _method("gmail.users.threads.trash", *_GMAIL_MODIFY), _O.GMAIL_TRASH_THREAD
    ),
    *_policies(
        _G,
        _method("gmail.users.threads.untrash", *_GMAIL_MODIFY),
        _O.GMAIL_UNTRASH_THREAD,
    ),
    *_policies(
        _G,
        _method("gmail.users.settings.filters.list", *_GMAIL_SETTINGS_READ),
        _O.GMAIL_LIST_FILTERS,
    ),
    *_policies(
        _G,
        _method("gmail.users.settings.filters.get", *_GMAIL_SETTINGS_READ),
        _O.GMAIL_GET_FILTER,
    ),
    *_policies(
        _G,
        _method("gmail.users.settings.filters.create", "gmail.settings.basic"),
        _O.GMAIL_CREATE_FILTER,
    ),
    *_policies(
        _G,
        _method("gmail.users.settings.filters.delete", "gmail.settings.basic"),
        _O.GMAIL_DELETE_FILTER,
    ),
    GoogleOperationPolicy(
        _O.GMAIL_REPLACE_FILTER,
        _G,
        (
            _method("gmail.users.settings.filters.create", "gmail.settings.basic"),
            _method("gmail.users.settings.filters.delete", "gmail.settings.basic"),
        ),
    ),
    GoogleOperationPolicy(
        _O.GMAIL_APPLY_FILTER,
        _G,
        (
            _method("gmail.users.settings.filters.get", *_GMAIL_SETTINGS_READ),
            _method("gmail.users.messages.list", *_GMAIL_READ),
            _method("gmail.users.messages.batchModify", *_GMAIL_MODIFY),
        ),
    ),
    GoogleOperationPolicy(
        _O.GMAIL_PREVIEW_FILTER,
        _G,
        (
            _method("gmail.users.settings.filters.get", *_GMAIL_SETTINGS_READ),
            _method("gmail.users.messages.list", *_GMAIL_READ),
        ),
    ),
    *_policies(
        _C,
        _method(
            "calendar.calendarList.list",
            "calendar",
            "calendar.readonly",
            "calendar.calendarlist",
            "calendar.calendarlist.readonly",
        ),
        _O.CALENDAR_LIST_CALENDARS,
    ),
    *_policies(
        _C,
        _method("calendar.events.list", *_CALENDAR_EVENTS_READ),
        _O.CALENDAR_LIST_EVENTS,
        _O.CALENDAR_LIST_STATUS_EVENTS,
    ),
    *_policies(
        _C,
        _method("calendar.events.get", *_CALENDAR_EVENTS_READ),
        _O.CALENDAR_GET_EVENT,
    ),
    *_policies(
        _C,
        _method("calendar.events.instances", *_CALENDAR_EVENTS_READ),
        _O.CALENDAR_LIST_INSTANCES,
    ),
    *_policies(
        _C,
        _method(
            "calendar.freebusy.query",
            "calendar",
            "calendar.readonly",
            "calendar.events.freebusy",
            "calendar.freebusy",
        ),
        _O.CALENDAR_QUERY_FREEBUSY,
        _O.CALENDAR_SUGGEST_TIME,
    ),
    *_policies(
        _C,
        _method("calendar.events.insert", *_CALENDAR_EVENTS_WRITE),
        _O.CALENDAR_CREATE_EVENT,
        _O.CALENDAR_CREATE_STATUS_EVENT,
    ),
    *_policies(
        _C,
        _method("calendar.events.patch", *_CALENDAR_EVENTS_WRITE),
        _O.CALENDAR_UPDATE_EVENT,
    ),
    *_policies(
        _C,
        _method("calendar.events.delete", *_CALENDAR_EVENTS_WRITE),
        _O.CALENDAR_DELETE_EVENT,
    ),
    GoogleOperationPolicy(
        _O.CALENDAR_UPDATE_STATUS_EVENT,
        _C,
        (
            _method("calendar.events.get", *_CALENDAR_EVENTS_READ),
            _method("calendar.events.patch", *_CALENDAR_EVENTS_WRITE),
        ),
    ),
    GoogleOperationPolicy(
        _O.CALENDAR_DELETE_STATUS_EVENT,
        _C,
        (
            _method("calendar.events.get", *_CALENDAR_EVENTS_READ),
            _method("calendar.events.delete", *_CALENDAR_EVENTS_WRITE),
        ),
    ),
    GoogleOperationPolicy(
        _O.CALENDAR_RESPOND_EVENT,
        _C,
        (
            _method("calendar.events.get", *_CALENDAR_EVENTS_READ),
            _method("calendar.events.patch", *_CALENDAR_EVENTS_WRITE),
        ),
    ),
    *_policies(
        _C,
        _method(
            "calendar.calendars.insert",
            "calendar",
            "calendar.calendars",
            "calendar.app.created",
        ),
        _O.CALENDAR_CREATE_CALENDAR,
    ),
    *_policies(
        _D, _method("drive.files.list", *_DRIVE_METADATA), _O.DRIVE_SEARCH_FILES
    ),
    *_policies(
        _D,
        _method("drive.files.get", *_DRIVE_METADATA),
        _O.DRIVE_GET_METADATA,
        _O.DRIVE_GET_LINK,
    ),
    *_policies(
        _D,
        _method("drive.files.get", *_DRIVE_CONTENT),
        _O.DRIVE_READ_CONTENT,
        _O.DRIVE_DOWNLOAD_FILE,
    ),
    *_policies(
        _D, _method("drive.files.export", *_DRIVE_CONTENT), _O.DRIVE_EXPORT_FILE
    ),
    *_policies(
        _D,
        _method("drive.permissions.list", *_DRIVE_METADATA),
        _O.DRIVE_LIST_PERMISSIONS,
    ),
    *_policies(
        _D, _method("drive.permissions.get", *_DRIVE_METADATA), _O.DRIVE_GET_PERMISSION
    ),
    *_policies(
        _D,
        _method("drive.files.create", *_DRIVE_WRITE),
        _O.DRIVE_CREATE_FILE,
        _O.DRIVE_CREATE_FOLDER,
        _O.DRIVE_IMPORT_DOCUMENT,
        _O.DRIVE_IMPORT_SPREADSHEET,
        _O.DRIVE_IMPORT_PRESENTATION,
    ),
    *_policies(_D, _method("drive.files.copy", *_DRIVE_WRITE), _O.DRIVE_COPY_FILE),
    *_policies(
        _D,
        _method("drive.files.update", *_DRIVE_WRITE, "drive.metadata"),
        _O.DRIVE_UPDATE_METADATA,
        _O.DRIVE_UPDATE_ACCESS,
    ),
    *_policies(
        _D,
        _method("drive.files.update", *_DRIVE_WRITE),
        _O.DRIVE_UPDATE_CONTENT,
    ),
    GoogleOperationPolicy(
        _O.DRIVE_APPEND_TEXT,
        _D,
        (
            _method("drive.files.get", *_DRIVE_CONTENT),
            _method("drive.files.update", *_DRIVE_WRITE),
        ),
    ),
    *_policies(
        _D,
        _method("drive.permissions.create", *_DRIVE_WRITE),
        _O.DRIVE_CREATE_PERMISSION,
        _O.DRIVE_TRANSFER_OWNERSHIP,
    ),
    *_policies(
        _D,
        _method("drive.permissions.update", *_DRIVE_WRITE),
        _O.DRIVE_UPDATE_PERMISSION,
    ),
    *_policies(
        _D,
        _method("drive.permissions.delete", *_DRIVE_WRITE),
        _O.DRIVE_DELETE_PERMISSION,
    ),
)


def _include_metadata_prerequisite(
    policy: GoogleOperationPolicy,
) -> GoogleOperationPolicy:
    if policy.operation in {
        _O.DRIVE_READ_CONTENT,
        _O.DRIVE_DOWNLOAD_FILE,
        _O.DRIVE_EXPORT_FILE,
        _O.DRIVE_COPY_FILE,
        _O.DRIVE_UPDATE_CONTENT,
    }:
        return dataclasses.replace(
            policy,
            methods=(_method("drive.files.get", *_DRIVE_METADATA), *policy.methods),
        )
    return policy


GOOGLE_WORKSPACE_OPERATIONS = MappingProxyType(
    {policy.operation: _include_metadata_prerequisite(policy) for policy in _POLICIES}
)


def eligible_operations(
    services: tuple[GoogleService, ...],
    actual_scopes: tuple[str, ...] | None,
) -> frozenset[GoogleWorkspaceOperation]:
    """Project the actual credential; request intent is deliberately not an input."""
    if not actual_scopes:
        return frozenset()
    granted = frozenset(actual_scopes)
    return frozenset(
        policy.operation
        for policy in GOOGLE_WORKSPACE_OPERATIONS.values()
        if policy.service in services and policy.permits(granted)
    )


def operation_permitted(
    operation: GoogleWorkspaceOperation,
    services: tuple[GoogleService, ...],
    actual_scopes: tuple[str, ...] | None,
    auxiliary_operations: tuple[GoogleWorkspaceOperation, ...],
) -> bool:
    """Check the exact operation and argument-dependent prerequisites together."""
    eligible = eligible_operations(services, actual_scopes)
    return operation in eligible and all(
        item in eligible for item in auxiliary_operations
    )


@dataclasses.dataclass(frozen=True)
class GoogleDriveAccess:
    """Scope extent only; Google retains resource eligibility and ACL authority."""

    whole_metadata_read: bool
    whole_content_read: bool
    whole_content_write: bool
    whole_metadata_write: bool
    app_file_read: bool
    app_file_write: bool


def drive_access(
    services: tuple[GoogleService, ...], actual_scopes: tuple[str, ...] | None
) -> GoogleDriveAccess:
    scopes = (
        frozenset(actual_scopes or ())
        if GoogleService.DRIVE in services
        else frozenset()
    )
    whole_write = _scope("drive") in scopes
    whole_read = whole_write or _scope("drive.readonly") in scopes
    metadata_write = whole_write or _scope("drive.metadata") in scopes
    app_file = whole_write or _scope("drive.file") in scopes
    return GoogleDriveAccess(
        whole_metadata_read=whole_read
        or metadata_write
        or _scope("drive.metadata.readonly") in scopes,
        whole_content_read=whole_read,
        whole_content_write=whole_write,
        whole_metadata_write=metadata_write,
        app_file_read=whole_read or app_file,
        app_file_write=app_file,
    )
