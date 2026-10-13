"""Creation retains current App authority and exact fail-open cleanup."""

import dataclasses
from typing import NamedTuple
from unittest.mock import MagicMock, Mock, create_autospec

import pytest
from azcommon.result import Failure

from azents.core.enums import WorkspaceUserRole
from azents.core.github_setup import GitHubSetupAppIdentity
from azents.core.github_user_auth import GitHubUserProviderError
from azents.core.github_user_creation import (
    GitHubUserCreationAttempt,
    GitHubUserCreationFinalSettings,
    GitHubUserCreationSubject,
)
from azents.core.github_user_oauth import (
    GitHubUserAttemptStatus,
    GitHubUserCandidate,
    GitHubUserErrorCode,
    GitHubUserOAuthError,
    GitHubUserRevocation,
)
from azents.repos.github_user_oauth.creation import GitHubUserCreationRepository
from azents.repos.toolkit.data import ToolkitCreate
from azents.services.github_user_oauth import creation as creation_module
from azents.services.github_user_oauth.creation import GitHubUserCreationService
from azents.services.github_user_oauth.service_test import _Harness, _harness
from azents.services.toolkit import ToolkitService
from azents.services.toolkit.data import InvalidCredentials, ToolkitCreateInput
from azents.services.toolkit.service_test import _service as toolkit_service


class CreationHarness(NamedTuple):
    """Typed original OAuth and creation-specific collaborators."""

    service: GitHubUserCreationService
    repository: Mock
    oauth: _Harness
    attempt: GitHubUserCreationAttempt


def _creation(*, platform: bool) -> CreationHarness:
    h = _harness(platform=platform, agent_id=None)
    assert h.state.context is not None
    original = h.attempt
    attempt = GitHubUserCreationAttempt(
        id=original.id,
        subject=GitHubUserCreationSubject(
            h.requester.user_id,
            h.requester.session_id,
            h.requester.workspace_id,
            h.requester.agent_id,
        ),
        desired=ToolkitCreate(
            workspace_id=h.requester.workspace_id,
            owner_agent_id=h.requester.agent_id,
            toolkit_type="github",
            slug="github",
            name="GitHub",
            config=h.state.context.toolkit.config,
            credentials=h.state.context.toolkit.credentials,
            always_expose_tools=False,
        ),
        registration=original.registration,
        redirect_uri=original.redirect_uri,
        nonce=original.nonce,
        code_verifier=original.code_verifier,
        expires_at=original.expires_at,
        status=GitHubUserAttemptStatus.REVIEW,
        candidate=GitHubUserCandidate("new-token", 2, "new-account", None),
    )
    repository = create_autospec(GitHubUserCreationRepository, instance=True)
    repository.load.return_value = attempt
    repository.claim.return_value = dataclasses.replace(
        attempt, status=GitHubUserAttemptStatus.EXCHANGING, candidate=None
    )
    repository.confirm.return_value = "created-toolkit"
    repository.cancel.return_value = (
        GitHubUserRevocation(attempt.registration, "new-token"),
    )
    toolkits = create_autospec(ToolkitService, instance=True)
    toolkits.toolkit_registry = {"github": Mock(name="provider")}
    toolkits.toolkit_registry["github"].name = "GitHub"
    repository.load_review.return_value = attempt
    return CreationHarness(
        GitHubUserCreationService(repository, h.service, toolkits),
        repository,
        h,
        attempt,
    )


def _settings() -> GitHubUserCreationFinalSettings:
    return GitHubUserCreationFinalSettings(
        name="Final reviewed name",
        slug="final_slug",
        description="Final description",
        prompt=None,
        enabled=True,
        always_expose_tools=True,
        toolsets=["repos", "projects", "future_group"],
        timeout=12.0,
        inject_runtime_environment=True,
        runtime_risk_acknowledged=True,
    )


async def test_platform_generation_change_rejects_review_and_publication() -> None:
    h = _creation(platform=True)
    h.oauth.platform.resolve.return_value = dataclasses.replace(
        h.oauth.platform.resolve.return_value,
        effective_generation="replaced-generation",
    )
    with pytest.raises(GitHubUserOAuthError) as error:
        await h.service.review(h.attempt.subject, h.attempt.id)
    assert error.value.code is GitHubUserErrorCode.STALE
    with pytest.raises(GitHubUserOAuthError) as error:
        await h.service.confirm(h.attempt.subject, h.attempt.id, _settings())
    assert error.value.code is GitHubUserErrorCode.STALE
    h.repository.confirm.assert_not_awaited()
    h.oauth.provider.exchange.assert_not_awaited()


async def test_confirm_returns_only_toolkit_id_after_explicit_review() -> None:
    h = _creation(platform=False)
    reviewed = await h.service.review(h.attempt.subject, h.attempt.id)
    assert reviewed.candidate.account_login == "new-account"
    assert "new-token" not in reviewed.model_dump_json()
    assert "client-secret" not in reviewed.model_dump_json()
    h.repository.confirm.assert_not_awaited()
    created = await h.service.confirm(h.attempt.subject, h.attempt.id, _settings())
    assert created.toolkit_id == "created-toolkit"
    h.repository.confirm.assert_awaited_once()


async def test_failed_exchange_discards_only_claim_and_attempts_exact_cleanup() -> None:
    h = _creation(platform=False)
    h.oauth.provider.identity.side_effect = GitHubUserProviderError(
        reason="provider_unavailable", status_code=503
    )
    with pytest.raises(GitHubUserProviderError):
        await h.service.exchange(
            h.attempt.subject,
            code="code",
            state=f"github_user_create.{h.attempt.id}.{h.attempt.nonce}",
        )
    h.repository.discard_claimed.assert_awaited_once_with(h.attempt.id)
    h.oauth.provider.revoke.assert_awaited_once_with(
        client_id="client", client_secret="client-secret", token="new-token"
    )
    h.repository.confirm.assert_not_awaited()


async def test_creation_cancel_finishes_local_removal_despite_provider_failure() -> (
    None
):
    h = _creation(platform=False)
    h.oauth.provider.revoke.side_effect = GitHubUserProviderError(
        reason="provider_unavailable", status_code=503
    )
    await h.service.cancel(h.attempt.subject, h.attempt.id)
    h.repository.cancel.assert_awaited_once_with(h.attempt.subject, h.attempt.id)
    h.oauth.provider.revoke.assert_awaited_once_with(
        client_id="client", client_secret="client-secret", token="new-token"
    )
    h.repository.confirm.assert_not_awaited()


@pytest.mark.parametrize("platform", [False, True])
def test_same_registration_form_hydration_retains_write_only_credentials(
    platform: bool,
) -> None:
    h = _creation(platform=platform)
    assert h.oauth.state.context is not None
    mode = "github_app_platform_user" if platform else "github_app_user"
    existing = h.oauth.state.context.toolkit.model_copy(
        update={"config": {"github_auth_type": mode}}
    )
    patch = ToolkitService._build_repo_update(
        {"config": {"github_auth_type": mode, "auth_type": "bearer"}},
        existing=existing,
        normalized_credentials=None,
    )
    assert "credentials" not in patch


@pytest.mark.parametrize("mode", ["github_app_user", "github_app_platform_user"])
async def test_ordinary_shared_and_agent_create_require_authorization(
    mode: str,
) -> None:
    service = toolkit_service(
        toolkit_repo=MagicMock(),
        agent_toolkit_repo=MagicMock(),
        agent_repo=MagicMock(),
    )
    create = ToolkitCreateInput(
        workspace_id="workspace",
        toolkit_type="github",
        config={"github_auth_type": mode},
        always_expose_tools=False,
    )
    shared = await service.create(create, user_id="user")
    owned = await service.create_agent_owned(
        "agent",
        create,
        workspace_id="workspace",
        workspace_user_id="member",
        user_id="user",
        role=WorkspaceUserRole.OWNER,
    )
    for result in [shared, owned]:
        assert isinstance(result, Failure)
        assert isinstance(result.error, InvalidCredentials)
        assert "Authorize and confirm" in result.error.detail


async def test_invalid_final_identifiers_preserve_live_candidate() -> None:
    h = _creation(platform=False)
    invalid = _settings().model_copy(update={"slug": "invalid/slug"})
    with pytest.raises(GitHubUserOAuthError) as error:
        await h.service.confirm(h.attempt.subject, h.attempt.id, invalid)
    assert error.value.code is GitHubUserErrorCode.INVALID
    h.repository.confirm.assert_not_awaited()
    h.repository.cancel.assert_not_awaited()
    reviewed = await h.service.review(h.attempt.subject, h.attempt.id)
    assert reviewed.candidate.account_login == "new-account"


async def test_confirm_forwards_only_validated_settings_overlay() -> None:
    h = _creation(platform=False)
    await h.service.confirm(h.attempt.subject, h.attempt.id, _settings())
    h.repository.confirm.assert_awaited_once_with(
        h.attempt.subject,
        attempt_id=h.attempt.id,
        registration=h.attempt.registration,
        settings=_settings().prepare(canonical_name="GitHub"),
    )


async def test_candidate_app_metadata_rechecks_exact_review_after_provider_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _creation(platform=False)
    monkeypatch.setattr(
        creation_module, "create_github_app_jwt", lambda *_: "private-jwt"
    )
    h.oauth.provider.setup_app.return_value = GitHubSetupAppIdentity(
        app_id="123", name="Actual App", slug="actual-app"
    )
    result = await h.service.app(h.attempt.subject, h.attempt.id)
    assert result.app is not None and result.app.name == "Actual App"
    assert h.repository.load_review.await_count == 2
    h.repository.confirm.assert_not_awaited()
    h.repository.stage.assert_not_awaited()
    assert "private-jwt" not in result.model_dump_json()


async def test_candidate_cancelled_during_metadata_io_has_no_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _creation(platform=False)
    monkeypatch.setattr(
        creation_module, "create_github_app_jwt", lambda *_: "private-jwt"
    )
    h.oauth.provider.setup_app.return_value = GitHubSetupAppIdentity(
        app_id="123", name="Actual App", slug="actual-app"
    )
    h.repository.load_review.side_effect = [
        h.attempt,
        GitHubUserOAuthError(GitHubUserErrorCode.NOT_FOUND, "Attempt cancelled."),
    ]
    with pytest.raises(GitHubUserOAuthError) as error:
        await h.service.app(h.attempt.subject, h.attempt.id)
    assert error.value.code is GitHubUserErrorCode.NOT_FOUND
    h.oauth.provider.setup_app.assert_awaited_once()
    h.repository.confirm.assert_not_awaited()


async def test_metadata_provider_error_preserves_candidate_for_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _creation(platform=False)
    monkeypatch.setattr(
        creation_module, "create_github_app_jwt", lambda *_: "private-jwt"
    )
    h.oauth.provider.setup_app.side_effect = GitHubUserProviderError(
        reason="provider_unavailable", status_code=429
    )
    with pytest.raises(GitHubUserProviderError):
        await h.service.app(h.attempt.subject, h.attempt.id)
    h.repository.discard_claimed.assert_not_awaited()
    h.repository.cancel.assert_not_awaited()
    h.repository.confirm.assert_not_awaited()
    assert (
        await h.service.review(h.attempt.subject, h.attempt.id)
    ).candidate.account_id == 2
