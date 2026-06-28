"""GCP Toolkit update_context() and handler tests.

Validate that GcpToolkit.update_context() correctly performs per-service MCP
connection, tool filtering, and prompt creation.
Validate that wrapped tool handler calls mcp_call_tool.
Also validate background connection (__aenter__ -> update_context -> __aexit__).
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from mcp.types import TextContent, ToolAnnotations
from mcp.types import Tool as McpBaseTool

from azents.core.tools import GcpService, GcpToolkitConfig, ToolkitState, TurnContext
from azents.engine.run.types import FunctionTool
from azents.engine.tools.gcp import (
    GcpAccessTokenProvider,
    GcpToolkit,
    _GcpServerConfig,  # pyright: ignore[reportPrivateUsage] — directly configure internal server settings in tests
    _is_read_only_tool,  # pyright: ignore[reportPrivateUsage] — directly validate internal utility function in tests
)

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


def _make_mcp_tool(
    name: str,
    *,
    read_only: bool | None = None,
) -> McpBaseTool:
    """Create MCP tool for tests.

    :param name: Tool name
    :param read_only: readOnlyHint value; no annotations when None
    """
    annotations_obj: ToolAnnotations | None = None
    if read_only is not None:
        annotations_obj = ToolAnnotations(readOnlyHint=read_only)
    return McpBaseTool(
        name=name,
        description=f"Test tool {name}",
        inputSchema={"type": "object", "properties": {}},
        annotations=annotations_obj,
    )


def _make_toolkit(
    *,
    services: list[GcpService] | None = None,
    writable_services: set[GcpService] | None = None,
    project_id: str = "my-project-123456",
) -> GcpToolkit:
    """Create GcpToolkit for tests."""
    svc_list = services or [GcpService.LOGGING, GcpService.MONITORING]
    config = GcpToolkitConfig(
        project_id=project_id,
        services=svc_list,
        writable_services=list(writable_services or set()),
    )
    token_provider = AsyncMock(spec=GcpAccessTokenProvider)
    token_provider.get_token = AsyncMock(return_value="mock-access-token")

    server_configs = [
        _GcpServerConfig(
            service=svc,
            endpoint=f"https://{svc.value}.googleapis.com/mcp",
            timeout=30.0,
        )
        for svc in svc_list
    ]

    return GcpToolkit(
        config=config,
        token_provider=token_provider,
        server_configs=server_configs,
        project_id=project_id,
        writable_services=writable_services or set(),
    )


# ---------------------------------------------------------------------------
# _is_read_only_tool tests
# ---------------------------------------------------------------------------


class TestIsReadOnlyTool:
    """_is_read_only_tool utility function tests."""

    def test_no_annotations_is_read_only(self) -> None:
        """Treat as read-only when annotations are absent."""
        tool = _make_mcp_tool("tool_a")
        assert _is_read_only_tool(tool) is True

    def test_read_only_hint_true(self) -> None:
        """readOnlyHint=True is read-only."""
        tool = _make_mcp_tool("tool_b", read_only=True)
        assert _is_read_only_tool(tool) is True

    def test_read_only_hint_false(self) -> None:
        """readOnlyHint=False is write tool."""
        tool = _make_mcp_tool("tool_c", read_only=False)
        assert _is_read_only_tool(tool) is False


# ---------------------------------------------------------------------------
# update_context() default behavior tests
# ---------------------------------------------------------------------------


class TestGcpToolkitUpdateContext:
    """GcpToolkit.update_context() unit tests."""

    @pytest.mark.asyncio
    async def test_returns_toolkit_state(self) -> None:
        """Check that update_context returns ToolkitState."""
        toolkit = _make_toolkit()
        ctx = _make_context()

        with patch(
            "azents.engine.tools.gcp.mcp_list_tools",
            new_callable=AsyncMock,
            return_value=([_make_mcp_tool("log_query")], False),
        ):
            state = await toolkit.update_context(ctx)

        assert isinstance(state, ToolkitState)

    @pytest.mark.asyncio
    async def test_tools_from_multiple_services(self) -> None:
        """Collect tools from multiple services in parallel."""
        toolkit = _make_toolkit(
            services=[GcpService.LOGGING, GcpService.MONITORING],
        )
        ctx = _make_context()

        async def mock_list_tools(
            endpoint: str,
            _headers: dict[str, str],
            _timeout: float,
            *,
            proxy_url: str | None = None,
            auth: object = None,
        ) -> tuple[list[McpBaseTool], bool]:
            if "logging" in endpoint:
                return [_make_mcp_tool("log_query")], False
            return [_make_mcp_tool("metric_query")], False

        with patch(
            "azents.engine.tools.gcp.mcp_list_tools",
            side_effect=mock_list_tools,
        ):
            async with toolkit:
                await _wait_gcp_tasks(toolkit)
                state = await toolkit.update_context(ctx)

        names = {t.spec.name for t in state.tools}
        assert "log_query" in names
        assert "metric_query" in names

    @pytest.mark.asyncio
    async def test_prompt_includes_project_id(self) -> None:
        """Prompt includes project ID."""
        toolkit = _make_toolkit(project_id="my-project-123456")
        ctx = _make_context()

        with patch(
            "azents.engine.tools.gcp.mcp_list_tools",
            new_callable=AsyncMock,
            return_value=([], False),
        ):
            state = await toolkit.update_context(ctx)

        assert "my-project-123456" in state.prompt

    @pytest.mark.asyncio
    async def test_prompt_includes_service_descriptions(self) -> None:
        """Prompt includes enabled service descriptions."""
        toolkit = _make_toolkit(services=[GcpService.LOGGING])
        ctx = _make_context()

        with patch(
            "azents.engine.tools.gcp.mcp_list_tools",
            new_callable=AsyncMock,
            return_value=([], False),
        ):
            state = await toolkit.update_context(ctx)

        assert "Logging" in state.prompt


# ---------------------------------------------------------------------------
# read_only filtering tests
# ---------------------------------------------------------------------------


class TestGcpToolkitReadOnlyFiltering:
    """Tool filtering tests based on writable_services settings."""

    @pytest.mark.asyncio
    async def test_read_only_service_excludes_write_tools(self) -> None:
        """Write tools for services absent from writable_services are excluded."""
        toolkit = _make_toolkit(
            services=[GcpService.LOGGING],
            writable_services=set(),
        )
        ctx = _make_context()

        read_tool = _make_mcp_tool("log_query", read_only=True)
        write_tool = _make_mcp_tool("log_delete", read_only=False)

        with patch(
            "azents.engine.tools.gcp.mcp_list_tools",
            new_callable=AsyncMock,
            return_value=([read_tool, write_tool], False),
        ):
            async with toolkit:
                await _wait_gcp_tasks(toolkit)
                state = await toolkit.update_context(ctx)

        names = {t.spec.name for t in state.tools}
        assert "log_query" in names
        assert "log_delete" not in names

    @pytest.mark.asyncio
    async def test_writable_service_includes_write_tools(self) -> None:
        """Write tools for services included in writable_services are also returned."""
        toolkit = _make_toolkit(
            services=[GcpService.LOGGING],
            writable_services={GcpService.LOGGING},
        )
        ctx = _make_context()

        read_tool = _make_mcp_tool("log_query", read_only=True)
        write_tool = _make_mcp_tool("log_delete", read_only=False)

        with patch(
            "azents.engine.tools.gcp.mcp_list_tools",
            new_callable=AsyncMock,
            return_value=([read_tool, write_tool], False),
        ):
            async with toolkit:
                await _wait_gcp_tasks(toolkit)
                state = await toolkit.update_context(ctx)

        names = {t.spec.name for t in state.tools}
        assert "log_query" in names
        assert "log_delete" in names

    @pytest.mark.asyncio
    async def test_prompt_shows_read_write_mode(self) -> None:
        """Writable services are shown as read+write in prompt."""
        toolkit = _make_toolkit(
            services=[GcpService.LOGGING, GcpService.MONITORING],
            writable_services={GcpService.LOGGING},
        )
        ctx = _make_context()

        with patch(
            "azents.engine.tools.gcp.mcp_list_tools",
            new_callable=AsyncMock,
            return_value=([], False),
        ):
            state = await toolkit.update_context(ctx)

        assert "read+write" in state.prompt
        assert "read-only" in state.prompt


# ---------------------------------------------------------------------------
# Graceful handling on MCP server connection failure
# ---------------------------------------------------------------------------


class TestGcpToolkitConnectionFailure:
    """Continue when per-service MCP server connection fails."""

    @pytest.mark.asyncio
    async def test_partial_failure_returns_available_tools(self) -> None:
        """When some service connections fail, return successful service tools."""
        toolkit = _make_toolkit(
            services=[GcpService.LOGGING, GcpService.MONITORING],
        )
        ctx = _make_context()

        call_count = 0

        async def mock_list_tools(
            endpoint: str,
            _headers: dict[str, str],
            _timeout: float,
            *,
            proxy_url: str | None = None,
            auth: object = None,
        ) -> tuple[list[McpBaseTool], bool]:
            nonlocal call_count
            call_count += 1
            if "logging" in endpoint:
                return [_make_mcp_tool("log_query")], False
            msg = "Connection refused"
            raise ConnectionError(msg)

        with patch(
            "azents.engine.tools.gcp.mcp_list_tools",
            side_effect=mock_list_tools,
        ):
            async with toolkit:
                await _wait_gcp_tasks(toolkit)
                state = await toolkit.update_context(ctx)

        # Only logging service tools are returned
        assert len(state.tools) == 1
        assert state.tools[0].spec.name == "log_query"


# ---------------------------------------------------------------------------
# Helper: utility to find tool by name
# ---------------------------------------------------------------------------


def _find_tool(tools: list[FunctionTool], name: str) -> FunctionTool:
    """Find tool by name. AssertionError when absent."""
    for t in tools:
        if t.spec.name == name:
            return t
    available = [t.spec.name for t in tools]
    msg = f"Tool '{name}' not found. Available: {available}"
    raise AssertionError(msg)


def _make_call_tool_result(text: str) -> MagicMock:
    """Create CallToolResult for tests."""
    result = MagicMock()
    result.content = [TextContent(type="text", text=text)]
    result.isError = False
    return result


async def _wait_gcp_tasks(toolkit: GcpToolkit) -> None:
    """Wait for background GCP MCP discovery tasks."""
    for task in toolkit._bg_tasks.values():  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        await task


# ---------------------------------------------------------------------------
# GCP Tool handler feature tests
# ---------------------------------------------------------------------------


class TestGcpToolHandlers:
    """Test that handler of GCP wrapped tool calls mcp_call_tool."""

    @pytest.mark.asyncio
    async def test_handler_calls_mcp_call_tool(self) -> None:
        """Wrapped tool handler calls mcp_call_tool correctly."""
        toolkit = _make_toolkit(services=[GcpService.LOGGING])
        ctx = _make_context()

        mock_success = _make_call_tool_result("log query result")

        with (
            patch(
                "azents.engine.tools.gcp.mcp_list_tools",
                new_callable=AsyncMock,
                return_value=([_make_mcp_tool("log_query")], False),
            ),
            patch(
                "azents.engine.tools.mcp_base.mcp_call_tool",
                new_callable=AsyncMock,
                return_value=mock_success,
            ) as mock_call,
        ):
            async with toolkit:
                await _wait_gcp_tasks(toolkit)
                state = await toolkit.update_context(ctx)
                assert len(state.tools) == 1
                tool = _find_tool(state.tools, "log_query")

                result = await tool.handler('{"filter": "severity=ERROR"}')

        assert result == "log query result"
        mock_call.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handler_retries_on_401(self) -> None:
        """Refresh token and retry on 401 error."""
        toolkit = _make_toolkit(services=[GcpService.LOGGING])
        ctx = _make_context()

        http_401 = httpx.HTTPStatusError(
            "Unauthorized",
            request=httpx.Request("POST", "https://example.com"),
            response=httpx.Response(401),
        )
        mock_success = _make_call_tool_result("retried result")

        with (
            patch(
                "azents.engine.tools.gcp.mcp_list_tools",
                new_callable=AsyncMock,
                return_value=([_make_mcp_tool("log_query")], False),
            ),
            patch(
                "azents.engine.tools.mcp_base.mcp_call_tool",
                new_callable=AsyncMock,
                side_effect=[http_401, mock_success],
            ) as mock_call,
        ):
            async with toolkit:
                await _wait_gcp_tasks(toolkit)
                state = await toolkit.update_context(ctx)
                tool = _find_tool(state.tools, "log_query")
                result = await tool.handler("{}")

        assert result == "retried result"
        # Two calls: first (401) + retry (success)
        assert mock_call.await_count == 2


# ---------------------------------------------------------------------------
# Background connection tests (__aenter__ / update_context / __aexit__)
# ---------------------------------------------------------------------------


class TestGcpToolkitBackgroundConnect:
    """Test dynamic status transition after background parallel connection."""

    @pytest.mark.asyncio
    async def test_loading_to_ready(self) -> None:
        """All service connection success transitions loading -> ready."""
        toolkit = _make_toolkit(
            services=[GcpService.LOGGING, GcpService.MONITORING],
        )
        ctx = _make_context()

        connect_events: dict[str, asyncio.Event] = {
            "logging": asyncio.Event(),
            "monitoring": asyncio.Event(),
        }

        async def mock_list_tools(
            endpoint: str,
            _headers: dict[str, str],
            _timeout: float,
            *,
            proxy_url: str | None = None,
            auth: object = None,
        ) -> tuple[list[McpBaseTool], bool]:
            if "logging" in endpoint:
                await connect_events["logging"].wait()
                return [_make_mcp_tool("log_query")], False
            await connect_events["monitoring"].wait()
            return [_make_mcp_tool("metric_query")], False

        with patch(
            "azents.engine.tools.gcp.mcp_list_tools",
            side_effect=mock_list_tools,
        ):
            async with toolkit:
                # Both services connecting -> loading
                state = await toolkit.update_context(ctx)
                assert state.tools == []
                assert "Loading" not in state.prompt

                # Only logging complete
                connect_events["logging"].set()
                await asyncio.sleep(0)  # Allow task switch
                # Wait for logging task completion
                logging_task = toolkit._bg_tasks.get(GcpService.LOGGING)  # noqa: SLF001  # pyright: ignore[reportPrivateUsage] -- directly validate per-service task status in tests
                if logging_task:
                    await logging_task

                state = await toolkit.update_context(ctx)
                # Return only logging tools; monitoring still loading
                assert len(state.tools) == 1
                assert state.tools[0].spec.name == "log_query"
                assert "Loading" not in state.prompt

                # monitoring also complete
                connect_events["monitoring"].set()
                monitoring_task = toolkit._bg_tasks.get(GcpService.MONITORING)  # noqa: SLF001  # pyright: ignore[reportPrivateUsage] -- directly validate per-service task status in tests
                if monitoring_task:
                    await monitoring_task

                state = await toolkit.update_context(ctx)
                assert len(state.tools) == 2
                names = {t.spec.name for t in state.tools}
                assert names == {"log_query", "metric_query"}
                assert "Loading" not in state.prompt

    @pytest.mark.asyncio
    async def test_partial_failure_in_background(self) -> None:
        """When some service connections fail, return only successful service tools."""
        toolkit = _make_toolkit(
            services=[GcpService.LOGGING, GcpService.MONITORING],
        )
        ctx = _make_context()

        async def mock_list_tools(
            endpoint: str,
            _headers: dict[str, str],
            _timeout: float,
            *,
            proxy_url: str | None = None,
            auth: object = None,
        ) -> tuple[list[McpBaseTool], bool]:
            if "logging" in endpoint:
                return [_make_mcp_tool("log_query")], False
            msg = "Connection refused"
            raise ConnectionError(msg)

        with patch(
            "azents.engine.tools.gcp.mcp_list_tools",
            side_effect=mock_list_tools,
        ):
            async with toolkit:
                # Wait for all tasks to complete
                for task in toolkit._bg_tasks.values():  # noqa: SLF001  # pyright: ignore[reportPrivateUsage] -- directly validate per-service task status in tests
                    await task

                state = await toolkit.update_context(ctx)
                assert len(state.tools) == 1
                assert state.tools[0].spec.name == "log_query"

    @pytest.mark.asyncio
    async def test_aexit_cancels_all_tasks(self) -> None:
        """__aexit__ cancels all background tasks."""
        toolkit = _make_toolkit(
            services=[GcpService.LOGGING, GcpService.MONITORING],
        )

        async def forever_list_tools(
            *args: object, **kwargs: object
        ) -> tuple[list[McpBaseTool], bool]:
            await asyncio.sleep(3600)
            return ([], False)

        with patch(
            "azents.engine.tools.gcp.mcp_list_tools",
            side_effect=forever_list_tools,
        ):
            async with toolkit:
                assert len(toolkit._bg_tasks) == 2  # noqa: SLF001  # pyright: ignore[reportPrivateUsage] -- directly validate per-service task count in tests
                for task in toolkit._bg_tasks.values():  # noqa: SLF001  # pyright: ignore[reportPrivateUsage] -- directly validate per-service task status in tests
                    assert not task.done()

        # All tasks are cleaned up after __aexit__
        assert len(toolkit._bg_tasks) == 0  # noqa: SLF001  # pyright: ignore[reportPrivateUsage] -- directly validate task cleanup in tests

    @pytest.mark.asyncio
    async def test_without_aenter_does_not_sync_discover_tools(self) -> None:
        """update_context without __aenter__ does not synchronously list tools."""
        toolkit = _make_toolkit(services=[GcpService.LOGGING])
        ctx = _make_context()

        with patch(
            "azents.engine.tools.gcp.mcp_list_tools",
            new_callable=AsyncMock,
            return_value=([_make_mcp_tool("log_query")], False),
        ):
            state = await toolkit.update_context(ctx)

        assert state.tools == []
