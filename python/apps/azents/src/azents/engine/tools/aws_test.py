"""AWS Toolkit update_context() tests.

Validate that AwsToolkit.update_context() collects MCP tools with SigV4
authentication and creates prompt correctly. Also validate background connection
(__aenter__ -> update_context -> __aexit__).
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from mcp.types import Tool as McpBaseTool

from azents.core.tools import AwsToolkitConfig, ToolkitState, TurnContext
from azents.engine.tools.aws import AwsCredentialProvider, AwsToolkit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context(
    *,
    user_id: str | None = "user-1",
) -> TurnContext:
    """Create TurnContext for tests."""
    return TurnContext(
        user_id=user_id,
        workspace_id="ws-1",
        model="test-model",
        run_id="run-1",
        publish_event=AsyncMock(),
    )


def _make_mcp_tool(name: str) -> McpBaseTool:
    """Create MCP tool for tests."""
    return McpBaseTool(
        name=name,
        description=f"Test tool {name}",
        inputSchema={"type": "object", "properties": {}},
    )


def _make_toolkit(
    *,
    region: str = "us-east-1",
    role_arn: str | None = None,
) -> AwsToolkit:
    """Create AwsToolkit for tests."""
    config = AwsToolkitConfig(
        region=region,
        role_arn=role_arn,
    )
    credential_provider = AsyncMock(spec=AwsCredentialProvider)
    # Configure get_credentials to return mock Credentials
    mock_credentials = AsyncMock()
    mock_credentials.access_key = "EXAMPLE_AWS_ACCESS_KEY_ID"
    mock_credentials.secret_key = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    mock_credentials.token = None
    credential_provider.get_credentials = AsyncMock(return_value=mock_credentials)

    return AwsToolkit(
        config=config,
        credential_provider=credential_provider,
        default_region=region,
        timeout=30.0,
    )


# ---------------------------------------------------------------------------
# update_context() default behavior tests
# ---------------------------------------------------------------------------


class TestAwsToolkitUpdateContext:
    """AwsToolkit.update_context() unit tests."""

    @pytest.mark.asyncio
    async def test_returns_toolkit_state(self) -> None:
        """Check that update_context returns ToolkitState."""
        toolkit = _make_toolkit()
        ctx = _make_context()

        with patch(
            "azents.engine.tools.aws.mcp_list_tools",
            new_callable=AsyncMock,
            return_value=([_make_mcp_tool("aws___call_aws")], False),
        ):
            state = await toolkit.update_context(ctx)

        assert isinstance(state, ToolkitState)

    @pytest.mark.asyncio
    async def test_tools_returned(self) -> None:
        """Fetch and return tools from MCP server."""
        toolkit = _make_toolkit()
        ctx = _make_context()

        mock_tools = [
            _make_mcp_tool("aws___call_aws"),
            _make_mcp_tool("aws___suggest_aws_commands"),
        ]

        with patch(
            "azents.engine.tools.aws.mcp_list_tools",
            new_callable=AsyncMock,
            return_value=(mock_tools, False),
        ):
            state = await toolkit.update_context(ctx)

        assert len(state.tools) == 2
        names = {t.spec.name for t in state.tools}
        assert "aws___call_aws" in names
        assert "aws___suggest_aws_commands" in names

    @pytest.mark.asyncio
    async def test_prompt_includes_region(self) -> None:
        """Prompt includes AWS region."""
        toolkit = _make_toolkit(region="ap-northeast-2")
        ctx = _make_context()

        with patch(
            "azents.engine.tools.aws.mcp_list_tools",
            new_callable=AsyncMock,
            return_value=([], False),
        ):
            state = await toolkit.update_context(ctx)

        assert "ap-northeast-2" in state.prompt

    @pytest.mark.asyncio
    async def test_prompt_includes_role_arn_when_set(self) -> None:
        """role_arn is included in prompt when configured."""
        toolkit = _make_toolkit(
            role_arn="arn:aws:iam::123456789012:role/MyRole",
        )
        ctx = _make_context()

        with patch(
            "azents.engine.tools.aws.mcp_list_tools",
            new_callable=AsyncMock,
            return_value=([], False),
        ):
            state = await toolkit.update_context(ctx)

        assert "arn:aws:iam::123456789012:role/MyRole" in state.prompt

    @pytest.mark.asyncio
    async def test_prompt_no_role_info_when_unset(self) -> None:
        """When role_arn is None, prompt has no Assumed Role information."""
        toolkit = _make_toolkit(role_arn=None)
        ctx = _make_context()

        with patch(
            "azents.engine.tools.aws.mcp_list_tools",
            new_callable=AsyncMock,
            return_value=([], False),
        ):
            state = await toolkit.update_context(ctx)

        assert "Assumed Role" not in state.prompt


# ---------------------------------------------------------------------------
# Graceful handling on MCP server connection failure
# ---------------------------------------------------------------------------


class TestAwsToolkitConnectionFailure:
    """Test that empty tools are returned on MCP server connection failure."""

    @pytest.mark.asyncio
    async def test_connection_failure_returns_empty(self) -> None:
        """Connection failure -> empty tools, exception not propagated."""
        toolkit = _make_toolkit()
        ctx = _make_context()

        with patch(
            "azents.engine.tools.aws.mcp_list_tools",
            new_callable=AsyncMock,
            side_effect=ConnectionError("Connection refused"),
        ):
            state = await toolkit.update_context(ctx)

        assert state.tools == []
        assert "connection failed" in state.prompt.lower()


# ---------------------------------------------------------------------------
# Background connection tests (__aenter__ / update_context / __aexit__)
# ---------------------------------------------------------------------------


class TestAwsToolkitBackgroundConnect:
    """Test dynamic status transition after starting background connection."""

    @pytest.mark.asyncio
    async def test_loading_to_ready(self) -> None:
        """Background connection success transitions loading -> ready."""
        toolkit = _make_toolkit()
        ctx = _make_context()

        connect_event = asyncio.Event()
        mock_tools = [
            _make_mcp_tool("aws___call_aws"),
            _make_mcp_tool("aws___suggest_aws_commands"),
        ]

        async def slow_list_tools(
            *args: object, **kwargs: object
        ) -> tuple[list[McpBaseTool], bool]:
            await connect_event.wait()
            return mock_tools, False

        with patch(
            "azents.engine.tools.aws.mcp_list_tools",
            side_effect=slow_list_tools,
        ):
            async with toolkit:
                # connection in progress -> loading
                state = await toolkit.update_context(ctx)
                assert state.tools == []
                assert state.prompt == "Loading tools..."

                # connection complete
                connect_event.set()
                assert toolkit._bg_task is not None  # noqa: SLF001  # pyright: ignore[reportPrivateUsage] -- directly validate background task status in tests
                await toolkit._bg_task  # noqa: SLF001  # pyright: ignore[reportPrivateUsage] -- wait for background task completion in tests

                # ready status
                state = await toolkit.update_context(ctx)
                assert len(state.tools) == 2
                assert "us-east-1" in state.prompt

    @pytest.mark.asyncio
    async def test_loading_to_error(self) -> None:
        """Background connection failure transitions loading -> error."""
        toolkit = _make_toolkit()
        ctx = _make_context()

        async def failing_list_tools(
            *args: object, **kwargs: object
        ) -> tuple[list[McpBaseTool], bool]:
            msg = "Connection refused"
            raise ConnectionError(msg)

        with patch(
            "azents.engine.tools.aws.mcp_list_tools",
            side_effect=failing_list_tools,
        ):
            async with toolkit:
                assert toolkit._bg_task is not None  # noqa: SLF001  # pyright: ignore[reportPrivateUsage] -- directly validate background task status in tests
                await toolkit._bg_task  # noqa: SLF001  # pyright: ignore[reportPrivateUsage] -- wait for background task completion in tests

                state = await toolkit.update_context(ctx)
                assert state.tools == []
                assert "AWS MCP server connection failed" in state.prompt

    @pytest.mark.asyncio
    async def test_aexit_cancels_task(self) -> None:
        """__aexit__ cancels background task."""
        toolkit = _make_toolkit()

        async def forever_list_tools(
            *args: object, **kwargs: object
        ) -> tuple[list[McpBaseTool], bool]:
            await asyncio.sleep(3600)
            return ([], False)

        with patch(
            "azents.engine.tools.aws.mcp_list_tools",
            side_effect=forever_list_tools,
        ):
            async with toolkit:
                assert toolkit._bg_task is not None  # noqa: SLF001  # pyright: ignore[reportPrivateUsage] -- directly validate background task status in tests
                assert not toolkit._bg_task.done()  # noqa: SLF001  # pyright: ignore[reportPrivateUsage] -- directly validate background task status in tests

        assert toolkit._bg_task is None  # noqa: SLF001  # pyright: ignore[reportPrivateUsage] -- directly validate background task cleanup in tests

    @pytest.mark.asyncio
    async def test_fallback_sync_without_aenter(self) -> None:
        """Synchronous connection fallback when called without __aenter__."""
        toolkit = _make_toolkit()
        ctx = _make_context()

        mock_tools = [_make_mcp_tool("aws___call_aws")]

        with patch(
            "azents.engine.tools.aws.mcp_list_tools",
            new_callable=AsyncMock,
            return_value=(mock_tools, False),
        ):
            state = await toolkit.update_context(ctx)

        assert len(state.tools) == 1
        assert "us-east-1" in state.prompt
