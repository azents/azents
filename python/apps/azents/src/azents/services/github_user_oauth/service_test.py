"""Completed-operation service evidence, separate from repository atomicity tests."""

import asyncio
import dataclasses
import datetime
import json
from typing import NoReturn
from unittest.mock import Mock, create_autospec
from urllib.parse import parse_qs, urlsplit

import httpx
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
    GitHubUserCleanup,
    GitHubUserCleanupStatus,
    GitHubUserConnection,
    GitHubUserConnectionStatus,
    GitHubUserContext,
    GitHubUserErrorCode,
    GitHubUserOAuthError,
    GitHubUserRegistration,
    GitHubUserRequester,
)
from azents.core.system_setting import SystemSettingFieldSource
from azents.repos.github_user_oauth.operations import GitHubUserOAuthOperationRepository
from azents.repos.toolkit.data import ToolkitConfig
from azents.services.github_platform_system_setting.runtime import (
    PlatformGitHubAppRuntimeService,
    ResolvedPlatformGitHubApp,
)
from azents.services.github_user_oauth import service as service_module
from azents.services.github_user_oauth.exchange_owner import GitHubUserExchangeOwner
from azents.services.github_user_oauth.provider import GitHubUserProvider
from azents.services.github_user_oauth.service import GitHubUserOAuthService


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing collaborator fake cannot issue live provider traffic."""

    def reject(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("No provider network is authorized in service tests.")

    monkeypatch.setattr(httpx, "AsyncClient", reject)


@dataclasses.dataclass
class _State:
    context: GitHubUserContext
    retired: list[GitHubUserCleanup]
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
        registration=registration,
        access_token="old-token",
        account_id=1,
        account_login="old-account",
        account_avatar_url=None,
        status=GitHubUserConnectionStatus.CONNECTED,
        failure_reason=None,
    )
    state = _State(
        GitHubUserContext(toolkit=toolkit, connection=active, cleanup_pending=False),
        [],
        [],
    )
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
        return state.context

    async def list_cleanup(
        *, requester: GitHubUserRequester
    ) -> tuple[GitHubUserCleanup, ...]:
        assert requester == attempt.requester
        state.events.append("cleanup-read:completed")
        return tuple(state.retired)

    async def finish_retired(*, cleanup_id: str) -> None:
        state.events.append("cleanup-finish:completed")
        state.retired[:] = [row for row in state.retired if row.id != cleanup_id]

    async def retire_exchange_result(
        *,
        attempt_id: str,
        registration: GitHubUserRegistration,
        access_token: str,
        reason: str,
    ) -> GitHubUserCleanup:
        assert attempt_id == attempt.id
        cleanup = GitHubUserCleanup(
            id="cleanup",
            toolkit_id="toolkit",
            registration=registration,
            access_token=access_token,
            reason=reason,
            status=GitHubUserCleanupStatus.PENDING,
            failure_reason=None,
        )
        state.retired.append(cleanup)
        state.events.append("retire:completed")
        return cleanup

    async def record_exchange_token(
        *,
        attempt_id: str,
        registration: GitHubUserRegistration,
        access_token: str,
    ) -> GitHubUserCleanup | None:
        assert attempt_id == attempt.id and registration == attempt.registration
        assert access_token == "new-token"
        state.events.append("issued-token:completed")
        return None

    async def identity(token: str) -> GitHubUserIdentity:
        if token == "old-token":
            state.events.append("cleanup-identity:provider")
            return GitHubUserIdentity(
                account_id=1, login="old-account", avatar_url=None
            )
        assert token == "new-token"
        assert "issued-token:completed" in state.events
        state.events.append("identity:provider")
        return GitHubUserIdentity(account_id=2, login="new-account", avatar_url=None)

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
        return dataclasses.replace(
            attempt, candidate=candidate, status=GitHubUserAttemptStatus.REVIEW
        )

    async def revoke(*, client_id: str, client_secret: str, token: str) -> None:
        assert client_id == "client" and client_secret == "client-secret"
        state.events.append("revoke:provider")
        assert any(row.access_token == token for row in state.retired)

    repository.read_context.side_effect = read_context
    repository.list_cleanup.side_effect = list_cleanup
    repository.finish_retired.side_effect = finish_retired
    repository.retire_exchange_result.side_effect = retire_exchange_result
    repository.record_exchange_token.side_effect = record_exchange_token
    repository.claim_exchange.return_value = attempt
    repository.store_review.side_effect = store_review
    repository.complete_failed_exchange.return_value = None
    repository.authorize_scope.return_value = None
    repository.mark_retired_failure.return_value = None
    provider.exchange.return_value = GitHubUserToken(access_token="new-token")
    provider.identity.side_effect = identity
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
        exchange_owner=GitHubUserExchangeOwner(),
    )
    return _Harness(
        service, repository, provider, runtime, state, requester, registration, attempt
    )


def _cleanup(harness: _Harness, *, token: str = "old-token") -> GitHubUserCleanup:
    return GitHubUserCleanup(
        id="cleanup",
        toolkit_id="toolkit",
        registration=harness.registration,
        access_token=token,
        reason="disconnected",
        status=GitHubUserCleanupStatus.PENDING,
        failure_reason=None,
    )


async def test_connect_validates_app_and_reserves_fixed_callback_pkce_without_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _harness()
    monkeypatch.setattr(service_module, "create_github_app_jwt", lambda *args: "jwt")
    harness.repository.start.return_value = harness.attempt
    output = await harness.service.connect(harness.requester)
    params = parse_qs(urlsplit(output.authorization_url).query)
    assert params["client_id"] == ["client"]
    assert params["redirect_uri"] == ["https://app.test/oauth/github/callback"]
    assert params["code_challenge_method"] == ["S256"]
    assert "scope" not in params
    assert params["state"][0].startswith("github_user.attempt.")
    assert (
        output.install_url == "https://github.com/apps/selected-app/installations/new"
    )
    assert harness.state.context.connection is not None
    assert harness.state.context.connection.access_token == "old-token"
    harness.repository.confirm.assert_not_awaited()


async def test_exchange_records_token_before_identity_without_activation() -> None:
    harness = _harness(agent_id="agent")
    output = await harness.service.exchange(
        harness.requester, code="code", state="github_user.attempt.nonce"
    )
    assert output.account_id == 2 and output.sharing_scope == "agent_only"
    assert "new-token" not in output.model_dump_json()
    assert "client-secret" not in output.model_dump_json()
    assert harness.state.events.index(
        "issued-token:completed"
    ) < harness.state.events.index("identity:provider")
    harness.repository.confirm.assert_not_awaited()
    harness.provider.revoke.assert_not_awaited()


async def test_expiring_rejection_revokes_issued_token_and_preserves_active() -> None:
    harness = _harness()
    harness.provider.exchange.side_effect = GitHubUserTokenRejected(
        reason="expiring_token", issued_token="issued-expiring"
    )
    with pytest.raises(GitHubUserOAuthError, match="Disable user-to-server"):
        await harness.service.exchange(
            harness.requester, code="code", state="github_user.attempt.nonce"
        )
    harness.provider.revoke.assert_awaited_once_with(
        client_id="client", client_secret="client-secret", token="issued-expiring"
    )
    assert harness.state.retired == []
    assert harness.state.context.connection is not None
    assert harness.state.context.connection.access_token == "old-token"
    harness.provider.identity.assert_not_awaited()


async def test_cleanup_failure_retains_token_nonexecutable_and_surfaces_failure() -> (
    None
):
    harness = _harness()
    harness.state.retired.append(_cleanup(harness))
    harness.provider.revoke.side_effect = GitHubUserProviderError(
        reason="provider_unavailable", status_code=None
    )
    with pytest.raises(GitHubUserOAuthError) as error:
        await harness.service.cleanup_retry(harness.requester)
    assert error.value.code is GitHubUserErrorCode.CLEANUP_REQUIRED
    assert len(harness.state.retired) == 1
    harness.repository.finish_retired.assert_not_awaited()
    harness.repository.mark_retired_failure.assert_awaited_once_with(
        cleanup_id="cleanup", reason="provider_cleanup_failed"
    )
    assert "old-token" not in str(error.value)


async def test_late_cleanup_only_revokes_captured_old_token_after_reconnection() -> (
    None
):
    harness = _harness()
    harness.state.retired.append(_cleanup(harness))
    entered, release = asyncio.Event(), asyncio.Event()
    captured: list[str] = []

    async def revoke(*, client_id: str, client_secret: str, token: str) -> None:
        captured.append(token)
        entered.set()
        await release.wait()

    harness.provider.revoke.side_effect = revoke
    cleanup_task = asyncio.create_task(harness.service.cleanup_retry(harness.requester))
    await entered.wait()
    old = harness.state.context.connection
    assert old is not None
    harness.state.context = dataclasses.replace(
        harness.state.context,
        connection=dataclasses.replace(
            old, id="new-connection", access_token="new-token"
        ),
    )
    release.set()
    await cleanup_task
    assert captured == ["old-token"]
    assert harness.state.context.connection is not None
    assert harness.state.context.connection.access_token == "new-token"


async def test_confirm_transfers_candidate_and_revokes_only_previous_token() -> None:
    harness = _harness()
    old = harness.state.context.connection
    assert old is not None
    new = dataclasses.replace(
        old, id="new-connection", access_token="new-token", account_id=2
    )

    async def confirm(
        *,
        requester: GitHubUserRequester,
        attempt_id: str,
        registration: GitHubUserRegistration,
    ) -> GitHubUserConnection:
        harness.state.context = dataclasses.replace(
            harness.state.context, connection=new
        )
        harness.state.retired.append(_cleanup(harness))
        return new

    harness.repository.confirm.side_effect = confirm
    output = await harness.service.confirm(harness.requester, attempt_id="attempt")
    assert output.id == "new-connection"
    harness.provider.revoke.assert_awaited_once_with(
        client_id="client", client_secret="client-secret", token="old-token"
    )


async def test_wrong_context_denial_precedes_any_provider_exchange() -> None:
    harness = _harness()
    harness.repository.claim_exchange.side_effect = GitHubUserOAuthError(
        GitHubUserErrorCode.STALE, "Wrong initiating session."
    )
    with pytest.raises(GitHubUserOAuthError):
        await harness.service.exchange(
            harness.requester, code="code", state="github_user.attempt.nonce"
        )
    harness.provider.exchange.assert_not_awaited()


async def test_provider_exchange_failure_finishes_claim_without_retry() -> None:
    harness = _harness()
    harness.provider.exchange.side_effect = GitHubUserProviderError(
        reason="provider_unavailable", status_code=None
    )
    with pytest.raises(GitHubUserProviderError):
        await harness.service.exchange(
            harness.requester, code="code", state="github_user.attempt.nonce"
        )
    harness.provider.exchange.assert_awaited_once()
    harness.repository.complete_failed_exchange.assert_awaited_once_with(
        attempt_id="attempt"
    )
    harness.repository.record_exchange_token.assert_not_awaited()


async def test_authority_loss_after_identity_retires_and_revokes_token() -> None:
    harness = _harness()
    harness.repository.store_review.side_effect = GitHubUserOAuthError(
        GitHubUserErrorCode.AUTHORITY, "Management authority changed."
    )
    with pytest.raises(GitHubUserOAuthError, match="Management authority changed"):
        await harness.service.exchange(
            harness.requester, code="code", state="github_user.attempt.nonce"
        )
    harness.repository.retire_exchange_result.assert_awaited_once()
    harness.provider.revoke.assert_awaited_once_with(
        client_id="client", client_secret="client-secret", token="new-token"
    )


async def test_cleanup_retry_uses_same_app_rotated_byoa_secret() -> None:
    harness = _harness()
    harness.state.retired.append(_cleanup(harness))
    credentials = json.loads(harness.state.context.toolkit.credentials or "null")
    credentials["client_secret"] = "rotated-secret"
    harness.state.context = dataclasses.replace(
        harness.state.context,
        toolkit=harness.state.context.toolkit.model_copy(
            update={"credentials": json.dumps(credentials), "revision": 2}
        ),
    )
    harness.provider.revoke.side_effect = None
    await harness.service.cleanup_retry(harness.requester)
    harness.provider.revoke.assert_awaited_once_with(
        client_id="client", client_secret="rotated-secret", token="old-token"
    )


async def test_missing_platform_registration_stops_local_use_and_retains_cleanup() -> (
    None
):
    harness = _harness(platform=True)
    harness.platform.resolve.return_value = ResolvedPlatformGitHubApp(
        app_id=None,
        client_id=None,
        private_key=None,
        client_secret=None,
        app_id_source=SystemSettingFieldSource.UNSET,
        effective_generation="missing",
    )
    cleanup = dataclasses.replace(
        _cleanup(harness),
        registration=dataclasses.replace(harness.registration, client_secret=None),
    )

    async def disconnect(
        *, requester: GitHubUserRequester, registration: GitHubUserRegistration | None
    ) -> None:
        assert registration is None
        harness.state.context = dataclasses.replace(
            harness.state.context, connection=None
        )
        harness.state.retired.append(cleanup)

    harness.repository.disconnect.side_effect = disconnect
    with pytest.raises(GitHubUserOAuthError) as error:
        await harness.service.disconnect(harness.requester)
    assert error.value.code is GitHubUserErrorCode.CLEANUP_REQUIRED
    assert harness.state.context.connection is None
    assert harness.state.retired == [cleanup]
    harness.provider.revoke.assert_not_awaited()


@pytest.mark.parametrize(
    "reason,marks",
    [
        ("authentication", True),
        ("target_denied", False),
        ("provider_unavailable", False),
    ],
)
async def test_access_failure_marks_only_confirmed_authentication(
    reason: str, marks: bool
) -> None:
    harness = _harness()
    if reason == "authentication":
        failure = GitHubUserProviderError(reason="authentication", status_code=401)
    elif reason == "target_denied":
        failure = GitHubUserProviderError(reason="target_denied", status_code=403)
    else:
        failure = GitHubUserProviderError(
            reason="provider_unavailable", status_code=None
        )
    harness.provider.access.side_effect = failure
    with pytest.raises(GitHubUserProviderError):
        await harness.service.access(harness.requester, cursor=None)
    if marks:
        harness.repository.mark_reconnect_required.assert_awaited_once_with(
            requester=harness.requester,
            connection_id="old-connection",
            reason="authentication_failed",
        )
    else:
        harness.repository.mark_reconnect_required.assert_not_awaited()


async def test_scope_denial_precedes_availability_settings_read() -> None:
    harness = _harness()
    harness.repository.authorize_scope.side_effect = GitHubUserOAuthError(
        GitHubUserErrorCode.AUTHORITY, "Not a manager."
    )
    with pytest.raises(GitHubUserOAuthError):
        await harness.service.availability(
            user_id="manager",
            session_id="login",
            workspace_id="workspace",
            agent_id=None,
        )
    harness.platform.resolve.assert_not_awaited()


async def test_platform_availability_is_local_not_provider_health() -> None:
    harness = _harness()
    output = await harness.service.availability(
        user_id="manager", session_id="login", workspace_id="workspace", agent_id=None
    )
    assert output.platform == "configured"
    assert "client-secret" not in output.model_dump_json()
    harness.provider.app.assert_not_awaited()


async def test_access_success_returns_observations_without_mutating_authority() -> None:
    harness = _harness()
    harness.provider.access.return_value = GitHubUserAccessPage(
        installations=(), next_cursor="more"
    )
    output = await harness.service.access(harness.requester, cursor=None)
    assert output.next_cursor == "more"
    harness.repository.mark_reconnect_required.assert_not_awaited()
    harness.repository.confirm.assert_not_awaited()


async def test_review_reads_current_verified_account_without_popup_metadata() -> None:
    harness = _harness()
    harness.repository.read_review.return_value = dataclasses.replace(
        harness.attempt,
        status=GitHubUserAttemptStatus.REVIEW,
        candidate=GitHubUserCandidate(
            access_token="candidate-token",
            account_id=2,
            account_login="candidate",
            account_avatar_url=None,
        ),
    )
    output = await harness.service.review(harness.requester, attempt_id="attempt")
    assert output.account_login == "candidate"
    assert "candidate-token" not in output.model_dump_json()
    harness.provider.exchange.assert_not_awaited()
    harness.repository.confirm.assert_not_awaited()


async def test_new_setup_does_not_claim_unknown_old_exchange_cleanup_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _harness()
    harness.repository.ensure_cleanup_complete.side_effect = GitHubUserOAuthError(
        GitHubUserErrorCode.CLEANUP_REQUIRED, "Unknown prior exchange remains."
    )
    monkeypatch.setattr(service_module, "create_github_app_jwt", lambda *args: "jwt")
    harness.repository.start.return_value = harness.attempt
    output = await harness.service.connect(harness.requester)
    assert output.attempt_id == "attempt"
    harness.repository.ensure_cleanup_complete.assert_not_awaited()
    with pytest.raises(GitHubUserOAuthError, match="Unknown prior"):
        await harness.service.cleanup_retry(harness.requester)


async def test_cancellation_retains_received_token_for_explicit_later_cleanup() -> None:
    harness = _harness()
    entered = asyncio.Event()
    never_release = asyncio.Event()

    async def blocked_identity(token: str) -> GitHubUserIdentity:
        entered.set()
        await never_release.wait()
        raise AssertionError("Cancelled identity call cannot return.")

    harness.provider.identity.side_effect = blocked_identity
    exchange_task = asyncio.create_task(
        harness.service.exchange(
            harness.requester, code="code", state="github_user.attempt.nonce"
        )
    )
    await entered.wait()
    exchange_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await exchange_task
    harness.repository.record_exchange_token.assert_awaited_once_with(
        attempt_id="attempt",
        registration=harness.registration,
        access_token="new-token",
    )
    harness.repository.store_review.assert_not_awaited()
    harness.provider.revoke.assert_not_awaited()

    async def cancel(*, requester: GitHubUserRequester, attempt_id: str) -> None:
        harness.state.retired.append(_cleanup(harness, token="new-token"))

    harness.repository.cancel.side_effect = cancel
    await harness.service.cancel(harness.requester, attempt_id="attempt")
    harness.provider.revoke.assert_awaited_once_with(
        client_id="client", client_secret="client-secret", token="new-token"
    )


async def test_extra_credential_token_is_rejected_without_input_disclosure() -> None:
    harness = _harness()
    values = json.loads(harness.state.context.toolkit.credentials or "null")
    values["access_token"] = "injected-secret-token"
    harness.state.context = dataclasses.replace(
        harness.state.context,
        toolkit=harness.state.context.toolkit.model_copy(
            update={"credentials": json.dumps(values)}
        ),
    )
    with pytest.raises(GitHubUserOAuthError) as error:
        await harness.service.access(harness.requester, cursor=None)
    assert "injected-secret-token" not in str(error.value)
    assert error.value.__cause__ is None
    harness.provider.access.assert_not_awaited()


async def test_invalid_local_cursor_is_input_error_not_provider_failure() -> None:
    harness = _harness()
    harness.provider.access.side_effect = ValueError("Invalid cursor.")
    with pytest.raises(GitHubUserOAuthError) as error:
        await harness.service.access(harness.requester, cursor="bad-cursor")
    assert error.value.code is GitHubUserErrorCode.INVALID
    harness.repository.mark_reconnect_required.assert_not_awaited()


async def test_lost_delete_response_completes_only_after_exact_token_rest_401() -> None:
    harness = _harness()
    harness.state.retired.append(_cleanup(harness))
    harness.provider.revoke.side_effect = GitHubUserProviderError(
        reason="provider_unavailable", status_code=None
    )
    harness.provider.identity.side_effect = GitHubUserProviderError(
        reason="authentication", status_code=401
    )
    await harness.service.cleanup_retry(harness.requester)
    harness.provider.revoke.assert_awaited_once_with(
        client_id="client", client_secret="client-secret", token="old-token"
    )
    harness.provider.identity.assert_awaited_once_with("old-token")
    harness.repository.finish_retired.assert_awaited_once_with(cleanup_id="cleanup")
    harness.repository.mark_retired_failure.assert_not_awaited()
    assert harness.state.retired == []
    assert harness.state.context.connection is not None


@pytest.mark.parametrize(
    "delete_error",
    [
        GitHubUserProviderError(reason="target_denied", status_code=404),
        GitHubUserProviderError(reason="authentication", status_code=401),
        GitHubUserProviderError(reason="provider_unavailable", status_code=422),
    ],
)
async def test_delete_error_and_valid_identity_never_prove_revocation(
    delete_error: GitHubUserProviderError,
) -> None:
    harness = _harness()
    harness.state.retired.append(_cleanup(harness))
    harness.provider.revoke.side_effect = delete_error
    with pytest.raises(GitHubUserOAuthError) as error:
        await harness.service.cleanup_retry(harness.requester)
    assert error.value.code is GitHubUserErrorCode.CLEANUP_REQUIRED
    harness.provider.identity.assert_awaited_once_with("old-token")
    harness.repository.finish_retired.assert_not_awaited()
    assert len(harness.state.retired) == 1


@pytest.mark.parametrize(
    "verification_error",
    [
        GitHubUserProviderError(reason="target_denied", status_code=403),
        GitHubUserProviderError(reason="target_denied", status_code=404),
        GitHubUserProviderError(reason="provider_unavailable", status_code=429),
        GitHubUserProviderError(reason="provider_unavailable", status_code=500),
        GitHubUserProviderError(reason="provider_unavailable", status_code=None),
        GitHubUserProviderError(reason="invalid_response", status_code=None),
        GitHubUserProviderError(reason="authentication", status_code=None),
    ],
)
async def test_inconclusive_token_verification_retains_cleanup(
    verification_error: GitHubUserProviderError,
) -> None:
    harness = _harness()
    harness.state.retired.append(_cleanup(harness))
    harness.provider.revoke.side_effect = GitHubUserProviderError(
        reason="provider_unavailable", status_code=None
    )
    harness.provider.identity.side_effect = verification_error
    with pytest.raises(GitHubUserOAuthError) as error:
        await harness.service.cleanup_retry(harness.requester)
    assert error.value.code is GitHubUserErrorCode.CLEANUP_REQUIRED
    harness.repository.finish_retired.assert_not_awaited()
    assert len(harness.state.retired) == 1


async def test_missing_app_secret_can_complete_already_invalid_exact_token() -> None:
    harness = _harness(platform=True)
    cleanup = dataclasses.replace(
        _cleanup(harness),
        registration=dataclasses.replace(harness.registration, client_secret=None),
    )
    harness.state.retired.append(cleanup)
    harness.platform.resolve.return_value = ResolvedPlatformGitHubApp(
        app_id=None,
        client_id=None,
        private_key=None,
        client_secret=None,
        app_id_source=SystemSettingFieldSource.UNSET,
        effective_generation="missing",
    )
    harness.provider.identity.side_effect = GitHubUserProviderError(
        reason="authentication", status_code=401
    )
    await harness.service.cleanup_retry(harness.requester)
    harness.provider.revoke.assert_not_awaited()
    harness.provider.identity.assert_awaited_once_with("old-token")
    assert harness.state.retired == []


async def test_invalidity_probe_never_tests_or_clears_new_active_token() -> None:
    harness = _harness()
    harness.state.retired.append(_cleanup(harness))
    old = harness.state.context.connection
    assert old is not None
    new = dataclasses.replace(old, id="new-connection", access_token="new-token")
    harness.state.context = dataclasses.replace(harness.state.context, connection=new)
    harness.provider.revoke.side_effect = GitHubUserProviderError(
        reason="provider_unavailable", status_code=None
    )
    harness.provider.identity.side_effect = GitHubUserProviderError(
        reason="authentication", status_code=401
    )
    await harness.service.cleanup_retry(harness.requester)
    harness.provider.identity.assert_awaited_once_with("old-token")
    harness.repository.mark_reconnect_required.assert_not_awaited()
    assert harness.state.context.connection == new
    assert harness.state.retired == []


async def test_invalidity_probe_programming_failure_remains_visible() -> None:
    harness = _harness()
    harness.state.retired.append(_cleanup(harness))
    harness.provider.revoke.side_effect = GitHubUserProviderError(
        reason="provider_unavailable", status_code=None
    )
    harness.provider.identity.side_effect = RuntimeError("Unexpected local defect.")
    with pytest.raises(RuntimeError, match="Unexpected local defect"):
        await harness.service.cleanup_retry(harness.requester)
    harness.repository.finish_retired.assert_not_awaited()
    assert len(harness.state.retired) == 1


async def test_exchange_timeout_never_claims_unknown_token_revoked() -> None:
    harness = _harness()
    harness.provider.exchange.side_effect = TimeoutError()
    with pytest.raises(GitHubUserProviderError) as caught:
        await harness.service.exchange(
            harness.requester, code="one-use-code", state="github_user.attempt.nonce"
        )
    assert caught.value.reason == "provider_unavailable"
    harness.provider.exchange.assert_awaited_once()
    harness.repository.complete_failed_exchange.assert_awaited_once_with(
        attempt_id="attempt"
    )
    harness.repository.record_exchange_token.assert_not_awaited()
    harness.provider.revoke.assert_not_awaited()
    await harness.service.exchange_owner.drain()
    assert harness.service.exchange_owner.operations == set()
