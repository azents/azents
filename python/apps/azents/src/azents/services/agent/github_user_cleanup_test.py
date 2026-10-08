"""Parent Agent deletion uses bounded provider cleanup after its local commit."""

import datetime
import json
import logging
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from azcommon.result import Success
from githubkit import BaseAuthStrategy, GitHub, UnauthAuthStrategy

from azents.core.config import Config
from azents.core.enums import (
    AgentDecommissionStatus,
    AgentLifecycleStatus,
    WorkspaceUserRole,
)
from azents.core.github_user_oauth import GitHubUserRegistration, GitHubUserRevocation
from azents.repos.agent_decommission.data import AgentDecommissionJob
from azents.repos.agent_operations import AgentDecommissionRequest
from azents.repos.github_user_oauth.operations import GitHubUserOAuthOperationRepository
from azents.services.github_platform_system_setting.runtime import (
    PlatformGitHubAppRuntimeService,
)
from azents.services.github_user_oauth.provider import GitHubUserProvider
from azents.services.github_user_oauth.service import GitHubUserOAuthService
from azents.testing.types import require_instance

from .service_test import _make_agent, _make_service


@pytest.mark.parametrize("provider_status", [204, 404, 503, None])
async def test_provider_cleanup_does_not_block_committed_agent_decommission(
    provider_status: int | None, caplog: pytest.LogCaptureFixture
) -> None:
    service = _make_service()
    repository = require_instance(service.repository, AsyncMock)
    existing = _make_agent()
    decommissioned = existing.model_copy(
        update={"lifecycle_status": AgentLifecycleStatus.DECOMMISSIONING}
    )
    repository.get_by_id.return_value = existing
    operation_committed = False
    requests: list[httpx.Request] = []
    revocation = GitHubUserRevocation(
        registration=GitHubUserRegistration(
            source="byoa_user",
            app_id="123",
            client_id="client-123",
            client_secret="private-client-secret",
            toolkit_revision=1,
            platform_generation=None,
        ),
        access_token="private-owned-token",
    )
    now = datetime.datetime.now(datetime.UTC)
    job = AgentDecommissionJob(
        id="job-1",
        agent_id=existing.id,
        workspace_id=existing.workspace_id,
        status=AgentDecommissionStatus.PENDING,
        attempt_count=0,
        created_at=now,
        updated_at=now,
    )

    async def commit(
        *, agent_id: str, workspace_user_id: str
    ) -> Success[AgentDecommissionRequest]:
        nonlocal operation_committed
        assert agent_id == existing.id and workspace_user_id == "member-1"
        operation_committed = True
        return Success(
            AgentDecommissionRequest(
                agent=decommissioned,
                job=job,
                github_user_revocations=(revocation,),
            )
        )

    def handle(request: httpx.Request) -> httpx.Response:
        assert operation_committed  # No provider HTTP is inside the local write.
        requests.append(request)
        assert request.method == "DELETE"
        assert request.url.host == "api.github.com"
        assert request.url.path == "/applications/client-123/token"
        assert json.loads(request.content) == {"access_token": "private-owned-token"}
        if provider_status is None:
            raise httpx.ReadTimeout("private-provider-detail", request=request)
        if provider_status == 204:
            return httpx.Response(204)
        return httpx.Response(
            provider_status, json={"message": "private-provider-body"}
        )

    def factory(auth: BaseAuthStrategy | None) -> GitHub[BaseAuthStrategy]:
        return GitHub[BaseAuthStrategy](
            auth=auth if auth is not None else UnauthAuthStrategy(),
            async_transport=httpx.MockTransport(handle),
            auto_retry=False,
            http_cache=False,
            follow_redirects=False,
            timeout=5.0,
        )

    platform = AsyncMock(spec=PlatformGitHubAppRuntimeService)
    service.github_user_oauth_service = GitHubUserOAuthService(
        repository=require_instance(
            AsyncMock(spec=GitHubUserOAuthOperationRepository),
            GitHubUserOAuthOperationRepository,
        ),
        config=require_instance(Mock(spec=Config), Config),
        platform_runtime=require_instance(platform, PlatformGitHubAppRuntimeService),
        provider=GitHubUserProvider(client_factory=factory),
    )
    repository.request_decommission.side_effect = commit
    with caplog.at_level(logging.WARNING):
        result = await service.delete_by_id(
            existing.id,
            workspace_id=existing.workspace_id,
            workspace_user_id="member-1",
            role=WorkspaceUserRole.OWNER,
        )
    assert result.success and result.value.job.id == job.id
    assert operation_committed and len(requests) == 1
    assert "private-owned-token" not in caplog.text
    assert "private-client-secret" not in caplog.text
    assert "private-provider-body" not in caplog.text
    assert "private-provider-detail" not in caplog.text
    platform.resolve.assert_not_awaited()  # Captured BYOA identity is sufficient.


async def test_unauthorized_parent_delete_has_no_local_or_provider_effect() -> None:
    service = _make_service()
    repository = require_instance(service.repository, AsyncMock)
    repository.get_by_id.return_value = _make_agent()
    repository.is_admin.return_value = False
    cleanup = require_instance(service.github_user_oauth_service, AsyncMock)
    result = await service.delete_by_id(
        "agent-1",
        workspace_id="ws-1",
        workspace_user_id="member-1",
        role=WorkspaceUserRole.MEMBER,
    )
    assert result.failure
    repository.request_decommission.assert_not_awaited()
    cleanup.cleanup_revocations.assert_not_awaited()
