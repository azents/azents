"""Fail-closed authorization and bounded fail-open cleanup service evidence."""

import asyncio
import dataclasses
import datetime
import json
import logging
from unittest.mock import Mock, create_autospec
from urllib.parse import parse_qs, urlsplit

import pytest

from azents.core.config import Config
from azents.core.github_user_auth import (
    GitHubUserAccessPage,
    GitHubUserAppIdentity,
    GitHubUserIdentity,
    GitHubUserProviderError,
    GitHubUserToken,
    GitHubUserTokenRejected,
)
from azents.core.github_user_oauth import (
    GitHubUserAttempt,
    GitHubUserAttemptStatus,
    GitHubUserCandidate,
    GitHubUserConfirmResult,
    GitHubUserConnection,
    GitHubUserConnectionStatus,
    GitHubUserContext,
    GitHubUserErrorCode,
    GitHubUserOAuthError,
    GitHubUserRegistration,
    GitHubUserRequester,
    GitHubUserRevocation,
    GitHubUserStartResult,
)
from azents.core.system_setting import SystemSettingFieldSource
from azents.repos.github_user_oauth.operations import GitHubUserOAuthOperationRepository
from azents.repos.toolkit.data import ToolkitConfig
from azents.services.github_platform_system_setting.runtime import (
    PlatformGitHubAppRuntimeService,
    ResolvedPlatformGitHubApp,
)
from azents.services.github_user_oauth import service as service_module
from azents.services.github_user_oauth.provider import GitHubUserProvider
from azents.services.github_user_oauth.service import GitHubUserOAuthService


@dataclasses.dataclass
class _State:
    context: GitHubUserContext | None
    candidate: GitHubUserCandidate | None
    events: list[str]


@dataclasses.dataclass(frozen=True)
class _Harness:
    service: GitHubUserOAuthService
    repository: Mock
    provider: Mock
    platform: Mock
    state: _State
    requester: GitHubUserRequester
    registration: GitHubUserRegistration
    attempt: GitHubUserAttempt


def _harness(*, platform: bool = False, agent_id: str | None = None) -> _Harness:
    now = datetime.datetime.now(datetime.UTC)
    requester = GitHubUserRequester(
        user_id="manager",
        session_id="login",
        workspace_id="workspace",
        agent_id=agent_id,
        toolkit_id="toolkit",
    )
    registration = GitHubUserRegistration(
        source="platform_user" if platform else "byoa_user",
        app_id="123",
        client_id="client",
        client_secret="client-secret",
        toolkit_revision=1,
        platform_generation="generation" if platform else None,
    )
    credentials = {"type": "github_app_platform_user", "app_id": "123"}
    if not platform:
        credentials = {
            "type": "github_app_user",
            "app_id": "123",
            "private_key": "private-key",
            "client_id": "client",
            "client_secret": "client-secret",
        }
    toolkit = ToolkitConfig(
        id="toolkit",
        workspace_id="workspace",
        owner_agent_id=agent_id,
        toolkit_type="github",
        slug="github",
        name="GitHub",
        config={"github_auth_type": credentials["type"]},
        credentials=json.dumps(credentials),
        enabled=True,
        always_expose_tools=False,
        revision=1,
        created_at=now,
        updated_at=now,
    )
    active = GitHubUserConnection(
        id="old-connection",
        toolkit_id="toolkit",
        registration=dataclasses.replace(registration, client_secret=None),
        access_token="old-token",
        account_id=1,
        account_login="old-account",
        account_avatar_url=None,
        status=GitHubUserConnectionStatus.CONNECTED,
        failure_reason=None,
    )
    state = _State(GitHubUserContext(toolkit=toolkit, connection=active), None, [])
    attempt = GitHubUserAttempt(
        id="attempt",
        requester=requester,
        registration=registration,
        redirect_uri="https://app.test/oauth/github/callback",
        nonce="nonce",
        code_verifier="verifier",
        expires_at=now + datetime.timedelta(minutes=10),
        captured_connection_id="old-connection",
        status=GitHubUserAttemptStatus.EXCHANGING,
        candidate=None,
    )
    repository = create_autospec(GitHubUserOAuthOperationRepository, instance=True)
    provider = create_autospec(GitHubUserProvider, instance=True)
    runtime = create_autospec(PlatformGitHubAppRuntimeService, instance=True)

    async def read_context(*, requester: GitHubUserRequester) -> GitHubUserContext:
        assert requester == attempt.requester
        state.events.append("context:completed")
        if state.context is None:
            raise GitHubUserOAuthError(
                GitHubUserErrorCode.NOT_FOUND, "Toolkit removed."
            )
        return state.context

    async def store_review(
        *,
        requester: GitHubUserRequester,
        attempt_id: str,
        candidate: GitHubUserCandidate,
        registration: GitHubUserRegistration,
    ) -> GitHubUserAttempt:
        assert requester == attempt.requester and attempt_id == attempt.id
        assert registration == attempt.registration
        state.events.append("review:completed")
        state.candidate = candidate
        return dataclasses.replace(
            attempt, candidate=candidate, status=GitHubUserAttemptStatus.REVIEW
        )

    async def received_revocation(
        *,
        toolkit_id: str,
        registration: GitHubUserRegistration,
        access_token: str,
    ) -> GitHubUserRevocation | None:
        assert toolkit_id == "toolkit"
        current = state.context.connection if state.context is not None else None
        if current is not None and current.access_token == access_token:
            return None
        return GitHubUserRevocation(
            registration=registration, access_token=access_token
        )

    async def disconnect(
        *,
        requester: GitHubUserRequester,
        registration: GitHubUserRegistration | None,
    ) -> tuple[GitHubUserRevocation, ...]:
        assert state.context is not None
        current = state.context.connection
        state.context = dataclasses.replace(state.context, connection=None)
        state.events.append("disconnect:completed")
        if current is None:
            return ()
        return (
            GitHubUserRevocation(
                registration=registration
                if registration is not None
                else current.registration,
                access_token=current.access_token,
            ),
        )

    async def revoke(*, client_id: str, client_secret: str, token: str) -> None:
        assert client_id == "client" and client_secret == "client-secret"
        state.events.append("revoke:provider")

    repository.read_context.side_effect = read_context
    repository.claim_exchange.return_value = attempt
    repository.start.return_value = GitHubUserStartResult(
        attempt=attempt, revocations=()
    )
    repository.store_review.side_effect = store_review
    repository.received_revocation.side_effect = received_revocation
    repository.complete_failed_exchange.return_value = None
    repository.authorize_scope.return_value = None
    repository.disconnect.side_effect = disconnect
    repository.cancel.return_value = ()
    provider.exchange.return_value = GitHubUserToken(access_token="new-token")
    provider.identity.return_value = GitHubUserIdentity(
        account_id=2, login="new-account", avatar_url=None
    )
    provider.revoke.side_effect = revoke
    provider.app.return_value = GitHubUserAppIdentity(
        app_id=123, slug="selected-app", client_id="client"
    )
    runtime.resolve.return_value = ResolvedPlatformGitHubApp(
        app_id="123",
        client_id="client",
        client_secret="client-secret",
        private_key="private-key",
        app_id_source=SystemSettingFieldSource.ADMIN,
        effective_generation="generation",
    )
    service = GitHubUserOAuthService(
        repository=repository,
        config=Config.model_construct(web_url="https://app.test"),
        platform_runtime=runtime,
        provider=provider,
    )
    return _Harness(
        service, repository, provider, runtime, state, requester, registration, attempt
    )


def _revocation(h: _Harness, token: str) -> GitHubUserRevocation:
    return GitHubUserRevocation(registration=h.registration, access_token=token)


def _failure() -> GitHubUserProviderError:
    return GitHubUserProviderError(reason="provider_unavailable", status_code=503)


async def test_connect_has_pkce_fixed_callback_and_preserves_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _harness()
    monkeypatch.setattr(service_module, "create_github_app_jwt", lambda *args: "jwt")
    output = await h.service.connect(h.requester)
    params = parse_qs(urlsplit(output.authorization_url).query)
    assert params["redirect_uri"] == ["https://app.test/oauth/github/callback"]
    assert params["code_challenge_method"] == ["S256"]
    assert params["state"][0].startswith("github_user.attempt.")
    assert "scope" not in params
    assert (
        output.install_url == "https://github.com/apps/selected-app/installations/new"
    )
    assert h.state.context is not None and h.state.context.connection is not None
    assert h.state.context.connection.access_token == "old-token"


async def test_exchange_stages_verified_identity_without_activation() -> None:
    h = _harness(agent_id="agent")
    output = await h.service.exchange(
        h.requester, code="code", state="github_user.attempt.nonce"
    )
    assert output.account_id == 2 and output.sharing_scope == "agent_only"
    assert "new-token" not in output.model_dump_json()
    h.repository.confirm.assert_not_awaited()
    h.provider.revoke.assert_not_awaited()
    assert (
        h.state.candidate is not None and h.state.candidate.access_token == "new-token"
    )


@pytest.mark.parametrize("testenv_enabled", [False, True])
async def test_synthetic_browser_origin_requires_explicit_testenv(
    monkeypatch: pytest.MonkeyPatch, testenv_enabled: bool
) -> None:
    h = _harness()
    monkeypatch.setattr(service_module, "create_github_app_jwt", lambda *args: "jwt")
    service = dataclasses.replace(
        h.service,
        config=Config.model_construct(
            web_url="https://app.test",
            testenv_api_enabled=testenv_enabled,
            testenv_github_platform_validation_base_url="http://synthetic.test:8082",
        ),
    )
    output = await service.connect(h.requester)
    url = urlsplit(output.authorization_url)
    assert url.netloc == ("synthetic.test:8082" if testenv_enabled else "github.com")
    assert url.path == "/login/oauth/authorize"
    assert parse_qs(url.query)["redirect_uri"] == [
        "https://app.test/oauth/github/callback"
    ]


async def test_context_failure_never_calls_provider() -> None:
    h = _harness()
    h.repository.claim_exchange.side_effect = GitHubUserOAuthError(
        GitHubUserErrorCode.STALE, "Wrong session."
    )
    with pytest.raises(GitHubUserOAuthError):
        await h.service.exchange(
            h.requester, code="code", state="github_user.attempt.nonce"
        )
    h.provider.exchange.assert_not_awaited()


async def test_expiring_response_stays_rejected_when_cleanup_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    h = _harness()
    h.provider.exchange.side_effect = GitHubUserTokenRejected(
        reason="expiring_token", issued_token="expiring-token"
    )
    h.provider.revoke.side_effect = _failure()
    with (
        caplog.at_level(logging.WARNING),
        pytest.raises(GitHubUserOAuthError, match="expiring user token"),
    ):
        await h.service.exchange(
            h.requester, code="code", state="github_user.attempt.nonce"
        )
    h.provider.revoke.assert_awaited_once_with(
        client_id="client", client_secret="client-secret", token="expiring-token"
    )
    h.provider.identity.assert_not_awaited()
    assert "local completion is unchanged" in caplog.text
    assert "expiring-token" not in caplog.text and "client-secret" not in caplog.text
    assert h.state.context is not None and h.state.context.connection is not None
    assert h.state.context.connection.access_token == "old-token"


async def test_disconnect_failure_still_completes_locally_without_probe(
    caplog: pytest.LogCaptureFixture,
) -> None:
    h = _harness()
    h.provider.revoke.side_effect = _failure()
    with caplog.at_level(logging.WARNING):
        await h.service.disconnect(h.requester)
    assert h.state.context is not None and h.state.context.connection is None
    h.provider.revoke.assert_awaited_once()
    h.provider.identity.assert_not_awaited()
    assert "old-token" not in caplog.text and "client-secret" not in caplog.text
    assert "revocation attempt failed" in caplog.text
    assert "revoke:provider" not in h.state.events


async def test_replacement_failure_keeps_new_connection_and_old_cleanup_target() -> (
    None
):
    h = _harness()
    assert h.state.context is not None and h.state.context.connection is not None
    before = h.state.context.connection
    after = dataclasses.replace(before, id="new-connection", access_token="new-token")

    async def confirm(
        *,
        requester: GitHubUserRequester,
        attempt_id: str,
        registration: GitHubUserRegistration,
    ) -> GitHubUserConfirmResult:
        assert h.state.context is not None
        h.state.context = dataclasses.replace(h.state.context, connection=after)
        return GitHubUserConfirmResult(
            connection=after, revocations=(_revocation(h, "old-token"),)
        )

    h.repository.confirm.side_effect = confirm
    h.provider.revoke.side_effect = _failure()
    output = await h.service.confirm(h.requester, attempt_id="attempt")
    assert output.id == "new-connection"
    assert h.state.context.connection == after
    h.provider.revoke.assert_awaited_once_with(
        client_id="client", client_secret="client-secret", token="old-token"
    )
    h.provider.identity.assert_not_awaited()


async def test_successful_transfer_does_not_revoke_active_candidate() -> None:
    h = _harness()
    assert h.state.context is not None and h.state.context.connection is not None
    connection = dataclasses.replace(
        h.state.context.connection, id="new", access_token="new-token"
    )
    h.repository.confirm.return_value = GitHubUserConfirmResult(
        connection=connection, revocations=()
    )
    assert (await h.service.confirm(h.requester, attempt_id="attempt")).id == "new"
    h.provider.revoke.assert_not_awaited()


async def test_cancel_cleanup_failure_is_local_success() -> None:
    h = _harness()
    h.repository.cancel.return_value = (_revocation(h, "candidate-token"),)
    h.provider.revoke.side_effect = _failure()
    await h.service.cancel(h.requester, attempt_id="attempt")
    h.repository.cancel.assert_awaited_once_with(
        requester=h.requester, attempt_id="attempt"
    )
    h.provider.revoke.assert_awaited_once_with(
        client_id="client", client_secret="client-secret", token="candidate-token"
    )
    h.provider.identity.assert_not_awaited()


async def test_cleanup_is_awaited_and_bounded_without_background_work(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    h = _harness()
    entered = asyncio.Event()
    never_release = asyncio.Event()

    async def revoke(*, client_id: str, client_secret: str, token: str) -> None:
        entered.set()
        await never_release.wait()

    h.provider.revoke.side_effect = revoke
    assert service_module._REVOCATION_TIMEOUT_SECONDS == 5.0
    monkeypatch.setattr(service_module, "_REVOCATION_TIMEOUT_SECONDS", 0.01)
    with caplog.at_level(logging.WARNING):
        await h.service.cleanup_revocations((_revocation(h, "old-token"),))
    assert entered.is_set()
    assert any(record.__dict__.get("reason") == "timeout" for record in caplog.records)
    h.provider.revoke.assert_awaited_once()
    h.provider.identity.assert_not_awaited()


async def test_cleanup_programming_defect_remains_visible() -> None:
    h = _harness()
    h.provider.revoke.side_effect = RuntimeError("Unexpected defect.")
    with pytest.raises(RuntimeError, match="Unexpected defect"):
        await h.service.cleanup_revocations((_revocation(h, "old-token"),))
    h.provider.identity.assert_not_awaited()


async def test_cleanup_cancellation_propagates_without_later_io() -> None:
    h = _harness()
    h.provider.revoke.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await h.service.cleanup_revocations(
            (_revocation(h, "old-token"), _revocation(h, "second-token"))
        )
    h.provider.revoke.assert_awaited_once()
    h.provider.identity.assert_not_awaited()


async def test_missing_platform_registration_does_not_block_disconnect(
    caplog: pytest.LogCaptureFixture,
) -> None:
    h = _harness(platform=True)
    h.platform.resolve.return_value = ResolvedPlatformGitHubApp(
        app_id=None,
        client_id=None,
        private_key=None,
        client_secret=None,
        app_id_source=SystemSettingFieldSource.UNSET,
        effective_generation="absent",
    )
    with caplog.at_level(logging.WARNING):
        await h.service.disconnect(h.requester)
    assert h.state.context is not None and h.state.context.connection is None
    h.provider.revoke.assert_not_awaited()
    h.provider.identity.assert_not_awaited()
    assert "registration unavailable" in caplog.text


async def test_late_parent_removal_cannot_activate_and_uses_captured_cleanup() -> None:
    h = _harness()
    entered, release = asyncio.Event(), asyncio.Event()

    async def identity(token: str) -> GitHubUserIdentity:
        entered.set()
        await release.wait()
        return GitHubUserIdentity(account_id=2, login="new-account", avatar_url=None)

    h.provider.identity.side_effect = identity
    h.provider.revoke.side_effect = _failure()
    task = asyncio.create_task(
        h.service.exchange(h.requester, code="code", state="github_user.attempt.nonce")
    )
    await entered.wait()
    h.state.context = None
    release.set()
    with pytest.raises(GitHubUserOAuthError, match="Toolkit removed"):
        await task
    h.repository.store_review.assert_not_awaited()
    h.provider.revoke.assert_awaited_once_with(
        client_id="client", client_secret="client-secret", token="new-token"
    )


async def test_cancelled_exchange_is_not_shielded_or_finalized() -> None:
    h = _harness()
    entered, release = asyncio.Event(), asyncio.Event()

    async def identity(token: str) -> GitHubUserIdentity:
        entered.set()
        await release.wait()
        raise AssertionError("Cancelled identity must not finish.")

    h.provider.identity.side_effect = identity
    task = asyncio.create_task(
        h.service.exchange(h.requester, code="code", state="github_user.attempt.nonce")
    )
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    h.provider.revoke.assert_not_awaited()
    h.repository.store_review.assert_not_awaited()
    h.repository.complete_failed_exchange.assert_not_awaited()


async def test_received_token_equal_to_current_active_is_not_revoked() -> None:
    h = _harness()
    h.provider.exchange.side_effect = GitHubUserTokenRejected(
        reason="invalid_response", issued_token="old-token"
    )
    with pytest.raises(GitHubUserOAuthError):
        await h.service.exchange(
            h.requester, code="code", state="github_user.attempt.nonce"
        )
    h.provider.revoke.assert_not_awaited()


async def test_current_review_and_status_have_no_cleanup_contract() -> None:
    h = _harness()
    h.repository.read_review.return_value = dataclasses.replace(
        h.attempt,
        status=GitHubUserAttemptStatus.REVIEW,
        candidate=GitHubUserCandidate(
            access_token="candidate-token",
            account_id=2,
            account_login="candidate",
            account_avatar_url=None,
        ),
    )
    review = await h.service.review(h.requester, attempt_id="attempt")
    status = await h.service.status(h.requester)
    assert review.account_login == "candidate"
    assert "candidate-token" not in review.model_dump_json()
    assert "cleanup" not in status.model_dump_json()
    assert "old-token" not in status.model_dump_json()


async def test_scope_denial_precedes_availability_settings_read() -> None:
    h = _harness()
    h.repository.authorize_scope.side_effect = GitHubUserOAuthError(
        GitHubUserErrorCode.AUTHORITY, "Not a manager."
    )
    with pytest.raises(GitHubUserOAuthError):
        await h.service.availability(
            user_id="manager",
            session_id="login",
            workspace_id="workspace",
            agent_id=None,
        )
    h.platform.resolve.assert_not_awaited()


@pytest.mark.parametrize(
    "reason", ["authentication", "target_denied", "provider_unavailable"]
)
async def test_access_failures_preserve_account_classification(reason: str) -> None:
    h = _harness()
    if reason == "authentication":
        failure = GitHubUserProviderError(reason="authentication", status_code=401)
    elif reason == "target_denied":
        failure = GitHubUserProviderError(reason="target_denied", status_code=403)
    else:
        failure = _failure()
    h.provider.access.side_effect = failure
    with pytest.raises(GitHubUserProviderError):
        await h.service.access(h.requester, cursor=None)
    if reason == "authentication":
        h.repository.mark_reconnect_required.assert_awaited_once_with(
            requester=h.requester,
            connection_id="old-connection",
            reason="authentication_failed",
        )
    else:
        h.repository.mark_reconnect_required.assert_not_awaited()


async def test_extra_credential_token_is_rejected_without_disclosure() -> None:
    h = _harness()
    assert h.state.context is not None
    values = json.loads(h.state.context.toolkit.credentials or "null")
    values["access_token"] = "injected-secret-token"
    h.state.context = dataclasses.replace(
        h.state.context,
        toolkit=h.state.context.toolkit.model_copy(
            update={"credentials": json.dumps(values)}
        ),
    )
    with pytest.raises(GitHubUserOAuthError) as error:
        await h.service.access(h.requester, cursor=None)
    assert "injected-secret-token" not in str(error.value)
    assert error.value.__cause__ is None
    h.provider.access.assert_not_awaited()


async def test_invalid_local_cursor_remains_an_input_error() -> None:
    h = _harness()
    h.provider.access.side_effect = ValueError("Invalid cursor.")
    with pytest.raises(GitHubUserOAuthError) as error:
        await h.service.access(h.requester, cursor="bad")
    assert error.value.code is GitHubUserErrorCode.INVALID
    h.repository.mark_reconnect_required.assert_not_awaited()


async def test_access_returns_observations_not_new_authority() -> None:
    h = _harness()
    h.provider.access.return_value = GitHubUserAccessPage(
        installations=(), next_cursor="more"
    )
    assert (await h.service.access(h.requester, cursor=None)).next_cursor == "more"
    h.repository.confirm.assert_not_awaited()
