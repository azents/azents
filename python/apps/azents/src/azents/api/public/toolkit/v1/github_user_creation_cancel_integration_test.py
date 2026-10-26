"""Scoped HTTP cancellation reaches real creation storage without publication."""

import dataclasses
import datetime
import json
from unittest.mock import create_autospec

import httpx
import pytest
from fastapi import FastAPI
from githubkit import BaseAuthStrategy, GitHub, UnauthAuthStrategy

from azents.api.public.toolkit.v1 import router
from azents.api.public.toolkit.v1.github_user_creation import router as creation_router
from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.core.auth.roles import get_permissions_for_role
from azents.core.config import Config
from azents.core.enums import WorkspaceUserRole
from azents.core.github_user_creation import GitHubUserCreationSubject
from azents.core.github_user_oauth import GitHubUserCandidate
from azents.rdb.models.agent import RDBAgent
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent import AgentRepository
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.github_user_installation import GithubUserInstallationRepository
from azents.repos.github_user_oauth.creation import GitHubUserCreationRepository
from azents.repos.github_user_oauth.operations_test import _harness
from azents.repos.github_user_oauth.payloads import SetupPayload
from azents.repos.mcp_oauth_connection import MCPOAuthConnectionRepository
from azents.repos.toolkit import AgentToolkitRepository, ToolkitRepository
from azents.repos.toolkit.data import ToolkitCreate
from azents.repos.toolkit_namespace import ToolkitNamespaceRepository
from azents.services.github_platform_system_setting.runtime import (
    PlatformGitHubAppRuntimeService,
)
from azents.services.github_user_oauth.creation import GitHubUserCreationService
from azents.services.github_user_oauth.provider import GitHubUserProvider
from azents.services.github_user_oauth.service import GitHubUserOAuthService
from azents.services.toolkit import ToolkitService
from azents.services.toolkit.service_test import _build_service
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_selectable_model_option_dicts,
)


async def _agent(
    manager: SessionManager[WriteSession], workspace_id: str, name: str
) -> str:
    selection = make_test_model_selection().model_dump(mode="json")
    async with manager() as session:
        agent = RDBAgent(
            workspace_id=workspace_id,
            name=name,
            model_selection=selection,
            lightweight_model_selection=selection,
            selectable_model_options=make_test_selectable_model_option_dicts(
                model_selection=selection, lightweight_model_selection=selection
            ),
            main_model_label="default",
            lightweight_model_label="lightweight",
        )
        session.write_session.add(agent)
        await session.write_session.flush()
        return agent.id


@pytest.mark.parametrize("provider_status", [204, 503])
async def test_http_cancel_deletes_only_owned_candidate_and_never_publishes(
    rdb_session_manager: SessionManager[WriteSession], provider_status: int
) -> None:
    h = await _harness(rdb_session_manager)
    agent_id = await _agent(rdb_session_manager, h.requester.workspace_id, "Owner")
    other_agent_id = await _agent(
        rdb_session_manager, h.requester.workspace_id, "Other"
    )
    operations = dataclasses.replace(
        h.repository,
        agent_repository=AgentRepository(),
        agent_admin_repository=AgentAdminRepository(),
    )
    revocations: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        assert request.url.path == "/applications/Iv1.client/token"
        assert json.loads(request.content) == {"access_token": "cancel-canary"}
        revocations.append("exact-candidate")
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

    oauth = GitHubUserOAuthService(
        repository=operations,
        config=Config.model_construct(web_url="https://app.test"),
        platform_runtime=create_autospec(
            PlatformGitHubAppRuntimeService, instance=True
        ),
        provider=GitHubUserProvider(client_factory=client_factory),
    )
    repository = GitHubUserCreationRepository(operations, ToolkitNamespaceRepository())
    subject = GitHubUserCreationSubject(
        h.requester.user_id,
        h.requester.session_id,
        h.requester.workspace_id,
        agent_id,
    )
    started = await repository.start(
        subject,
        desired=ToolkitCreate(
            workspace_id=subject.workspace_id,
            owner_agent_id=agent_id,
            toolkit_type="github",
            slug="unpublished",
            name="Unpublished candidate",
            config={"github_auth_type": "github_app_user"},
            credentials=json.dumps(
                {
                    "type": "github_app_user",
                    "app_id": h.registration.app_id,
                    "client_id": h.registration.client_id,
                    "client_secret": h.registration.client_secret,
                    "private_key": "synthetic-private-key",
                }
            ),
            always_expose_tools=False,
        ),
        setup=SetupPayload(
            registration=h.registration,
            redirect_uri=oauth.callback_url(),
            nonce="candidate-nonce",
            code_verifier="candidate-verifier",
        ),
        expires_at=datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=10),
    )
    await repository.claim(
        subject,
        attempt_id=started.attempt.id,
        nonce="candidate-nonce",
        redirect_uri=oauth.callback_url(),
    )
    await repository.stage(
        subject,
        attempt_id=started.attempt.id,
        registration=h.registration,
        candidate=GitHubUserCandidate("cancel-canary", 42, "reviewed-user", None),
    )
    toolkits = _build_service(
        toolkit_repo=ToolkitRepository(h.cipher),
        mcp_oauth_connection_repo=create_autospec(
            MCPOAuthConnectionRepository, instance=True
        ),
        agent_toolkit_repo=AgentToolkitRepository(),
        agent_repo=AgentRepository(),
        agent_admin_repo=AgentAdminRepository(),
        github_user_installation_repo=GithubUserInstallationRepository(),
        session_manager=rdb_session_manager,
        toolkit_registry={},
        github_runtime=create_autospec(PlatformGitHubAppRuntimeService, instance=True),
    )
    service = GitHubUserCreationService(repository, oauth, toolkits)
    owner = WorkspaceMember(
        user_id=subject.user_id,
        session_id=subject.session_id,
        workspace_id=subject.workspace_id,
        workspace_user_id="m" * 32,
        role=WorkspaceUserRole.OWNER,
        permissions=get_permissions_for_role(WorkspaceUserRole.OWNER),
    )
    member = owner

    def current_member() -> WorkspaceMember:
        return member

    app = FastAPI()
    app.include_router(router)
    app.include_router(creation_router)
    app.dependency_overrides[get_workspace_member] = current_member
    app.dependency_overrides[GitHubUserCreationService] = lambda: service
    app.dependency_overrides[ToolkitService] = lambda: toolkits
    base = f"/workspaces/ws/agents/{agent_id}"
    candidate_path = f"{base}/github-user-creations/{started.attempt.id}"
    inventory_path = f"{base}/toolkit-configs"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        review = await client.get(candidate_path)
        assert review.status_code == 200
        assert review.json()["candidate"]["sharing_scope"] == "agent_only"
        assert review.json()["candidate"]["account_login"] == "reviewed-user"
        assert "cancel-canary" not in review.text
        inventory = await client.get(inventory_path)
        assert inventory.status_code == 200 and inventory.json()["items"] == []
        for field in ("user_id", "session_id", "workspace_id", "agent_id"):
            member = (
                owner
                if field == "agent_id"
                else dataclasses.replace(owner, **{field: "x" * 32})
            )
            path = (
                candidate_path.replace(agent_id, other_agent_id)
                if field == "agent_id"
                else candidate_path
            )
            rejected = await client.delete(path)
            assert rejected.status_code in {403, 404}
            assert revocations == []
            member = owner
            assert (await client.get(candidate_path)).status_code == 200
        cancelled = await client.delete(candidate_path)
        assert cancelled.status_code == 204 and cancelled.content == b""
        assert revocations == ["exact-candidate"]
        assert (await client.get(candidate_path)).status_code == 404
        inventory = await client.get(inventory_path)
        assert inventory.status_code == 200 and inventory.json()["items"] == []
