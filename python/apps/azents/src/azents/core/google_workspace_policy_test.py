"""Actual grant, request intent and method-specific Workspace scope contracts."""

import dataclasses
from itertools import product

import pytest
from pydantic import ValidationError

from azents.core.google_policy import GoogleService
from azents.core.google_workspace_policy import (
    GOOGLE_WORKSPACE_OPERATIONS,
    IDENTITY_SCOPES,
    REQUEST_SCOPE_SERVICES,
    GoogleWorkspaceConfig,
    GoogleWorkspaceConnectInput,
    GoogleWorkspaceOperation,
    drive_access,
    eligible_operations,
    operation_permitted,
)

_O = GoogleWorkspaceOperation
_ALL = tuple(GoogleService)


def _s(name: str) -> str:
    return (
        "https://mail.google.com/"
        if name == "mail"
        else "https://www.googleapis.com/auth/" + name
    )


def _eligible(
    service: GoogleService, *names: str
) -> frozenset[GoogleWorkspaceOperation]:
    return eligible_operations((service,), tuple(_s(name) for name in names))


@pytest.mark.parametrize(
    "actual", [None, (), ("unsupported.scope",), ("openid", "email")]
)
def test_empty_unknown_or_identity_only_grants_admit_nothing(
    actual: tuple[str, ...] | None,
) -> None:
    assert not eligible_operations(_ALL, actual)


@pytest.mark.parametrize("operation", tuple(_O))
def test_catalog_is_complete_with_nonempty_explicit_method_scope_alternatives(
    operation: _O,
) -> None:
    policy = GOOGLE_WORKSPACE_OPERATIONS[operation]
    assert policy.operation is operation
    assert policy.methods
    for method in policy.methods:
        assert method.method.startswith(policy.service + ".")
        assert method.sufficient
        assert all(alternative for alternative in method.sufficient)
        assert not method.permits(frozenset())
        for alternative in method.sufficient:
            assert alternative <= REQUEST_SCOPE_SERVICES.keys()
            assert method.permits(alternative)
    # Every complete combination of prerequisite alternatives authorizes this
    # operation, while local service-off always defeats the same receipt.
    for alternatives in product(*(method.sufficient for method in policy.methods)):
        receipt = tuple(frozenset().union(*alternatives))
        assert operation in eligible_operations((policy.service,), receipt)
        assert operation not in eligible_operations((), receipt)


def test_catalog_has_no_duplicate_operation_identity() -> None:
    assert len(GOOGLE_WORKSPACE_OPERATIONS) == len(_O)


def test_broad_actual_grant_authorizes_new_work_despite_narrow_request_intent() -> None:
    config = GoogleWorkspaceConfig(
        services=(GoogleService.GMAIL,),
        oauth_request_scopes=(_s("gmail.readonly"),),
        timeout=30,
    )
    actual = (_s("gmail.modify"),)
    allowed = eligible_operations(config.services, actual)
    assert {
        _O.GMAIL_SEND_MESSAGE,
        _O.GMAIL_DELETE_DRAFT,
        _O.GMAIL_BATCH_MODIFY_MESSAGES,
    } <= allowed
    assert _O.GMAIL_CREATE_FILTER not in allowed  # different official scope
    assert config.oauth_request_scopes == tuple(
        sorted({"openid", "email", _s("gmail.readonly")})
    )


def test_partial_consent_is_per_operation_and_per_service() -> None:
    actual = (_s("calendar.events.readonly"), _s("gmail.send"))
    allowed = eligible_operations(_ALL, actual)
    assert {_O.CALENDAR_GET_EVENT, _O.GMAIL_SEND_MESSAGE} <= allowed
    assert {
        _O.CALENDAR_LIST_CALENDARS,
        _O.CALENDAR_CREATE_EVENT,
        _O.GMAIL_GET_MESSAGE,
        _O.DRIVE_SEARCH_FILES,
    }.isdisjoint(allowed)


def test_send_only_has_no_saved_draft_send_or_implicit_read_for_reply() -> None:
    assert _eligible(GoogleService.GMAIL, "gmail.send") == {_O.GMAIL_SEND_MESSAGE}
    assert _O.GMAIL_SEND_DRAFT in _eligible(GoogleService.GMAIL, "gmail.compose")
    assert _O.GMAIL_REPLY_MESSAGE not in _eligible(GoogleService.GMAIL, "gmail.compose")
    assert _O.GMAIL_REPLY_MESSAGE in _eligible(
        GoogleService.GMAIL, "gmail.send", "gmail.readonly"
    )


def test_labels_and_metadata_do_not_authorize_message_body_or_mailbox_mutation() -> (
    None
):
    allowed = _eligible(GoogleService.GMAIL, "gmail.labels", "gmail.metadata")
    assert {_O.GMAIL_CREATE_LABEL, _O.GMAIL_LIST_LABELS} <= allowed
    assert {
        _O.GMAIL_GET_MESSAGE,
        _O.GMAIL_MODIFY_MESSAGE,
        _O.GMAIL_SEARCH_MESSAGES,
    }.isdisjoint(allowed)


def test_filter_settings_write_and_existing_mail_effects_are_distinct() -> None:
    settings = _eligible(GoogleService.GMAIL, "gmail.settings.basic")
    assert {_O.GMAIL_LIST_FILTERS, _O.GMAIL_REPLACE_FILTER} <= settings
    assert _O.GMAIL_APPLY_FILTER not in settings
    modify = _eligible(GoogleService.GMAIL, "gmail.modify")
    assert _O.GMAIL_APPLY_FILTER in modify
    assert _O.GMAIL_REPLACE_FILTER not in modify


@pytest.mark.parametrize("name", ["calendar.events.freebusy", "calendar.freebusy"])
def test_availability_does_not_expose_event_bodies_or_require_calendar_list(
    name: str,
) -> None:
    assert _eligible(GoogleService.CALENDAR, name) == {
        _O.CALENDAR_QUERY_FREEBUSY,
        _O.CALENDAR_SUGGEST_TIME,
    }


def test_event_scopes_do_not_imply_freebusy_or_calendar_list() -> None:
    allowed = _eligible(GoogleService.CALENDAR, "calendar.events")
    assert {
        _O.CALENDAR_CREATE_EVENT,
        _O.CALENDAR_GET_EVENT,
        _O.CALENDAR_RESPOND_EVENT,
    } <= allowed
    assert {_O.CALENDAR_QUERY_FREEBUSY, _O.CALENDAR_LIST_CALENDARS}.isdisjoint(allowed)


def test_app_created_calendar_scope_exposes_secondary_creation_and_scoped_events() -> (
    None
):
    allowed = _eligible(GoogleService.CALENDAR, "calendar.app.created")
    assert {_O.CALENDAR_CREATE_CALENDAR, _O.CALENDAR_CREATE_EVENT} <= allowed
    assert _O.CALENDAR_QUERY_FREEBUSY not in allowed


def test_drive_file_scope_search_is_google_app_file_scoped_not_whole_drive() -> None:
    allowed = _eligible(GoogleService.DRIVE, "drive.file")
    assert {
        _O.DRIVE_SEARCH_FILES,
        _O.DRIVE_READ_CONTENT,
        _O.DRIVE_UPDATE_CONTENT,
        _O.DRIVE_CREATE_PERMISSION,
    } <= allowed
    access = drive_access((GoogleService.DRIVE,), (_s("drive.file"),))
    assert access.app_file_read and access.app_file_write
    assert not access.whole_content_read and not access.whole_content_write
    assert not access.whole_metadata_read and not access.whole_metadata_write


def test_mixed_drive_scope_has_whole_read_and_only_app_file_content_write() -> None:
    scopes = (_s("drive.readonly"), _s("drive.file"))
    access = drive_access((GoogleService.DRIVE,), scopes)
    assert access.whole_content_read and access.whole_metadata_read
    assert access.app_file_write
    assert not access.whole_content_write and not access.whole_metadata_write
    assert _O.DRIVE_UPDATE_CONTENT in eligible_operations(
        (GoogleService.DRIVE,), scopes
    )
    assert _O.DRIVE_UPDATE_CONTENT not in _eligible(
        GoogleService.DRIVE, "drive.readonly"
    )


def test_metadata_only_drive_grant_does_not_authorize_content_or_sharing() -> None:
    allowed = _eligible(GoogleService.DRIVE, "drive.metadata")
    assert {
        _O.DRIVE_GET_METADATA,
        _O.DRIVE_GET_LINK,
        _O.DRIVE_LIST_PERMISSIONS,
        _O.DRIVE_UPDATE_METADATA,
        _O.DRIVE_UPDATE_ACCESS,
    } <= allowed
    assert {
        _O.DRIVE_READ_CONTENT,
        _O.DRIVE_CREATE_PERMISSION,
        _O.DRIVE_UPDATE_PERMISSION,
        _O.DRIVE_DELETE_PERMISSION,
        _O.DRIVE_TRANSFER_OWNERSHIP,
        _O.DRIVE_UPDATE_CONTENT,
    }.isdisjoint(allowed)
    access = drive_access((GoogleService.DRIVE,), (_s("drive.metadata"),))
    assert access.whole_metadata_write
    assert not access.whole_content_read and not access.whole_content_write


@pytest.mark.parametrize("actual", [None, (), (_s("drive"),)])
def test_disabled_drive_has_no_capability_extent(
    actual: tuple[str, ...] | None,
) -> None:
    assert not any(dataclasses.astuple(drive_access((), actual)))


def test_argument_dependent_auxiliary_operations_need_their_own_scope_and_service() -> (
    None
):
    services = (GoogleService.GMAIL,)
    assert operation_permitted(_O.GMAIL_SEND_MESSAGE, services, (_s("gmail.send"),), ())
    assert not operation_permitted(
        _O.GMAIL_SEND_MESSAGE, services, (_s("gmail.send"),), (_O.GMAIL_GET_MESSAGE,)
    )
    assert operation_permitted(
        _O.GMAIL_SEND_MESSAGE,
        services,
        (_s("gmail.send"), _s("gmail.readonly")),
        (_O.GMAIL_GET_MESSAGE,),
    )
    assert not operation_permitted(
        _O.GMAIL_SEND_MESSAGE,
        services,
        (_s("gmail.send"), _s("drive")),
        (_O.DRIVE_READ_CONTENT,),
    )


def test_saved_all_off_config_retains_canonical_request_intent() -> None:
    config = GoogleWorkspaceConfig(
        services=(),
        oauth_request_scopes=(_s("drive.file"), "openid", _s("drive.file")),
        timeout=20,
    )
    assert config.services == ()
    assert config.oauth_request_scopes == tuple(
        sorted(IDENTITY_SCOPES | {_s("drive.file")})
    )
    assert not eligible_operations(config.services, (_s("drive"),))
    assert GoogleWorkspaceConfig.model_validate_json(config.model_dump_json()) == config


def test_request_services_and_scopes_are_canonical_not_task_groups() -> None:
    config = GoogleWorkspaceConnectInput(
        services=(GoogleService.GMAIL, GoogleService.CALENDAR, GoogleService.GMAIL),
        oauth_request_scopes=(_s("gmail.send"),),
        timeout=20,
    )
    assert config.services == (GoogleService.CALENDAR, GoogleService.GMAIL)


@pytest.mark.parametrize(
    "services,scopes",
    [
        ((), (_s("drive"),)),
        ((GoogleService.GMAIL,), (_s("drive"),)),
        ((GoogleService.GMAIL,), ("https://untrusted.invalid/token",)),
    ],
)
def test_consent_request_rejects_unselected_services_or_unsupported_scopes(
    services: tuple[GoogleService, ...], scopes: tuple[str, ...]
) -> None:
    with pytest.raises(ValidationError):
        GoogleWorkspaceConnectInput(
            services=services, oauth_request_scopes=scopes, timeout=30
        )


@pytest.mark.parametrize("timeout", [0, -1, 301, float("inf"), float("nan")])
def test_config_timeout_is_bounded(timeout: float) -> None:
    with pytest.raises(ValidationError):
        GoogleWorkspaceConfig(services=(), oauth_request_scopes=(), timeout=timeout)


def test_new_config_rejects_unknown_fields_at_ingress() -> None:
    with pytest.raises(ValidationError):
        GoogleWorkspaceConfig.model_validate(
            {"services": [], "oauth_request_scopes": [], "timeout": 30, "granted": True}
        )


@pytest.mark.parametrize("timeout", [True, "30", None])
def test_new_config_rejects_wrong_timeout_types(timeout: object) -> None:
    with pytest.raises(ValidationError):
        GoogleWorkspaceConfig.model_validate(
            {"services": [], "oauth_request_scopes": [], "timeout": timeout}
        )
