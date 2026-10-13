"""Scope evidence, partial consent and selected-task authorization."""

import pytest

from azents.core.google_policy import (
    GoogleService,
    GoogleTask,
    permitted_tools,
    requested_scopes,
)


def _s(name: str) -> str:
    return "https://www.googleapis.com/auth/" + name


@pytest.mark.parametrize("scopes", [None, ()])
def test_unknown_or_empty_grant_admits_nothing(scopes: tuple[str, ...] | None) -> None:
    assert not permitted_tools(tuple(GoogleTask), scopes, GoogleService.CALENDAR)


def test_calendar_partial_read_does_not_grant_list_or_write() -> None:
    tools = permitted_tools(
        (GoogleTask.CALENDAR_READ, GoogleTask.CALENDAR_EDIT),
        (_s("calendar.events.readonly"),),
        GoogleService.CALENDAR,
    )
    assert tools == {"get_event", "list_events", "search_events"}


def test_full_grant_does_not_select_unselected_work() -> None:
    tools = permitted_tools(
        (GoogleTask.CALENDAR_READ,),
        (_s("calendar"),),
        GoogleService.CALENDAR,
    )
    assert "list_calendars" in tools
    assert "delete_event" not in tools


def test_restricted_drive_does_not_admit_whole_drive_search() -> None:
    tools = permitted_tools(
        (GoogleTask.DRIVE_FILES, GoogleTask.DRIVE_READ),
        (_s("drive.file"),),
        GoogleService.DRIVE,
    )
    assert "create_file" in tools
    assert "read_file_content" in tools
    assert "search_files" not in tools
    assert "list_recent_files" not in tools


def test_denied_gmail_does_not_deny_calendar() -> None:
    tasks = (GoogleTask.CALENDAR_READ, GoogleTask.GMAIL_READ)
    scopes = (_s("calendar.events.readonly"),)
    assert permitted_tools(tasks, scopes, GoogleService.CALENDAR)
    assert not permitted_tools(tasks, scopes, GoogleService.GMAIL)


def test_requested_scopes_are_exact_and_no_gmail_send_tool_exists() -> None:
    assert requested_scopes((GoogleTask.GMAIL_READ,)) == (
        "email",
        _s("gmail.readonly"),
        "openid",
    )
    assert "send_message" not in permitted_tools(
        tuple(GoogleTask),
        ("https://mail.google.com/",),
        GoogleService.GMAIL,
    )


def test_partial_draft_read_does_not_admit_create() -> None:
    assert permitted_tools(
        (GoogleTask.GMAIL_DRAFTS,),
        (_s("gmail.readonly"),),
        GoogleService.GMAIL,
    ) == {"get_draft", "list_drafts"}
