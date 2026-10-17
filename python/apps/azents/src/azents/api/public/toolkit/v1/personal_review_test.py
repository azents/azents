"""Real owner/grant boundaries remain inspectable through the personal HTTP API."""

import dataclasses
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from azents.api.public.toolkit.v1.personal import router as personal_router
from azents.api.public.toolkit.v1.personal_github import router as github_router
from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.core.enums import WorkspaceUserRole
from azents.core.github_user_auth import GitHubUserAccessPage
from azents.core.personal_toolkit import PersonalToolkitManager
from azents.repos.github_user_oauth.personal_test import prepare, review
from azents.repos.toolkit.personal_management_test import Harness
from azents.repos.toolkit.personal_management_test import (
    fixture as fixture,  # noqa: PLC0414 -- shared PostgreSQL foundation
)
from azents.repos.toolkit.personal_management_test import (
    harness as harness,  # noqa: PLC0414 -- actual account and personal management
)
from azents.services.github_user_oauth.service import (
    GitHubUserOAuthService,
    _PreparedRegistration,
)
from azents.services.github_user_oauth.service_test import _harness
from azents.services.toolkit.personal import PersonalToolkitService


def member(subject: PersonalToolkitManager) -> WorkspaceMember:
    """Capture the admitted Workspace without shared-management authority."""
    return WorkspaceMember(
        user_id=subject.user_id,
        session_id=subject.session_id,
        workspace_id=subject.workspace_id,
        workspace_user_id="fixture-member",
        role=WorkspaceUserRole.MEMBER,
        permissions=set(),
    )


@pytest.mark.parametrize("active", [True, False])
async def test_personal_registration_change_conflict_is_409_and_preserves_grant(
    harness: Harness, active: bool
) -> None:
    h = await prepare(harness)
    attempt_id = await review(h, "fixture-candidate-token")
    if active:
        await h.operations.confirm(
            requester=h.requester, attempt_id=attempt_id, registration=h.registration
        )
    before = await h.operations.read_context(requester=h.requester)
    app = FastAPI()
    app.include_router(personal_router)
    app.dependency_overrides[get_workspace_member] = lambda: member(
        h.management.subject
    )
    app.dependency_overrides[PersonalToolkitService] = lambda: h.management.service
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        result = await client.patch(
            f"/workspaces/ws/personal-toolkit-configs/{h.requester.toolkit_id}",
            json={
                "config": {"github_auth_type": "pat"},
                "credentials": {"type": "pat", "token": "fixture-pat"},
            },
        )
    assert result.status_code == 409
    assert "disconnect" in result.text.lower() or "cancel" in result.text.lower()
    assert (
        "fixture-pat" not in result.text
        and "fixture-candidate-token" not in result.text
    )
    after = await h.operations.read_context(requester=h.requester)
    assert after.toolkit.config == before.toolkit.config
    assert after.toolkit.credentials == before.toolkit.credentials
    assert after.connection == before.connection
    if not active:
        assert (
            await h.operations.read_review(requester=h.requester, attempt_id=attempt_id)
        ).id == attempt_id


async def test_personal_access_observation_binds_owner_and_continuation_before_provider(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = await prepare(harness)
    attempt_id = await review(h, "fixture-connected-token")
    await h.operations.confirm(
        requester=h.requester, attempt_id=attempt_id, registration=h.registration
    )
    common = _harness(platform=False, agent_id=None)
    service = dataclasses.replace(common.service, repository=h.operations)
    monkeypatch.setattr(
        GitHubUserOAuthService,
        "_registration",
        AsyncMock(return_value=_PreparedRegistration(h.registration, "fixture-key")),
    )
    common.provider.access.side_effect = [
        GitHubUserAccessPage((), "fixture-next-cursor"),
        GitHubUserAccessPage((), None),
    ]
    app = FastAPI()
    app.include_router(github_router)
    app.dependency_overrides[GitHubUserOAuthService] = lambda: service
    app.dependency_overrides[get_workspace_member] = lambda: member(
        h.management.subject
    )
    path = (
        f"/workspaces/ws/personal-toolkit-configs/{h.requester.toolkit_id}"
        "/github-user/access"
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.get(path)
        assert (
            first.status_code == 200
            and first.json()["next_cursor"] == "fixture-next-cursor"
        )
        second = await client.get(path, params={"cursor": first.json()["next_cursor"]})
        assert second.status_code == 200 and second.json()["next_cursor"] is None
        assert common.provider.access.await_args.kwargs == {
            "app_id": 123,
            "cursor": "fixture-next-cursor",
        }
        assert common.provider.access.await_count == 2
        invalid = await client.get(path, params={"cursor": "x" * 4097})
        assert invalid.status_code == 422
        app.dependency_overrides[get_workspace_member] = lambda: member(
            dataclasses.replace(
                h.management.subject,
                workspace_id=h.management.foundation.workspace_ids[1],
            )
        )
        cross_workspace = await client.get(path)
        assert cross_workspace.status_code == 404
        assert common.provider.access.await_count == 2
        app.dependency_overrides[get_workspace_member] = lambda: member(
            h.management.other
        )
        foreign = await client.get(path)
        assert foreign.status_code in (403, 404)
        assert common.provider.access.await_count == 2
    assert "fixture-connected-token" not in first.text + second.text + foreign.text
