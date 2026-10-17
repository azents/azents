"""Exact current User-owned GitHub account grant lifecycle in PostgreSQL."""

import dataclasses
import datetime
from unittest.mock import Mock

import pytest

from azents.core.github_user_oauth import (
    GitHubPersonalRequester,
    GitHubUserCandidate,
    GitHubUserOAuthError,
    GitHubUserRegistration,
    GitHubUserRequester,
)
from azents.core.system_setting_payload import SystemSettingPayloadResolver
from azents.core.toolkit_ownership import PersonalToolkitAccessMode
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.github_user_oauth.operations import GitHubUserOAuthOperationRepository
from azents.repos.toolkit.data import ToolkitCreation
from azents.repos.toolkit.personal_management_test import Harness
from azents.repos.toolkit.personal_management_test import (
    fixture as fixture,  # noqa: PLC0414 -- common SQL fixture registration
)
from azents.repos.toolkit.personal_management_test import (
    harness as harness,  # noqa: PLC0414 -- current-account management fixture
)


@dataclasses.dataclass(frozen=True)
class PersonalGitHubHarness:
    management: Harness
    operations: GitHubUserOAuthOperationRepository
    requester: GitHubPersonalRequester
    registration: GitHubUserRegistration


async def prepare(h: Harness) -> PersonalGitHubHarness:
    common = h.repository.shared_operations
    assert h.foundation.repository.cipher is not None
    operations = GitHubUserOAuthOperationRepository(
        session_manager=h.repository.session_manager,
        toolkit_repository=common.toolkit_repository,
        cipher=h.foundation.repository.cipher,
        user_repository=h.repository.user_repository,
        session_repository=h.repository.auth_session_repository,
        workspace_repository=common.workspace_repository,
        workspace_user_repository=common.workspace_user_repository,
        agent_repository=common.agent_repository,
        agent_admin_repository=AgentAdminRepository(),
        system_setting_repository=common.system_setting_repository,
        setting_payloads=Mock(spec=SystemSettingPayloadResolver),
        personal_toolkits=h.foundation.repository,
    )
    snapshot = await h.repository.create(
        h.subject,
        ToolkitCreation(
            toolkit_type="github",
            slug="github",
            name="Personal GitHub",
            config={
                "github_auth_type": "github_app_user",
                "inject_runtime_environment": True,
            },
            credentials=None,
            always_expose_tools=True,
        ),
        platform_authority=None,
    )
    return PersonalGitHubHarness(
        h,
        operations,
        GitHubPersonalRequester(
            user_id=h.subject.user_id,
            session_id=h.subject.session_id,
            toolkit_id=snapshot.toolkit.id,
            owner=snapshot.toolkit.owner,
        ),
        GitHubUserRegistration(
            source="byoa_user",
            app_id="123",
            client_id="fixture-client",
            client_secret="fixture-client-secret",
            toolkit_revision=snapshot.toolkit.revision,
            platform_generation=None,
        ),
    )


async def review(h: PersonalGitHubHarness, token: str) -> str:
    started = await h.operations.start(
        requester=h.requester,
        registration=h.registration,
        redirect_uri="https://app.test/oauth/github/callback",
        nonce="fixture-nonce",
        code_verifier="fixture-verifier",
        expires_at=datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=10),
    )
    assert started.attempt.requester == h.requester
    await h.operations.claim_exchange(
        requester=h.requester,
        attempt_id=started.attempt.id,
        nonce="fixture-nonce",
        redirect_uri=started.attempt.redirect_uri,
    )
    await h.operations.store_review(
        requester=h.requester,
        attempt_id=started.attempt.id,
        candidate=GitHubUserCandidate(
            access_token=token,
            account_id=42,
            account_login="fixture-account",
            account_avatar_url=None,
        ),
        registration=h.registration,
    )
    return started.attempt.id


async def test_personal_github_review_confirm_replace_disconnect(
    harness: Harness,
) -> None:
    """Use the current grant implementation without Workspace manager privileges."""
    h = await prepare(harness)
    first = await review(h, "fixture-first-token")
    context = await h.operations.read_context(requester=h.requester)
    assert context.connection is None
    saved = await h.operations.confirm(
        requester=h.requester, attempt_id=first, registration=h.registration
    )
    assert (
        saved.connection.access_token == "fixture-first-token"
        and saved.revocations == ()
    )
    assert context.toolkit.owner == h.requester.owner
    assert context.toolkit.config["inject_runtime_environment"] is True
    second = await review(h, "fixture-second-token")
    replaced = await h.operations.confirm(
        requester=h.requester, attempt_id=second, registration=h.registration
    )
    assert replaced.connection.id != saved.connection.id
    assert (
        len(replaced.revocations) == 1
        and replaced.revocations[0].access_token == "fixture-first-token"
    )
    toolkit = await h.management.foundation.operations.get(
        user_id=h.requester.user_id,
        workspace_id=h.requester.workspace_id,
        toolkit_id=h.requester.toolkit_id,
    )
    assert toolkit is not None and toolkit.access_mode is PersonalToolkitAccessMode.ALL
    assert (
        toolkit.always_expose_tools
        and toolkit.config["inject_runtime_environment"] is True
    )
    revocations = await h.operations.disconnect(
        requester=h.requester, registration=None
    )
    assert (
        len(revocations) == 1 and revocations[0].access_token == "fixture-second-token"
    )
    assert (await h.operations.read_context(requester=h.requester)).connection is None


async def test_personal_github_cannot_rebind_shared_owner_or_other_user(
    harness: Harness,
) -> None:
    h = await prepare(harness)
    attempt_id = await review(h, "fixture-candidate")
    wrong_shared = GitHubUserRequester(
        h.requester.user_id,
        h.requester.session_id,
        h.management.foundation.workspace_ids[0],
        None,
        h.requester.toolkit_id,
    )
    for requester in [
        wrong_shared,
        dataclasses.replace(
            h.requester,
            owner=h.requester.owner.model_copy(
                update={"workspace_id": h.management.foundation.workspace_ids[1]}
            ),
        ),
        dataclasses.replace(
            h.requester,
            user_id=h.management.other.user_id,
            session_id=h.management.other.session_id,
            owner=h.requester.owner.model_copy(
                update={"user_id": h.management.other.user_id}
            ),
        ),
    ]:
        with pytest.raises(GitHubUserOAuthError):
            await h.operations.read_review(requester=requester, attempt_id=attempt_id)
    # Cancellation revokes the unpublished candidate without publishing a grant.
    revoked = await h.operations.cancel(requester=h.requester, attempt_id=attempt_id)
    assert len(revoked) == 1 and revoked[0].access_token == "fixture-candidate"
    with pytest.raises(GitHubUserOAuthError):
        await h.operations.confirm(
            requester=h.requester, attempt_id=attempt_id, registration=h.registration
        )
