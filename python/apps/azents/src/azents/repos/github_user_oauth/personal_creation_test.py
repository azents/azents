"""Personal GitHub creation retains reviewed publication and existing auth options."""

import dataclasses
import datetime

import pytest
import sqlalchemy as sa

from azents.core.enums import WorkspaceUserRole
from azents.core.github_user_creation import (
    GitHubPersonalCreationSubject,
    GitHubUserCreationFinalSettings,
    GitHubUserCreationSubject,
)
from azents.core.github_user_oauth import GitHubUserCandidate, GitHubUserOAuthError
from azents.core.toolkit_ownership import PersonalToolkitAccessMode
from azents.rdb.models.github_user_oauth import RDBGitHubUserCreation
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.repos.github_user_oauth.creation import GitHubUserCreationRepository
from azents.repos.github_user_oauth.payloads import SetupPayload
from azents.repos.github_user_oauth.personal_test import prepare
from azents.repos.toolkit.data import ToolkitCreate, ToolkitCreation
from azents.repos.toolkit.personal_management_test import Harness
from azents.repos.toolkit.personal_management_test import (
    fixture as fixture,  # noqa: PLC0414 -- register SQL foundation
)
from azents.repos.toolkit.personal_management_test import (
    harness as harness,  # noqa: PLC0414 -- register current-account management
)


@pytest.mark.parametrize("personal_first", [True, False])
async def test_shared_and_personal_creation_coexist_and_cancel_independently(
    harness: Harness, personal_first: bool
) -> None:
    """Exact-target replacement and cancellation leave the sibling owner untouched."""
    h = await prepare(harness)
    async with h.management.foundation.writes() as session:
        await session.write_session.execute(
            sa.update(RDBWorkspaceUser)
            .where(
                RDBWorkspaceUser.user_id == h.requester.user_id,
                RDBWorkspaceUser.workspace_id == h.requester.workspace_id,
            )
            .values(role=WorkspaceUserRole.OWNER)
        )
    creation = GitHubUserCreationRepository(
        h.operations, h.management.repository.shared_operations.namespace_repository
    )
    personal = GitHubPersonalCreationSubject(
        h.requester.user_id, h.requester.session_id, h.requester.owner
    )
    shared = GitHubUserCreationSubject(
        h.requester.user_id, h.requester.session_id, h.requester.workspace_id, None
    )
    personal_desired = ToolkitCreation(
        toolkit_type="github",
        name="Personal",
        slug="personal",
        config={"github_auth_type": "github_app_user"},
        credentials=None,
        always_expose_tools=False,
    )
    shared_desired = ToolkitCreate(
        workspace_id=h.requester.workspace_id,
        owner_agent_id=None,
        toolkit_type="github",
        name="Shared",
        slug="shared",
        config={"github_auth_type": "github_app_user"},
        credentials=None,
        always_expose_tools=False,
    )
    setup = SetupPayload(
        registration=h.registration,
        redirect_uri="https://app.test/callback",
        nonce="independent-nonce",
        code_verifier="independent-verifier",
    )
    subjects = [personal, shared] if personal_first else [shared, personal]
    desired = (
        [personal_desired, shared_desired]
        if personal_first
        else [shared_desired, personal_desired]
    )
    first = await creation.start(
        subjects[0],
        desired=desired[0],
        setup=setup,
        expires_at=datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=10),
    )
    second = await creation.start(
        subjects[1],
        desired=desired[1],
        setup=setup,
        expires_at=datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=10),
    )
    assert (await creation.load(subjects[0], first.attempt.id)).subject == subjects[0]
    assert (await creation.load(subjects[1], second.attempt.id)).subject == subjects[1]
    replacement = await creation.start(
        subjects[0],
        desired=desired[0],
        setup=setup,
        expires_at=datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=10),
    )
    with pytest.raises(GitHubUserOAuthError):
        await creation.load(subjects[0], first.attempt.id)
    assert (await creation.load(subjects[1], second.attempt.id)).id == second.attempt.id
    assert await creation.cancel(subjects[0], replacement.attempt.id) == ()
    assert (await creation.load(subjects[1], second.attempt.id)).id == second.attempt.id
    assert await creation.cancel(subjects[1], second.attempt.id) == ()


async def test_personal_creation_publishes_only_after_reviewed_confirm(
    harness: Harness,
) -> None:
    """Personal setup shares staged creation and default All without an attachment."""
    h = await prepare(harness)
    creation = GitHubUserCreationRepository(
        h.operations,
        h.management.repository.shared_operations.namespace_repository,
    )
    subject = GitHubPersonalCreationSubject(
        h.requester.user_id,
        h.requester.session_id,
        h.requester.owner,
    )
    desired = ToolkitCreation(
        toolkit_type="github",
        name="Pending personal",
        slug="pending_personal",
        config={
            "github_auth_type": "github_app_user",
            "inject_runtime_environment": True,
        },
        credentials=None,
        always_expose_tools=True,
    )
    start = await creation.start(
        subject,
        desired=desired,
        setup=SetupPayload(
            registration=h.registration,
            redirect_uri="https://app.test/callback",
            nonce="creation-nonce",
            code_verifier="creation-verifier",
        ),
        expires_at=datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=10),
    )
    before = await h.management.foundation.operations.list_personal(
        user_id=subject.user_id, workspace_id=subject.workspace_id
    )
    assert [toolkit.id for toolkit in before] == [h.requester.toolkit_id]
    async with h.management.foundation.writes() as session:
        row = await session.read_session.get(RDBGitHubUserCreation, start.attempt.id)
        assert (
            row is not None
            and row.workspace_id == subject.workspace_id
            and row.agent_id is None
        )
        assert row.owner_user_id == subject.user_id
    await creation.claim(
        subject,
        attempt_id=start.attempt.id,
        nonce="creation-nonce",
        redirect_uri="https://app.test/callback",
    )
    await creation.stage(
        subject,
        attempt_id=start.attempt.id,
        registration=h.registration,
        candidate=GitHubUserCandidate(
            access_token="creation-token-fixture",
            account_id=52,
            account_login="creation-fixture",
            account_avatar_url=None,
        ),
    )
    with pytest.raises(GitHubUserOAuthError):
        await creation.load(
            GitHubUserCreationSubject(
                subject.user_id,
                subject.session_id,
                h.management.foundation.workspace_ids[0],
                None,
            ),
            start.attempt.id,
        )
    settings = GitHubUserCreationFinalSettings(
        name="Reviewed personal",
        slug="reviewed_personal",
        description="Reviewed",
        prompt="Personal GitHub",
        enabled=True,
        always_expose_tools=True,
        toolsets=["repos"],
        timeout=30,
        inject_runtime_environment=True,
        runtime_risk_acknowledged=True,
    ).prepare(canonical_name="GitHub")
    toolkit_id = await creation.confirm(
        subject,
        attempt_id=start.attempt.id,
        registration=h.registration,
        settings=settings,
    )
    toolkit = await h.management.foundation.operations.get(
        user_id=subject.user_id,
        workspace_id=subject.workspace_id,
        toolkit_id=toolkit_id,
    )
    assert toolkit is not None and toolkit.access_mode is PersonalToolkitAccessMode.ALL
    assert toolkit.owner == subject.owner and toolkit.name == "Reviewed personal"
    assert (
        toolkit.config["inject_runtime_environment"] is True
        and toolkit.always_expose_tools
    )
    current = await h.operations.read_context(
        requester=dataclasses.replace(h.requester, toolkit_id=toolkit_id)
    )
    assert current.connection is not None
    assert current.connection.access_token == "creation-token-fixture"
    with pytest.raises(GitHubUserOAuthError):
        await creation.confirm(
            subject,
            attempt_id=start.attempt.id,
            registration=h.registration,
            settings=settings,
        )
