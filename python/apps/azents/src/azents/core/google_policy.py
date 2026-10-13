"""Compiled Google MCP task and scope policy; discovery is not authorization."""

import dataclasses
import enum


class GoogleService(enum.StrEnum):
    """Fixed official Google Workspace MCP services."""

    CALENDAR = "calendar"
    DRIVE = "drive"
    GMAIL = "gmail"


class GoogleTask(enum.StrEnum):
    """Explicit selected work; no task is silently selected."""

    CALENDAR_READ = "calendar_read"
    CALENDAR_AVAILABILITY = "calendar_availability"
    CALENDAR_EDIT = "calendar_edit"
    DRIVE_READ = "drive_read"
    DRIVE_FILES = "drive_files"
    GMAIL_READ = "gmail_read"
    GMAIL_DRAFTS = "gmail_drafts"
    GMAIL_MODIFY = "gmail_modify"


GOOGLE_MCP_ENDPOINTS: dict[GoogleService, str] = {
    GoogleService.CALENDAR: "https://calendarmcp.googleapis.com/mcp/v1",
    GoogleService.DRIVE: "https://drivemcp.googleapis.com/mcp/v1",
    GoogleService.GMAIL: "https://gmailmcp.googleapis.com/mcp/v1",
}


def _scope(name: str) -> str:
    return f"https://www.googleapis.com/auth/{name}"


TASK_SCOPES: dict[GoogleTask, tuple[str, ...]] = {
    GoogleTask.CALENDAR_READ: (
        _scope("calendar.events.readonly"),
        _scope("calendar.calendarlist.readonly"),
    ),
    GoogleTask.CALENDAR_AVAILABILITY: (
        _scope("calendar.events.freebusy"),
        _scope("calendar.calendarlist.readonly"),
    ),
    GoogleTask.CALENDAR_EDIT: (_scope("calendar.events"),),
    GoogleTask.DRIVE_READ: (_scope("drive.readonly"),),
    GoogleTask.DRIVE_FILES: (_scope("drive.file"),),
    GoogleTask.GMAIL_READ: (_scope("gmail.readonly"),),
    GoogleTask.GMAIL_DRAFTS: (_scope("gmail.compose"),),
    GoogleTask.GMAIL_MODIFY: (_scope("gmail.modify"),),
}


@dataclasses.dataclass(frozen=True)
class GoogleToolPolicy:
    """Exact admitted remote name with explicit sufficient scope alternatives."""

    service: GoogleService
    name: str
    task: GoogleTask
    sufficient: tuple[frozenset[str], ...]

    def permits(self, scopes: frozenset[str]) -> bool:
        """Accept only a complete explicit sufficient scope set."""
        return any(required <= scopes for required in self.sufficient)


def _alternatives(*names: str) -> tuple[frozenset[str], ...]:
    return tuple(frozenset((_scope(name),)) for name in names)


def _tools(
    service: GoogleService,
    task: GoogleTask,
    names: tuple[str, ...],
    sufficient: tuple[frozenset[str], ...],
) -> tuple[GoogleToolPolicy, ...]:
    return tuple(GoogleToolPolicy(service, name, task, sufficient) for name in names)


# These conservative mappings use documented Google API scope semantics. Exact
# authenticated remote-MCP acceptance remains a separately reported live test.
GOOGLE_TOOL_POLICY = (
    *_tools(
        GoogleService.CALENDAR,
        GoogleTask.CALENDAR_READ,
        ("list_events", "get_event", "search_events"),
        _alternatives(
            "calendar.events.readonly",
            "calendar.events",
            "calendar.readonly",
            "calendar",
        ),
    ),
    *_tools(
        GoogleService.CALENDAR,
        GoogleTask.CALENDAR_READ,
        ("list_calendars",),
        _alternatives(
            "calendar.calendarlist.readonly",
            "calendar.calendarlist",
            "calendar.readonly",
            "calendar",
        ),
    ),
    *_tools(
        GoogleService.CALENDAR,
        GoogleTask.CALENDAR_AVAILABILITY,
        ("suggest_time",),
        (
            frozenset(TASK_SCOPES[GoogleTask.CALENDAR_AVAILABILITY]),
            *_alternatives("calendar.readonly", "calendar"),
        ),
    ),
    *_tools(
        GoogleService.CALENDAR,
        GoogleTask.CALENDAR_EDIT,
        ("create_event", "update_event", "delete_event", "respond_to_event"),
        _alternatives("calendar.events", "calendar"),
    ),
    *_tools(
        GoogleService.DRIVE,
        GoogleTask.DRIVE_READ,
        (
            "download_file_content",
            "get_file_metadata",
            "get_file_permissions",
            "list_recent_files",
            "read_file_content",
            "search_files",
        ),
        _alternatives("drive.readonly", "drive"),
    ),
    *_tools(
        GoogleService.DRIVE,
        GoogleTask.DRIVE_FILES,
        (
            "copy_file",
            "create_file",
            "download_file_content",
            "get_file_metadata",
            "get_file_permissions",
            "read_file_content",
        ),
        _alternatives("drive.file", "drive"),
    ),
    *_tools(
        GoogleService.GMAIL,
        GoogleTask.GMAIL_READ,
        ("get_thread", "get_message", "search_threads", "list_labels"),
        (
            *_alternatives("gmail.readonly", "gmail.modify"),
            frozenset(("https://mail.google.com/",)),
        ),
    ),
    *_tools(
        GoogleService.GMAIL,
        GoogleTask.GMAIL_DRAFTS,
        ("list_drafts", "get_draft"),
        (
            *_alternatives("gmail.readonly", "gmail.compose", "gmail.modify"),
            frozenset(("https://mail.google.com/",)),
        ),
    ),
    *_tools(
        GoogleService.GMAIL,
        GoogleTask.GMAIL_DRAFTS,
        ("create_draft",),
        (
            *_alternatives("gmail.compose", "gmail.modify"),
            frozenset(("https://mail.google.com/",)),
        ),
    ),
    *_tools(
        GoogleService.GMAIL,
        GoogleTask.GMAIL_MODIFY,
        (
            "label_thread",
            "unlabel_thread",
            "apply_sensitive_thread_label",
            "trash_thread",
            "untrash_thread",
            "mark_thread_spam",
            "unmark_thread_spam",
            "label_message",
            "update_message_labels",
            "unlabel_message",
            "apply_sensitive_message_label",
            "trash_message",
            "untrash_message",
            "mark_message_spam",
            "unmark_message_spam",
            "create_label",
        ),
        (*_alternatives("gmail.modify"), frozenset(("https://mail.google.com/",))),
    ),
)


def requested_scopes(tasks: tuple[GoogleTask, ...]) -> tuple[str, ...]:
    """Request only selected work plus minimal verified-account identity."""
    return tuple(
        sorted(
            {"openid", "email"}.union(
                scope for task in tasks for scope in TASK_SCOPES[task]
            )
        )
    )


def permitted_tools(
    tasks: tuple[GoogleTask, ...],
    scopes: tuple[str, ...] | None,
    service: GoogleService,
) -> frozenset[str]:
    """Unknown grant evidence admits nothing, including previously cached tools."""
    if scopes is None:
        return frozenset()
    granted = frozenset(scopes)
    return frozenset(
        policy.name
        for policy in GOOGLE_TOOL_POLICY
        if policy.service is service
        and policy.task in tasks
        and policy.permits(granted)
    )


def selected_services(tasks: tuple[GoogleTask, ...]) -> tuple[GoogleService, ...]:
    """Deterministically derive service composition from explicit task selection."""
    return tuple(
        service
        for service in GoogleService
        if any(
            policy.service is service and policy.task in tasks
            for policy in GOOGLE_TOOL_POLICY
        )
    )
