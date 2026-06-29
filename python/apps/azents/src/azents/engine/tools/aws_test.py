"""AWS Toolkit update_context() tests.

Validate that AwsToolkit.update_context() collects MCP tools with SigV4
authentication and creates prompt correctly. Also validate background connection
(__aenter__ -> update_context -> __aexit__).
"""

import asyncio
from typing import AsyncContextManager
from unittest.mock import AsyncMock, patch

import pytest
from mcp.types import Tool as McpBaseTool
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.tools import AwsToolkitConfig, ToolkitState, TurnContext
from azents.engine.tooling.toolkit_state import ToolkitStateIdentity
from azents.engine.tools.aws import AwsCredentialProvider, AwsToolkit


class _FakeToolkitStateHandle:
    """In-memory Toolkit State handle for tests."""

    _states: dict[tuple[str, str, str, str], object] = {}

    def __init__(self, identity: ToolkitStateIdentity) -> None:
        self.identity = identity

    async def load(self, default_factory: object) -> object:
        """Load state from in-memory store."""
        key = self._key()
        if key not in self._states:
            return default_factory()  # type: ignore[operator]
        return self._states[key]

    async def save(self, state: object) -> object:
        """Save state to in-memory store."""
        self._states[self._key()] = state
        return object()

    @classmethod
    def clear(cls) -> None:
        """Clear stored Toolkit State."""
        cls._states.clear()

    def _key(self) -> tuple[str, str, str, str]:
        return (
            self.identity.agent_id,
            self.identity.session_id,
            self.identity.toolkit_namespace,
            self.identity.state_name,
        )


class _FakeToolkitStateStore:
    """In-memory Toolkit State store for tests."""

    def __init__(self, *, session: object) -> None:
        del session

    def handle(
        self, identity: ToolkitStateIdentity, _model_type: object
    ) -> _FakeToolkitStateHandle:
        """Return fake handle."""
        return _FakeToolkitStateHandle(identity)


class _FakeSessionContext:
    """Minimal async session context manager for tests."""

    async def __aenter__(self) -> AsyncSession:
        return AsyncSession()

    async def __aexit__(self, *exc: object) -> None:
        pass


class _FakeSessionManager:
    """Minimal async context manager factory for tests."""

    def __call__(self) -> AsyncContextManager[AsyncSession]:
        return _FakeSessionContext()


_session_manager = _FakeSessionManager()


@pytest.fixture(autouse=True)
def _toolkit_state_store(  # pyright: ignore[reportUnusedFunction] -- pytest autouse fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Patch Toolkit State to an in-memory store."""
    _FakeToolkitStateHandle.clear()
    monkeypatch.setattr(
        "azents.engine.tools.aws.ToolkitStateStore",
        _FakeToolkitStateStore,
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
        proxy_url=None,
        artifact_service=None,
        session_manager=_session_manager,
        agent_id="agent-1",
        session_id="session-1",
        state_name="tool_snapshot:test",
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
            await toolkit._refresh_tool_snapshot()  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
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

        await toolkit.update_context(ctx)

        assert "ap-northeast-2" in (await toolkit.get_static_prompt(ctx))

    @pytest.mark.asyncio
    async def test_prompt_includes_role_arn_when_set(self) -> None:
        """role_arn is included in prompt when configured."""
        toolkit = _make_toolkit(
            role_arn="arn:aws:iam::123456789012:role/MyRole",
        )
        ctx = _make_context()

        await toolkit.update_context(ctx)

        assert "arn:aws:iam::123456789012:role/MyRole" in (
            await toolkit.get_static_prompt(ctx)
        )

    @pytest.mark.asyncio
    async def test_prompt_no_role_info_when_unset(self) -> None:
        """When role_arn is None, prompt has no Assumed Role information."""
        toolkit = _make_toolkit(role_arn=None)
        ctx = _make_context()

        await toolkit.update_context(ctx)

        assert "Assumed Role" not in (await toolkit.get_static_prompt(ctx))


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
        assert "connection failed" not in (await toolkit.get_static_prompt(ctx)).lower()


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
                assert "Loading" not in (await toolkit.get_static_prompt(ctx))

                # connection complete
                connect_event.set()
                assert toolkit._bg_task is not None  # noqa: SLF001  # pyright: ignore[reportPrivateUsage] -- directly validate background task status in tests
                await toolkit._bg_task  # noqa: SLF001  # pyright: ignore[reportPrivateUsage] -- wait for background task completion in tests

                # ready status
                state = await toolkit.update_context(ctx)
                assert len(state.tools) == 2
                assert "us-east-1" in (await toolkit.get_static_prompt(ctx))

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
                assert "AWS MCP server connection failed" not in (
                    await toolkit.get_static_prompt(ctx)
                )

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
    async def test_without_aenter_does_not_sync_discover_tools(self) -> None:
        """update_context without __aenter__ does not synchronously list tools."""
        toolkit = _make_toolkit()
        ctx = _make_context()

        mock_tools = [_make_mcp_tool("aws___call_aws")]

        with patch(
            "azents.engine.tools.aws.mcp_list_tools",
            new_callable=AsyncMock,
            return_value=(mock_tools, False),
        ):
            state = await toolkit.update_context(ctx)

        assert state.tools == []
        assert "us-east-1" in (await toolkit.get_static_prompt(ctx))
