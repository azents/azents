"""One-time config/outcome transformations preserve intent without inventing grants."""

import copy

import pytest

from azents.core.google_policy import GoogleService
from azents.core.google_workspace_cutover import (
    GoogleCutoverError,
    transform_google_config,
    transform_google_final_settings,
    transform_google_published_outcome,
)
from azents.core.google_workspace_policy import GoogleWorkspaceFinalSettings


def _s(name: str) -> str:
    return "https://www.googleapis.com/auth/" + name


@pytest.mark.parametrize(
    "task,service,scopes",
    [
        (
            "calendar_read",
            GoogleService.CALENDAR,
            ("calendar.events.readonly", "calendar.calendarlist.readonly"),
        ),
        (
            "calendar_availability",
            GoogleService.CALENDAR,
            ("calendar.events.freebusy", "calendar.calendarlist.readonly"),
        ),
        ("calendar_edit", GoogleService.CALENDAR, ("calendar.events",)),
        ("drive_read", GoogleService.DRIVE, ("drive.readonly",)),
        ("drive_files", GoogleService.DRIVE, ("drive.file",)),
        ("gmail_read", GoogleService.GMAIL, ("gmail.readonly",)),
        ("gmail_drafts", GoogleService.GMAIL, ("gmail.compose",)),
        ("gmail_modify", GoogleService.GMAIL, ("gmail.modify",)),
    ],
)
def test_old_tasks_preserve_exact_requested_scope_intent(
    task: str, service: GoogleService, scopes: tuple[str, ...]
) -> None:
    result = transform_google_config(
        {"tasks": [task], "timeout": 42, "security_risk_acknowledged": True}
    )
    assert result.services == (service,)
    assert result.oauth_request_scopes == tuple(
        sorted({"openid", "email", *(_s(scope) for scope in scopes)})
    )
    assert result.timeout == 42
    assert transform_google_config(result.model_dump(mode="json")) == result


def test_mixed_old_selection_preserves_both_drive_scopes_and_canonicalizes() -> None:
    payload = {
        "tasks": ["gmail_read", "drive_files", "drive_read", "drive_files"],
        "timeout": 12,
        "security_risk_acknowledged": False,
    }
    before = copy.deepcopy(payload)
    result = transform_google_config(payload)
    assert payload == before
    assert result.services == (GoogleService.DRIVE, GoogleService.GMAIL)
    assert set(result.oauth_request_scopes) == {
        "openid",
        "email",
        _s("drive.file"),
        _s("drive.readonly"),
        _s("gmail.readonly"),
    }


def test_old_omitted_timeout_uses_historical_default() -> None:
    result = transform_google_config(
        {"tasks": ["gmail_read"], "security_risk_acknowledged": True}
    )
    assert result.timeout == 30


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        "secret.invalid.config",
        {"tasks": [], "security_risk_acknowledged": True},
        {"tasks": ["invented_task"], "security_risk_acknowledged": True},
        {"tasks": ["gmail_read"], "security_risk_acknowledged": "true"},
        {"tasks": ["gmail_read"], "security_risk_acknowledged": True, "timeout": 0},
        {
            "tasks": ["gmail_read"],
            "security_risk_acknowledged": True,
            "timeout": float("nan"),
        },
        {
            "tasks": ["gmail_read"],
            "security_risk_acknowledged": True,
            "secret": "credential-canary",
        },
        {
            "tasks": ["gmail_read"],
            "services": ["gmail"],
            "oauth_request_scopes": [],
            "timeout": 30,
            "security_risk_acknowledged": True,
        },
        {"services": ["unknown"], "oauth_request_scopes": [], "timeout": 30},
        {
            "services": ["gmail"],
            "oauth_request_scopes": ["credential-canary"],
            "timeout": 30,
        },
    ],
)
def test_malformed_or_hybrid_config_fails_with_only_nonsecret_diagnostics(
    payload: object,
) -> None:
    with pytest.raises(GoogleCutoverError) as error:
        transform_google_config(payload)
    assert str(error.value) == "Invalid Google Toolkit configuration for cutover."
    assert error.value.__cause__ is None


def test_transformed_all_off_config_remains_valid_without_reenabling_services() -> None:
    result = transform_google_config(
        {
            "services": [],
            "oauth_request_scopes": [_s("drive.file"), "openid", "email"],
            "timeout": 30,
        }
    )
    assert result.services == ()
    assert result.oauth_request_scopes == tuple(
        sorted({_s("drive.file"), "openid", "email"})
    )


def test_published_creation_keeps_all_historical_metadata_and_identity() -> None:
    metadata = {
        "name": "Connection",
        "slug": "google",
        "description": "kept description",
        "prompt": "kept prompt",
        "enabled": False,
        "always_expose_tools": True,
    }
    old = {
        **metadata,
        "tasks": ["calendar_read"],
        "timeout": 19,
        "security_risk_acknowledged": True,
    }
    before = copy.deepcopy(old)
    result = transform_google_published_outcome(
        toolkit_id="historical-toolkit",
        connection_id="historical-connection",
        final_settings=old,
    )
    assert result.toolkit_id == "historical-toolkit"
    assert result.connection_id == "historical-connection"
    assert isinstance(result.final_settings, GoogleWorkspaceFinalSettings)
    assert result.final_settings.model_dump(include=set(metadata)) == metadata
    assert result.final_settings.services == (GoogleService.CALENDAR,)
    assert result.final_settings.timeout == 19
    assert old == before
    assert (
        transform_google_final_settings(result.final_settings.model_dump(mode="json"))
        == result.final_settings
    )


def test_published_reconnect_has_no_manufactured_metadata_or_new_account_binding() -> (
    None
):
    old = {"tasks": ["drive_files"], "timeout": 11, "security_risk_acknowledged": True}
    result = transform_google_published_outcome(
        toolkit_id="existing-toolkit",
        connection_id="replaced-historical-connection",
        final_settings=old,
    )
    assert result.toolkit_id == "existing-toolkit"
    assert result.connection_id == "replaced-historical-connection"
    assert result.final_settings.services == (GoogleService.DRIVE,)
    assert result.final_settings.model_dump(mode="json") == {
        "services": ["drive"],
        "oauth_request_scopes": sorted(["openid", "email", _s("drive.file")]),
        "timeout": 11.0,
    }


@pytest.mark.parametrize(
    "toolkit_id,connection_id",
    [(None, "connection"), ("toolkit", None), ("", "connection"), ("toolkit", "")],
)
def test_incomplete_historical_publication_identity_aborts(
    toolkit_id: str | None, connection_id: str | None
) -> None:
    with pytest.raises(
        GoogleCutoverError, match="Incomplete published Google outcome identity"
    ):
        transform_google_published_outcome(
            toolkit_id=toolkit_id, connection_id=connection_id, final_settings={}
        )


def test_invalid_historical_metadata_does_not_silently_decode_as_reconnect() -> None:
    old = {
        "tasks": ["drive_files"],
        "timeout": 11,
        "security_risk_acknowledged": True,
        "name": "credential-canary",
    }
    with pytest.raises(GoogleCutoverError) as error:
        transform_google_final_settings(old)
    assert str(error.value) == "Invalid published Google settings for cutover."
