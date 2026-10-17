"""Personal MCP discovery, cached dispatch and OAuth finalization current authority."""

import datetime
from typing import Literal
from unittest.mock import AsyncMock

import httpx
import pytest
from mcp.types import CallToolResult, TextContent
from mcp.types import Tool as RemoteTool

from azents.core.enums import MCPOAuthConnectionStatus
from azents.core.mcp_transport import McpToolListResult
from azents.core.oauth2 import OAuthTokenError, OAuthTokenResponse
from azents.core.personal_toolkit import PersonalToolkitAccessMutation
from azents.core.personal_toolkit_runtime import PersonalToolkitExecutionDenied
from azents.core.toolkit_ownership import PersonalToolkitAccessMode as Mode
from azents.core.tools import McpToolkitConfig
from azents.engine.run.types import FunctionToolError
from azents.engine.tooling.personal_admission import PersonalToolkitAdmission
from azents.engine.tools import mcp as mcp_module
from azents.engine.tools import mcp_base
from azents.engine.tools.mcp import McpToolkit
from azents.engine.tools.notion import NotionToolkit
from azents.engine.tools.sentry import SentryToolkit
from azents.repos.engine_tool_repositories import EngineMcpSnapshotFactory
from azents.repos.mcp_oauth_connection import MCPOAuthConnectionRepository
from azents.repos.mcp_oauth_connection.operations import (
    MCPOAuthRuntimeOperationRepository,
)
from azents.repos.toolkit.personal_runtime_test import Harness, Root
from azents.repos.toolkit.personal_runtime_test import (
    fixture as fixture,  # noqa: PLC0414 -- committed PostgreSQL ownership fixture
)
from azents.repos.toolkit.personal_runtime_test import (
    runtime as runtime,  # noqa: PLC0414 -- canonical root/current source fixture
)
from azents.repos.toolkit.personal_test import creation


async def restrict(h: Harness, root: Root, toolkit_id: str) -> None:
    await h.foundation.operations.mutate_access(
        user_id=h.foundation.user_id,
        mutations=[
            PersonalToolkitAccessMutation(
                toolkit_id, None, frozenset(), frozenset([root.agent_id]), Mode.ALL
            )
        ],
    )


@pytest.mark.parametrize(
    "timing",
    ["before_discovery", "after_discovery", "authorization_gap", "discovery_gap"],
)
@pytest.mark.parametrize("composition", ["mcp", "notion", "sentry"])
async def test_personal_mcp_background_and_cached_calls_recheck_current_source(
    runtime: Harness,
    monkeypatch: pytest.MonkeyPatch,
    timing: str,
    composition: str,
) -> None:
    h = runtime
    saved = await h.foundation.operations.create(
        user_id=h.foundation.user_id, create=creation()
    )
    root = await h.root(h.foundation.user_id, 0)
    [source] = await h.sources(root)
    toolkit = McpToolkit(
        config=McpToolkitConfig(server_url="https://mcp.test", auth_type="bearer"),
        secret="fixture-personal-token",
        snapshot_factory=EngineMcpSnapshotFactory(
            h.foundation.writes, h.foundation.writes
        ),
        agent_id=root.agent_id,
        session_id=root.owner.session_id,
    )
    guard = PersonalToolkitAdmission(h.repository, source.target)
    if composition == "notion":
        wrapper = NotionToolkit(mcp_toolkit=toolkit)
        wrapper.bind_effect_admission(guard)
    elif composition == "sentry":
        sentry = SentryToolkit(mcp_toolkit=toolkit, enabled_skills=["inspect"])
        sentry.bind_effect_admission(guard)
    else:
        toolkit.bind_effect_admission(guard)
    assert toolkit.effect_admission is guard
    remote = RemoteTool(
        name="send", description="Send", input_schema={"type": "object"}
    )
    listing = AsyncMock(return_value=McpToolListResult([remote], True))
    call = AsyncMock(
        return_value=CallToolResult(
            content=[TextContent(type="text", text="fixture-result")]
        )
    )
    monkeypatch.setattr(mcp_base, "mcp_list_tools", listing)
    monkeypatch.setattr(mcp_base, "mcp_call_tool", call)
    if timing == "discovery_gap":

        async def discover(*args: object, **kwargs: object) -> McpToolListResult:
            del args, kwargs
            await restrict(h, root, saved.id)
            return McpToolListResult([remote], True)

        listing.side_effect = discover
    if timing == "authorization_gap":
        original = toolkit._request_authorization

        async def authorize() -> mcp_base.McpRequestAuthorization:
            result = await original()
            await restrict(h, root, saved.id)
            return result

        monkeypatch.setattr(toolkit, "_request_authorization", authorize)
    if timing == "before_discovery":
        await restrict(h, root, saved.id)
    await toolkit._connect_and_list_tools()
    if timing == "discovery_gap":
        listing.assert_awaited_once()
        assert toolkit._bg_error is not None
        assert await toolkit._load_tool_snapshot() is None
    elif timing != "after_discovery":
        listing.assert_not_awaited()
        assert toolkit._bg_error is not None
    else:
        listing.assert_awaited_once()
        assert await toolkit._load_tool_snapshot() is not None
        snapshot = mcp_base._build_mcp_tool_snapshot(
            server_url="https://mcp.test", mcp_tools=[remote], use_streamable_http=True
        )
        [prepared] = toolkit._tools_from_snapshot(snapshot)
        await restrict(h, root, saved.id)
        with pytest.raises(FunctionToolError):
            await prepared.handler("{}")
        await toolkit._connect_and_list_tools()
        listing.assert_awaited_once()
    call.assert_not_awaited()


@pytest.mark.parametrize("outcome", ["success", "invalid_grant", "transient"])
@pytest.mark.parametrize("withdrawal", ["before", "during", "none"])
async def test_personal_oauth_refresh_cannot_publish_after_current_allowance_withdrawal(
    runtime: Harness,
    monkeypatch: pytest.MonkeyPatch,
    outcome: Literal["success", "invalid_grant", "transient"],
    withdrawal: str,
) -> None:
    h = runtime
    f = h.foundation
    saved = await f.operations.create(
        user_id=f.user_id,
        create=creation().model_copy(
            update={
                "config": {"server_url": "https://mcp.test", "auth_type": "oauth2"},
                "credentials": None,
            }
        ),
    )
    assert f.repository.cipher is not None
    grants = MCPOAuthConnectionRepository(f.repository.cipher)
    async with f.writes() as session:
        await grants.upsert_connected(
            session,
            toolkit_id=saved.id,
            issuer=None,
            resource="https://mcp.test",
            server_url="https://mcp.test",
            authorization_endpoint="https://oauth.test/authorize",
            token_endpoint="https://oauth.test/token",
            registration_endpoint=None,
            client_id="fixture-client",
            client_secret="fixture-secret",
            token_endpoint_auth_method="client_secret_post",
            scope="read",
            access_token="fixture-old-token",
            refresh_token="fixture-renewal",
            expires_at=datetime.datetime.now(datetime.UTC)
            - datetime.timedelta(minutes=1),
        )
    root = await h.root(f.user_id, 0)
    [source] = await h.sources(root)
    operations = MCPOAuthRuntimeOperationRepository(f.writes, grants).for_personal(
        source.target
    )

    async def refresh(**kwargs: object) -> OAuthTokenResponse:
        del kwargs
        if withdrawal == "during":
            await restrict(h, root, saved.id)
        if outcome == "invalid_grant":
            raise OAuthTokenError("invalid_grant")
        if outcome == "transient":
            raise httpx.ConnectError("fixture temporary outage")
        return OAuthTokenResponse(
            access_token="fixture-new-token", refresh_token="fixture-new-renewal"
        )

    external = AsyncMock(side_effect=refresh)
    monkeypatch.setattr(mcp_module, "refresh_access_token", external)
    if withdrawal == "before":
        await restrict(h, root, saved.id)
    if withdrawal == "none":
        result = await mcp_module._ensure_oauth_connection_token(
            operations=operations, toolkit_id=saved.id, proxy_url=None
        )
        assert result is not None
        assert result.access_token == (
            "fixture-new-token" if outcome == "success" else "fixture-old-token"
        )
    else:
        with pytest.raises(PersonalToolkitExecutionDenied):
            await mcp_module._ensure_oauth_connection_token(
                operations=operations, toolkit_id=saved.id, proxy_url=None
            )
    async with f.writes() as session:
        current = await grants.get_by_toolkit_id(session, saved.id)
    assert current is not None
    if withdrawal != "none":
        assert current.access_token == "fixture-old-token"
        assert current.refresh_token == "fixture-renewal"
        assert current.status is MCPOAuthConnectionStatus.CONNECTED
    elif outcome == "invalid_grant":
        assert current.status is MCPOAuthConnectionStatus.RECONNECT_REQUIRED
    if withdrawal == "before":
        external.assert_not_awaited()
    else:
        external.assert_awaited_once()
