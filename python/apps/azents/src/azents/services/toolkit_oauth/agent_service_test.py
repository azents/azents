"""Agent OAuth orchestration preserves completed authority and API projections."""

import asyncio
from typing import NoReturn
from unittest.mock import create_autospec
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from azcommon.result import Result, Success

from azents.api.public.toolkit.v1 import oauth
from azents.core import tools
from azents.core.enums import WorkspaceUserRole
from azents.core.oauth2 import (
    create_agent_toolkit_oauth_state,
    verify_agent_github_platform_oauth_state,
    verify_platform_oauth_state,
)
from azents.core.system_setting import SystemSettingFieldSource
from azents.engine.tools.mcp import McpToolkitProvider
from azents.repos.toolkit_oauth_data import SharedOAuthContext
from azents.services.agent.data import NotAdmin
from azents.services.github_platform_system_setting.runtime import (
    ResolvedPlatformGitHubApp,
)
from azents.services.toolkit import ToolkitService
from azents.services.toolkit.data import AgentToolkitOAuthContext, ToolkitOutput
from azents.services.toolkit_oauth import helpers
from azents.services.toolkit_oauth import service as service_module
from azents.services.toolkit_oauth.service_test import (
    _connection,
    _harness,
    _member,
    _patch_discovery,
    _toolkit,
)


@pytest.fixture(autouse=True)
def _deny_live_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every provider effect must have an explicit local collaborator."""

    def reject(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("External collaborator was not explicitly mocked.")

    monkeypatch.setattr(httpx, "AsyncClient", reject)


@pytest.mark.parametrize("scope", ["shared", "agent"])
@pytest.mark.parametrize("outcome", ["success", "http_error", "cancel"])
async def test_install_url_provider_effects_follow_completed_admission(
    monkeypatch: pytest.MonkeyPatch, scope: str, outcome: str
) -> None:
    """URL projection preserves provider failures and exact Agent admission."""
    h = _harness(SharedOAuthContext(None, None), Success(None))
    toolkits = create_autospec(ToolkitService, instance=True)

    async def authorize(*args: object, **kwargs: object) -> Result[None, NotAdmin]:
        async with h.boundary.operation("agent-authorize"):
            return Success(None)

    async def resolve() -> ResolvedPlatformGitHubApp:
        h.boundary.external("platform")
        return ResolvedPlatformGitHubApp(
            app_id="123",
            client_id="platform-client",
            private_key="synthetic-key",
            client_secret="platform-secret",
            app_id_source=SystemSettingFieldSource.ADMIN,
            effective_generation="generation-1",
        )

    def jwt(app_id: str, private_key: str) -> str:
        h.boundary.external("jwt")
        assert (app_id, private_key) == ("123", "synthetic-key")
        return "synthetic-jwt"

    failure = (
        asyncio.CancelledError()
        if outcome == "cancel"
        else httpx.HTTPStatusError(
            "synthetic",
            request=httpx.Request("GET", "https://api.github.test/app"),
            response=httpx.Response(503),
        )
    )

    async def slug(token: str) -> str:
        h.boundary.external("app")
        assert token == "synthetic-jwt"
        if outcome != "success":
            raise failure
        return "actual-app"

    toolkits.authorize_agent_management.side_effect = authorize
    h.runtime.resolve.side_effect = resolve
    monkeypatch.setattr(service_module, "create_github_app_jwt", jwt)
    monkeypatch.setattr(service_module, "get_app_slug", slug)

    async def invoke() -> oauth.GitHubPlatformInstallUrlResponse:
        member = _member(WorkspaceUserRole.OWNER)
        if scope == "agent":
            return await oauth.get_agent_github_platform_install_url(
                member, toolkits, h.runtime, handle="workspace", agent_id="agent-1"
            )
        return await oauth.get_github_platform_install_url(
            member, h.runtime, handle="workspace"
        )

    if outcome == "success":
        response = await invoke()
        assert response.install_url == (
            "https://github.com/apps/actual-app/installations/new"
        )
    elif outcome == "cancel":
        with pytest.raises(asyncio.CancelledError) as raised:
            await invoke()
        assert raised.value is failure
    else:
        with pytest.raises(RuntimeError, match="App info: HTTP 503"):
            await invoke()
    assert h.boundary.calls == (
        ["agent-authorize:open", "agent-authorize:closed"] if scope == "agent" else []
    ) + ["platform", "jwt", "app"]


@pytest.mark.parametrize("scope", ["shared", "agent"])
async def test_platform_oauth_url_keeps_registered_generation_and_callback_scope(
    scope: str,
) -> None:
    """Signed state projects through the unchanged Public route response."""
    h = _harness(SharedOAuthContext(None, None), Success(None))
    toolkits = create_autospec(ToolkitService, instance=True)

    async def authorize(*args: object, **kwargs: object) -> Result[None, NotAdmin]:
        async with h.boundary.operation("agent-authorize"):
            return Success(None)

    toolkits.authorize_agent_management.side_effect = authorize
    member = _member(WorkspaceUserRole.OWNER)
    if scope == "agent":
        response = await oauth.get_agent_github_platform_oauth_url(
            member,
            toolkits,
            h.service.config,
            h.runtime,
            handle="workspace",
            agent_id="agent-1",
        )
    else:
        response = await oauth.get_github_platform_oauth_url(
            member, h.service.config, h.runtime, handle="workspace"
        )
    parsed = urlsplit(response.oauth_url)
    assert (parsed.scheme, parsed.netloc, parsed.path) == (
        "https",
        "github.com",
        "/login/oauth/authorize",
    )
    query = parse_qs(parsed.query)
    assert query["client_id"] == ["platform-client"]
    assert query["redirect_uri"] == ["https://app.test/oauth/github/callback"]
    if scope == "agent":
        state = verify_agent_github_platform_oauth_state(
            query["state"][0], "state-secret"
        )
        assert state is not None
        assert (
            state.workspace_id,
            state.agent_id,
            state.user_id,
            state.redirect_uri,
            state.callback_target,
        ) == (
            "workspace-1",
            "agent-1",
            "user-1",
            "https://app.test/oauth/github/callback",
            "agent_github_installations",
        )
        assert state.effective_generation == "generation-1"
    else:
        shared_state = verify_platform_oauth_state(query["state"][0], "state-secret")
        assert shared_state is not None
        assert shared_state.effective_generation == "generation-1"


@pytest.mark.parametrize("saved", [False, True])
@pytest.mark.parametrize("outcome", ["success", "error", "cancel"])
async def test_agent_connection_probe_runs_after_completed_authority(
    monkeypatch: pytest.MonkeyPatch, saved: bool, outcome: str
) -> None:
    """Both Agent probe paths retain credentials and transparent failures."""
    h = _harness(SharedOAuthContext(None, None), Success(None))
    toolkits = create_autospec(ToolkitService, instance=True)
    toolkit = ToolkitOutput.model_validate(
        _toolkit(None)
        .model_copy(
            update={
                "owner_agent_id": "agent-1",
                "config": {"server_url": "https://mcp.test", "auth_type": "bearer"},
                "credentials": '{"type":"bearer","token":"stored"}',
            }
        )
        .model_dump()
    )

    async def authorize(*args: object, **kwargs: object) -> Result[None, NotAdmin]:
        async with h.boundary.operation("agent-authorize"):
            return Success(None)

    async def read(*args: object, **kwargs: object) -> Result[ToolkitOutput, NotAdmin]:
        async with h.boundary.operation("agent-toolkit"):
            return Success(toolkit)

    failure = asyncio.CancelledError() if outcome == "cancel" else RuntimeError("probe")

    async def probe(
        self: McpToolkitProvider,
        validated: tools.McpToolkitConfig,
        credentials_json: str | None,
        proxy_url: str | None,
    ) -> tools.TestConnectionResult:
        h.boundary.external("provider")
        assert validated.server_url == "https://mcp.test"
        assert credentials_json == (
            '{"type":"bearer","token":"stored"}'
            if saved
            else '{"type": "bearer", "token": "form"}'
        )
        if outcome != "success":
            raise failure
        return tools.TestConnectionResult(
            success=True,
            message="verified",
            discovered_auth_url="https://mcp.test/authorize",
            discovered_token_url="https://mcp.test/token",
            supports_dcr=True,
        )

    toolkits.authorize_agent_management.side_effect = authorize
    toolkits.get_agent_owned.side_effect = read
    monkeypatch.setattr(McpToolkitProvider, "test_connection", probe)

    async def invoke() -> oauth.TestConnectionResponse:
        member = _member(WorkspaceUserRole.OWNER)
        if saved:
            return await oauth.test_agent_connection_saved(
                member,
                toolkits,
                h.service.config,
                h.service.registry,
                agent_id="agent-1",
                toolkit_config_id="toolkit-1",
            )
        return await oauth.test_agent_connection_unsaved(
            member,
            toolkits,
            h.service.config,
            h.runtime,
            h.service.registry,
            agent_id="agent-1",
            body=oauth.TestConnectionRequest(
                toolkit_type="mcp",
                config={"server_url": "https://mcp.test", "auth_type": "bearer"},
                credentials={"type": "bearer", "token": "form"},
                toolkit_config_id=None,
            ),
        )

    if outcome == "success":
        response = await invoke()
        assert response.success and response.message == "verified"
        assert response.discovered_auth_url == "https://mcp.test/authorize"
        assert response.discovered_token_url == "https://mcp.test/token"
        assert response.supports_dcr is True
    else:
        with pytest.raises(type(failure)) as raised:
            await invoke()
        assert raised.value is failure
    assert h.boundary.calls == (
        ["agent-toolkit:open", "agent-toolkit:closed"]
        if saved
        else ["agent-authorize:open", "agent-authorize:closed"]
    ) + ["provider"]


@pytest.mark.parametrize("stage", ["discovery", "dcr", "exchange"])
@pytest.mark.parametrize("cancel", [False, True])
async def test_agent_oauth_external_failure_does_not_start_persistence(
    monkeypatch: pytest.MonkeyPatch, stage: str, cancel: bool
) -> None:
    """Completed preflight cannot become a write after failed external work."""
    h = _harness(SharedOAuthContext(None, None), Success(None))
    toolkits = create_autospec(ToolkitService, instance=True)
    toolkit = ToolkitOutput.model_validate(
        _toolkit(None)
        .model_copy(update={"owner_agent_id": "agent-1", "credentials": None})
        .model_dump()
    )

    async def read(
        *args: object, **kwargs: object
    ) -> Result[AgentToolkitOAuthContext, NotAdmin]:
        async with h.boundary.operation("agent-context"):
            return Success(AgentToolkitOAuthContext(toolkit, _connection()))

    toolkits.get_agent_oauth_context.side_effect = read
    failure = asyncio.CancelledError() if cancel else RuntimeError("external")

    async def fail(*args: object, **kwargs: object) -> NoReturn:
        h.boundary.external(stage)
        raise failure

    if stage == "discovery":
        monkeypatch.setattr(helpers, "discover_required_metadata", fail)
    elif stage == "dcr":

        async def without_connection(
            *args: object, **kwargs: object
        ) -> Result[AgentToolkitOAuthContext, NotAdmin]:
            async with h.boundary.operation("agent-context"):
                return Success(AgentToolkitOAuthContext(toolkit, None))

        toolkits.get_agent_oauth_context.side_effect = without_connection
        _patch_discovery(monkeypatch, h.boundary)
        monkeypatch.setattr(service_module, "register_client", fail)
    else:
        monkeypatch.setattr(helpers, "exchange_and_handle_errors", fail)
    with pytest.raises(type(failure)) as raised:
        if stage == "exchange":
            await oauth.exchange_agent_oauth_connection(
                _member(WorkspaceUserRole.OWNER),
                toolkits,
                h.service.config,
                h.service.registry,
                oauth.OAuthExchangeRequest(
                    code="code",
                    state=create_agent_toolkit_oauth_state(
                        toolkit_id="toolkit-1",
                        workspace_id="workspace-1",
                        agent_id="agent-1",
                        user_id="user-1",
                        redirect_uri=(
                            "https://app.test/oauth/mcp/callback"
                            "?handle=workspace&agent_id=agent-1"
                            "&toolkit_config_id=toolkit-1"
                        ),
                        code_verifier="verifier",
                        callback_target="agent_toolkits",
                        secret_key="state-secret",
                    ),
                ),
                handle="workspace",
                agent_id="agent-1",
                toolkit_config_id="toolkit-1",
            )
        else:
            await oauth.connect_agent_oauth(
                _member(WorkspaceUserRole.OWNER),
                toolkits,
                h.service.config,
                h.service.registry,
                handle="workspace",
                agent_id="agent-1",
                toolkit_config_id="toolkit-1",
            )
    assert raised.value is failure
    toolkits.store_agent_oauth_connection.assert_not_awaited()
    assert not h.boundary.active
