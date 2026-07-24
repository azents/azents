"""write tool tests."""

import json

import pytest

from azents.engine.run.types import FunctionTool, FunctionToolError
from azents.engine.tools.testing import FakeSharedStorage
from azents.engine.tools.write import make_write_tool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool(
    *,
    raise_permission: bool = False,
    agent_id: str = "agent-1",
) -> tuple[FunctionTool, FakeSharedStorage]:
    """Create write tool and fake storage for tests."""
    storage = FakeSharedStorage(raise_permission_on_put=raise_permission)
    tool = make_write_tool(
        session_storage=storage,
        agent_id=agent_id,
    )
    return tool, storage


# ---------------------------------------------------------------------------
# TestWriteFile
# ---------------------------------------------------------------------------


class TestWriteFile:
    """File write tests."""

    async def test_write_agent_file(self) -> None:
        """Write file to agent path."""
        # Given
        tool, storage = _make_tool()

        # When
        result = await tool.handler(
            json.dumps(
                {
                    "path": "/workspace/agent/output.txt",
                    "content": "Hello, world!",
                }
            )
        )

        # Then
        assert isinstance(result, str)
        assert "File written" in result
        assert "13 bytes" in result
        assert len(storage.put_calls) == 1
        path, data = storage.put_calls[0]
        assert path == "/workspace/agent/output.txt"
        assert data == b"Hello, world!"

    async def test_write_agent_subdirectory_file(self) -> None:
        """Write file to an Agent workspace subdirectory."""
        # Given
        tool, storage = _make_tool()

        # When
        result = await tool.handler(
            json.dumps(
                {
                    "path": "/workspace/agent/config/settings.json",
                    "content": '{"key": "value"}',
                }
            )
        )

        # Then
        assert isinstance(result, str)
        assert "File written" in result
        path, _ = storage.put_calls[0]
        assert path == "/workspace/agent/config/settings.json"

    async def test_write_nested_path(self) -> None:
        """Write file to nested path."""
        # Given
        tool, storage = _make_tool()

        # When
        await tool.handler(
            json.dumps(
                {
                    "path": "/workspace/agent/dir/sub/file.md",
                    "content": "# Title",
                }
            )
        )

        # Then
        path, _ = storage.put_calls[0]
        assert path == "/workspace/agent/dir/sub/file.md"


# ---------------------------------------------------------------------------
# TestWriteErrors
# ---------------------------------------------------------------------------


class TestWriteErrors:
    """Error case tests."""

    async def test_permission_error(self) -> None:
        """Writing read-only path maps PermissionError to FunctionToolError."""
        tool, _ = _make_tool(raise_permission=True)
        with pytest.raises(FunctionToolError, match="read-only scope"):
            await tool.handler(
                json.dumps(
                    {
                        "path": "/workspace/agent/data.txt",
                        "content": "x",
                    }
                )
            )


# ---------------------------------------------------------------------------
# TestOverwrite
# ---------------------------------------------------------------------------


class TestOverwrite:
    """overwrite option tests."""

    async def test_default_overwrite_false_blocks_existing(self) -> None:
        """Fail writing existing file when overwrite default is false."""
        # Given: existing file
        tool, storage = _make_tool()
        storage.add_file("/workspace/agent/existing.txt", b"old content")

        # When/Then: try writing without overwrite -> failure
        with pytest.raises(FunctionToolError, match="File already exists"):
            await tool.handler(
                json.dumps(
                    {
                        "path": "/workspace/agent/existing.txt",
                        "content": "new content",
                    }
                )
            )

    async def test_overwrite_true_replaces_existing(self) -> None:
        """overwrite=true overwrites existing file."""
        # Given: existing file
        tool, storage = _make_tool()
        storage.add_file("/workspace/agent/existing.txt", b"old content")

        # When: write with overwrite=true
        result = await tool.handler(
            json.dumps(
                {
                    "path": "/workspace/agent/existing.txt",
                    "content": "new content",
                    "overwrite": True,
                }
            )
        )

        # Then: success
        assert isinstance(result, str)
        assert "File written" in result
        assert len(storage.put_calls) == 1

    async def test_overwrite_false_allows_new_file(self) -> None:
        """New file is created normally even when overwrite=false."""
        # Given: empty storage
        tool, storage = _make_tool()

        # When: write new file
        result = await tool.handler(
            json.dumps(
                {
                    "path": "/workspace/agent/new.txt",
                    "content": "content",
                }
            )
        )

        # Then: success
        assert isinstance(result, str)
        assert "File written" in result
        assert len(storage.put_calls) == 1
