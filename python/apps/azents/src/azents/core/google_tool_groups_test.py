"""Catalog coverage and sufficient scope requests independent of actual grants."""

import pytest

from azents.core.google_policy import GoogleToolGroup
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
def test_preset_request_scopes_support_selected_operations_without_redundant_requests(
    preset: str,
) -> None:
    groups = GOOGLE_GROUP_PRESETS[preset]
    scopes = frozenset(group_request_scopes(groups))
    operations = group_operations(groups) | group_prerequisites(groups)
    for operation in operations:
        assert GOOGLE_WORKSPACE_OPERATIONS[operation].permits(scopes)
    for scope in scopes - {"openid", "email"}:
        assert any(
            not GOOGLE_WORKSPACE_OPERATIONS[operation].permits(scopes - {scope})
            for operation in operations
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
