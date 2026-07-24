"""glob tool tests."""

import json

import pytest

from azents.engine.io.attachments import RuntimeAttachment
from azents.engine.run.types import FunctionTool, FunctionToolError
from azents.engine.tools.glob import make_glob_tool
from azents.engine.tools.testing import FakeSharedStorage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool(
    *,
    files: dict[str, bytes] | None = None,
    agent_id: str = "agent-1",
) -> tuple[FunctionTool, FakeSharedStorage]:
    """Create glob tool and fake storage for tests."""
    storage = FakeSharedStorage(files)
    tool = make_glob_tool(
        session_storage=storage,
        agent_id=agent_id,
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

    async def test_recursive_brace_pattern_matches_current_and_nested_directories(
        self,
    ) -> None:
        """Match brace alternatives with `**` consuming zero or more directories."""
        tool, _ = _make_tool(
            files={
                "/foo/bar/baz.jpg": b"jpg",
                "/foo/bar/baz.png": b"png",
                "/foo/bar/images/baz.jpg": b"nested-jpg",
                "/foo/bar/images/baz.png": b"nested-png",
                "/foo/bar/baz.gif": b"gif",
                "/foo/bar/images/other.jpg": b"other",
            }
        )

        result = await tool.handler(
            json.dumps({"pattern": "/foo/bar/**/baz.{jpg,png}"})
        )

        assert isinstance(result, str)
        assert "/foo/bar/baz.jpg" in result
        assert "/foo/bar/baz.png" in result
        assert "/foo/bar/images/baz.jpg" in result
        assert "/foo/bar/images/baz.png" in result
        assert "/foo/bar/baz.gif" not in result
        assert "/foo/bar/images/other.jpg" not in result

    async def test_nested_brace_alternatives(self) -> None:
        """Expand nested comma-separated brace alternatives."""
        tool, _ = _make_tool(
            files={
                "/foo/baz.jpg": b"jpg",
                "/foo/baz.jpeg": b"jpeg",
                "/foo/baz.png": b"png",
                "/foo/baz.gif": b"gif",
            }
        )

        result = await tool.handler(
            json.dumps({"pattern": "/foo/baz.{jpg,{jpeg,png}}"})
        )

        assert isinstance(result, str)
        assert "/foo/baz.jpg" in result
        assert "/foo/baz.jpeg" in result
        assert "/foo/baz.png" in result
        assert "/foo/baz.gif" not in result

    async def test_unbalanced_braces_remain_literal(self) -> None:
        """Keep an unbalanced brace expression literal like Bash."""
        tool, _ = _make_tool(
            files={
                "/foo/baz.{jpg,png": b"literal",
                "/foo/baz.jpg": b"jpg",
                "/foo/baz.png": b"png",
            }
        )

        result = await tool.handler(json.dumps({"pattern": "/foo/baz.{jpg,png"}))

        assert isinstance(result, str)
        assert "/foo/baz.{jpg,png" in result
        assert "/foo/baz.jpg" not in result
        assert "/foo/baz.png" not in result

    async def test_later_balanced_brace_expands_after_unmatched_opening(self) -> None:
        """Expand a later balanced group after an unmatched opening brace."""
        tool, _ = _make_tool(
            files={
                "/foo/{literal/baz.jpg": b"jpg",
                "/foo/{literal/baz.png": b"png",
            }
        )

        result = await tool.handler(
            json.dumps({"pattern": "/foo/{literal/baz.{jpg,png}"})
        )

        assert isinstance(result, str)
        assert "/foo/{literal/baz.jpg" in result
        assert "/foo/{literal/baz.png" in result

    async def test_later_brace_expands_after_literal_braces(self) -> None:
        """Continue searching after a balanced brace without alternatives."""
        tool, _ = _make_tool(
            files={
                "/foo/{literal}/baz.jpg": b"jpg",
                "/foo/{literal}/baz.png": b"png",
            }
        )

        result = await tool.handler(
            json.dumps({"pattern": "/foo/{literal}/baz.{jpg,png}"})
        )

        assert isinstance(result, str)
        assert "/foo/{literal}/baz.jpg" in result
        assert "/foo/{literal}/baz.png" in result

    async def test_brace_pattern_in_directory_segment(self) -> None:
        """List from the non-glob prefix when braces select directories."""
        tool, _ = _make_tool(
            files={
                "/foo/bar/report.txt": b"bar",
                "/foo/baz/report.txt": b"baz",
                "/foo/qux/report.txt": b"qux",
            }
        )

        result = await tool.handler(json.dumps({"pattern": "/foo/{bar,baz}/*.txt"}))

        assert isinstance(result, str)
        assert "/foo/bar/report.txt" in result
        assert "/foo/baz/report.txt" in result
        assert "/foo/qux/report.txt" not in result

    async def test_match_recursive_hidden_directory_pattern(self) -> None:
        """Find recursive patterns under hidden directories."""
        tool, _ = _make_tool(
            files={
                "/workspace/agent/.claude/skills/feature-design/SKILL.md": b"s",
                "/workspace/agent/.claude/skills/create-pr/SKILL.md": b"c",
                "/workspace/agent/.claude/settings.json": b"{}",
            }
        )

        result = await tool.handler(
            json.dumps({"pattern": "/workspace/agent/.claude/skills/**"})
        )

        assert isinstance(result, str)
        assert "/workspace/agent/.claude/skills/feature-design" in result
        assert "/workspace/agent/.claude/skills/feature-design/SKILL.md" in result
        assert "/workspace/agent/.claude/skills/create-pr/SKILL.md" in result
        assert "settings.json" not in result

    async def test_match_hidden_directory_child_directories(self) -> None:
        """Glob patterns also return directory matches."""
        tool, _ = _make_tool(
            files={
                "/workspace/agent/.claude/skills/feature-design/SKILL.md": b"s",
                "/workspace/agent/.claude/skills/create-pr/SKILL.md": b"c",
            }
        )

        result = await tool.handler(
            json.dumps({"pattern": "/workspace/agent/.claude/skills/*"})
        )

        assert isinstance(result, str)
        assert "/workspace/agent/.claude/skills/feature-design" in result
        assert "/workspace/agent/.claude/skills/create-pr" in result

    async def test_default_exclude_skips_node_modules(self) -> None:
        """Skip heavy directories with default exclude."""
        tool, _ = _make_tool(
            files={
                "/workspace/agent/src/app.ts": b"a",
                "/workspace/agent/node_modules/pkg/index.ts": b"b",
            }
        )

        result = await tool.handler(json.dumps({"pattern": "/workspace/agent/**"}))

        assert isinstance(result, str)
        assert "/workspace/agent/src/app.ts" in result
        assert "node_modules" not in result

    async def test_exclude_adds_to_default_excludes(self) -> None:
        """exclude adds patterns while preserving default excludes."""
        tool, _ = _make_tool(
            files={
                "/workspace/agent/src/app.ts": b"a",
                "/workspace/agent/generated/output.ts": b"b",
                "/workspace/agent/node_modules/pkg/index.ts": b"c",
            }
        )

        result = await tool.handler(
            json.dumps(
                {
                    "pattern": "/workspace/agent/**",
                    "exclude": ["generated"],
                }
            )
        )

        assert isinstance(result, str)
        assert "/workspace/agent/src/app.ts" in result
        assert "generated" not in result
        assert "node_modules" not in result

    async def test_disable_default_excludes_allows_node_modules(self) -> None:
        """disable_default_excludes=true allows default-excluded directories."""
        tool, _ = _make_tool(
            files={
                "/workspace/agent/src/app.ts": b"a",
                "/workspace/agent/node_modules/pkg/index.ts": b"b",
            }
        )

        result = await tool.handler(
            json.dumps(
                {
                    "pattern": "/workspace/agent/**/node_modules/**",
                    "disable_default_excludes": True,
                }
            )
        )

        assert isinstance(result, str)
        assert "/workspace/agent/node_modules/pkg/index.ts" in result
        assert "/workspace/agent/src/app.ts" not in result

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

    @pytest.mark.parametrize("group_count", [9, 1000])
    async def test_brace_expansion_limit_is_rejected(self, group_count: int) -> None:
        """Reject excessive alternatives without recursive parser failure."""
        tool, _ = _make_tool()
        pattern = "/foo/" + "{a,b}" * group_count

        with pytest.raises(FunctionToolError, match="maximum of 256 alternatives"):
            await tool.handler(json.dumps({"pattern": pattern}))

    @pytest.mark.parametrize("pattern", ["~", "~/*.txt", "~alice/*.txt"])
    async def test_tilde_expansion_is_rejected(self, pattern: str) -> None:
        """Reject shell-dependent home-directory expansion."""
        tool, _ = _make_tool()

        with pytest.raises(FunctionToolError, match="Tilde expansion is not supported"):
            await tool.handler(json.dumps({"pattern": pattern}))

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
                include_directories: bool = False,
            ) -> list[RuntimeAttachment]:
                _ = agent_id, user_id, recursive, exclude_patterns, include_directories
                raise FileNotFoundError(f"Directory not found: {path}")

        storage = _RaisingStorage()
        tool = make_glob_tool(
            session_storage=storage,
            agent_id="agent-1",
        )
        result = await tool.handler(
            json.dumps({"pattern": "/workspace/agent/user/memories/*.md"})
        )
        assert isinstance(result, str)
        assert "No files matched" in result
