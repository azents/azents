"""Callback isolation, grant projections and no credential exposure in management."""

import dataclasses
import datetime
from typing import NamedTuple
from unittest.mock import Mock, create_autospec

import pytest
from cryptography.fernet import Fernet

from azents.core.crypto import CredentialCipher
from azents.core.google_oauth import (
    GoogleAttempt,
    GoogleAttemptStatus,
    GoogleCandidate,
    GoogleConnection,
    GoogleConnectionStatus,
    GoogleIdentity,
    GoogleOAuthError,
    GooglePersonalSubject,
    GooglePublication,
    GoogleSavedConnection,
    GoogleSetup,
    GoogleSubject,
)
from azents.core.google_policy import GoogleService, GoogleToolGroup
from azents.core.google_system_setting import GoogleApplicationRegistration
from azents.core.google_tool_groups import groups_for_services
from azents.core.google_workspace_policy import GoogleWorkspaceOperation as Op
from azents.core.toolkit_ownership import ToolkitOwnerKind, UserToolkitOwner
from azents.repos.google_oauth.management import GoogleOAuthRepository
from azents.repos.google_oauth.management_test import _settings
from azents.services.google_application.service import GoogleApplicationService
from azents.services.google_oauth.data import (
    GoogleConnectInput,
    GoogleServicesUpdateInput,
)
from azents.services.google_oauth.provider import (
    GoogleOAuthProvider,
    GoogleTokenResponse,
)
from azents.services.google_oauth.service import (
    GoogleOAuthService,
    _CallbackState,
    _PersonalCallbackState,
)


class Harness(NamedTuple):
    service: GoogleOAuthService
    repo: Mock
    provider: Mock
    application: Mock
    subject: GoogleSubject
    attempt: GoogleAttempt
    state: str


def _harness(
    *, scope: str | None = "https://www.googleapis.com/auth/calendar.events.readonly"
) -> Harness:
    repo = create_autospec(GoogleOAuthRepository, instance=True)
    app = create_autospec(GoogleApplicationService, instance=True)
    provider = create_autospec(GoogleOAuthProvider, instance=True)
    cipher = CredentialCipher(Fernet.generate_key().decode())
    registration = GoogleApplicationRegistration(
        "client",
        "OPERATOR-SECRET",
        "generation",
        "https://app.invalid/oauth/google/callback",
    )
    app.resolve.return_value = registration
    subject = GoogleSubject("manager", "login", "workspace", None)
    setup = GoogleSetup(
        client_id="client",
        effective_generation="generation",
        redirect_uri=registration.redirect_uri,
        state_nonce="state",
        oidc_nonce="oidc",
        code_verifier="pkce",
        services=(GoogleService.CALENDAR, GoogleService.GMAIL),
        oauth_request_scopes=(
            "https://www.googleapis.com/auth/calendar.events.readonly",
            "https://www.googleapis.com/auth/gmail.readonly",
        ),
        timeout=30.0,
        target=None,
        tool_groups=groups_for_services((GoogleService.CALENDAR, GoogleService.GMAIL)),
    )
    receipt_payload: dict[str, object] = {
        "access_token": "ACCESS-SECRET",
        "refresh_token": "RENEWAL-SECRET",
        "expires_in": 3600,
        "id_token": "SIGNED-IDENTITY",
    }
    if scope is not None:
        receipt_payload["scope"] = scope
    receipt = GoogleTokenResponse.model_validate(receipt_payload)
    identity = GoogleIdentity(
        issuer="https://accounts.google.com",
        subject="subject",
        email="test@example.invalid",
    )
    attempt = GoogleAttempt(
        id="attempt",
        subject=subject,
        status=GoogleAttemptStatus.EXCHANGING,
        expires_at=datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=10),
        setup=setup,
        candidate=None,
        published_toolkit_id=None,
        published_connection_id=None,
        final_settings=None,
    )
    repo.claim.return_value = attempt
    provider.exchange.return_value = receipt
    provider.identity.return_value = identity
    repo.stage.return_value = dataclasses.replace(
        attempt,
        status=GoogleAttemptStatus.REVIEW,
        candidate=GoogleCandidate(
            identity=identity,
            tokens=receipt.tokens(),
            requested_scopes=("requested",),
        ),
    )
    state = cipher.encrypt(
        _CallbackState(
            purpose="google_connection",
            attempt_id="attempt",
            user_id=subject.user_id,
            session_id=subject.session_id,
            workspace_id=subject.workspace_id,
            agent_id=subject.agent_id,
            nonce="state",
        ).model_dump_json()
    )
    return Harness(
        GoogleOAuthService(repo, app, provider, cipher),
        repo,
        provider,
        app,
        subject,
        attempt,
        state,
    )


async def test_all_off_save_remains_connected_without_provider_io() -> None:
    h = _harness()
    candidate = h.repo.stage.return_value.candidate
    assert isinstance(candidate, GoogleCandidate)
    connection = GoogleConnection(
        "connection",
        "toolkit",
        "client",
        candidate,
        GoogleConnectionStatus.CONNECTED,
        datetime.datetime.now(datetime.UTC),
        "encrypted-current",
    )
    h.repo.saved.return_value = GoogleSavedConnection(
        "toolkit",
        8,
        (),
        (),
        ("https://www.googleapis.com/auth/calendar.events.readonly",),
        30.0,
        connection,
    )
    result = await h.service.update_services(
        h.subject,
        "toolkit",
        GoogleServicesUpdateInput(
            expected_revision=7,
            services=(),
            tool_groups=groups_for_services(("calendar", "drive", "gmail")),
        ),
    )
    assert result.status == "connected" and result.services == ()
    assert result.connection_id == connection.id and result.revision == 8
    assert result.identity == candidate.identity and result.renewable
    assert all(item.status == "disabled" for item in result.accesses)
    h.repo.update_services.assert_awaited_once_with(
        h.subject,
        toolkit_id="toolkit",
        expected_revision=7,
        services=(),
        tool_groups=groups_for_services(("calendar", "drive", "gmail")),
    )
    h.provider.refresh.assert_not_awaited()
    h.provider.exchange.assert_not_awaited()


async def test_broader_receipt_exposes_actual_tools_outside_requested_intent() -> None:
    h = _harness(scope="https://www.googleapis.com/auth/calendar")
    result = await h.service.exchange(h.subject, code="CODE-SECRET", state=h.state)
    calendar = next(
        item for item in result.accesses if item.service is GoogleService.CALENDAR
    )
    assert Op.CALENDAR_CREATE_EVENT in calendar.permitted_tools
    assert result.can_confirm and result.granted_scopes == (
        "https://www.googleapis.com/auth/calendar",
    )


async def test_gmail_scope_receipt_difference_does_not_imply_read_or_send_denial() -> (
    None
):
    h = _harness(scope="https://www.googleapis.com/auth/gmail.modify")
    setup = h.attempt.setup
    assert setup is not None
    setup = setup.model_copy(
        update={
            "services": (GoogleService.GMAIL,),
            "oauth_request_scopes": (
                "openid",
                "email",
                "https://www.googleapis.com/auth/gmail.readonly",
            ),
            "tool_groups": [
                item.value for item in groups_for_services((GoogleService.GMAIL,))
            ],
        }
    )
    h.repo.claim.return_value = dataclasses.replace(h.attempt, setup=setup)
    staged = h.repo.stage.return_value
    assert isinstance(staged, GoogleAttempt)
    h.repo.stage.return_value = dataclasses.replace(staged, setup=setup)
    result = await h.service.exchange(h.subject, code="CODE-SECRET", state=h.state)
    gmail = next(
        item for item in result.accesses if item.service is GoogleService.GMAIL
    )
    assert result.grant_result == "partial"
    assert result.can_confirm
    assert result.granted_scopes == ("https://www.googleapis.com/auth/gmail.modify",)
    assert Op.GMAIL_GET_MESSAGE in gmail.permitted_tools
    assert Op.GMAIL_SEND_MESSAGE in gmail.permitted_tools


async def test_personal_callback_is_distinct_and_returns_same_grant_review() -> None:
    h = _harness()
    personal = GooglePersonalSubject(
        h.subject.user_id,
        h.subject.session_id,
        UserToolkitOwner(
            kind=ToolkitOwnerKind.USER,
            user_id=h.subject.user_id,
            workspace_id=h.subject.workspace_id,
        ),
    )
    attempt = dataclasses.replace(h.attempt, subject=personal)
    h.repo.claim.return_value = attempt
    h.repo.stage.return_value = dataclasses.replace(
        h.repo.stage.return_value, subject=personal
    )
    state = h.service.cipher.encrypt(
        _PersonalCallbackState(
            purpose="google_personal_connection",
            attempt_id=attempt.id,
            user_id=personal.user_id,
            session_id=personal.session_id,
            owner=personal.owner,
            nonce="state",
        ).model_dump_json()
    )
    review = await h.service.exchange(personal, code="CODE-SECRET", state=state)
    assert review.ownership == "personal" and review.can_confirm
    assert "ACCESS-SECRET" not in review.model_dump_json()
    assert "RENEWAL-SECRET" not in review.model_dump_json()
    with pytest.raises(GoogleOAuthError, match="invalid"):
        await h.service.exchange(h.subject, code="CODE-SECRET", state=state)
    with pytest.raises(GoogleOAuthError, match="invalid"):
        await h.service.exchange(personal, code="CODE-SECRET", state=h.state)
    h.provider.exchange.assert_awaited_once()


async def test_personal_callback_rejects_foreign_auth_session_before_provider() -> None:
    h = _harness()
    personal = GooglePersonalSubject(
        h.subject.user_id,
        h.subject.session_id,
        UserToolkitOwner(
            kind=ToolkitOwnerKind.USER,
            user_id=h.subject.user_id,
            workspace_id=h.subject.workspace_id,
        ),
    )
    state = h.service.cipher.encrypt(
        _PersonalCallbackState(
            purpose="google_personal_connection",
            attempt_id=h.attempt.id,
            user_id=personal.user_id,
            session_id=personal.session_id,
            owner=personal.owner,
            nonce="state",
        ).model_dump_json()
    )
    with pytest.raises(GoogleOAuthError, match="context"):
        await h.service.exchange(
            dataclasses.replace(personal, session_id="different-login"),
            code="CODE-SECRET",
            state=state,
        )
    h.provider.exchange.assert_not_awaited()
    h.repo.claim.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["user_id", "session_id", "workspace_id", "agent_id"])
async def test_callback_requires_exact_context_before_provider_io(field: str) -> None:
    h = _harness()
    wrong = dataclasses.replace(h.subject, **{field: "other"})
    with pytest.raises(GoogleOAuthError) as caught:
        await h.service.exchange(wrong, code="CODE-SECRET", state=h.state)
    assert caught.value.code == "invalid_state"
    h.repo.claim.assert_not_awaited()
    h.provider.exchange.assert_not_awaited()


@pytest.mark.asyncio
async def test_tampered_state_fails_without_plaintext_diagnostics() -> None:
    h = _harness()
    with pytest.raises(GoogleOAuthError) as caught:
        await h.service.exchange(h.subject, code="CODE-SECRET", state="broken")
    assert "CODE-SECRET" not in str(caught.value)
    h.provider.exchange.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scope,result,can_confirm",
    [
        (None, "unknown", False),
        ("", "none", False),
        ("https://www.googleapis.com/auth/calendar.events.readonly", "partial", True),
        (
            "https://www.googleapis.com/auth/calendar.events.readonly https://www.googleapis.com/auth/gmail.readonly",
            "full",
            True,
        ),
    ],
)
async def test_grants_have_truthful_redacted_review(
    scope: str | None,
    result: str,
    can_confirm: bool,
) -> None:
    h = _harness(scope=scope)
    reviewed = await h.service.exchange(h.subject, code="CODE-SECRET", state=h.state)
    assert reviewed.grant_result == result and reviewed.can_confirm is can_confirm
    assert not reviewed.service_access_verified
    rendered = reviewed.model_dump_json()
    for secret in (
        "CODE-SECRET",
        "ACCESS-SECRET",
        "RENEWAL-SECRET",
        "SIGNED-IDENTITY",
        "OPERATOR-SECRET",
        "pkce",
    ):
        assert secret not in rendered
    h.repo.claim.assert_awaited_once()
    h.repo.stage.assert_awaited_once()
    h.repo.confirm.assert_not_awaited()


@pytest.mark.asyncio
async def test_setting_rotation_during_exchange_discards_candidate() -> None:
    h = _harness()
    current = h.application.resolve.return_value
    h.application.resolve.side_effect = [
        current,
        dataclasses.replace(current, effective_generation="rotated"),
    ]
    with pytest.raises(GoogleOAuthError) as caught:
        await h.service.exchange(h.subject, code="code", state=h.state)
    assert caught.value.code == "stale"
    h.repo.stage.assert_not_awaited()
    h.repo.discard_claimed.assert_awaited_once_with("attempt")


@pytest.mark.asyncio
async def test_historical_confirm_does_not_require_current_client_secret() -> None:
    h = _harness()
    h.repo.load.return_value = dataclasses.replace(
        h.attempt,
        setup=None,
        status=GoogleAttemptStatus.PUBLISHED,
        published_toolkit_id="toolkit",
        published_connection_id="old-connection",
        final_settings=_settings(),
    )
    h.repo.confirm.return_value = GooglePublication("toolkit", "old-connection", False)
    result = await h.service.confirm(
        h.subject, attempt_id="attempt", settings=_settings()
    )
    assert not result.current
    h.application.resolve.assert_not_awaited()
    assert h.repo.confirm.call_args.kwargs["registration"] is None


@pytest.mark.asyncio
async def test_start_returns_ciphertext_and_distinct_oidc_nonce() -> None:
    h = _harness()
    captured: list[GoogleSetup] = []

    async def start(
        subject: GoogleSubject,
        *,
        registration: GoogleApplicationRegistration,
        setup: GoogleSetup,
        target_toolkit_id: str | None,
    ) -> GoogleAttempt:
        captured.append(setup)
        return dataclasses.replace(
            h.attempt, setup=setup, status=GoogleAttemptStatus.PENDING
        )

    h.repo.start.side_effect = start
    h.provider.authorization_url.return_value = "https://accounts.google.com/authorize"
    await h.service.connect(
        h.subject,
        GoogleConnectInput(
            services=(GoogleService.CALENDAR,),
            oauth_request_scopes=(
                "https://www.googleapis.com/auth/calendar.events.readonly",
            ),
            timeout=30.0,
            tool_groups=groups_for_services((GoogleService.CALENDAR,)),
        ),
        target_toolkit_id=None,
    )
    encrypted = h.provider.authorization_url.call_args.args[1]
    assert h.subject.session_id not in encrypted
    decoded = h.service._state(h.subject, encrypted)
    assert decoded.nonce == captured[0].state_nonce
    assert decoded.nonce != captured[0].oidc_nonce


@pytest.mark.parametrize("target", [None, "existing-toolkit"])
async def test_connect_and_reconnect_request_whole_drive_read_with_app_file_writes(
    target: str | None,
) -> None:
    h = _harness()
    h.repo.start.return_value = dataclasses.replace(
        h.attempt, status=GoogleAttemptStatus.PENDING
    )
    h.provider.authorization_url.return_value = "https://accounts.google.com/authorize"
    await h.service.connect(
        h.subject,
        GoogleConnectInput(
            services=(GoogleService.DRIVE,),
            tool_groups=(GoogleToolGroup.DRIVE_READ, GoogleToolGroup.DRIVE_FILES),
            # The caller's old app-file-only intent is not scope authority.
            oauth_request_scopes=("https://www.googleapis.com/auth/drive.file",),
            timeout=30.0,
        ),
        target_toolkit_id=target,
    )
    setup = h.repo.start.call_args.kwargs["setup"]
    assert set(setup.oauth_request_scopes) == {
        "openid",
        "email",
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/drive.file",
    }
    assert h.repo.start.call_args.kwargs["target_toolkit_id"] == target
    sent_setup = h.provider.authorization_url.call_args.args[0]
    assert sent_setup.oauth_request_scopes == setup.oauth_request_scopes
    h.provider.exchange.assert_not_awaited()
    h.provider.refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_disconnected_status_has_no_identity_or_google_network_call() -> None:
    h = _harness()
    h.repo.saved.return_value = GoogleSavedConnection(
        "toolkit",
        1,
        (GoogleService.CALENDAR,),
        groups_for_services((GoogleService.CALENDAR,)),
        ("https://www.googleapis.com/auth/calendar.events.readonly",),
        30.0,
        None,
    )
    output = await h.service.status(h.subject, "toolkit")
    assert output.status == "not_connected"
    assert output.identity is None and not output.renewable
    assert not output.service_access_verified
    h.provider.refresh.assert_not_awaited()
    h.application.resolve.assert_not_awaited()
