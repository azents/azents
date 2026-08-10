"""Skill Toolkit tests."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentRuntimeCapability, AgentSessionRunState
from azents.core.runtime_capabilities import (
    RuntimeCapabilityResolver,
    RuntimeCapabilitySnapshot,
)
from azents.core.tools import TurnContext
from azents.core.vfs import (
    VfsProjection,
    make_vfs_projection,
    make_vfs_source_revision,
)
from azents.engine.run.types import FunctionToolError
from azents.engine.tools.runtime_io import (
    RuntimeFileListEntry,
    RuntimeFileListResult,
    RuntimeFileTextReadResult,
)
from azents.engine.tools.skill import (
    SkillProjectionItem,
    SkillProjectionService,
    SkillProjectionSnapshot,
    SkillProjectionState,
    SkillRuntimeFileReader,
    SkillToolkit,
    load_skill_projection_for_actions,
    make_load_skill_tool,
    render_skill_items,
    render_skill_prompt,
    resolve_active_skill,
    skill_actions_from_snapshot,
    skill_items_from_vfs_projection,
)
from azents.repos.session_workspace_project.data import SessionWorkspaceProject
from azents.services.agent_runtime.lifecycle_data import (
    RuntimeOperationTarget,
    RuntimeOperationTargetResolver,
)
from azents.services.vfs import VfsFileResolutionError, VfsResolvedFile


def _managed_runtime_capability_resolver() -> RuntimeCapabilityResolver:
    """Return a managed shell-enabled Runtime capability resolver."""
    return RuntimeCapabilityResolver.from_agent(
        state=AgentRuntimeCapability.MANAGED,
        version=1,
        shell_enabled=True,
    )


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


async def _noop_publish_event(event: object) -> None:
    """Ignore test-only published events."""
    del event


class _RuntimeTargetResolver(RuntimeOperationTargetResolver):
    """Return one deterministic target for projection service tests."""

    async def resolve_operation_target(
        self,
        agent_id: str,
        *,
        wait_timeout_seconds: float = 120.0,
        poll_interval_seconds: float = 1.0,
        expected_authority: object = None,
        start_if_stopped: bool = True,
    ) -> RuntimeOperationTarget:
        """Return exact fixture evidence."""
        del (
            agent_id,
            wait_timeout_seconds,
            poll_interval_seconds,
            expected_authority,
            start_if_stopped,
        )
        return RuntimeOperationTarget(
            id="runtime-1",
            desired_generation=1,
            runner_generation=1,
            configuration_revision_id="revision-1",
            configuration_digest="a" * 64,
            workspace_path="/workspace/agent",
        )


@asynccontextmanager
async def _session_manager() -> AsyncIterator[AsyncSession]:
    """Yield one unused but correctly typed test session."""
    session = AsyncSession()
    try:
        yield session
    finally:
        await session.close()


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

    async def read_text_file(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None,
        path: str,
        offset: int,
        max_bytes: int,
        encoding: str,
        deadline_at: datetime,
    ) -> RuntimeFileTextReadResult:
        """Return configured Skill content and record reads."""
        del runtime_id, runner_generation, owner_session_id, deadline_at
        self.read_calls.append(path)
        data = self.files[path]
        chunk = data[offset : offset + max_bytes]
        return RuntimeFileTextReadResult(
            text=chunk.decode(encoding),
            final_cursor="cursor-read",
        )


class _TestableSkillProjectionService(SkillProjectionService):
    """Expose protected Skill scanning for focused service tests."""

    async def scan_runtime_for_test(
        self,
        *,
        runner_operations: SkillRuntimeFileReader,
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
            workspace_root="/runtime/home",
        )


def _managed_projection() -> VfsProjection:
    """Create one managed Skill and adjacent resource projection."""
    revision = make_vfs_source_revision(
        source_id="release:azents",
        source_kind="global_release",
        namespace="azents",
        entries=[
            (
                "azents://skills/azents/review/SKILL.md",
                b"---\nname: review\ndescription: Review code.\n---\nManaged body",
                "text/markdown",
            ),
            (
                "azents://skills/azents/review/references/checklist.md",
                b"# Checklist",
                "text/markdown",
            ),
        ],
    )
    return make_vfs_projection([revision])


class _VfsService:
    """VfsProjectionService test double bound to one projection."""

    def __init__(self, projection: VfsProjection) -> None:
        self.projection = projection
        self.action_calls: list[tuple[bool, str | None]] = []
        self.load_calls: list[dict[str, object]] = []
        self.resolve_calls: list[dict[str, object]] = []

    async def resolve_file(
        self,
        *,
        run_id: str,
        agent_id: str,
        session_id: str,
        workspace_id: str,
        uri: str,
    ) -> VfsResolvedFile:
        """Resolve one file from the configured projection."""
        self.resolve_calls.append(
            {
                "run_id": run_id,
                "agent_id": agent_id,
                "session_id": session_id,
                "workspace_id": workspace_id,
                "uri": uri,
            }
        )
        entry = self.projection.find(uri)
        if entry is None:
            raise AssertionError(f"Missing fixture URI: {uri}")
        return VfsResolvedFile(
            projection_revision_id=self.projection.revision_id,
            projection_hash=self.projection.projection_hash,
            entry=entry,
        )

    async def load_run_projection(
        self,
        *,
        run_id: str,
        agent_id: str,
        session_id: str,
        workspace_id: str,
    ) -> VfsProjection:
        """Return one managed projection and capture its authorization identity."""
        self.load_calls.append(
            {
                "run_id": run_id,
                "agent_id": agent_id,
                "session_id": session_id,
                "workspace_id": workspace_id,
            }
        )
        return self.projection

    async def projection_for_actions(
        self,
        *,
        agent_id: str,
        session_id: str,
        workspace_id: str,
        running: bool,
        active_run_id: str | None,
    ) -> VfsProjection:
        """Return configured composer projection and capture run identity."""
        del agent_id, session_id, workspace_id
        self.action_calls.append((running, active_run_id))
        return self.projection


class _UnavailableVfsService:
    """VFS projection test double that simulates an in-progress run."""

    async def projection_for_actions(
        self,
        *,
        agent_id: str,
        session_id: str,
        workspace_id: str,
        running: bool,
        active_run_id: str | None,
    ) -> VfsProjection:
        """Report that the current run has not persisted a VFS projection yet."""
        del agent_id, session_id, workspace_id, running, active_run_id
        raise VfsFileResolutionError(
            "storage_unavailable",
            "Active run VFS projection is unavailable",
        )


class _ForbiddenVfsService:
    """VFS projection test double that rejects access."""

    async def projection_for_actions(
        self,
        *,
        agent_id: str,
        session_id: str,
        workspace_id: str,
        running: bool,
        active_run_id: str | None,
    ) -> VfsProjection:
        """Report an authorization failure that must not be hidden."""
        del agent_id, session_id, workspace_id, running, active_run_id
        raise VfsFileResolutionError(
            "permission_denied",
            "Run VFS projection access denied",
        )


class _SkillStore:
    """SkillStateStore test double."""

    def __init__(self, state: SkillProjectionState) -> None:
        self.state = state

    async def load(self, agent_id: str, session_id: str) -> SkillProjectionState:
        """Return configured state."""
        del agent_id, session_id
        return self.state

    async def adopt_latest(
        self,
        agent_id: str,
        session_id: str,
    ) -> SkillProjectionState:
        """Return configured state after accepting a latest projection adoption."""
        del agent_id, session_id
        return self.state

    async def replace_latest(
        self,
        agent_id: str,
        session_id: str,
        snapshot: SkillProjectionSnapshot,
    ) -> SkillProjectionState:
        """Replace latest state for projection-service tests."""
        del agent_id, session_id
        self.state = self.state.model_copy(update={"latest": snapshot})
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


class TestManagedSkillProjection:
    """Managed VFS Skill projection behavior."""

    def test_projection_parses_entrypoint_and_ignores_adjacent_resources(self) -> None:
        """Only canonical package-root SKILL.md files become Skill items."""
        items = skill_items_from_vfs_projection(_managed_projection())

        assert len(items) == 1
        assert items[0].skill_path == "azents://skills/azents/review/SKILL.md"
        assert items[0].source_kind == "azents"
        assert items[0].body.endswith("Managed body")
        assert items[0].relative_hint == "azents/review"

    def test_combined_render_keeps_equal_slugs_with_distinct_locators(self) -> None:
        """Filesystem and managed Skills with one slug remain separate entries."""
        filesystem = _skill_item()
        managed = skill_items_from_vfs_projection(_managed_projection())[0]

        prompt = render_skill_items([filesystem, managed])

        assert prompt.count("**review**: Review code.") == 2
        assert filesystem.skill_path in prompt
        assert managed.skill_path in prompt


class TestSkillToolkit:
    """Skill Toolkit managed VFS authorization behavior."""

    @pytest.mark.asyncio
    async def test_turn_workspace_authorizes_managed_skill_reads(self) -> None:
        """Managed Skill reads use the current Run workspace authorization."""
        projection = _managed_projection()
        service = _VfsService(projection)
        toolkit = SkillToolkit(
            store=_SkillStore(SkillProjectionState()),
            projection_service=None,
            vfs_projection_service=service,
            agent_id="agent-1",
            session_id="session-1",
        )
        context = TurnContext(
            workspace_id="workspace-current",
            model="test-model",
            run_id="run-1",
            publish_event=_noop_publish_event,
        )

        state = await toolkit.update_context(context)

        assert service.load_calls == [
            {
                "run_id": "run-1",
                "agent_id": "agent-1",
                "session_id": "session-1",
                "workspace_id": "workspace-current",
            }
        ]
        [load_skill] = state.tools
        await load_skill.handler(
            json.dumps({"skill_path": "azents://skills/azents/review/SKILL.md"})
        )
        assert service.resolve_calls[-1]["workspace_id"] == "workspace-current"

    @pytest.mark.asyncio
    async def test_shell_disabled_keeps_managed_and_hides_filesystem_skills(
        self,
    ) -> None:
        """Managed VFS Skills remain while filesystem Skills are denied."""
        projection = _managed_projection()
        toolkit = SkillToolkit(
            store=_SkillStore(
                SkillProjectionState(
                    active=SkillProjectionSnapshot(items=[_skill_item()])
                )
            ),
            projection_service=None,
            vfs_projection_service=_VfsService(projection),
            agent_id="agent-1",
            session_id="session-1",
        )
        toolkit.set_runtime_capability_resolver(
            RuntimeCapabilityResolver.from_agent(
                state=AgentRuntimeCapability.MANAGED,
                version=1,
                shell_enabled=False,
            )
        )
        context = TurnContext(
            workspace_id="workspace-1",
            model="test-model",
            run_id="run-1",
            publish_event=_noop_publish_event,
        )

        prompt = await toolkit.get_static_prompt(context)
        state = await toolkit.update_context(context)

        assert "/workspace/agent/project" not in prompt
        assert "azents://skills/azents/review/SKILL.md" in prompt
        [load_skill] = state.tools
        with pytest.raises(FunctionToolError, match="Filesystem Skill capability"):
            await load_skill.handler(
                json.dumps({"skill_path": _skill_item().skill_path})
            )

    @pytest.mark.asyncio
    async def test_prompt_and_catalog_recheck_filesystem_skill_authority(
        self,
    ) -> None:
        """Each projection surface hides filesystem Skills after a downgrade."""
        provider_calls = 0
        current = RuntimeCapabilityResolver.from_agent(
            state=AgentRuntimeCapability.REMOVING,
            version=2,
            shell_enabled=False,
        )

        async def current_snapshot_provider() -> RuntimeCapabilitySnapshot:
            nonlocal provider_calls
            provider_calls += 1
            return current.snapshot

        toolkit = SkillToolkit(
            store=_SkillStore(
                SkillProjectionState(
                    active=SkillProjectionSnapshot(items=[_skill_item()])
                )
            ),
            projection_service=None,
            vfs_projection_service=None,
            agent_id="agent-1",
            session_id="session-1",
        )
        toolkit.set_runtime_capability_resolver(
            RuntimeCapabilityResolver.from_agent(
                state=AgentRuntimeCapability.MANAGED,
                version=1,
                shell_enabled=True,
                current_snapshot_provider=current_snapshot_provider,
            )
        )
        context = TurnContext(
            workspace_id="workspace-1",
            model="test-model",
            run_id="run-1",
            publish_event=_noop_publish_event,
        )

        prompt = await toolkit.get_static_prompt(context)
        state = await toolkit.update_context(context)

        assert prompt == ""
        assert state.tools == []
        assert provider_calls == 2


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
            store=store,
            vfs_projection_service=None,
            agent_id="agent-1",
            session_id="session-1",
            workspace_id="workspace-1",
            run_id="run-1",
            runtime_capability_resolver=_managed_runtime_capability_resolver(),
        )

        output = await tool.handler(json.dumps({"skill_path": item.skill_path}))

        assert isinstance(output, str)
        assert "Skill loaded from the active projection." in output
        assert item.body in output
        assert item.skill_path in output

    @pytest.mark.asyncio
    async def test_load_skill_returns_body_from_current_run_vfs(self) -> None:
        """Tool resolves a canonical managed URI from the persisted run view."""
        projection = _managed_projection()
        service = _VfsService(projection)
        store = _SkillStore(SkillProjectionState())
        skill_uri = "azents://skills/azents/review/SKILL.md"
        tool = make_load_skill_tool(
            store=store,
            vfs_projection_service=service,
            agent_id="agent-1",
            session_id="session-1",
            workspace_id="workspace-1",
            run_id="run-1",
            runtime_capability_resolver=None,
        )

        output = await tool.handler(json.dumps({"skill_path": skill_uri}))

        assert isinstance(output, str)
        assert "Managed body" in output
        assert projection.revision_id in output
        assert projection.projection_hash in output
        assert skill_uri in output

    @pytest.mark.asyncio
    async def test_load_skill_rejects_missing_path(self) -> None:
        """Tool fails fast without runtime fallback when path is absent."""
        store = _SkillStore(SkillProjectionState())
        tool = make_load_skill_tool(
            store=store,
            vfs_projection_service=None,
            agent_id="agent-1",
            session_id="session-1",
            workspace_id="workspace-1",
            run_id="run-1",
            runtime_capability_resolver=_managed_runtime_capability_resolver(),
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
            store=store,
            vfs_projection_service=None,
            agent_id="agent-1",
            session_id="session-1",
            workspace_id="workspace-1",
            run_id="run-1",
            runtime_capability_resolver=_managed_runtime_capability_resolver(),
        )

        output = await tool.handler(json.dumps({"skill_path": item.skill_path}))

        assert isinstance(output, str)
        assert "Skill loaded from the active projection." in output
        assert item.body in output

    @pytest.mark.asyncio
    async def test_load_skill_denies_filesystem_without_capability_context(
        self,
    ) -> None:
        """Filesystem Skill loading fails closed without resolver context."""
        item = _skill_item()
        tool = make_load_skill_tool(
            store=_SkillStore(
                SkillProjectionState(active=SkillProjectionSnapshot(items=[item]))
            ),
            vfs_projection_service=None,
            agent_id="agent-1",
            session_id="session-1",
            workspace_id="workspace-1",
            run_id="run-1",
            runtime_capability_resolver=None,
        )

        with pytest.raises(FunctionToolError, match="capability context"):
            await tool.handler(json.dumps({"skill_path": item.skill_path}))


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
            store=_SkillStore(SkillProjectionState()),
            session_manager=_session_manager,
            runtime_target_resolver=_RuntimeTargetResolver(),
        )

        items = await service.scan_runtime_for_test(
            runner_operations=runner,
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
            store=_SkillStore(SkillProjectionState()),
            session_manager=_session_manager,
            runtime_target_resolver=_RuntimeTargetResolver(),
        )

        items = await service.scan_runtime_for_test(
            runner_operations=runner,
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
            store=_SkillStore(SkillProjectionState()),
            session_manager=_session_manager,
            runtime_target_resolver=_RuntimeTargetResolver(),
            broadcast=broadcast,
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

    @pytest.mark.asyncio
    async def test_running_actions_use_the_exact_live_run_projection(self) -> None:
        """Composer action resolution forwards the authorized active run ID."""
        filesystem = _skill_item()
        store = _SkillStore(
            SkillProjectionState(active=SkillProjectionSnapshot(items=[filesystem]))
        )
        service = _VfsService(_managed_projection())

        snapshot = await load_skill_projection_for_actions(
            store,
            vfs_projection_service=service,
            agent_id="agent-1",
            session_id="session-1",
            workspace_id="workspace-1",
            run_state=AgentSessionRunState.RUNNING,
            active_run_id="run-1",
        )

        assert service.action_calls == [(True, "run-1")]
        assert [item.skill_path for item in snapshot.items] == [
            filesystem.skill_path,
            "azents://skills/azents/review/SKILL.md",
        ]

    @pytest.mark.asyncio
    async def test_running_actions_omit_managed_skills_when_vfs_is_unavailable(
        self,
    ) -> None:
        """A not-yet-persisted run projection cannot break the composer."""
        filesystem = _skill_item()
        store = _SkillStore(
            SkillProjectionState(active=SkillProjectionSnapshot(items=[filesystem]))
        )

        snapshot = await load_skill_projection_for_actions(
            store,
            vfs_projection_service=_UnavailableVfsService(),
            agent_id="agent-1",
            session_id="session-1",
            workspace_id="workspace-1",
            run_state=AgentSessionRunState.RUNNING,
            active_run_id=None,
        )

        assert snapshot.items == [filesystem]

    @pytest.mark.asyncio
    async def test_running_actions_propagate_vfs_access_denial(self) -> None:
        """Only temporary VFS unavailability falls back to filesystem actions."""
        store = _SkillStore(SkillProjectionState())

        with pytest.raises(VfsFileResolutionError, match="access denied"):
            await load_skill_projection_for_actions(
                store,
                vfs_projection_service=_ForbiddenVfsService(),
                agent_id="agent-1",
                session_id="session-1",
                workspace_id="workspace-1",
                run_state=AgentSessionRunState.RUNNING,
                active_run_id="run-1",
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
