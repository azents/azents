"""ClaudeRulesToolkit discovery and appendix tests."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from azents.core.tools import TurnContext
from azents.engine.hooks.types import (
    AfterToolCallHookContext,
    SessionCompactHookContext,
    ToolOutputReplace,
)
from azents.engine.io.attachments import RuntimeAttachment
from azents.engine.tools.claude_rules import (
    ClaudeRuleFile,
    ClaudeRuleRoot,
    ClaudeRulesAppendixDedupeState,
    ClaudeRulesToolkit,
    claude_rule_roots_for_path,
    discover_claude_rule_files,
    render_claude_rules_appendix,
    rule_matches_target,
    truncate_claude_rule_content,
)
from azents.engine.tools.runtime_instruction_context import (
    RuntimeInstructionContext,
    RuntimeInstructionContextStore,
)
from azents.engine.tools.testing import FakeSharedStorage
from azents.repos.session_workspace_project.data import SessionWorkspaceProject
from azents.services.runtime_storage_error import RuntimeStorageError


class _FakeClaudeRulesAppendixDedupeStateStore:
    """Claude rules appendix dedupe state store for tests."""

    def __init__(self) -> None:
        self.dedupe_states: dict[tuple[str, str], ClaudeRulesAppendixDedupeState] = {}

    async def load_appendix_dedupe(
        self, agent_id: str, session_id: str
    ) -> ClaudeRulesAppendixDedupeState:
        """Return stored appendix dedupe state."""
        return self.dedupe_states.get(
            (agent_id, session_id), ClaudeRulesAppendixDedupeState()
        )

    async def update_appendix_dedupe(
        self,
        agent_id: str,
        session_id: str,
        mutator: Callable[
            [ClaudeRulesAppendixDedupeState], ClaudeRulesAppendixDedupeState
        ],
    ) -> None:
        """Apply appendix dedupe state update."""
        state = await self.load_appendix_dedupe(agent_id, session_id)
        self.dedupe_states[(agent_id, session_id)] = mutator(state)


class _FailingListStorage(FakeSharedStorage):
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
        """Simulate runtime communication failure."""
        del path, agent_id, user_id, recursive, exclude_patterns, include_directories
        raise RuntimeStorageError("runtime disconnected")


class _SymlinkStorage(FakeSharedStorage):
    def __init__(
        self,
        files: dict[str, bytes],
        *,
        real_paths: dict[str, str],
    ) -> None:
        super().__init__(files)
        self._real_paths = real_paths

    async def stat(
        self,
        path: str,
        *,
        agent_id: str = "",
        user_id: str = "",
    ) -> dict[str, object]:
        """Return metadata with configured real path."""
        metadata = await super().stat(path, agent_id=agent_id, user_id=user_id)
        metadata["real_path"] = self._real_paths.get(path)
        return metadata


def _make_project(*, path: str = "/workspace/agent/project") -> SessionWorkspaceProject:
    """Create SessionWorkspaceProject for tests."""
    now = datetime.now(UTC)
    return SessionWorkspaceProject(
        id="project-1",
        session_id="session-1",
        path=path,
        created_at=now,
        updated_at=now,
    )


def _make_after_read_context(
    path: str,
    *,
    tool_name: str = "read",
    output_text: str | None = "file body",
    error_message: str | None = None,
) -> AfterToolCallHookContext:
    """Create successful read hook context."""
    return AfterToolCallHookContext(
        tool_name=tool_name,
        toolkit_slug="shell",
        args_json=f'{{"path": "{path}"}}',
        workspace_id="ws-1",
        agent_id="agent-1",
        session_id="session-1",
        run_id="run-1",
        output_text=output_text,
        error_message=error_message,
    )


def _make_toolkit(storage: FakeSharedStorage) -> ClaudeRulesToolkit:
    """Create toolkit with shared runtime instruction context."""
    store = _FakeClaudeRulesAppendixDedupeStateStore()
    toolkit = ClaudeRulesToolkit(
        store=store, agent_id="agent-1", session_id="session-1"
    )
    context_store = RuntimeInstructionContextStore()
    context_store.set(
        RuntimeInstructionContext(
            file_storage=storage,
            projects=(_make_project(),),
        )
    )
    toolkit.set_instruction_context_store(context_store)
    return toolkit


async def _run_after_tool_call_hook(
    toolkit: ClaudeRulesToolkit,
    context: AfterToolCallHookContext,
) -> ToolOutputReplace | None:
    """Run public after-tool hook mapping for tests."""
    hook = toolkit.hooks().get("on_after_tool_call")
    assert hook is not None
    result = await hook(context)
    assert result is None or isinstance(result, ToolOutputReplace)
    return result


async def _run_session_compact_hook(
    toolkit: ClaudeRulesToolkit,
    context: SessionCompactHookContext,
) -> None:
    """Run public compaction hook mapping for tests."""
    hook = toolkit.hooks().get("on_session_compact")
    assert hook is not None
    await hook(context)


class TestClaudeRuleRoots:
    """Claude rule root selection tests."""

    def test_workspace_file_uses_workspace_root_only(self) -> None:
        """Workspace files outside registered Projects use only workspace rules."""
        roots = claude_rule_roots_for_path(
            "/workspace/agent/notes.txt",
            [_make_project()],
        )

        assert [(root.kind, root.rules_root) for root in roots] == [
            ("workspace", "/workspace/agent/.claude/rules")
        ]

    def test_project_file_uses_workspace_then_project_roots(self) -> None:
        """Project files use workspace rules before Project rules."""
        roots = claude_rule_roots_for_path(
            "/workspace/agent/project/src/app.py",
            [_make_project()],
        )

        assert [(root.kind, root.rules_root) for root in roots] == [
            ("workspace", "/workspace/agent/.claude/rules"),
            ("project", "/workspace/agent/project/.claude/rules"),
        ]


class TestClaudeRuleDiscovery:
    """Claude rule discovery tests."""

    async def test_discovers_markdown_files_deterministically(self) -> None:
        """Discovery returns Markdown rule files in sorted path order."""
        storage = FakeSharedStorage(
            {
                "/workspace/agent/.claude/rules/b.md": b"b",
                "/workspace/agent/.claude/rules/a.md": b"a",
                "/workspace/agent/.claude/rules/ignored.txt": b"x",
            }
        )

        files = await discover_claude_rule_files(
            storage,
            [
                ClaudeRuleRoot(
                    owner_root="/workspace/agent",
                    rules_root="/workspace/agent/.claude/rules",
                    kind="workspace",
                )
            ],
            agent_id="agent-1",
        )

        assert [file.path for file in files] == [
            "/workspace/agent/.claude/rules/a.md",
            "/workspace/agent/.claude/rules/b.md",
        ]

    async def test_realpath_dedupe_keeps_first_root_order_occurrence(self) -> None:
        """Duplicate resolved paths keep the first source-root occurrence."""
        workspace_rule = "/workspace/agent/.claude/rules/shared.md"
        project_rule = "/workspace/agent/project/.claude/rules/shared.md"
        storage = _SymlinkStorage(
            {
                workspace_rule: b"workspace",
                project_rule: b"project",
            },
            real_paths={
                workspace_rule: "/workspace/agent/shared.md",
                project_rule: "/workspace/agent/shared.md",
            },
        )

        files = await discover_claude_rule_files(
            storage,
            claude_rule_roots_for_path(
                "/workspace/agent/project/src/app.py",
                [_make_project()],
            ),
            agent_id="agent-1",
        )

        assert [file.content for file in files] == ["workspace"]

    async def test_symlink_outside_owner_root_is_skipped(self) -> None:
        """Rules resolving outside their owner root are skipped quietly."""
        outside_rule = "/workspace/agent/project/.claude/rules/outside.md"
        storage = _SymlinkStorage(
            {outside_rule: b"outside"},
            real_paths={outside_rule: "/workspace/agent/other/outside.md"},
        )

        files = await discover_claude_rule_files(
            storage,
            [
                ClaudeRuleRoot(
                    owner_root="/workspace/agent/project",
                    rules_root="/workspace/agent/project/.claude/rules",
                    kind="project",
                )
            ],
            agent_id="agent-1",
        )

        assert files == []


class TestClaudeRuleMatching:
    """Claude rule frontmatter and glob matching tests."""

    def test_global_rule_matches_owner_root(self) -> None:
        """Rules without paths apply to their owner root."""
        roots = claude_rule_roots_for_path(
            "/workspace/agent/project/src/app.py",
            [_make_project()],
        )

        assert rule_matches_target(
            "# Global",
            "/workspace/agent/project/.claude/rules/global.md",
            roots,
            "/workspace/agent/project/src/app.py",
        )

    def test_relative_paths_glob_uses_owner_root_and_segment_aware_starstar(
        self,
    ) -> None:
        """Relative globs resolve against owner root and support ** segments."""
        roots = claude_rule_roots_for_path(
            "/workspace/agent/project/src/app.py",
            [_make_project()],
        )

        assert rule_matches_target(
            "---\npaths: src/**/*.py\n---\n# Python",
            "/workspace/agent/project/.claude/rules/python.md",
            roots,
            "/workspace/agent/project/src/app.py",
        )
        assert rule_matches_target(
            "---\npaths: src/**/*.py\n---\n# Python",
            "/workspace/agent/project/.claude/rules/python.md",
            roots,
            "/workspace/agent/project/src/pkg/app.py",
        )
        assert not rule_matches_target(
            "---\npaths: src/**/*.py\n---\n# Python",
            "/workspace/agent/project/.claude/rules/python.md",
            roots,
            "/workspace/agent/project/tests/app.py",
        )

    def test_absolute_paths_glob_matches_absolute_runtime_path(self) -> None:
        """Absolute globs match normalized absolute Runtime paths."""
        roots = claude_rule_roots_for_path(
            "/workspace/agent/project/src/app.py",
            [_make_project()],
        )

        assert rule_matches_target(
            "---\npaths:\n  - /workspace/agent/project/**/*.py\n---\n# Python",
            "/workspace/agent/.claude/rules/python.md",
            roots,
            "/workspace/agent/project/src/app.py",
        )

    def test_malformed_frontmatter_and_bad_paths_shape_skip(self) -> None:
        """Malformed or unsupported paths metadata skips the rule quietly."""
        roots = claude_rule_roots_for_path(
            "/workspace/agent/project/src/app.py",
            [_make_project()],
        )

        assert not rule_matches_target(
            "---\npaths: [unterminated\n---\n# Bad",
            "/workspace/agent/.claude/rules/bad.md",
            roots,
            "/workspace/agent/project/src/app.py",
        )
        assert not rule_matches_target(
            "---\npaths: {bad: shape}\n---\n# Bad",
            "/workspace/agent/.claude/rules/bad.md",
            roots,
            "/workspace/agent/project/src/app.py",
        )


class TestClaudeRulesToolkit:
    """ClaudeRulesToolkit hook behavior tests."""

    async def test_successful_read_appends_matching_rules_once(self) -> None:
        """Successful reads append matching rules and then dedupe by path."""
        toolkit = _make_toolkit(
            FakeSharedStorage(
                {
                    "/workspace/agent/.claude/rules/global.md": b"# Global",
                    "/workspace/agent/project/.claude/rules/python.md": (
                        b"---\npaths: src/**/*.py\n---\n# Python"
                    ),
                }
            )
        )

        result = await _run_after_tool_call_hook(
            toolkit,
            _make_after_read_context("/workspace/agent/project/src/app.py"),
        )
        second = await _run_after_tool_call_hook(
            toolkit,
            _make_after_read_context("/workspace/agent/project/src/other.py"),
        )

        assert result is not None
        assert "Relevant Claude rules" in result.output_text
        assert "### /workspace/agent/.claude/rules/global.md" in result.output_text
        assert (
            "### /workspace/agent/project/.claude/rules/python.md" in result.output_text
        )
        assert second is None

    async def test_failed_read_and_non_read_are_unchanged(self) -> None:
        """Original read failures and non-read tools do not append rules."""
        toolkit = _make_toolkit(
            FakeSharedStorage({"/workspace/agent/.claude/rules/global.md": b"# Global"})
        )
        failed_read = _make_after_read_context(
            "/workspace/agent/project/src/app.py",
            output_text=None,
            error_message="boom",
        )
        non_read = _make_after_read_context(
            "/workspace/agent/project/src/app.py",
            tool_name="write",
        )

        assert await _run_after_tool_call_hook(toolkit, failed_read) is None
        assert await _run_after_tool_call_hook(toolkit, non_read) is None

    async def test_compaction_clears_dedupe(self) -> None:
        """Compaction clears path dedupe so rules can append again."""
        toolkit = _make_toolkit(
            FakeSharedStorage({"/workspace/agent/.claude/rules/global.md": b"# Global"})
        )

        first = await _run_after_tool_call_hook(
            toolkit,
            _make_after_read_context("/workspace/agent/project/src/app.py"),
        )
        await _run_session_compact_hook(
            toolkit,
            SessionCompactHookContext(
                workspace_id="ws-1",
                agent_id="agent-1",
                session_id="session-1",
                run_id="run-1",
            ),
        )
        second = await _run_after_tool_call_hook(
            toolkit,
            _make_after_read_context("/workspace/agent/project/src/other.py"),
        )

        assert first is not None
        assert second is not None

    async def test_runtime_storage_failure_logs_and_keeps_output_unchanged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Runtime/FileStorage communication failure logs and returns unchanged."""
        toolkit = _make_toolkit(_FailingListStorage())
        caplog.set_level(logging.ERROR)

        result = await _run_after_tool_call_hook(
            toolkit,
            _make_after_read_context("/workspace/agent/project/src/app.py"),
        )

        assert result is None
        assert "Failed to load Claude rules appendix candidates" in caplog.text

    async def test_update_context_exposes_no_tools(self) -> None:
        """Toolkit stays hook-active without exposing model-visible tools."""
        toolkit = _make_toolkit(FakeSharedStorage())

        state = await toolkit.update_context(
            TurnContext(
                user_id="user-1",
                workspace_id="ws-1",
                model="test-model",
                run_id="run-1",
                publish_event=AsyncMock(),
            )
        )

        assert state.tools == []


def test_truncate_claude_rule_content_uses_claude_rule_marker() -> None:
    """Truncation uses the Claude-rule-specific marker."""
    content = truncate_claude_rule_content(("a" * 70_000).encode())

    assert content.endswith("\n\n... (Claude rule truncated)")


def test_render_claude_rules_appendix_includes_raw_frontmatter() -> None:
    """Renderer includes raw rule content including frontmatter."""
    rendered = render_claude_rules_appendix(
        [
            ClaudeRuleFile(
                path="/workspace/agent/.claude/rules/python.md",
                real_path="/workspace/agent/.claude/rules/python.md",
                content="---\npaths: '**/*.py'\n---\n# Python",
            )
        ]
    )

    assert "---\npaths: '**/*.py'\n---" in rendered
