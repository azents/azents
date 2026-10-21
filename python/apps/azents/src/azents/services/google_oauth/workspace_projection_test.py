"""Management capability evidence is scope-derived and service-switch-aware."""

import pytest

from azents.core.google_policy import GoogleService
from azents.core.google_workspace_policy import GoogleWorkspaceOperation as Op
from azents.core.google_workspace_policy import drive_access
from azents.services.google_oauth.workspace_projection import service_accesses


def _scope(value: str) -> str:
    return "https://www.googleapis.com/auth/" + value


@pytest.mark.parametrize("actual", [None, ()])
def test_unknown_and_empty_receipts_never_invent_capabilities(
    actual: tuple[str, ...] | None,
) -> None:
    accesses = service_accesses(tuple(GoogleService), actual)
    assert len(accesses) == 3
    assert all(item.enabled for item in accesses)
    assert all(not item.permitted_tools and item.unavailable_tools for item in accesses)
    assert {item.status for item in accesses} == {
        "unknown" if actual is None else "not_granted"
    }


def test_broad_gmail_grant_exposes_supported_sending_without_request_ceiling() -> None:
    accesses = service_accesses((GoogleService.GMAIL,), (_scope("gmail.modify"),))
    gmail = next(item for item in accesses if item.service is GoogleService.GMAIL)
    assert gmail.enabled and Op.GMAIL_SEND_MESSAGE in gmail.permitted_tools
    assert Op.GMAIL_GET_MESSAGE in gmail.permitted_tools
    assert Op.GMAIL_CREATE_FILTER in gmail.unavailable_tools
    assert gmail.status == "partial"


def test_saved_all_off_retains_visible_inactive_services() -> None:
    accesses = service_accesses((), (_scope("drive"), _scope("calendar")))
    assert {item.service for item in accesses} == set(GoogleService)
    assert all(item.status == "disabled" and not item.enabled for item in accesses)
    assert all(not item.permitted_tools and item.unavailable_tools for item in accesses)


def test_service_off_is_independent_of_a_sufficient_actual_grant() -> None:
    accesses = service_accesses((GoogleService.CALENDAR,), (_scope("drive"),))
    drive = next(item for item in accesses if item.service is GoogleService.DRIVE)
    calendar = next(item for item in accesses if item.service is GoogleService.CALENDAR)
    assert drive.status == "disabled" and not drive.permitted_tools
    assert calendar.enabled and calendar.status == "not_granted"


def test_mixed_drive_capabilities_preserve_actual_resource_extent() -> None:
    services = (GoogleService.DRIVE,)
    scopes = (_scope("drive.readonly"), _scope("drive.file"))
    access = next(
        item
        for item in service_accesses(services, scopes)
        if item.service is GoogleService.DRIVE
    )
    extent = drive_access(services, scopes)
    assert Op.DRIVE_SEARCH_FILES in access.permitted_tools
    assert Op.DRIVE_UPDATE_CONTENT in access.permitted_tools
    assert extent.whole_content_read and extent.app_file_write
    assert not extent.whole_content_write
