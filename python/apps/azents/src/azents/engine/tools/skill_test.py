"""Skill Toolkit tests."""

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from azents.engine.run.types import FunctionToolError
from azents.engine.tools.runtime_io import (
    RuntimeFileListEntry,
    RuntimeFileListResult,
    RuntimeFileReadResult,
    RuntimeRunnerOperationClient,
)
from azents.engine.tools.skill import (
    SkillProjectionItem,
    SkillProjectionService,
    SkillProjectionSnapshot,
    SkillProjectionState,
    make_load_skill_tool,
    render_skill_prompt,
    resolve_active_skill,
    skill_actions_from_snapshot,
)
from azents.repos.session_workspace_project.data import SessionWorkspaceProject


def _skill_item(
    *,
    skill_path: str = "/workspace/agent/project/.agents/skills/review/SKILL.md",
    body: str = "---\nname: review\ndescription: Review code.\n---\nBody",
) -> SkillProjectionItem:
    """Create projected Skill item for tests."""
    return SkillProjectionItem(
        id="skill-1",
        source_kind="project_agents",
        project_id="project-1",
        project_path="/workspace/agent/project",
        skill_dir_path="/workspace/agent/project/.agents/skills/review",
        skill_path=skill_path,
        slug="review",
        name="review",
        description="Review code.",
        frontmatter={"name": "review", "description": "Review code."},
        body=body,
        content_hash="hash-1",
        source_label="project",
        relative_hint=".agents/skills/review",
    )


def _project(
    path: str = "/workspace/agent/project",
) -> SessionWorkspaceProject:
    """Create a registered Project for Skill scan tests."""
    now = datetime.now(UTC)
    return SessionWorkspaceProject(
        id="project-1",
        session_id="session-1",
        session_agent_context_id="context-1",
        path=path,
        created_at=now,
        updated_at=now,
    )


class _SkillScanRunner:
    """Runtime operation test double for Skill discovery."""

    def __init__(
        self,
        *,
        entries_by_root: dict[str, tuple[str, ...]],
        files: dict[str, bytes],
    ) -> None:
        self.entries_by_root = entries_by_root
        self.files = files
        self.read_calls: list[str] = []

    async def list_files(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None,
        path: str,
        recursive: bool = False,
        exclude_patterns: list[str] | None = None,
        deadline_at: datetime,
    ) -> RuntimeFileListResult:
        """Return configured canonical directory entries for a source root."""
        del (
            runtime_id,
            runner_generation,
            owner_session_id,
            recursive,
            exclude_patterns,
            deadline_at,
        )
        entries = tuple(
            RuntimeFileListEntry(
                path=entry_path,
                type="directory",
                size_bytes=None,
            )
            for entry_path in self.entries_by_root.get(path, ())
        )
        return RuntimeFileListResult(entries=entries, final_cursor="cursor-list")

    async def read_file(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None,
        path: str,
        offset: int,
        max_bytes: int | None,
        deadline_at: datetime,
    ) -> RuntimeFileReadResult:
        """Return configured Skill content and record reads."""
        del runtime_id, runner_generation, owner_session_id, deadline_at
        self.read_calls.append(path)
        data = self.files[path]
        chunk = (
            data[offset:] if max_bytes is None else data[offset : offset + max_bytes]
        )
        return RuntimeFileReadResult(data=chunk, final_cursor="cursor-read")


class _TestableSkillProjectionService(SkillProjectionService):
    """Expose protected Skill scanning for focused service tests."""

    async def scan_runtime_for_test(
        self,
        *,
        runner_operations: RuntimeRunnerOperationClient,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str,
        projects: list[SessionWorkspaceProject],
    ) -> list[SkillProjectionItem]:
        """Delegate to the runtime scanner from an allowed subclass boundary."""
        return await self._scan_runtime(
            runner_operations=runner_operations,
            runtime_id=runtime_id,
            runner_generation=runner_generation,
            owner_session_id=owner_session_id,
            projects=projects,
        )


class _SkillStore:
    """SkillStateStore test double."""

    def __init__(self, state: SkillProjectionState) -> None:
        self.state = state

    async def load(self, agent_id: str, session_id: str) -> SkillProjectionState:
        """Return configured state."""
        del agent_id, session_id
        return self.state


class _Broadcast:
    """WebSocketBroadcast test double."""

    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, object]]] = []

    async def publish(self, session_id: str, event_json: dict[str, object]) -> None:
        """Record published event payloads."""
        self.published.append((session_id, event_json))


class TestSkillPrompt:
    """Skill prompt rendering behavior."""

    def test_render_prompt_lists_path_without_body(self) -> None:
        """Prompt renders only Skill index metadata."""
        item = _skill_item(
            body="---\nname: review\ndescription: Review code.\n---\nSECRET"
        )
        prompt = render_skill_prompt(SkillProjectionSnapshot(items=[item]))

        assert "## Skills" in prompt
        assert "**review**: Review code." in prompt
        assert f"Path: `{item.skill_path}`" in prompt
        assert "SECRET" not in prompt

    def test_render_prompt_deduplicates_exact_skill_path(self) -> None:
        """Prompt rendering keeps one entry for each exact SKILL.md path."""
        item = _skill_item()
        duplicate = item.model_copy(update={"id": "skill-duplicate"})

        prompt = render_skill_prompt(SkillProjectionSnapshot(items=[item, duplicate]))

        assert prompt.count(f"Path: `{item.skill_path}`") == 1


class TestLoadSkill:
    """load_skill tool behavior."""

    @pytest.mark.asyncio
    async def test_load_skill_returns_body_from_active_projection(self) -> None:
        """Tool resolves exact path from active projection."""
        item = _skill_item()
        store = _SkillStore(
            SkillProjectionState(active=SkillProjectionSnapshot(items=[item]))
        )
        tool = make_load_skill_tool(
            store=store,  # pyright: ignore[reportArgumentType]
            agent_id="agent-1",
            session_id="session-1",
        )

        output = await tool.handler(json.dumps({"skill_path": item.skill_path}))

        assert isinstance(output, str)
        assert "Skill loaded from the active projection." in output
        assert item.body in output
        assert item.skill_path in output

    @pytest.mark.asyncio
    async def test_load_skill_rejects_missing_path(self) -> None:
        """Tool fails fast without runtime fallback when path is absent."""
        store = _SkillStore(SkillProjectionState())
        tool = make_load_skill_tool(
            store=store,  # pyright: ignore[reportArgumentType]
            agent_id="agent-1",
            session_id="session-1",
        )

        with pytest.raises(FunctionToolError, match="Skill not found"):
            await tool.handler(json.dumps({"skill_path": "/missing/SKILL.md"}))

    @pytest.mark.asyncio
    async def test_load_skill_tolerates_legacy_duplicate_exact_path(self) -> None:
        """Tool still resolves exact path when old projection state has duplicates."""
        item = _skill_item()
        duplicate = item.model_copy(update={"id": "skill-duplicate"})
        store = _SkillStore(
            SkillProjectionState(
                active=SkillProjectionSnapshot(items=[item, duplicate])
            )
        )
        tool = make_load_skill_tool(
            store=store,  # pyright: ignore[reportArgumentType]
            agent_id="agent-1",
            session_id="session-1",
        )

        output = await tool.handler(json.dumps({"skill_path": item.skill_path}))

        assert isinstance(output, str)
        assert "Skill loaded from the active projection." in output
        assert item.body in output


class TestSkillProjectionService:
    """Skill projection service behavior."""

    @pytest.mark.asyncio
    async def test_scan_runtime_collapses_symlinked_source_aliases(self) -> None:
        """Scanner reads one Skill and prefers its direct canonical source root."""
        project_path = "/workspace/agent/project"
        canonical_dir = f"{project_path}/.claude/skills/review"
        skill_path = f"{canonical_dir}/SKILL.md"
        runner = _SkillScanRunner(
            entries_by_root={
                f"{project_path}/.agents/skills": (canonical_dir,),
                f"{project_path}/.claude/skills": (canonical_dir,),
            },
            files={
                skill_path: b"---\nname: review\ndescription: Review code.\n---\nBody"
            },
        )
        service = _TestableSkillProjectionService(
            store=object(),  # pyright: ignore[reportArgumentType]
            session_manager=object(),  # pyright: ignore[reportArgumentType]
        )

        items = await service.scan_runtime_for_test(
            runner_operations=runner,  # pyright: ignore[reportArgumentType]
            runtime_id="runtime-1",
            runner_generation=1,
            owner_session_id="session-1",
            projects=[_project(project_path)],
        )

        assert runner.read_calls == [skill_path]
        assert len(items) == 1
        assert items[0].source_kind == "project_claude"
        assert items[0].skill_path == skill_path
        assert items[0].relative_hint == ".claude/skills/review"

    @pytest.mark.asyncio
    async def test_scan_runtime_keeps_duplicate_slugs_at_distinct_paths(self) -> None:
        """Scanner preserves same-slug Skills when their exact paths differ."""
        project_path = "/workspace/agent/project"
        agents_dir = f"{project_path}/.agents/skills/review"
        claude_dir = f"{project_path}/.claude/skills/review"
        agents_skill_path = f"{agents_dir}/SKILL.md"
        claude_skill_path = f"{claude_dir}/SKILL.md"
        body = b"---\nname: review\ndescription: Review code.\n---\nBody"
        runner = _SkillScanRunner(
            entries_by_root={
                f"{project_path}/.agents/skills": (agents_dir,),
                f"{project_path}/.claude/skills": (claude_dir,),
            },
            files={agents_skill_path: body, claude_skill_path: body},
        )
        service = _TestableSkillProjectionService(
            store=object(),  # pyright: ignore[reportArgumentType]
            session_manager=object(),  # pyright: ignore[reportArgumentType]
        )

        items = await service.scan_runtime_for_test(
            runner_operations=runner,  # pyright: ignore[reportArgumentType]
            runtime_id="runtime-1",
            runner_generation=1,
            owner_session_id="session-1",
            projects=[_project(project_path)],
        )

        assert runner.read_calls == [agents_skill_path, claude_skill_path]
        assert [item.skill_path for item in items] == [
            agents_skill_path,
            claude_skill_path,
        ]
        assert [item.source_kind for item in items] == [
            "project_agents",
            "project_claude",
        ]

    @pytest.mark.asyncio
    async def test_publish_input_actions_updated_uses_session_channel(self) -> None:
        """Skill projection changes notify clients to reload input actions."""
        broadcast = _Broadcast()
        service = SkillProjectionService(
            store=object(),  # pyright: ignore[reportArgumentType]
            session_manager=object(),  # pyright: ignore[reportArgumentType]
            broadcast=broadcast,  # pyright: ignore[reportArgumentType]
        )

        await service.publish_input_actions_updated("session-1")

        assert broadcast.published == [
            (
                "session-1",
                {"type": "input_actions_updated", "session_id": "session-1"},
            )
        ]


class TestSkillAction:
    """Skill action helpers."""

    def test_skill_actions_deduplicate_exact_skill_path(self) -> None:
        """Action rendering keeps one action for each exact SKILL.md path."""
        item = _skill_item()
        duplicate = item.model_copy(update={"id": "skill-duplicate"})

        actions = skill_actions_from_snapshot(
            SkillProjectionSnapshot(items=[item, duplicate])
        )

        assert [action.skill_path for action in actions] == [item.skill_path]

    def test_resolve_active_skill_uses_exact_path(self) -> None:
        """Active projection lookup uses exact SKILL.md path."""
        item = _skill_item()
        state = SkillProjectionState(active=SkillProjectionSnapshot(items=[item]))

        assert resolve_active_skill(state, skill_path=item.skill_path) == item
        assert (
            resolve_active_skill(state, skill_path="/workspace/agent/other/SKILL.md")
            is None
        )


def test_projection_state_dump_is_json_safe() -> None:
    """Projection state is serializable for Toolkit State storage."""
    item = _skill_item()
    state = SkillProjectionState(
        latest=SkillProjectionSnapshot(items=[item]),
        active=SkillProjectionSnapshot(items=[item]),
    )

    dumped: dict[str, Any] = state.model_dump(mode="json")

    assert dumped["latest"]["items"][0]["skill_path"] == item.skill_path
