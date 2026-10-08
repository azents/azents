"""Existing deletion routes report local success despite SDK cleanup failure."""

import json
from unittest.mock import create_autospec

import httpx
import pytest
from azcommon.result import Success
from fastapi import FastAPI
from fastapi.testclient import TestClient
from githubkit import BaseAuthStrategy, GitHub, UnauthAuthStrategy

from azents.api.public.toolkit.v1 import router
from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.core.auth.roles import get_permissions_for_role
from azents.core.config import Config
from azents.core.enums import WorkspaceUserRole
from azents.core.github_user_oauth import GitHubUserRegistration, GitHubUserRevocation
from azents.repos.github_user_oauth.operations import GitHubUserOAuthOperationRepository
from azents.services.github_platform_system_setting.runtime import (
    PlatformGitHubAppRuntimeService,
)
from azents.services.github_user_oauth.provider import GitHubUserProvider
from azents.services.github_user_oauth.service import GitHubUserOAuthService
from azents.services.toolkit import ToolkitService


def _member() -> WorkspaceMember:
    return WorkspaceMember(
        user_id="manager",
        session_id="login",
        workspace_id="workspace",
        workspace_user_id="membership",
        role=WorkspaceUserRole.OWNER,
        permissions=get_permissions_for_role(WorkspaceUserRole.OWNER),
    )


@pytest.mark.parametrize("agent_id", [None, "owning-agent"])
@pytest.mark.parametrize("provider_status", [204, 503])
def test_delete_local_completion_does_not_depend_on_provider_success(
    agent_id: str | None,
    provider_status: int,
) -> None:
    events: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        assert request.url.path == "/applications/client/token"
        assert json.loads(request.content) == {"access_token": "captured-token"}
        events.append("provider-revocation")
        return httpx.Response(provider_status)

    def client_factory(auth: BaseAuthStrategy | None) -> GitHub[BaseAuthStrategy]:
        return GitHub[BaseAuthStrategy](
            auth=auth if auth is not None else UnauthAuthStrategy(),
            async_transport=httpx.MockTransport(respond),
            timeout=5.0,
            auto_retry=False,
            http_cache=False,
            follow_redirects=False,
        )

    user_service = GitHubUserOAuthService(
        repository=create_autospec(GitHubUserOAuthOperationRepository, instance=True),
        config=Config.model_construct(),
        platform_runtime=create_autospec(
            PlatformGitHubAppRuntimeService, instance=True
        ),
        provider=GitHubUserProvider(client_factory=client_factory),
    )
    facts = (
        GitHubUserRevocation(
            registration=GitHubUserRegistration(
                source="byoa_user",
                app_id="123",
                client_id="client",
                client_secret="client-secret",
                toolkit_revision=1,
                platform_generation=None,
            ),
            access_token="captured-token",
        ),
    )
    toolkit_service = create_autospec(ToolkitService, instance=True)

    async def delete(*args: object, **kwargs: object) -> Success[None]:
        events.append("local-delete")
        await user_service.cleanup_revocations(facts)
        return Success(None)

    toolkit_service.delete_by_id.side_effect = delete
    toolkit_service.delete_agent_owned.side_effect = delete
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_workspace_member] = _member
    app.dependency_overrides[ToolkitService] = lambda: toolkit_service
    path = "/workspaces/ws"
    if agent_id is not None:
        path += f"/agents/{agent_id}"
    with TestClient(app) as client:
        response = client.delete(path + "/toolkit-configs/toolkit")
    assert response.status_code == 204
    assert response.content == b""
    assert events == ["local-delete", "provider-revocation"]
