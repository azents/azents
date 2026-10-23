"""Catalog coverage and sufficient scope requests independent of actual grants."""

from itertools import combinations

import pytest

from azents.core.google_policy import GoogleService, GoogleToolGroup
from azents.core.google_tool_groups import (
    GOOGLE_GROUP_PRESETS,
    GOOGLE_TOOL_GROUPS,
    group_operations,
    group_prerequisites,
    group_request_scopes,
)
from azents.core.google_workspace_policy import (
    GOOGLE_WORKSPACE_OPERATIONS,
    REQUEST_SCOPE_SERVICES,
    GoogleWorkspaceOperation,
    drive_access,
)


def test_every_model_operation_belongs_to_exactly_one_group() -> None:
    operations = [
        op for group in GOOGLE_TOOL_GROUPS.values() for op in group.operations
    ]
    assert len(operations) == len(set(operations))
    assert set(operations) == set(GoogleWorkspaceOperation) - {
        GoogleWorkspaceOperation.GMAIL_GET_SEND_AS
    }
    assert set(GOOGLE_TOOL_GROUPS) == set(GoogleToolGroup)


@pytest.mark.parametrize("group", list(GoogleToolGroup))
def test_group_requests_are_sufficient_and_belong_to_its_service(
    group: GoogleToolGroup,
) -> None:
    definition = GOOGLE_TOOL_GROUPS[group]
    scopes = frozenset(group_request_scopes((group,)))
    assert all(
        REQUEST_SCOPE_SERVICES[scope] == definition.service
        for scope in scopes - {"openid", "email"}
    )
    for operation in (*definition.operations, *group_prerequisites((group,))):
        assert GOOGLE_WORKSPACE_OPERATIONS[operation].service == definition.service
        assert GOOGLE_WORKSPACE_OPERATIONS[operation].permits(scopes)


@pytest.mark.parametrize("preset", list(GOOGLE_GROUP_PRESETS))
def test_preset_request_scopes_support_selected_operations_and_resource_extent(
    preset: str,
) -> None:
    groups = GOOGLE_GROUP_PRESETS[preset]
    scopes = frozenset(group_request_scopes(groups))
    operations = group_operations(groups) | group_prerequisites(groups)
    for operation in operations:
        assert GOOGLE_WORKSPACE_OPERATIONS[operation].permits(scopes)
    if GoogleToolGroup.DRIVE_READ in groups:
        access = drive_access((GoogleService.DRIVE,), tuple(scopes))
        assert access.whole_content_read
        assert not access.whole_content_write
    if GoogleToolGroup.CALENDAR_READ in groups:
        assert "https://www.googleapis.com/auth/calendar.events.readonly" in scopes or (
            "https://www.googleapis.com/auth/calendar.events" in scopes
        )


def test_read_only_presets_do_not_request_write_scopes() -> None:
    scopes = group_request_scopes(GOOGLE_GROUP_PRESETS["read_only"])
    assert set(scopes) == {
        "openid",
        "email",
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/calendar.events.readonly",
        "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
        "https://www.googleapis.com/auth/calendar.events.freebusy",
        "https://www.googleapis.com/auth/drive.readonly",
    }


@pytest.mark.parametrize(
    "groups",
    [
        combination
        for size in range(1, 5)
        for combination in combinations(
            (
                GoogleToolGroup.DRIVE_READ,
                GoogleToolGroup.DRIVE_FILES,
                GoogleToolGroup.DRIVE_SHARING,
                GoogleToolGroup.DRIVE_OWNERSHIP,
            ),
            size,
        )
    ],
)
def test_drive_group_combinations_preserve_read_extent_and_app_file_writes(
    groups: tuple[GoogleToolGroup, ...],
) -> None:
    scopes = group_request_scopes(groups)
    access = drive_access((GoogleService.DRIVE,), scopes)
    assert access.whole_content_read is (GoogleToolGroup.DRIVE_READ in groups)
    assert not access.whole_content_write
    write_selected = any(group != GoogleToolGroup.DRIVE_READ for group in groups)
    assert access.app_file_write is write_selected
    expected = {"openid", "email"}
    if GoogleToolGroup.DRIVE_READ in groups:
        expected.add("https://www.googleapis.com/auth/drive.readonly")
    if write_selected:
        expected.add("https://www.googleapis.com/auth/drive.file")
    assert set(scopes) == expected


@pytest.mark.parametrize(
    "group",
    [
        GoogleToolGroup.CALENDAR_READ,
        GoogleToolGroup.CALENDAR_EVENTS,
        GoogleToolGroup.CALENDAR_STATUS,
    ],
)
def test_calendar_creation_cannot_replace_existing_calendar_access(
    group: GoogleToolGroup,
) -> None:
    scopes = group_request_scopes((group, GoogleToolGroup.CALENDAR_CREATE))
    prefix = "https://www.googleapis.com/auth/"
    assert prefix + "calendar.app.created" in scopes
    expected = (
        "calendar.events.readonly"
        if group == GoogleToolGroup.CALENDAR_READ
        else "calendar.events"
    )
    assert prefix + expected in scopes


def test_same_resource_superset_scopes_still_remove_redundancy() -> None:
    scopes = group_request_scopes(
        (
            GoogleToolGroup.GMAIL_READ,
            GoogleToolGroup.GMAIL_DRAFTS,
            GoogleToolGroup.GMAIL_LABELS,
            GoogleToolGroup.GMAIL_ORGANIZE,
            GoogleToolGroup.CALENDAR_READ,
            GoogleToolGroup.CALENDAR_EVENTS,
        )
    )
    assert set(scopes) == {
        "openid",
        "email",
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
    }
