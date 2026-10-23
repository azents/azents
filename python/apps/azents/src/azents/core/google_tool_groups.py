"""Selected Google capabilities, presets and sufficient OAuth request construction."""

from collections.abc import Iterable
from dataclasses import dataclass
from types import MappingProxyType

from azents.core.google_policy import GoogleService, GoogleToolGroup
from azents.core.google_workspace_policy import (
    GOOGLE_WORKSPACE_OPERATIONS,
)
from azents.core.google_workspace_policy import (
    GoogleWorkspaceOperation as Op,
)


@dataclass(frozen=True)
class GoogleGroupDefinition:
    group: GoogleToolGroup
    service: GoogleService
    operations: tuple[Op, ...]
    request_scopes: tuple[str, ...]


def _group(
    group: GoogleToolGroup,
    service: GoogleService,
    scopes: tuple[str, ...],
    *operations: Op,
) -> GoogleGroupDefinition:
    return GoogleGroupDefinition(
        group=group,
        service=service,
        operations=operations,
        request_scopes=tuple(
            "https://www.googleapis.com/auth/" + item for item in scopes
        ),
    )


_G = GoogleService.GMAIL
_C = GoogleService.CALENDAR
_D = GoogleService.DRIVE
_T = GoogleToolGroup
_DEFINITIONS = (
    _group(
        _T.GMAIL_READ,
        _G,
        ("gmail.readonly",),
        Op.GMAIL_SEARCH_MESSAGES,
        Op.GMAIL_GET_MESSAGE,
        Op.GMAIL_BATCH_GET_MESSAGES,
        Op.GMAIL_SEARCH_THREADS,
        Op.GMAIL_GET_THREAD,
        Op.GMAIL_DOWNLOAD_ATTACHMENT,
    ),
    _group(
        _T.GMAIL_LABELS,
        _G,
        ("gmail.labels",),
        Op.GMAIL_LIST_LABELS,
        Op.GMAIL_GET_LABEL,
        Op.GMAIL_CREATE_LABEL,
        Op.GMAIL_UPDATE_LABEL,
        Op.GMAIL_DELETE_LABEL,
    ),
    _group(
        _T.GMAIL_DRAFTS,
        _G,
        ("gmail.compose", "gmail.readonly"),
        Op.GMAIL_LIST_DRAFTS,
        Op.GMAIL_GET_DRAFT,
        Op.GMAIL_CREATE_DRAFT,
        Op.GMAIL_UPDATE_DRAFT,
        Op.GMAIL_DELETE_DRAFT,
    ),
    _group(
        _T.GMAIL_SEND,
        _G,
        ("gmail.readonly", "gmail.compose"),
        Op.GMAIL_SEND_DRAFT,
        Op.GMAIL_SEND_MESSAGE,
        Op.GMAIL_REPLY_MESSAGE,
        Op.GMAIL_FORWARD_MESSAGE,
    ),
    _group(
        _T.GMAIL_ORGANIZE,
        _G,
        ("gmail.modify",),
        Op.GMAIL_MODIFY_MESSAGE,
        Op.GMAIL_BATCH_MODIFY_MESSAGES,
        Op.GMAIL_MODIFY_THREAD,
        Op.GMAIL_TRASH_MESSAGE,
        Op.GMAIL_UNTRASH_MESSAGE,
        Op.GMAIL_TRASH_THREAD,
        Op.GMAIL_UNTRASH_THREAD,
    ),
    _group(
        _T.GMAIL_FILTERS,
        _G,
        ("gmail.settings.basic", "gmail.modify"),
        Op.GMAIL_LIST_FILTERS,
        Op.GMAIL_GET_FILTER,
        Op.GMAIL_CREATE_FILTER,
        Op.GMAIL_DELETE_FILTER,
        Op.GMAIL_REPLACE_FILTER,
        Op.GMAIL_APPLY_FILTER,
        Op.GMAIL_PREVIEW_FILTER,
    ),
    _group(
        _T.CALENDAR_READ,
        _C,
        ("calendar.events.readonly", "calendar.calendarlist.readonly"),
        Op.CALENDAR_LIST_CALENDARS,
        Op.CALENDAR_LIST_EVENTS,
        Op.CALENDAR_GET_EVENT,
        Op.CALENDAR_LIST_INSTANCES,
    ),
    _group(
        _T.CALENDAR_AVAILABILITY,
        _C,
        ("calendar.events.freebusy",),
        Op.CALENDAR_QUERY_FREEBUSY,
        Op.CALENDAR_SUGGEST_TIME,
    ),
    _group(
        _T.CALENDAR_EVENTS,
        _C,
        ("calendar.events",),
        Op.CALENDAR_CREATE_EVENT,
        Op.CALENDAR_UPDATE_EVENT,
        Op.CALENDAR_DELETE_EVENT,
        Op.CALENDAR_RESPOND_EVENT,
    ),
    _group(
        _T.CALENDAR_STATUS,
        _C,
        ("calendar.events",),
        Op.CALENDAR_LIST_STATUS_EVENTS,
        Op.CALENDAR_CREATE_STATUS_EVENT,
        Op.CALENDAR_UPDATE_STATUS_EVENT,
        Op.CALENDAR_DELETE_STATUS_EVENT,
    ),
    _group(
        _T.CALENDAR_CREATE, _C, ("calendar.app.created",), Op.CALENDAR_CREATE_CALENDAR
    ),
    _group(
        _T.DRIVE_READ,
        _D,
        ("drive.readonly",),
        Op.DRIVE_SEARCH_FILES,
        Op.DRIVE_GET_METADATA,
        Op.DRIVE_READ_CONTENT,
        Op.DRIVE_DOWNLOAD_FILE,
        Op.DRIVE_EXPORT_FILE,
        Op.DRIVE_GET_LINK,
    ),
    _group(
        _T.DRIVE_FILES,
        _D,
        ("drive.file",),
        Op.DRIVE_CREATE_FILE,
        Op.DRIVE_CREATE_FOLDER,
        Op.DRIVE_COPY_FILE,
        Op.DRIVE_UPDATE_METADATA,
        Op.DRIVE_UPDATE_CONTENT,
        Op.DRIVE_APPEND_TEXT,
        Op.DRIVE_IMPORT_DOCUMENT,
        Op.DRIVE_IMPORT_SPREADSHEET,
        Op.DRIVE_IMPORT_PRESENTATION,
    ),
    _group(
        _T.DRIVE_SHARING,
        _D,
        ("drive.file",),
        Op.DRIVE_LIST_PERMISSIONS,
        Op.DRIVE_GET_PERMISSION,
        Op.DRIVE_CREATE_PERMISSION,
        Op.DRIVE_UPDATE_PERMISSION,
        Op.DRIVE_DELETE_PERMISSION,
        Op.DRIVE_UPDATE_ACCESS,
    ),
    _group(_T.DRIVE_OWNERSHIP, _D, ("drive.file",), Op.DRIVE_TRANSFER_OWNERSHIP),
)
GOOGLE_TOOL_GROUPS = MappingProxyType({item.group: item for item in _DEFINITIONS})
GOOGLE_GROUP_PRESETS = MappingProxyType(
    {
        "read_only": (
            _T.GMAIL_READ,
            _T.CALENDAR_READ,
            _T.CALENDAR_AVAILABILITY,
            _T.DRIVE_READ,
        ),
        "assistant": (
            _T.GMAIL_READ,
            _T.GMAIL_DRAFTS,
            _T.GMAIL_SEND,
            _T.GMAIL_ORGANIZE,
            _T.CALENDAR_READ,
            _T.CALENDAR_AVAILABILITY,
            _T.CALENDAR_EVENTS,
            _T.DRIVE_READ,
            _T.DRIVE_FILES,
        ),
        "full": tuple(GoogleToolGroup),
        "clear": (),
    }
)

# Only same-resource coverage permits consent-scope reduction. Method eligibility
# alone cannot distinguish app-created/per-file access from whole-service access.
_REQUEST_SCOPE_COVERAGE = MappingProxyType(
    {
        "https://www.googleapis.com/auth/gmail.modify": frozenset(
            "https://www.googleapis.com/auth/" + name
            for name in ("gmail.readonly", "gmail.compose", "gmail.labels")
        ),
        "https://www.googleapis.com/auth/calendar.events": frozenset(
            {"https://www.googleapis.com/auth/calendar.events.readonly"}
        ),
    }
)


def group_operations(groups: tuple[GoogleToolGroup, ...]) -> frozenset[Op]:
    return frozenset(
        op for group in groups for op in GOOGLE_TOOL_GROUPS[group].operations
    )


def groups_for_services(
    services: Iterable[GoogleService | str],
) -> tuple[GoogleToolGroup, ...]:
    """Enumerate service groups for explicit preserved-selection conversion."""
    enabled = frozenset(services)
    return tuple(
        item.group for item in GOOGLE_TOOL_GROUPS.values() if item.service in enabled
    )


def group_prerequisites(groups: tuple[GoogleToolGroup, ...]) -> frozenset[Op]:
    """Include source reads and sender verification for supported compose variants."""
    if {_T.GMAIL_DRAFTS, _T.GMAIL_SEND}.intersection(groups):
        return frozenset(
            {Op.GMAIL_GET_MESSAGE, Op.GMAIL_DOWNLOAD_ATTACHMENT, Op.GMAIL_GET_SEND_AS}
        )
    return frozenset()


def group_request_scopes(groups: tuple[GoogleToolGroup, ...]) -> tuple[str, ...]:
    """Retain selected resource scope and SDK methods when reducing requests."""
    operations = group_operations(groups) | group_prerequisites(groups)
    scopes = {
        scope for group in groups for scope in GOOGLE_TOOL_GROUPS[group].request_scopes
    }
    for scope in sorted(scopes):
        remaining = frozenset(scopes - {scope})
        covered = any(
            scope in _REQUEST_SCOPE_COVERAGE.get(other, frozenset())
            for other in remaining
        )
        if covered and all(
            GOOGLE_WORKSPACE_OPERATIONS[op].permits(remaining) for op in operations
        ):
            scopes.remove(scope)
    return tuple(sorted(scopes | {"openid", "email"}))
