"""Creation retains current App authority and exact fail-open cleanup."""

import dataclasses
from typing import NamedTuple
from unittest.mock import MagicMock, Mock, create_autospec

import pytest
from azcommon.result import Failure

from azents.core.enums import WorkspaceUserRole
from azents.core.github_user_auth import GitHubUserProviderError
from azents.core.github_user_creation import (
    GitHubUserCreationAttempt,
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
    return CreationHarness(
        GitHubUserCreationService(
            repository, h.service, create_autospec(ToolkitService, instance=True)
        ),
        repository,
        h,
        attempt,
    )


async def test_platform_generation_change_rejects_review_and_publication() -> None:
    h = _creation(platform=True)
    h.oauth.platform.resolve.return_value = dataclasses.replace(
        h.oauth.platform.resolve.return_value,
        effective_generation="replaced-generation",
    )
    for operation in [h.service.review, h.service.confirm]:
        with pytest.raises(GitHubUserOAuthError) as error:
            await operation(h.attempt.subject, h.attempt.id)
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
    created = await h.service.confirm(h.attempt.subject, h.attempt.id)
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
