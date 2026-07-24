"""grep tool tests."""

import json

import pytest

from azents.engine.io.attachments import RuntimeAttachment
from azents.engine.run.types import FunctionTool, FunctionToolError
from azents.engine.tools.grep import make_grep_tool
from azents.engine.tools.testing import FakeSharedStorage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool(
    *,
    files: dict[str, bytes] | None = None,
    agent_id: str = "agent-1",
) -> tuple[FunctionTool, FakeSharedStorage]:
    """Create grep tool and fake storage for tests."""
    storage = FakeSharedStorage(files)
    tool = make_grep_tool(
        session_storage=storage,
        agent_id=agent_id,
    )
    return tool, storage


# ---------------------------------------------------------------------------
# TestGrep
# ---------------------------------------------------------------------------


class TestGrep:
    """Text search tests."""

    async def test_find_pattern_in_single_file(self) -> None:
        """Find pattern in single file."""
        # Given
        tool, _ = _make_tool(
            files={
                "/workspace/agent/notes.txt": (
                    b"line1 hello\nline2 world\nline3 hello world"
                ),
            },
        )

        # When
        result = await tool.handler(
            json.dumps(
                {
                    "pattern": "hello",
                    "path": "/workspace/agent/",
                }
            )
        )

        # Then
        assert isinstance(result, str)
        assert "1 file(s)" in result
        assert "notes.txt" in result
        assert "1: line1 hello" in result
        assert "3: line3 hello world" in result

    async def test_find_pattern_in_multiple_files(self) -> None:
        """Find pattern in multiple files."""
        # Given
        tool, _ = _make_tool(
            files={
                "/workspace/agent/a.txt": b"foo bar\nbaz",
                "/workspace/agent/b.txt": b"hello foo\nworld",
            },
        )

        # When
        result = await tool.handler(
            json.dumps(
                {
                    "pattern": "foo",
                    "path": "/workspace/agent/",
                }
            )
        )

        # Then
        assert isinstance(result, str)
        assert "2 file(s)" in result
        assert "a.txt" in result
        assert "b.txt" in result

    async def test_find_pattern_in_nested_files_by_default(self) -> None:
        """Search subdirectories recursively by default."""
        # Given
        tool, _ = _make_tool(
            files={
                "/workspace/agent/src/a.txt": b"target",
                "/workspace/agent/src/nested/b.txt": b"target",
            },
        )

        # When
        result = await tool.handler(
            json.dumps(
                {
                    "pattern": "target",
                    "path": "/workspace/agent/src",
                }
            )
        )

        # Then
        assert isinstance(result, str)
        assert "2 file(s)" in result
        assert "a.txt" in result
        assert "b.txt" in result

    async def test_file_path_searches_single_file(self) -> None:
        """When file path is passed directly, search only that file."""
        # Given
        tool, _ = _make_tool(
            files={
                "/workspace/agent/src/a.txt": b"target",
                "/workspace/agent/src/b.txt": b"target",
            },
        )

        # When
        result = await tool.handler(
            json.dumps(
                {
                    "pattern": "target",
                    "path": "/workspace/agent/src/a.txt",
                }
            )
        )

        # Then
        assert isinstance(result, str)
        assert "1 file(s)" in result
        assert "a.txt" in result
        assert "b.txt" not in result

    async def test_default_exclude_skips_node_modules(self) -> None:
        """Skip heavy directories with default exclude."""
        # Given
        tool, _ = _make_tool(
            files={
                "/workspace/agent/src/app.ts": b"target",
                "/workspace/agent/node_modules/pkg/index.ts": b"target",
            },
        )

        # When
        result = await tool.handler(
            json.dumps(
                {
                    "pattern": "target",
                    "path": "/workspace/agent",
                }
            )
        )

        # Then
        assert isinstance(result, str)
        assert "1 file(s)" in result
        assert "app.ts" in result
        assert "node_modules" not in result

    async def test_explicit_empty_exclude_keeps_default_exclude(self) -> None:
        """An empty exclude list does not disable default excludes."""
        # Given
        tool, _ = _make_tool(
            files={
                "/workspace/agent/src/app.ts": b"target",
                "/workspace/agent/node_modules/pkg/index.ts": b"target",
            },
        )

        # When
        result = await tool.handler(
            json.dumps(
                {
                    "pattern": "target",
                    "path": "/workspace/agent",
                    "exclude": [],
                }
            )
        )

        # Then
        assert isinstance(result, str)
        assert "1 file(s)" in result
        assert "app.ts" in result
        assert "node_modules" not in result

    async def test_exclude_adds_to_default_excludes(self) -> None:
        """exclude adds patterns while preserving default excludes."""
        tool, _ = _make_tool(
            files={
                "/workspace/agent/src/app.ts": b"target",
                "/workspace/agent/.next/cache.js": b"target",
                "/workspace/agent/generated/output.ts": b"target",
            },
        )

        result = await tool.handler(
            json.dumps(
                {
                    "pattern": "target",
                    "path": "/workspace/agent",
                    "exclude": ["generated"],
                }
            )
        )

        assert isinstance(result, str)
        assert "1 file(s)" in result
        assert "app.ts" in result
        assert ".next" not in result
        assert "generated" not in result

    async def test_disable_default_excludes_allows_heavy_directories(self) -> None:
        """disable_default_excludes=true skips default excludes."""
        tool, _ = _make_tool(
            files={
                "/workspace/agent/src/app.ts": b"target",
                "/workspace/agent/node_modules/pkg/index.ts": b"target",
            },
        )

        result = await tool.handler(
            json.dumps(
                {
                    "pattern": "target",
                    "path": "/workspace/agent",
                    "disable_default_excludes": True,
                }
            )
        )

        assert isinstance(result, str)
        assert "2 file(s)" in result
        assert "app.ts" in result
        assert "node_modules" in result

    async def test_recursive_false_searches_direct_files_only(self) -> None:
        """When recursive=false, search only direct files."""
        # Given
        tool, _ = _make_tool(
            files={
                "/workspace/agent/src/a.txt": b"target",
                "/workspace/agent/src/nested/b.txt": b"target",
            },
        )

        # When
        result = await tool.handler(
            json.dumps(
                {
                    "pattern": "target",
                    "path": "/workspace/agent/src",
                    "recursive": False,
                }
            )
        )

        # Then
        assert isinstance(result, str)
        assert "1 file(s)" in result
        assert "a.txt" in result
        assert "b.txt" not in result

    async def test_regex_pattern(self) -> None:
        """Search with regex pattern."""
        # Given
        tool, _ = _make_tool(
            files={
                "/workspace/agent/code.py": (
                    b"def hello():\n    return 42\ndef world():\n    pass"
                ),
            },
        )

        # When
        result = await tool.handler(
            json.dumps(
                {
                    "pattern": r"def \w+\(\)",
                    "path": "/workspace/agent/",
                }
            )
        )

        # Then
        assert isinstance(result, str)
        assert "1 file(s)" in result
        assert "1: def hello():" in result
        assert "3: def world():" in result

    async def test_no_matches(self) -> None:
        """Return guidance message when no match result exists."""
        # Given
        tool, _ = _make_tool(
            files={"/workspace/agent/data.txt": b"some content"},
        )

        # When
        result = await tool.handler(
            json.dumps(
                {
                    "pattern": "notfound",
                    "path": "/workspace/agent/",
                }
            )
        )

        # Then
        assert isinstance(result, str)
        assert "No matches found" in result

    async def test_empty_directory(self) -> None:
        """Empty directory returns no-files message."""
        # Given
        tool, _ = _make_tool(files={})

        # When
        result = await tool.handler(
            json.dumps(
                {
                    "pattern": "test",
                    "path": "/workspace/agent/",
                }
            )
        )

        # Then
        assert isinstance(result, str)
        assert "No files found" in result

    async def test_skip_binary_files(self) -> None:
        """Skip binary files."""
        # Given
        tool, _ = _make_tool(
            files={
                "/workspace/agent/text.txt": b"hello world",
                "/workspace/agent/bin.dat": b"\xff\xfe\x00\x01",
            },
        )

        # When
        result = await tool.handler(
            json.dumps(
                {
                    "pattern": ".*",
                    "path": "/workspace/agent/",
                }
            )
        )

        # Then: Only text files are included in result
        assert isinstance(result, str)
        assert "1 file(s)" in result
        assert "text.txt" in result
        assert "bin.dat" not in result


# ---------------------------------------------------------------------------
# TestGrepErrors
# ---------------------------------------------------------------------------


class TestGrepErrors:
    """Error case tests."""

    async def test_invalid_regex(self) -> None:
        """Invalid regex raises FunctionToolError."""
        tool, _ = _make_tool()
        with pytest.raises(FunctionToolError, match="Invalid regex"):
            await tool.handler(
                json.dumps(
                    {
                        "pattern": "[invalid",
                        "path": "/workspace/agent/",
                    }
                )
            )

    async def test_unsupported_path(self) -> None:
        """Disallowed path returns no files."""
        tool, _ = _make_tool()
        result = await tool.handler(
            json.dumps(
                {
                    "pattern": "test",
                    "path": "/tmp/",
                }
            )
        )
        assert isinstance(result, str)
        assert "No files found" in result

    async def test_relative_path(self) -> None:
        """Relative path returns no files."""
        tool, _ = _make_tool()
        result = await tool.handler(
            json.dumps(
                {
                    "pattern": "test",
                    "path": "agent/",
                }
            )
        )
        assert isinstance(result, str)
        assert "No files found" in result

    async def test_directory_not_found_returns_no_files(self) -> None:
        """Return no files when list() raises FileNotFoundError."""

        class _RaisingStorage(FakeSharedStorage):
            async def list(
                self,
                path: str,
                *,
                agent_id: str = "",
                user_id: str = "",
                recursive: bool = False,
                exclude_patterns: list[str] | None = None,
                include_directories: bool = False,
            ) -> list[RuntimeAttachment]:
                _ = agent_id, user_id, recursive, exclude_patterns, include_directories
                raise FileNotFoundError(f"Directory not found: {path}")

        storage = _RaisingStorage()
        tool = make_grep_tool(
            session_storage=storage,
            agent_id="agent-1",
        )
        result = await tool.handler(
            json.dumps({"pattern": "test", "path": "/workspace/agent/user/memories/"})
        )
        assert isinstance(result, str)
        assert "No files found" in result
