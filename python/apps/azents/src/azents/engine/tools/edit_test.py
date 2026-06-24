"""edit tool tests."""

import json

import pytest

from azents.engine.run.types import FunctionTool, FunctionToolError
from azents.engine.tools.edit import make_edit_tool
from azents.engine.tools.testing import FakeSharedStorage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool(
    *,
    files: dict[str, bytes] | None = None,
    raise_permission_on_put: bool = False,
    agent_id: str = "agent-1",
    user_id: str = "user-1",
) -> tuple[FunctionTool, FakeSharedStorage]:
    """Create edit tool and fake storage for tests."""
    storage = FakeSharedStorage(files, raise_permission_on_put=raise_permission_on_put)
    tool = make_edit_tool(
        session_storage=storage,
        agent_id=agent_id,
        user_id=user_id,
    )
    return tool, storage


# ---------------------------------------------------------------------------
# TestEditFile
# ---------------------------------------------------------------------------


class TestEditFile:
    """File edit tests."""

    async def test_replace_single_occurrence(self) -> None:
        """Replace single occurrence."""
        # Given
        tool, storage = _make_tool(
            files={"/workspace/agent/note.txt": b"Hello, world!"}
        )

        # When
        result = await tool.handler(
            json.dumps(
                {
                    "path": "/workspace/agent/note.txt",
                    "old_string": "world",
                    "new_string": "Python",
                }
            )
        )

        # Then
        assert isinstance(result, str)
        assert "replaced 1 occurrence(s)" in result
        assert len(storage.put_calls) == 1
        _, data = storage.put_calls[0]
        assert data == b"Hello, Python!"

    async def test_replace_all_occurrences(self) -> None:
        """Replace all occurrences (replace_all=true)."""
        # Given
        tool, storage = _make_tool(
            files={"/workspace/agent/data.txt": b"foo bar foo baz foo"}
        )

        # When
        result = await tool.handler(
            json.dumps(
                {
                    "path": "/workspace/agent/data.txt",
                    "old_string": "foo",
                    "new_string": "qux",
                    "replace_all": True,
                }
            )
        )

        # Then
        assert isinstance(result, str)
        assert "replaced 3 occurrence(s)" in result
        _, data = storage.put_calls[0]
        assert data == b"qux bar qux baz qux"

    async def test_replace_multiline(self) -> None:
        """Replace multiline text."""
        # Given
        original = b"line1\nline2\nline3\n"
        tool, storage = _make_tool(files={"/workspace/agent/multi.txt": original})

        # When
        await tool.handler(
            json.dumps(
                {
                    "path": "/workspace/agent/multi.txt",
                    "old_string": "line2",
                    "new_string": "replaced",
                }
            )
        )

        # Then
        _, data = storage.put_calls[0]
        assert data == b"line1\nreplaced\nline3\n"


# ---------------------------------------------------------------------------
# TestEditErrors
# ---------------------------------------------------------------------------


class TestEditErrors:
    """Error case tests."""

    async def test_file_not_found(self) -> None:
        """Nonexistent file raises FunctionToolError."""
        tool, _ = _make_tool()
        with pytest.raises(FunctionToolError, match="File not found"):
            await tool.handler(
                json.dumps(
                    {
                        "path": "/workspace/agent/missing.txt",
                        "old_string": "x",
                        "new_string": "y",
                    }
                )
            )

    async def test_old_string_not_found(self) -> None:
        """Missing old_string raises FunctionToolError."""
        tool, _ = _make_tool(files={"/workspace/agent/note.txt": b"Hello, world!"})
        with pytest.raises(FunctionToolError, match="old_string not found"):
            await tool.handler(
                json.dumps(
                    {
                        "path": "/workspace/agent/note.txt",
                        "old_string": "missing text",
                        "new_string": "replacement",
                    }
                )
            )

    async def test_multiple_occurrences_without_replace_all(self) -> None:
        """Multiple occurrences raise FunctionToolError when replace_all=false."""
        tool, _ = _make_tool(files={"/workspace/agent/dup.txt": b"foo foo foo"})
        with pytest.raises(FunctionToolError, match="found 3 times"):
            await tool.handler(
                json.dumps(
                    {
                        "path": "/workspace/agent/dup.txt",
                        "old_string": "foo",
                        "new_string": "bar",
                    }
                )
            )

    async def test_binary_file(self) -> None:
        """Non-UTF-8 file raises FunctionToolError."""
        tool, _ = _make_tool(files={"/workspace/agent/bin.dat": b"\xff\xfe\x00\x01"})
        with pytest.raises(FunctionToolError, match="not valid UTF-8"):
            await tool.handler(
                json.dumps(
                    {
                        "path": "/workspace/agent/bin.dat",
                        "old_string": "x",
                        "new_string": "y",
                    }
                )
            )

    async def test_unsupported_path(self) -> None:
        """Disallowed path raises FunctionToolError."""
        tool, _ = _make_tool()
        with pytest.raises(FunctionToolError, match="File not found"):
            await tool.handler(
                json.dumps(
                    {
                        "path": "/tmp/f.txt",
                        "old_string": "x",
                        "new_string": "y",
                    }
                )
            )

    async def test_read_only_scope_write_error(self) -> None:
        """Writing read-only path raises FunctionToolError."""
        tool, _ = _make_tool(
            files={"/workspace/agent/data.txt": b"content"},
            raise_permission_on_put=True,
        )
        with pytest.raises(FunctionToolError, match="read-only scope"):
            await tool.handler(
                json.dumps(
                    {
                        "path": "/workspace/agent/data.txt",
                        "old_string": "content",
                        "new_string": "new",
                    }
                )
            )
