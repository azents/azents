"""Current user token at live discovery, retained MCP wrappers and new commands."""

import asyncio
import json
from unittest.mock import AsyncMock, create_autospec

import httpx2 as httpx
import pytest
from mcp import MCPError
from mcp.types import CallToolResult, TextContent
from mcp.types import Tool as McpBaseTool

from azents.core.engine_tool_state import McpToolSnapshotState
from azents.core.github_user_oauth import (
    GitHubUserConnection,
    GitHubUserConnectionStatus,
    GitHubUserErrorCode,
    GitHubUserOAuthError,
    GitHubUserRegistration,
)
from azents.core.github_user_runtime import GitHubUserExecutionContext
from azents.core.mcp_transport import McpToolListResult
from azents.core.tools import GitHubToolkitConfig, McpToolkitConfig, ResolveContext
from azents.engine.run.types import FunctionToolError
from azents.engine.tools import mcp_base as mcp_module
from azents.engine.tools.github import (
    GitHubToolkitProvider,
    GitHubUserMcpToolkit,
    GitHubUserToolkit,
)
from azents.engine.tools.mcp_base import (
    McpAuthenticationFailureObserver,
    _build_mcp_tool_snapshot,
)
from azents.services.github_platform_system_setting.runtime import (
    PlatformGitHubAppRuntimeService,
)
from azents.services.github_user_oauth.runtime import GitHubUserRuntimeService


def _context() -> GitHubUserExecutionContext:
    return GitHubUserExecutionContext(
        workspace_id="workspace",
        agent_id="agent",
        session_id="session",
        toolkit_id="toolkit",
        source="byoa_user",
        app_id="123",
        client_id="client",
    )


def _connection(label: str) -> GitHubUserConnection:
    return GitHubUserConnection(
        id=f"connection-{label}",
        toolkit_id="toolkit",
        registration=GitHubUserRegistration(
            source="byoa_user",
            app_id="123",
            client_id="client",
            client_secret=None,
            toolkit_revision=1,
            platform_generation=None,
        ),
        access_token=f"token-{label}",
        account_id=42,
        account_login=f"account-{label}",
        account_avatar_url=None,
        status=GitHubUserConnectionStatus.CONNECTED,
        failure_reason=None,
    )


def _mcp(runtime: GitHubUserRuntimeService) -> GitHubUserMcpToolkit:
    return GitHubUserMcpToolkit(
        config=McpToolkitConfig(server_url="https://mcp.test", auth_type="bearer"),
        context=_context(),
        runtime=runtime,
        proxy_url=None,
        snapshot_factory=None,
    )


def _snapshot() -> McpToolSnapshotState:
    return _build_mcp_tool_snapshot(
        server_url="https://mcp.test",
        mcp_tools=[
            McpBaseTool(
                name="get_me", input_schema={"type": "object", "properties": {}}
            )
        ],
        use_streamable_http=True,
    )


def _failure(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://mcp.test")
    return httpx.HTTPStatusError(
        "Synthetic provider failure",
        request=request,
        response=httpx.Response(status, request=request),
    )


async def test_retained_snapshot_wrapper_resolves_each_current_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = create_autospec(GitHubUserRuntimeService, instance=True)
    runtime.current_connection.side_effect = [_connection("old"), _connection("new")]
    provider = AsyncMock(
        return_value=CallToolResult(content=[TextContent(type="text", text="ok")])
    )
    monkeypatch.setattr(mcp_module, "mcp_call_tool", provider)
    tool = _mcp(runtime)._tools_from_snapshot(_snapshot())[0]
    assert await tool.handler("{}") == "ok"
    assert await tool.handler("{}") == "ok"
    assert [call.args[1]["Authorization"] for call in provider.await_args_list] == [
        "Bearer token-old",
        "Bearer token-new",
    ]
    assert runtime.current_connection.await_count == 2
    runtime.authentication_failed.assert_not_awaited()


async def test_disconnected_call_uses_no_provider_or_cached_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = create_autospec(GitHubUserRuntimeService, instance=True)
    runtime.current_connection.side_effect = GitHubUserOAuthError(
        GitHubUserErrorCode.AUTHORITY,
        "Current authorization unavailable.",
    )
    provider = AsyncMock()
    monkeypatch.setattr(mcp_module, "mcp_call_tool", provider)
    tool = _mcp(runtime)._tools_from_snapshot(_snapshot())[0]
    with pytest.raises(FunctionToolError, match="unavailable"):
        await tool.handler("{}")
    provider.assert_not_awaited()


async def test_user_action_error_is_sanitized_without_invalidating_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = create_autospec(GitHubUserRuntimeService, instance=True)
    runtime.current_connection.return_value = _connection("current")
    provider = AsyncMock(
        return_value=CallToolResult(
            is_error=True,
            content=[TextContent(type="text", text="untrusted-private-provider-body")],
        )
    )
    monkeypatch.setattr(mcp_module, "mcp_call_tool", provider)
    tool = _mcp(runtime)._tools_from_snapshot(_snapshot())[0]
    with pytest.raises(FunctionToolError, match="target access") as caught:
        await tool.handler("{}")
    assert "untrusted-private-provider-body" not in str(caught.value)
    runtime.authentication_failed.assert_not_awaited()


@pytest.mark.parametrize("status", [401, 403])
async def test_auth_observation_survives_normalized_mcp_error(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    runtime = create_autospec(GitHubUserRuntimeService, instance=True)
    runtime.current_connection.return_value = _connection("current")

    async def provider(
        *args: object, auth: httpx.Auth | None, **kwargs: object
    ) -> CallToolResult:
        del args, kwargs
        assert isinstance(auth, McpAuthenticationFailureObserver)
        request = httpx.Request("POST", "https://mcp.test")
        flow = auth.async_auth_flow(request)
        assert await anext(flow) is request
        with pytest.raises(StopAsyncIteration):
            await flow.asend(httpx.Response(status, request=request))
        runtime.authentication_failed.assert_not_awaited()
        raise ExceptionGroup(
            "SDK normalized transport failure",
            [MCPError(-32000, "Session terminated")],
        )

    monkeypatch.setattr(mcp_module, "mcp_call_tool", provider)
    tool = _mcp(runtime)._tools_from_snapshot(_snapshot())[0]
    with pytest.raises(FunctionToolError):
        await tool.handler("{}")
    if status == 401:
        runtime.authentication_failed.assert_awaited_once_with(
            _context(), connection_id="connection-current"
        )
    else:
        runtime.authentication_failed.assert_not_awaited()


async def test_auth_failure_publication_does_not_hide_programming_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = create_autospec(GitHubUserRuntimeService, instance=True)
    runtime.current_connection.return_value = _connection("current")
    runtime.authentication_failed.side_effect = RuntimeError("Local persistence defect")
    monkeypatch.setattr(
        mcp_module, "mcp_call_tool", AsyncMock(side_effect=_failure(401))
    )
    tool = _mcp(runtime)._tools_from_snapshot(_snapshot())[0]
    with pytest.raises(RuntimeError, match="Local persistence defect"):
        await tool.handler("{}")


@pytest.mark.parametrize("status", [401, 403, 404, 500])
async def test_only_definite_auth_failure_is_published_without_reissue(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    runtime = create_autospec(GitHubUserRuntimeService, instance=True)
    runtime.current_connection.return_value = _connection("old")
    provider = AsyncMock(side_effect=_failure(status))
    monkeypatch.setattr(mcp_module, "mcp_call_tool", provider)
    tool = _mcp(runtime)._tools_from_snapshot(_snapshot())[0]
    with pytest.raises((FunctionToolError, httpx.HTTPStatusError)):
        await tool.handler("{}")
    assert provider.await_count == 1
    if status == 401:
        runtime.authentication_failed.assert_awaited_once_with(
            _context(), connection_id="connection-old"
        )
    else:
        runtime.authentication_failed.assert_not_awaited()


async def test_concurrent_old_failure_publishes_its_own_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = create_autospec(GitHubUserRuntimeService, instance=True)
    runtime.current_connection.side_effect = [_connection("old"), _connection("new")]
    entered, release = asyncio.Event(), asyncio.Event()

    async def provider(
        server: str, headers: dict[str, str], *args: object, **kwargs: object
    ) -> CallToolResult:
        del server, args, kwargs
        if headers["Authorization"] == "Bearer token-old":
            entered.set()
            await release.wait()
            raise _failure(401)
        return CallToolResult(content=[TextContent(type="text", text="new-call-ok")])

    monkeypatch.setattr(mcp_module, "mcp_call_tool", provider)
    tool = _mcp(runtime)._tools_from_snapshot(_snapshot())[0]
    old = asyncio.ensure_future(tool.handler("{}"))
    await entered.wait()
    assert await tool.handler("{}") == "new-call-ok"
    release.set()
    with pytest.raises(FunctionToolError):
        await old
    runtime.authentication_failed.assert_awaited_once_with(
        _context(), connection_id="connection-old"
    )


@pytest.mark.parametrize("failure", [None, 401, 403])
async def test_live_discovery_uses_current_authorization(
    monkeypatch: pytest.MonkeyPatch,
    failure: int | None,
) -> None:
    runtime = create_autospec(GitHubUserRuntimeService, instance=True)
    runtime.current_connection.return_value = _connection("current")
    discovery = AsyncMock(
        return_value=McpToolListResult(tools=[], use_streamable_http=True),
        side_effect=None if failure is None else _failure(failure),
    )
    monkeypatch.setattr(mcp_module, "mcp_list_tools", discovery)
    await _mcp(runtime)._connect_and_list_tools()
    assert discovery.await_args is not None
    assert discovery.await_args.args[1] == {"Authorization": "Bearer token-current"}
    if failure == 401:
        runtime.authentication_failed.assert_awaited_once_with(
            _context(), connection_id="connection-current"
        )
    else:
        runtime.authentication_failed.assert_not_awaited()


async def test_new_command_environment_uses_no_user_ttl_or_installation_map() -> None:
    runtime = create_autospec(GitHubUserRuntimeService, instance=True)
    config = GitHubToolkitConfig(github_auth_type="github_app_user")
    toolkit = GitHubUserToolkit(
        config=config,
        mcp_toolkit=_mcp(runtime),
        context=_context(),
        runtime=runtime,
    )
    assert await toolkit.expose_env() == {}
    runtime.current_connection.assert_not_awaited()
    config.inject_runtime_environment = True
    runtime.runtime_environment.side_effect = [
        {"GH_TOKEN": "token-old", "GITHUB_TOKEN": "token-old"},
        {"GH_TOKEN": "token-new", "GITHUB_TOKEN": "token-new"},
    ]
    assert await toolkit.expose_env() == {
        "GH_TOKEN": "token-old",
        "GITHUB_TOKEN": "token-old",
    }
    assert await toolkit.expose_env() == {
        "GH_TOKEN": "token-new",
        "GITHUB_TOKEN": "token-new",
    }
    runtime.runtime_environment.side_effect = GitHubUserOAuthError(
        GitHubUserErrorCode.AUTHORITY,
        "Current authorization unavailable.",
    )
    with pytest.raises(FunctionToolError):
        await toolkit.expose_env()
    assert toolkit._runtime_environment_token_cache is None


@pytest.mark.parametrize("platform", [False, True])
async def test_provider_resolves_user_mode_using_team_context_only(
    platform: bool,
) -> None:
    runtime = create_autospec(GitHubUserRuntimeService, instance=True)
    runtime.current_connection.return_value = _connection("current")
    settings = create_autospec(PlatformGitHubAppRuntimeService, instance=True)
    mode = "github_app_platform_user" if platform else "github_app_user"
    credentials = {"type": mode, "app_id": "123"}
    if not platform:
        credentials.update(
            client_id="client", client_secret="secret", private_key="private-key"
        )
    provider = GitHubToolkitProvider(
        platform_runtime=settings,
        user_runtime=runtime,
        user_mcp_server_url=None,
        snapshot_factory=None,
    )
    toolkit = await provider.resolve(
        GitHubToolkitConfig(github_auth_type=mode),
        ResolveContext(
            toolkit_id="toolkit",
            toolkit_name="GitHub",
            credentials_json=json.dumps(credentials),
            agent_id="agent",
            session_id="session",
            workspace_id="workspace",
            workspace_handle=None,
            web_url=None,
            oauth_secret_key=None,
        ),
    )
    assert isinstance(toolkit, GitHubUserToolkit)
    assert toolkit.user_context.source == ("platform_user" if platform else "byoa_user")
    assert toolkit.user_context.client_id == (None if platform else "client")
    assert toolkit.user_context.session_id == "session"
    runtime.current_connection.assert_awaited_once_with(toolkit.user_context)
    settings.resolve.assert_not_awaited()
    assert await toolkit.expose_env() == {}
