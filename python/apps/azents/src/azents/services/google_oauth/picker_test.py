"""Minimal receipt delivery is independent of the server-only main Google grant."""

import asyncio
import datetime
from typing import NamedTuple
from unittest.mock import Mock, create_autospec

import pytest

from azents.core.google_oauth import (
    GoogleConnection,
    GoogleConnectionStatus,
    GoogleOAuthError,
    GoogleSubject,
)
from azents.core.google_picker import GooglePickerState
from azents.core.google_policy import GoogleService
from azents.core.google_system_setting import (
    GoogleApplicationRegistration,
    GoogleApplicationUnavailable,
    GooglePickerApplication,
)
from azents.core.google_workspace_policy import GOOGLE_PICKER_SCOPE
from azents.core.tools import GoogleToolkitConfig
from azents.repos.google_oauth.management import GoogleOAuthRepository
from azents.repos.google_oauth.management_test import _candidate
from azents.services.google_application.service import GoogleApplicationService
from azents.services.google_oauth.data import GooglePickerTokenInput
from azents.services.google_oauth.picker import GooglePickerService
from azents.services.google_oauth.provider import (
    GoogleOAuthProvider,
    GoogleTokenResponse,
)


class Harness(NamedTuple):
    service: GooglePickerService
    repo: Mock
    provider: Mock
    application: Mock
    snapshot: GooglePickerState
    expected: GooglePickerTokenInput


def _harness() -> Harness:
    repo = create_autospec(GoogleOAuthRepository, instance=True)
    provider = create_autospec(GoogleOAuthProvider, instance=True)
    application = create_autospec(GoogleApplicationService, instance=True)
    candidate = _candidate("MAIN-ACCESS-CANARY")
    candidate = candidate.model_copy(
        update={
            "tokens": candidate.tokens.model_copy(
                update={
                    "granted_scopes": (
                        GOOGLE_PICKER_SCOPE,
                        "https://www.googleapis.com/auth/drive.readonly",
                        "https://www.googleapis.com/auth/gmail.readonly",
                    )
                }
            )
        }
    )
    operator = GooglePickerApplication(
        GoogleApplicationRegistration(
            "client",
            "SERVER-SECRET-CANARY",
            "generation",
            "https://app.invalid/callback",
        ),
        "BROWSER-KEY",
        "123456789",
    )
    snapshot = GooglePickerState(
        GoogleSubject("manager", "login", "workspace", None),
        "toolkit",
        3,
        GoogleToolkitConfig(
            services=(GoogleService.DRIVE, GoogleService.GMAIL),
            oauth_request_scopes=(GOOGLE_PICKER_SCOPE,),
            timeout=30.0,
        ),
        GoogleConnection(
            "connection",
            "toolkit",
            "client",
            candidate,
            GoogleConnectionStatus.CONNECTED,
            datetime.datetime.now(datetime.UTC),
            "encrypted-main",
        ),
        operator,
    )
    repo.admit_picker.return_value = snapshot
    application.picker.return_value = operator
    provider.refresh_picker.return_value = GoogleTokenResponse.model_validate(
        {
            "access_token": "PICKER-ACCESS-CANARY",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": GOOGLE_PICKER_SCOPE,
        }
    )
    return Harness(
        GooglePickerService(repo, application, provider),
        repo,
        provider,
        application,
        snapshot,
        GooglePickerTokenInput(expected_revision=3, connection_id="connection"),
    )


async def test_only_minimal_scoped_receipt_reaches_browser() -> None:
    h = _harness()
    output = await h.service.issue(h.snapshot.subject, "toolkit", h.expected)
    assert output.access_token == "PICKER-ACCESS-CANARY"
    assert output.api_key == "BROWSER-KEY" and output.app_id == "123456789"
    h.repo.finalize_picker.assert_awaited_once_with(
        h.snapshot, rotated_refresh=None, rejected=False
    )
    h.provider.refresh_picker.assert_awaited_once_with(
        h.snapshot.application.registration,
        h.snapshot.connection.candidate.tokens.refresh_token,
    )
    rendered = output.model_dump_json()
    assert all(
        value not in rendered
        for value in (
            "MAIN-ACCESS-CANARY",
            "renew-MAIN-ACCESS-CANARY",
            "SERVER-SECRET-CANARY",
            "gmail.readonly",
        )
    )
    assert "PICKER-ACCESS-CANARY" not in repr(output)


@pytest.mark.parametrize(
    "scope",
    [
        None,
        "",
        "https://www.googleapis.com/auth/drive",
        GOOGLE_PICKER_SCOPE + " openid",
    ],
)
async def test_unknown_empty_or_wider_scope_is_never_delivered(
    scope: str | None,
) -> None:
    h = _harness()
    payload: dict[str, object] = {
        "access_token": "PICKER-ACCESS-CANARY",
        "token_type": "Bearer",
        "expires_in": 3600,
    }
    if scope is not None:
        payload["scope"] = scope
    h.provider.refresh_picker.return_value = GoogleTokenResponse.model_validate(payload)
    with pytest.raises(GoogleOAuthError) as error:
        await h.service.issue(h.snapshot.subject, "toolkit", h.expected)
    assert error.value.code == "picker_scope_unverified"
    assert "PICKER-ACCESS-CANARY" not in str(error.value)
    h.repo.finalize_picker.assert_awaited_once_with(
        h.snapshot, rotated_refresh=None, rejected=False
    )


async def test_missing_explicit_bearer_evidence_is_not_an_sdk_default() -> None:
    h = _harness()
    h.provider.refresh_picker.return_value = GoogleTokenResponse.model_validate(
        {
            "access_token": "PICKER-ACCESS-CANARY",
            "expires_in": 3600,
            "scope": GOOGLE_PICKER_SCOPE,
        }
    )
    with pytest.raises(GoogleOAuthError) as error:
        await h.service.issue(h.snapshot.subject, "toolkit", h.expected)
    assert error.value.code == "picker_scope_unverified"


async def test_unusable_expiry_returns_no_credential() -> None:
    h = _harness()
    h.provider.refresh_picker.return_value = GoogleTokenResponse.model_validate(
        {
            "access_token": "PICKER-ACCESS-CANARY",
            "token_type": "Bearer",
            "expires_in": 1,
            "scope": GOOGLE_PICKER_SCOPE,
        }
    )
    with pytest.raises(GoogleOAuthError) as error:
        await h.service.issue(h.snapshot.subject, "toolkit", h.expected)
    assert error.value.code == "picker_token_unusable"


@pytest.mark.parametrize(
    "scope", [GOOGLE_PICKER_SCOPE, "https://www.googleapis.com/auth/drive"]
)
async def test_observed_rotation_is_preserved_without_browser_delivery(
    scope: str,
) -> None:
    h = _harness()
    h.provider.refresh_picker.return_value = GoogleTokenResponse.model_validate(
        {
            "access_token": "PICKER-ACCESS-CANARY",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": scope,
            "refresh_token": "ROTATED-REFRESH-CANARY",
        }
    )
    original = h.snapshot.connection.candidate.model_dump_json()
    with pytest.raises(GoogleOAuthError) as error:
        await h.service.issue(h.snapshot.subject, "toolkit", h.expected)
    assert error.value.code == "reconnect_required"
    h.repo.finalize_picker.assert_awaited_once_with(
        h.snapshot, rotated_refresh="ROTATED-REFRESH-CANARY", rejected=False
    )
    assert h.snapshot.connection.candidate.model_dump_json() == original
    assert "ROTATED-REFRESH-CANARY" not in str(error.value)


async def test_post_io_authority_loss_blocks_delivery_without_replay() -> None:
    h = _harness()
    h.repo.finalize_picker.side_effect = GoogleOAuthError(
        "stale", "Current target changed."
    )
    with pytest.raises(GoogleOAuthError) as error:
        await h.service.issue(h.snapshot.subject, "toolkit", h.expected)
    assert error.value.code == "stale"
    h.provider.refresh_picker.assert_awaited_once()


async def test_manager_authorization_precedes_operator_preparation() -> None:
    h = _harness()
    h.repo.authorize.side_effect = GoogleOAuthError(
        "forbidden", "No manager authority."
    )
    with pytest.raises(GoogleOAuthError):
        await h.service.issue(h.snapshot.subject, "toolkit", h.expected)
    h.application.picker.assert_not_awaited()
    h.provider.refresh_picker.assert_not_awaited()


async def test_current_grant_denial_precedes_any_provider_request() -> None:
    h = _harness()
    h.repo.admit_picker.side_effect = GoogleOAuthError(
        "picker_scope_required", "Reconnect with app-file scope."
    )
    with pytest.raises(GoogleOAuthError):
        await h.service.issue(h.snapshot.subject, "toolkit", h.expected)
    h.provider.refresh_picker.assert_not_awaited()


async def test_missing_picker_preparation_does_not_request_credentials() -> None:
    h = _harness()
    h.application.picker.side_effect = GoogleApplicationUnavailable(
        "Missing Picker fields."
    )
    with pytest.raises(GoogleOAuthError) as error:
        await h.service.issue(h.snapshot.subject, "toolkit", h.expected)
    assert error.value.code == "picker_setup_required"
    h.repo.authorize.assert_awaited_once()
    h.repo.admit_picker.assert_not_awaited()
    h.provider.refresh_picker.assert_not_awaited()


@pytest.mark.parametrize(
    "code", ["invalid_grant", "invalid_client", "provider_unavailable"]
)
async def test_only_matching_definitive_rejection_requests_invalidation(
    code: str,
) -> None:
    h = _harness()
    h.provider.refresh_picker.side_effect = GoogleOAuthError(
        code, "Redacted provider failure."
    )
    with pytest.raises(GoogleOAuthError) as error:
        await h.service.issue(h.snapshot.subject, "toolkit", h.expected)
    if code == "provider_unavailable":
        assert error.value.code == code
        h.repo.finalize_picker.assert_not_awaited()
    else:
        assert error.value.code == "reconnect_required"
        h.repo.finalize_picker.assert_awaited_once_with(
            h.snapshot, rotated_refresh=None, rejected=True
        )
    h.provider.refresh_picker.assert_awaited_once()


async def test_cancelled_picker_request_does_not_finalize_or_replay() -> None:
    h = _harness()
    h.provider.refresh_picker.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await h.service.issue(h.snapshot.subject, "toolkit", h.expected)
    h.repo.finalize_picker.assert_not_awaited()
    h.provider.refresh_picker.assert_awaited_once()
