"""delete_file tool tests."""

import json

import pytest

from azents.engine.run.types import FunctionTool, FunctionToolError
from azents.engine.tools.delete_file import make_delete_file_tool
from azents.engine.tools.testing import FakeSharedStorage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool(
    *,
    files: dict[str, bytes] | None = None,
) -> tuple[FunctionTool, FakeSharedStorage]:
    """Create delete_file tool and fake storage for tests."""
    storage = FakeSharedStorage(files)
    tool = make_delete_file_tool(
        session_storage=storage,
        agent_id="",
    )
    return tool, storage


# ---------------------------------------------------------------------------
# TestDeleteFileFromSessionData
# ---------------------------------------------------------------------------


class TestDeleteFileFromSessionData:
    """Session data file deletion tests."""

    async def test_delete_existing_file(self) -> None:
        """Delete existing file."""
        # Given: file exists in session data
        tool, storage = _make_tool(
            files={"/workspace/agent/report.csv": b"data"},
        )

        # When: call delete_file
        result = await tool.handler(json.dumps({"path": "/workspace/agent/report.csv"}))

        # Then: deletion success message
        assert isinstance(result, str)
        assert "File deleted: /workspace/agent/report.csv" in result
        # Check that file was deleted
        exists = await storage.exists("/workspace/agent/report.csv")
        assert not exists

    async def test_delete_nested_path(self) -> None:
        """Delete file in nested path."""
        # Given: file under tool_outputs
        tool, storage = _make_tool(
            files={"/workspace/agent/tool_outputs/call_123.txt": b"content"},
        )

        # When: call delete_file
        result = await tool.handler(
            json.dumps({"path": "/workspace/agent/tool_outputs/call_123.txt"})
        )

        # Then: deletion success
        assert isinstance(result, str)
        assert "File deleted" in result
        exists = await storage.exists("/workspace/agent/tool_outputs/call_123.txt")
        assert not exists


# ---------------------------------------------------------------------------
# TestDeleteFileErrors
# ---------------------------------------------------------------------------


class TestDeleteFileErrors:
    """Error case tests."""

    async def test_unsupported_path(self) -> None:
        """Disallowed path raises FunctionToolError."""
        tool, _ = _make_tool()
        with pytest.raises(FunctionToolError, match="File not found"):
            await tool.handler(json.dumps({"path": "/tmp/file.txt"}))

    async def test_file_not_found(self) -> None:
        """Nonexistent file raises FunctionToolError."""
        tool, _ = _make_tool(files={})
        with pytest.raises(FunctionToolError, match="File not found"):
            await tool.handler(json.dumps({"path": "/workspace/agent/nonexistent.txt"}))
