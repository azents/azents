"""Skill Toolkit tests."""

import json
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentSessionRunState, RuntimeRunnerState
from azents.core.tools import TurnContext
from azents.engine.hooks.types import RunStartHookContext, TurnStartHookContext
from azents.engine.run.types import FunctionToolError
from azents.engine.tools import skill as skill_module
from azents.engine.tools.runtime_io import RuntimeRunnerOperationClient
from azents.engine.tools.skill import (
    SkillProjectionItem,
    SkillProjectionService,
    SkillProjectionSnapshot,
    SkillProjectionState,
    SkillStateStore,
    SkillToolkit,
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


class _SkillStore:
    """SkillStateStore test double."""

    def __init__(
        self,
        state: SkillProjectionState,
        *,
        lock_order: list[str] | None = None,
    ) -> None:
        self.state = state
        self.lock_order = lock_order
        self.written_project_paths: list[list[str | None]] = []

    async def load(self, agent_id: str, session_id: str) -> SkillProjectionState:
        """Return configured state."""
        del agent_id, session_id
        return self.state

    async def load_in_session(
        self,
        session: AsyncSession,
        agent_id: str,
        session_id: str,
    ) -> SkillProjectionState:
        """Return state within a caller-owned transaction."""
        del session, agent_id, session_id
        return self.state

    async def replace_latest_in_session(
        self,
        session: AsyncSession,
        agent_id: str,
        session_id: str,
        snapshot: SkillProjectionSnapshot,
    ) -> SkillProjectionState:
        """Record an atomic projection replacement."""
        del session, agent_id, session_id
        if self.lock_order is not None:
            self.lock_order.append("toolkit")
        self.written_project_paths.append(
            [item.project_path for item in snapshot.items]
        )
        self.state = self.state.model_copy(update={"latest": snapshot})
        return self.state

    async def replace_latest_for_run_in_session(
        self,
        session: AsyncSession,
        agent_id: str,
        session_id: str,
        snapshot: SkillProjectionSnapshot,
        *,
        run_id: str,
        owner_generation: int,
    ) -> SkillProjectionState:
        """Reuse replacement behavior for this service test double."""
        del run_id, owner_generation
        return await self.replace_latest_in_session(
            session,
            agent_id,
            session_id,
            snapshot,
        )


class _SessionManager:
    """Yield inert short database sessions."""

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, object())


class _RuntimeRepository:
    """Return one ready Runtime."""

    async def get_by_agent_id(
        self,
        session: AsyncSession,
        agent_id: str,
    ) -> object:
        del session, agent_id
        return SimpleNamespace(
            id="runtime-1",
            runner_generation=1,
            runner_state=RuntimeRunnerState.READY,
        )


class _ChangingProjectRepository:
    """Replace the Project source set during the first external scan."""

    def __init__(
        self,
        old_project: SessionWorkspaceProject,
        new_project: SessionWorkspaceProject,
    ) -> None:
        self._results = [
            [old_project],
            [new_project],
            [new_project],
            [new_project],
        ]
        self.calls = 0

    async def list_projects(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> list[SessionWorkspaceProject]:
        del session, session_id
        result = self._results[min(self.calls, len(self._results) - 1)]
        self.calls += 1
        return result


class _AgentSessionRepository:
    """Record final validation lock order."""

    def __init__(self, lock_order: list[str]) -> None:
        self._lock_order = lock_order

    async def lock_by_id(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> object:
        del session, session_id
        self._lock_order.append("session")
        return SimpleNamespace()


class _ScanningProjectionService(SkillProjectionService):
    """Project one deterministic item for each scanned Project source."""

    def __init__(
        self,
        *,
        store: _SkillStore,
        session_manager: _SessionManager,
        agent_session_repository: _AgentSessionRepository,
        runner_operations: RuntimeRunnerOperationClient,
        runtime_repository: _RuntimeRepository,
        project_repository: _ChangingProjectRepository,
    ) -> None:
        super().__init__(
            store=cast(Any, store),
            session_manager=cast(Any, session_manager),
            agent_session_repository=cast(Any, agent_session_repository),
            runner_operations=runner_operations,
            runtime_repository=cast(Any, runtime_repository),
            project_repository=cast(Any, project_repository),
        )
        self.scanned_project_paths: list[list[str]] = []

    async def _scan_runtime(
        self,
        *,
        runner_operations: RuntimeRunnerOperationClient,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str,
        projects: Sequence[SessionWorkspaceProject],
    ) -> list[SkillProjectionItem]:
        del runner_operations, runtime_id, runner_generation, owner_session_id
        self.scanned_project_paths.append([project.path for project in projects])
        return [
            _skill_item().model_copy(
                update={
                    "id": f"skill-{project.id}",
                    "project_id": project.id,
                    "project_path": project.path,
                    "skill_dir_path": f"{project.path}/.agents/skills/review",
                    "skill_path": f"{project.path}/.agents/skills/review/SKILL.md",
                    "content_hash": f"hash-{project.id}",
                }
            )
            for project in projects
        ]


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
    async def test_publish_input_actions_updated_uses_session_channel(self) -> None:
        """Skill projection changes notify clients to reload input actions."""
        broadcast = _Broadcast()
        service = SkillProjectionService(
            store=object(),  # pyright: ignore[reportArgumentType]
            session_manager=object(),  # pyright: ignore[reportArgumentType]
            agent_session_repository=object(),  # pyright: ignore[reportArgumentType]
            broadcast=broadcast,  # pyright: ignore[reportArgumentType]
        )

        await service.publish_input_actions_updated("session-1")

        assert broadcast.published == [
            (
                "session-1",
                {"type": "input_actions_updated", "session_id": "session-1"},
            )
        ]

    @pytest.mark.asyncio
    async def test_source_set_change_retries_without_stale_projection_write(
        self,
    ) -> None:
        """Project replacement during scanning cannot commit the old source set."""
        old_project = SessionWorkspaceProject.model_construct(
            id="project-old",
            path="/workspace/agent/old",
        )
        new_project = SessionWorkspaceProject.model_construct(
            id="project-new",
            path="/workspace/agent/new",
        )
        project_repository = _ChangingProjectRepository(old_project, new_project)
        lock_order: list[str] = []
        store = _SkillStore(SkillProjectionState(), lock_order=lock_order)
        service = _ScanningProjectionService(
            store=store,
            session_manager=_SessionManager(),
            agent_session_repository=_AgentSessionRepository(lock_order),
            runner_operations=cast(RuntimeRunnerOperationClient, object()),
            runtime_repository=_RuntimeRepository(),
            project_repository=project_repository,
        )

        updated = await service.sync_latest(
            agent_id="agent-1",
            session_id="session-1",
            reason="project_change",
        )

        assert service.scanned_project_paths == [
            ["/workspace/agent/old"],
            ["/workspace/agent/new"],
        ]
        assert store.written_project_paths == [["/workspace/agent/new"]]
        assert [item.project_id for item in updated.latest.items] == ["project-new"]
        assert lock_order == ["session", "session", "toolkit"]


@pytest.mark.asyncio
async def test_project_invalidation_locks_session_before_toolkit_state() -> None:
    """Project deletion cleanup follows the global Session then state lock order."""
    lock_order: list[str] = []

    class AgentSessionRepository:
        async def lock_by_id(
            self,
            session: AsyncSession,
            session_id: str,
        ) -> object:
            del session, session_id
            lock_order.append("session")
            return SimpleNamespace(run_state=AgentSessionRunState.IDLE)

    class ToolkitStateRepository:
        async def get(self, session: AsyncSession, **kwargs: object) -> None:
            del session, kwargs
            lock_order.append("toolkit")
            return None

        async def save(self, session: AsyncSession, upsert: object) -> object:
            del session, upsert
            return SimpleNamespace(id="state-1", version=1, schema_version=1)

    store = SkillStateStore(
        session_manager=cast(Any, _SessionManager()),
        agent_run_repository=cast(Any, object()),
        agent_session_repository=cast(Any, AgentSessionRepository()),
        toolkit_state_repository=cast(Any, ToolkitStateRepository()),
    )

    await store.invalidate_project(
        "agent-1",
        "session-1",
        project_id="project-1",
        project_path="/workspace/agent/project",
    )

    assert lock_order == ["session", "toolkit"]


def test_skill_frontmatter_does_not_swallow_unexpected_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unexpected parser failures remain visible instead of hiding defects."""
    monkeypatch.setattr(
        skill_module.frontmatter,
        "loads",
        Mock(side_effect=RuntimeError("unexpected parser failure")),
    )

    with pytest.raises(RuntimeError, match="unexpected parser failure"):
        skill_module._parse_frontmatter(  # pyright: ignore[reportPrivateUsage]
            "---\nname: example\n---"
        )


async def _noop_event_publish(event: object) -> None:
    """Ignore a Toolkit projection event."""
    del event


async def test_skill_context_retries_adoption_after_failed_write() -> None:
    """A failed adoption is not cached as completed for the Run."""
    state = SkillProjectionState()
    store = AsyncMock(spec=SkillStateStore)
    store.adopt_latest_for_run.side_effect = [RuntimeError("write failed"), state]
    toolkit = SkillToolkit(
        store=store,
        agent_id="agent-1",
        session_id="session-1",
    )
    context = TurnContext(
        user_id="user-1",
        workspace_id="workspace-1",
        model="model-1",
        run_id="run-1",
        owner_generation=7,
        session_id="session-1",
        publish_event=_noop_event_publish,
    )

    with pytest.raises(RuntimeError, match="write failed"):
        await toolkit.update_context(context)

    resolved = await toolkit.update_context(context)

    assert resolved.tools == []
    assert store.adopt_latest_for_run.await_count == 2


async def test_skill_run_start_failure_remains_retryable_at_turn_start() -> None:
    """Run bookkeeping advances only after durable adoption succeeds."""
    state = SkillProjectionState()
    store = AsyncMock(spec=SkillStateStore)
    store.adopt_latest_for_run.side_effect = [RuntimeError("write failed"), state]
    toolkit = SkillToolkit(
        store=store,
        agent_id="agent-1",
        session_id="session-1",
    )
    hooks = toolkit.hooks()
    on_run_start = hooks.get("on_run_start")
    on_turn_start = hooks.get("on_turn_start")
    assert on_run_start is not None
    assert on_turn_start is not None

    with pytest.raises(RuntimeError, match="write failed"):
        await on_run_start(
            RunStartHookContext(
                workspace_id="workspace-1",
                agent_id="agent-1",
                session_id="session-1",
                run_id="run-1",
                owner_generation=7,
            )
        )

    await on_turn_start(
        TurnStartHookContext(
            workspace_id="workspace-1",
            agent_id="agent-1",
            session_id="session-1",
            run_id="run-1",
            owner_generation=7,
            turn_index=0,
        )
    )

    assert store.adopt_latest_for_run.await_count == 2


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
