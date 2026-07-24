"""read_text tool tests."""

import json

import pytest

from azents.engine.run.types import FunctionTool, FunctionToolError
from azents.engine.tools.read_text import make_read_text_tool
from azents.engine.tools.testing import FakeSharedStorage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool(
    *,
    files: dict[str, bytes] | None = None,
) -> tuple[FunctionTool, FakeSharedStorage]:
    """Create read_text tool and fake storage for tests."""
    storage = FakeSharedStorage(files)
    tool = make_read_text_tool(
        session_storage=storage,
        agent_id="",
    )
    return tool, storage


# ---------------------------------------------------------------------------
# TestReadTextFromSessionData
# ---------------------------------------------------------------------------


class TestReadTextFromSessionData:
    """Text file read tests from session data."""

    async def test_read_full_file(self) -> None:
        """Read entire short text file."""
        # Given: text file in session data
        content = "Hello, world!"
        tool, _ = _make_tool(files={"/workspace/agent/note.txt": content.encode()})

        # When: call read_text
        result = await tool.handler(json.dumps({"path": "/workspace/agent/note.txt"}))

        # Then: full content is included
        assert isinstance(result, str)
        assert "Hello, world!" in result
        assert "chars 0-13 of 13" in result

    async def test_read_with_offset(self) -> None:
        """Read from the middle with offset."""
        # Given: long text
        content = "A" * 100
        tool, _ = _make_tool(files={"/workspace/agent/data.txt": content.encode()})

        # When: call with offset=50
        result = await tool.handler(
            json.dumps({"path": "/workspace/agent/data.txt", "offset": 50})
        )

        # Then: read from 50th character
        assert isinstance(result, str)
        assert "chars 50-100 of 100" in result

    async def test_read_with_limit(self) -> None:
        """Read only beginning with limit."""
        # Given: long text
        content = "B" * 20_000
        tool, _ = _make_tool(files={"/workspace/agent/big.txt": content.encode()})

        # When: call with limit=5000
        result = await tool.handler(
            json.dumps({"path": "/workspace/agent/big.txt", "limit": 5000})
        )

        # Then: return only 5000 chars and include guidance to read more
        assert isinstance(result, str)
        assert "chars 0-5000 of 20000" in result
        assert "Use offset=5000 to read more" in result

    async def test_read_with_offset_and_limit(self) -> None:
        """offset + limit combination test."""
        # Given: text
        content = "C" * 500
        tool, _ = _make_tool(files={"/workspace/agent/mid.txt": content.encode()})

        # When: offset=100, limit=200
        result = await tool.handler(
            json.dumps(
                {"path": "/workspace/agent/mid.txt", "offset": 100, "limit": 200}
            )
        )

        # Then: return range 100-300
        assert isinstance(result, str)
        assert "chars 100-300 of 500" in result

    async def test_offset_beyond_file_length(self) -> None:
        """Return empty content when offset exceeds file length."""
        # Given: short text
        tool, _ = _make_tool(files={"/workspace/agent/short.txt": b"hi"})

        # When: offset=100
        result = await tool.handler(
            json.dumps({"path": "/workspace/agent/short.txt", "offset": 100})
        )

        # Then: empty content, range display
        assert isinstance(result, str)
        assert "chars 2-2 of 2" in result

    async def test_no_more_hint_when_fully_read(self) -> None:
        """No 'Use offset' guidance when entire file is read."""
        # Given: short text
        tool, _ = _make_tool(files={"/workspace/agent/small.txt": b"abc"})

        # When: read entire file
        result = await tool.handler(json.dumps({"path": "/workspace/agent/small.txt"}))

        # Then: no guidance to read more
        assert isinstance(result, str)
        assert "Use offset" not in result


# ---------------------------------------------------------------------------
# TestReadTextErrors
# ---------------------------------------------------------------------------


class TestReadTextErrors:
    """Error case tests."""

    async def test_unsupported_path(self) -> None:
        """Disallowed path raises FunctionToolError."""
        tool, _ = _make_tool()
        with pytest.raises(FunctionToolError, match="File not found"):
            await tool.handler(json.dumps({"path": "/tmp/file.txt"}))

    async def test_file_not_found(self) -> None:
        """Nonexistent file raises FunctionToolError."""
        tool, _ = _make_tool(files={})
        with pytest.raises(FunctionToolError, match="File not found") as exc_info:
            await tool.handler(json.dumps({"path": "/workspace/agent/missing.txt"}))
        message = str(exc_info.value)
        assert "/workspace/agent" in message
        assert "import_file" not in message
        assert "present_file" not in message

    async def test_binary_file_utf8_decode_error(self) -> None:
        """Non-UTF-8 binary file raises FunctionToolError."""
        # Given: binary data
        tool, _ = _make_tool(files={"/workspace/agent/binary.dat": b"\xff\xfe\x00\x01"})

        # When/Then: FunctionToolError
        with pytest.raises(FunctionToolError, match="not valid UTF-8"):
            await tool.handler(json.dumps({"path": "/workspace/agent/binary.dat"}))
