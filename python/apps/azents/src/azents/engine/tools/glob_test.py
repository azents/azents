"""glob tool tests."""

import json

from azents.engine.io.attachments import RuntimeAttachment
from azents.engine.run.types import FunctionTool
from azents.engine.tools.glob import make_glob_tool
from azents.engine.tools.testing import FakeSharedStorage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool(
    *,
    files: dict[str, bytes] | None = None,
    agent_id: str = "agent-1",
    user_id: str = "user-1",
) -> tuple[FunctionTool, FakeSharedStorage]:
    """Create glob tool and fake storage for tests."""
    storage = FakeSharedStorage(files)
    tool = make_glob_tool(
        session_storage=storage,
        agent_id=agent_id,
        user_id=user_id,
    )
    return tool, storage


# ---------------------------------------------------------------------------
# TestGlob
# ---------------------------------------------------------------------------


class TestGlob:
    """File pattern search tests."""

    async def test_match_all_txt(self) -> None:
        """Match only txt files with *.txt pattern."""
        tool, _ = _make_tool(
            files={
                "/workspace/agent/file1.txt": b"a",
                "/workspace/agent/file2.txt": b"b",
                "/workspace/agent/image.png": b"img",
            }
        )
        result = await tool.handler(json.dumps({"pattern": "/workspace/agent/*.txt"}))
        assert isinstance(result, str)
        assert "file1.txt" in result
        assert "file2.txt" in result
        assert "image.png" not in result

    async def test_match_nested_pattern(self) -> None:
        """Match nested pattern (skills/*/SKILL.md)."""
        tool, _ = _make_tool(
            files={
                "/workspace/agent/skills/search/SKILL.md": b"s",
                "/workspace/agent/skills/code/SKILL.md": b"c",
                "/workspace/agent/skills/code/README.md": b"r",
            }
        )
        result = await tool.handler(
            json.dumps({"pattern": "/workspace/agent/skills/*/SKILL.md"})
        )
        assert isinstance(result, str)
        assert "SKILL.md" in result

    async def test_no_matches(self) -> None:
        """Return guidance message when no file matches."""
        tool, _ = _make_tool(files={"/workspace/agent/data.csv": b"x"})
        result = await tool.handler(json.dumps({"pattern": "/workspace/agent/*.txt"}))
        assert isinstance(result, str)
        assert "No files matched" in result

    async def test_empty_directory(self) -> None:
        """Empty directory has no matches."""
        tool, _ = _make_tool()
        result = await tool.handler(json.dumps({"pattern": "/workspace/agent/*"}))
        assert isinstance(result, str)
        assert "No files matched" in result

    async def test_match_all(self) -> None:
        """Match all files with * pattern."""
        tool, _ = _make_tool(
            files={
                "/workspace/agent/a.txt": b"a",
                "/workspace/agent/b.md": b"b",
            }
        )

        # When
        result = await tool.handler(json.dumps({"pattern": "/workspace/agent/*"}))

        # Then
        assert isinstance(result, str)
        assert "2 file(s)" in result


# ---------------------------------------------------------------------------
# TestGlobErrors
# ---------------------------------------------------------------------------


class TestGlobErrors:
    """Error case tests."""

    async def test_no_matches_for_invalid_prefix(self) -> None:
        """Nonexistent path prefix pattern has no matches."""
        tool, _ = _make_tool()
        result = await tool.handler(json.dumps({"pattern": "/tmp/*.txt"}))
        assert isinstance(result, str)
        assert "No files matched" in result

    async def test_relative_path_pattern_no_matches(self) -> None:
        """Relative path pattern has no matches."""
        tool, _ = _make_tool()
        result = await tool.handler(json.dumps({"pattern": "agent/*.txt"}))
        assert isinstance(result, str)
        assert "No files matched" in result

    async def test_directory_not_found_returns_no_matches(self) -> None:
        """Return no matches when list() raises FileNotFoundError."""

        class _RaisingStorage(FakeSharedStorage):
            async def list(
                self,
                path: str,
                *,
                agent_id: str = "",
                user_id: str = "",
                recursive: bool = False,
                exclude_patterns: list[str] | None = None,
            ) -> list[RuntimeAttachment]:
                _ = agent_id, user_id, recursive, exclude_patterns
                raise FileNotFoundError(f"Directory not found: {path}")

        storage = _RaisingStorage()
        tool = make_glob_tool(
            session_storage=storage,
            agent_id="agent-1",
            user_id="user-1",
        )
        result = await tool.handler(
            json.dumps({"pattern": "/workspace/agent/user/memories/*.md"})
        )
        assert isinstance(result, str)
        assert "No files matched" in result
