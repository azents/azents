"""AWS/GCP authenticated background and credential gaps retain personal admission."""

from unittest.mock import AsyncMock

import pytest
from botocore.credentials import Credentials
from mcp.types import Tool as RemoteTool

from azents.core.engine_tool_state import McpToolSnapshotItem, McpToolSnapshotState
from azents.core.mcp_transport import McpToolListResult
from azents.core.tools import AwsToolkitConfig, GcpService, GcpToolkitConfig
from azents.engine.run.types import FunctionToolError
from azents.engine.tooling.personal_admission import PersonalToolkitAdmission
from azents.engine.tools import aws, gcp
from azents.engine.tools.personal_mcp_test import restrict
from azents.repos.engine_tool_repositories import EngineMcpSnapshotFactory
from azents.repos.toolkit.personal_runtime_test import Harness
from azents.repos.toolkit.personal_runtime_test import (
    fixture as fixture,  # noqa: PLC0414 -- shared committed ownership fixture
)
from azents.repos.toolkit.personal_runtime_test import (
    runtime as runtime,  # noqa: PLC0414 -- canonical root and current policy
)
from azents.repos.toolkit.personal_test import creation


@pytest.mark.parametrize("family", ["aws", "gcp"])
@pytest.mark.parametrize(
    "timing", ["before", "credential_gap", "after_discovery", "discovery_gap"]
)
async def test_cloud_background_and_cached_handlers_use_current_personal_source(
    runtime: Harness,
    monkeypatch: pytest.MonkeyPatch,
    family: str,
    timing: str,
) -> None:
    h = runtime
    saved = await h.foundation.operations.create(
        user_id=h.foundation.user_id,
        workspace_id=h.foundation.workspace_ids[0],
        create=creation().model_copy(update={"toolkit_type": family}),
    )
    root = await h.root(h.foundation.user_id, 0)
    [source] = await h.sources(root)

    async def withdraw() -> None:
        await restrict(h, root, saved.id)

    async def credentials() -> Credentials:
        if timing == "credential_gap":
            await withdraw()
        return Credentials("fixture-key", "fixture-secret", "fixture-token")

    async def token() -> str:
        if timing == "credential_gap":
            await withdraw()
        return "fixture-gcp-token"

    endpoint = "https://fixture.test/mcp"
    if family == "aws":
        provider = AsyncMock(spec=aws.AwsCredentialProvider)
        provider.get_credentials.side_effect = credentials
        credential_effect = provider.get_credentials
        toolkit = aws.AwsToolkit(
            config=AwsToolkitConfig(),
            credential_provider=provider,
            default_region="us-east-1",
            timeout=30,
            proxy_url=None,
            artifact_service=None,
            snapshot_factory=EngineMcpSnapshotFactory(
                h.foundation.writes, h.foundation.writes
            ),
            agent_id=root.agent_id,
            session_id=root.owner.session_id,
            state_name="fixture",
        )
        snapshot_server = aws._AWS_MCP_ENDPOINT
        module = aws
    else:
        tokens = AsyncMock(spec=gcp.GcpAccessTokenProvider)
        tokens.get_token.side_effect = token
        credential_effect = tokens.get_token
        toolkit = gcp.GcpToolkit(
            config=GcpToolkitConfig(project_id="fixture-project"),
            token_provider=tokens,
            server_configs=[gcp._GcpServerConfig(GcpService.LOGGING, endpoint, 30)],
            project_id="fixture-project",
            writable_services=set(),
            proxy_url=None,
            artifact_service=None,
            snapshot_factory=EngineMcpSnapshotFactory(
                h.foundation.writes, h.foundation.writes
            ),
            agent_id=root.agent_id,
            session_id=root.owner.session_id,
            state_name="fixture",
        )
        snapshot_server = "fixture-project"
        module = gcp
    toolkit.bind_effect_admission(PersonalToolkitAdmission(h.repository, source.target))
    listing = AsyncMock(
        return_value=McpToolListResult(
            [
                RemoteTool(
                    name="send", description="Send", input_schema={"type": "object"}
                )
            ],
            True,
        )
    )
    call = AsyncMock()
    monkeypatch.setattr(module, "mcp_list_tools", listing)
    monkeypatch.setattr(module, "mcp_call_tool", call)
    if timing == "discovery_gap":
        result = listing.return_value

        async def discover(*args: object, **kwargs: object) -> McpToolListResult:
            del args, kwargs
            await withdraw()
            return result

        listing.side_effect = discover
    if timing == "before":
        await withdraw()
    await toolkit._refresh_tool_snapshot()
    if timing == "discovery_gap":
        listing.assert_awaited_once()
        credential_effect.assert_awaited_once()
        assert await toolkit._load_tool_snapshot() is None
    elif timing == "after_discovery":
        listing.assert_awaited_once()
        credential_effect.assert_awaited_once()
        snapshot = McpToolSnapshotState(
            server_url=snapshot_server,
            tools=[
                McpToolSnapshotItem(
                    raw_name="send",
                    model_name="send",
                    description="Send",
                    input_schema={"type": "object"},
                    server_url=endpoint,
                    use_streamable_http=True,
                )
            ],
        )
        [handler] = toolkit._tools_from_snapshot(snapshot)
        await withdraw()
        with pytest.raises(FunctionToolError):
            await handler.handler("{}")
        await toolkit._refresh_tool_snapshot()
        listing.assert_awaited_once()
        credential_effect.assert_awaited_once()
    else:
        listing.assert_not_awaited()
        if timing == "credential_gap":
            credential_effect.assert_awaited_once()
        else:
            credential_effect.assert_not_awaited()
    call.assert_not_awaited()
