"""Filesystem-backed Skill projection Toolkit."""

import datetime
import hashlib
import json
import logging
import posixpath
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Literal, assert_never

import frontmatter
import yaml
from azcommon.uuid import uuid7
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.broadcast import WebSocketBroadcast, WebSocketBroadcastPublishError
from azents.core.enums import AgentSessionRunState, RuntimeRunnerState
from azents.core.tools import (
    ResolveContext,
    Toolkit,
    ToolkitProvider,
    ToolkitState,
    ToolkitStatus,
    TurnContext,
)
from azents.core.vfs import (
    AZENTS_VFS_SKILLS_MOUNT,
    VfsFileEntry,
    VfsProjection,
    VfsUriError,
    canonicalize_vfs_uri,
)
from azents.engine.hooks.types import (
    RunEndHookContext,
    RunStartHookContext,
    RuntimeHooks,
    SessionCompactHookContext,
    SessionStartHookContext,
    TurnStartHookContext,
    TurnStartResult,
)
from azents.engine.run.types import FunctionTool, FunctionToolError
from azents.engine.tooling.make_tool import make_tool
from azents.engine.tooling.toolkit_state import (
    ToolkitStateHandle,
    ToolkitStateIdentity,
    ToolkitStateModel,
    ToolkitStateStore,
)
from azents.engine.tools.runtime_io import (
    RuntimeRunnerOperationClient,
    RuntimeRunnerOperationFailedError,
    RuntimeRunnerOperationGenerationError,
    RuntimeRunnerOperationUnavailable,
)
from azents.rdb.session import SessionManager
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.session_workspace_project.data import SessionWorkspaceProject
from azents.services.vfs import VfsFileResolutionError, VfsProjectionService
from azents.transport.chat import chat_input_actions_updated_dump

logger = logging.getLogger(__name__)

SKILL_TOOLKIT_NAMESPACE = "skill"
SKILL_TOOLKIT_STATE_NAME = "projection"
SKILL_STATE_SCHEMA_VERSION = 1
AGENT_WORKSPACE_ROOT = "/workspace/agent"
AGENT_SKILL_ROOT = f"{AGENT_WORKSPACE_ROOT}/.azents/skills"
SKILL_MARKDOWN_FILENAME = "SKILL.md"
_SKILL_READ_MAX_BYTES = 512 * 1024
_RUNNER_FILE_OPERATION_TIMEOUT_SECONDS = 10

SkillSourceKind = Literal["agent", "project_agents", "project_claude", "azents"]
SyncReason = Literal[
    "session_start",
    "run_end",
    "compaction_start",
    "project_change",
    "manual",
]

_SKILL_PROMPT_HEADER = """## Skills

The following skills are available.
When a task matches a skill, use `load_skill` to load it BEFORE responding.
When the user types `/{skill-name}`, treat it as a request to load that skill.
If a skill's description says 'proactively', use it without waiting for the user to ask.
"""


class LoadSkillInput(BaseModel):
    """load_skill tool input."""

    skill_path: str = Field(
        min_length=1,
        description=(
            "Exact filesystem path or canonical azents:// SKILL.md URI from the "
            "Skills prompt."
        ),
    )


class SkillProjectionItem(ToolkitStateModel):
    """Projected filesystem Skill item."""

    schema_version: int = SKILL_STATE_SCHEMA_VERSION
    id: str = Field(min_length=1, description="Stable projection-local Skill item ID")
    source_kind: SkillSourceKind = Field(description="Skill source kind")
    project_id: str | None = Field(default=None, description="Project ID")
    project_path: str | None = Field(default=None, description="Project path")
    skill_dir_path: str = Field(
        min_length=1, description="Skill package directory path"
    )
    skill_path: str = Field(min_length=1, description="Exact SKILL.md path")
    slug: str = Field(min_length=1, description="Skill directory slug")
    name: str = Field(min_length=1, description="Skill display name")
    description: str = Field(description="Skill description")
    frontmatter: dict[str, Any] = Field(default_factory=dict)
    body: str = Field(description="Full SKILL.md body")
    content_hash: str = Field(min_length=1, description="SHA-256 content hash")
    source_label: str = Field(min_length=1, description="Compact source label")
    relative_hint: str = Field(min_length=1, description="Compact relative path hint")


class SkillProjectionSnapshot(ToolkitStateModel):
    """One complete Skill projection snapshot."""

    schema_version: int = SKILL_STATE_SCHEMA_VERSION
    revision_id: str = Field(default_factory=lambda: uuid7().hex)
    projection_hash: str = Field(default="", description="Hash of projected items")
    synced_at: str | None = Field(default=None, description="UTC sync timestamp")
    sync_reason: SyncReason | None = Field(default=None, description="Sync reason")
    items: list[SkillProjectionItem] = Field(default_factory=list)


class SkillProjectionState(ToolkitStateModel):
    """Session Skill projection Toolkit State payload."""

    schema_version: int = SKILL_STATE_SCHEMA_VERSION
    latest: SkillProjectionSnapshot = Field(default_factory=SkillProjectionSnapshot)
    active: SkillProjectionSnapshot = Field(default_factory=SkillProjectionSnapshot)


@dataclass(frozen=True)
class SkillSourceRoot:
    """Filesystem source root to scan for Skills."""

    source_kind: SkillSourceKind
    root_path: str
    source_label: str
    relative_prefix: str
    project_id: str | None = None
    project_path: str | None = None


@dataclass(frozen=True)
class _SkillPathCandidate:
    """Discovered Skill path associated with its requested source root."""

    source: SkillSourceRoot
    skill_path: str


class SkillStateStore:
    """Skill projection store based on Toolkit State."""

    def __init__(
        self,
        *,
        session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Create Skill state store."""
        self.session_manager = session_manager

    async def load(self, agent_id: str, session_id: str) -> SkillProjectionState:
        """Fetch Skill projection state."""
        async with self.session_manager() as session:
            return await self.load_in_session(session, agent_id, session_id)

    async def load_in_session(
        self,
        session: AsyncSession,
        agent_id: str,
        session_id: str,
    ) -> SkillProjectionState:
        """Fetch Skill projection state inside the caller transaction."""
        handle = await self._make_handle(session, agent_id, session_id)
        if handle is None:
            return SkillProjectionState()
        return await handle.load(default_factory=SkillProjectionState)

    async def replace_latest(
        self,
        agent_id: str,
        session_id: str,
        snapshot: SkillProjectionSnapshot,
    ) -> SkillProjectionState:
        """Replace latest projection snapshot."""
        return await self.update(
            agent_id,
            session_id,
            lambda current: current.model_copy(update={"latest": snapshot}),
        )

    async def adopt_latest(
        self, agent_id: str, session_id: str
    ) -> SkillProjectionState:
        """Copy latest projection into active projection."""
        return await self.update(
            agent_id,
            session_id,
            lambda current: current.model_copy(update={"active": current.latest}),
        )

    async def invalidate_project(
        self,
        agent_id: str,
        session_id: str,
        *,
        project_id: str,
        project_path: str,
        session_run_state: AgentSessionRunState,
    ) -> SkillProjectionState:
        """Remove deleted Project items without reading runtime files."""

        def mutate(current: SkillProjectionState) -> SkillProjectionState:
            latest = _filter_snapshot_project(
                current.latest,
                project_id=project_id,
                project_path=project_path,
                reason="project_change",
            )
            if session_run_state == AgentSessionRunState.IDLE:
                active = _filter_snapshot_project(
                    current.active,
                    project_id=project_id,
                    project_path=project_path,
                    reason="project_change",
                )
            else:
                active = current.active
            return current.model_copy(update={"latest": latest, "active": active})

        return await self.update(agent_id, session_id, mutate)

    async def update(
        self,
        agent_id: str,
        session_id: str,
        mutator: Callable[[SkillProjectionState], SkillProjectionState],
    ) -> SkillProjectionState:
        """Update Skill projection state with optimistic retry."""
        async with self.session_manager() as session:
            handle = await self._make_handle(session, agent_id, session_id)
            if handle is None:
                return SkillProjectionState()
            saved_state: SkillProjectionState | None = None

            def capture(current: SkillProjectionState) -> SkillProjectionState:
                nonlocal saved_state
                saved_state = mutator(current)
                return saved_state

            await handle.update(default_factory=SkillProjectionState, mutator=capture)
            return saved_state or SkillProjectionState()

    async def _make_handle(
        self,
        session: AsyncSession,
        agent_id: str,
        session_id: str,
    ) -> ToolkitStateHandle[SkillProjectionState] | None:
        """Create Skill Toolkit State handle for agent/session."""
        if not agent_id or not session_id:
            return None
        identity = ToolkitStateIdentity(
            agent_id=agent_id,
            session_id=session_id,
            toolkit_namespace=SKILL_TOOLKIT_NAMESPACE,
            state_name=SKILL_TOOLKIT_STATE_NAME,
        )
        return ToolkitStateStore(session=session).handle(identity, SkillProjectionState)


class SkillProjectionService:
    """Runtime-connected Skill projection synchronization service."""

    def __init__(
        self,
        *,
        store: SkillStateStore,
        session_manager: SessionManager[AsyncSession],
        runner_operations: RuntimeRunnerOperationClient | None = None,
        runtime_repository: AgentRuntimeRepository | None = None,
        project_repository: SessionWorkspaceProjectRepository | None = None,
        broadcast: WebSocketBroadcast | None = None,
    ) -> None:
        """Create Skill projection service."""
        self.store = store
        self.session_manager = session_manager
        self.runner_operations = runner_operations
        self.runtime_repository = runtime_repository or AgentRuntimeRepository()
        self.project_repository = (
            project_repository or SessionWorkspaceProjectRepository()
        )
        self.broadcast = broadcast

    async def sync_latest(
        self,
        *,
        agent_id: str,
        session_id: str,
        reason: SyncReason,
    ) -> SkillProjectionState:
        """Scan runtime filesystem and replace latest when runtime is ready."""
        runner_operations = self.runner_operations
        if runner_operations is None:
            return await self.store.load(agent_id, session_id)
        async with self.session_manager() as session:
            runtime = await self.runtime_repository.get_by_agent_id(session, agent_id)
            projects = await self.project_repository.list_projects(
                session,
                session_id=session_id,
            )
        if runtime is None or runtime.runner_state != RuntimeRunnerState.READY:
            return await self.store.load(agent_id, session_id)
        items = await self._scan_runtime(
            runner_operations=runner_operations,
            runtime_id=runtime.id,
            runner_generation=runtime.runner_generation,
            owner_session_id=session_id,
            projects=projects,
        )
        snapshot = _make_snapshot(items, reason=reason)
        current = await self.store.load(agent_id, session_id)
        if current.latest.projection_hash == snapshot.projection_hash:
            return current
        updated = await self.store.replace_latest(agent_id, session_id, snapshot)
        await self.publish_input_actions_updated(session_id)
        return updated

    async def publish_input_actions_updated(self, session_id: str) -> None:
        """Notify chat clients that composer actions should be reloaded."""
        if self.broadcast is None:
            return
        try:
            await self.broadcast.publish(
                session_id,
                chat_input_actions_updated_dump(session_id),
            )
        except WebSocketBroadcastPublishError:
            logger.exception(
                "Input action update broadcast failed",
                extra={"session_id": session_id},
            )

    async def _scan_runtime(
        self,
        *,
        runner_operations: RuntimeRunnerOperationClient,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str,
        projects: Sequence[SessionWorkspaceProject],
    ) -> list[SkillProjectionItem]:
        """Scan all Skill source roots through Runtime Runner file operations."""
        roots = _skill_source_roots(projects)
        candidates: list[_SkillPathCandidate] = []
        for root in roots:
            paths = await self._skill_paths_in_root(
                runner_operations=runner_operations,
                runtime_id=runtime_id,
                runner_generation=runner_generation,
                owner_session_id=owner_session_id,
                root_path=root.root_path,
            )
            candidates.extend(
                _SkillPathCandidate(source=root, skill_path=skill_path)
                for skill_path in paths
            )
        unique_candidates = _dedupe_skill_path_candidates(candidates)
        duplicate_count = len(candidates) - len(unique_candidates)
        if duplicate_count:
            logger.debug(
                "Duplicate Skill source paths collapsed",
                extra={
                    "session_id": owner_session_id,
                    "duplicate_count": duplicate_count,
                    "candidate_count": len(candidates),
                    "unique_path_count": len(unique_candidates),
                },
            )
        items: list[SkillProjectionItem] = []
        for candidate in unique_candidates:
            item = await self._read_skill_item(
                runner_operations=runner_operations,
                runtime_id=runtime_id,
                runner_generation=runner_generation,
                owner_session_id=owner_session_id,
                source=candidate.source,
                skill_path=candidate.skill_path,
            )
            if item is not None:
                items.append(item)
        return sorted(
            items,
            key=lambda item: (
                _source_priority(item.source_kind),
                item.project_path or "",
                item.slug,
                item.skill_path,
            ),
        )

    async def _skill_paths_in_root(
        self,
        *,
        runner_operations: RuntimeRunnerOperationClient,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str,
        root_path: str,
    ) -> list[str]:
        """Return direct child SKILL.md paths under a source root."""
        try:
            result = await runner_operations.list_files(
                runtime_id=runtime_id,
                runner_generation=runner_generation,
                owner_session_id=owner_session_id,
                path=root_path,
                recursive=False,
                deadline_at=_runner_file_operation_deadline(),
            )
        except (
            RuntimeRunnerOperationUnavailable,
            RuntimeRunnerOperationGenerationError,
            RuntimeRunnerOperationFailedError,
        ):
            return []
        skill_paths: list[str] = []
        for entry in result.entries:
            if entry.type != "directory":
                continue
            slug = posixpath.basename(posixpath.normpath(entry.path))
            if not slug:
                continue
            skill_paths.append(posixpath.join(entry.path, SKILL_MARKDOWN_FILENAME))
        return skill_paths

    async def _read_skill_item(
        self,
        *,
        runner_operations: RuntimeRunnerOperationClient,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str,
        source: SkillSourceRoot,
        skill_path: str,
    ) -> SkillProjectionItem | None:
        """Read and parse one SKILL.md file."""
        try:
            result = await runner_operations.read_file(
                runtime_id=runtime_id,
                runner_generation=runner_generation,
                owner_session_id=owner_session_id,
                path=skill_path,
                offset=0,
                max_bytes=_SKILL_READ_MAX_BYTES,
                deadline_at=_runner_file_operation_deadline(),
            )
        except (
            RuntimeRunnerOperationUnavailable,
            RuntimeRunnerOperationGenerationError,
            RuntimeRunnerOperationFailedError,
            UnicodeDecodeError,
        ):
            return None
        try:
            body = result.data.decode("utf-8")
        except UnicodeDecodeError:
            return None
        skill_dir_path = posixpath.dirname(skill_path)
        slug = posixpath.basename(skill_dir_path)
        metadata = _parse_frontmatter(body)
        name = _metadata_string(metadata, "name") or slug
        description = _metadata_string(metadata, "description")
        if not description:
            return None
        return SkillProjectionItem(
            id=_stable_item_id(skill_path),
            source_kind=source.source_kind,
            project_id=source.project_id,
            project_path=source.project_path,
            skill_dir_path=skill_dir_path,
            skill_path=skill_path,
            slug=slug,
            name=name,
            description=description,
            frontmatter=metadata,
            body=body,
            content_hash=_sha256_text(body),
            source_label=source.source_label,
            relative_hint=_relative_hint(source, skill_dir_path),
        )


class SkillToolkitConfig(BaseModel):
    """Skill Toolkit settings model."""


class SkillToolkit(Toolkit[SkillToolkitConfig]):
    """Always-on Toolkit that exposes projected filesystem Skills."""

    def __init__(
        self,
        *,
        store: SkillStateStore,
        projection_service: SkillProjectionService | None,
        vfs_projection_service: VfsProjectionService | None,
        agent_id: str,
        session_id: str,
        workspace_id: str,
    ) -> None:
        """Create Skill Toolkit."""
        self.store = store
        self.projection_service = projection_service
        self.vfs_projection_service = vfs_projection_service
        self._agent_id = agent_id
        self._session_id = session_id
        self._workspace_id = workspace_id
        self._adopted_run_ids: set[str] = set()
        self._adopt_latest_on_next_turn = False

    def set_agent_id(self, agent_id: str) -> None:
        """Inject agent_id."""
        self._agent_id = agent_id

    def set_session_id(self, session_id: str) -> None:
        """Inject session_id."""
        self._session_id = session_id

    def hooks(self) -> RuntimeHooks:
        """Return Skill projection lifecycle hooks."""
        return {
            "on_session_start": self._on_session_start,
            "on_session_compact": self._on_session_compact,
            "on_run_start": self._on_run_start,
            "on_run_end": self._on_run_end,
            "on_turn_start": self._on_turn_start,
        }

    async def get_static_prompt(self, context: TurnContext) -> str:
        """Render the combined active Skill index for the current run."""
        state = await self._active_state_for_context(context)
        managed = await self._managed_items(context.run_id)
        return render_skill_items([*state.active.items, *managed])

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Return load_skill when either Skill projection contains items."""
        state = await self._active_state_for_context(context)
        managed = await self._managed_items(context.run_id)
        if not state.active.items and not managed:
            return ToolkitState(status=ToolkitStatus.ENABLED, tools=[])
        return ToolkitState(
            status=ToolkitStatus.ENABLED,
            tools=[
                make_load_skill_tool(
                    store=self.store,
                    vfs_projection_service=self.vfs_projection_service,
                    agent_id=self._agent_id,
                    session_id=self._session_id,
                    workspace_id=self._workspace_id,
                    run_id=context.run_id,
                )
            ],
        )

    async def _managed_items(self, run_id: str) -> list[SkillProjectionItem]:
        """Load managed Skill entries from the exact current run projection."""
        if self.vfs_projection_service is None:
            return []
        projection = await self.vfs_projection_service.load_run_projection(
            run_id=run_id,
            agent_id=self._agent_id,
            session_id=self._session_id,
            workspace_id=self._workspace_id,
        )
        return skill_items_from_vfs_projection(projection)

    async def _active_state_for_context(
        self, context: TurnContext
    ) -> SkillProjectionState:
        """Ensure the run has adopted latest before turn prompt/tool collection."""
        if self._adopt_latest_on_next_turn:
            self._adopt_latest_on_next_turn = False
            return await self.store.adopt_latest(self._agent_id, self._session_id)
        if context.run_id and context.run_id not in self._adopted_run_ids:
            self._adopted_run_ids.add(context.run_id)
            return await self.store.adopt_latest(self._agent_id, self._session_id)
        return await self.store.load(self._agent_id, self._session_id)

    async def _on_session_start(self, context: SessionStartHookContext) -> None:
        """Create latest Skill projection when the session lifecycle starts."""
        await self._sync(context.agent_id, context.session_id, reason="session_start")

    async def _on_session_compact(self, context: SessionCompactHookContext) -> None:
        """Refresh latest projection at compaction start."""
        await self._sync(
            context.agent_id, context.session_id, reason="compaction_start"
        )
        self._adopt_latest_on_next_turn = True

    async def _on_run_start(self, context: RunStartHookContext) -> None:
        """Adopt latest projection for this run."""
        if not context.agent_id or not context.session_id:
            return
        self._adopted_run_ids.add(context.run_id)
        await self.store.adopt_latest(context.agent_id, context.session_id)

    async def _on_run_end(self, context: RunEndHookContext) -> None:
        """Refresh latest projection after a run completes."""
        await self._sync(context.agent_id, context.session_id, reason="run_end")

    async def _on_turn_start(
        self, context: TurnStartHookContext
    ) -> TurnStartResult | None:
        """Adopt latest on the first turn not covered by run-start dispatch."""
        if context.run_id in self._adopted_run_ids:
            return None
        self._adopted_run_ids.add(context.run_id)
        await self.store.adopt_latest(context.agent_id, context.session_id)
        return None

    async def _sync(
        self, agent_id: str, session_id: str, *, reason: SyncReason
    ) -> None:
        if self.projection_service is None:
            return
        await self.projection_service.sync_latest(
            agent_id=agent_id,
            session_id=session_id,
            reason=reason,
        )


class SkillToolkitProvider(ToolkitProvider[SkillToolkitConfig]):
    """Skill Toolkit provider always injected without user settings."""

    slug = "skill"
    name = "Skill"
    description = "Load projected filesystem Skills"
    system_prompt = ""
    config_model = SkillToolkitConfig

    def __init__(
        self,
        *,
        store: SkillStateStore,
        projection_service: SkillProjectionService | None,
        vfs_projection_service: VfsProjectionService | None,
    ) -> None:
        """Create Skill Toolkit provider."""
        self.store = store
        self.projection_service = projection_service
        self.vfs_projection_service = vfs_projection_service

    async def resolve(
        self,
        config: SkillToolkitConfig,
        context: ResolveContext,
    ) -> Toolkit[SkillToolkitConfig]:
        """Return executable Skill Toolkit."""
        del config
        return SkillToolkit(
            store=self.store,
            projection_service=self.projection_service,
            vfs_projection_service=self.vfs_projection_service,
            agent_id=context.agent_id,
            session_id=context.session_id,
            workspace_id=context.workspace_id,
        )


def render_skill_prompt(snapshot: SkillProjectionSnapshot) -> str:
    """Render a filesystem Skill snapshot for compatibility callers."""
    return render_skill_items(snapshot.items)


def render_skill_items(items: Sequence[SkillProjectionItem]) -> str:
    """Render a stable model-visible Skill index from combined sources."""
    rendered_items = _dedupe_items_by_skill_path(items)
    if not rendered_items:
        return ""
    lines = [_SKILL_PROMPT_HEADER.rstrip(), ""]
    for item in rendered_items:
        lines.append(f"- **{item.name}**: {item.description}")
        lines.append(f"  Path: `{item.skill_path}`")
    return "\n".join(lines)


def skill_items_from_vfs_projection(
    projection: VfsProjection,
) -> list[SkillProjectionItem]:
    """Parse managed Skill entrypoints from one immutable VFS projection."""
    items: list[SkillProjectionItem] = []
    for entry in projection.entries:
        if not _managed_skill_uri_parts(entry.canonical_uri):
            continue
        items.append(skill_item_from_vfs_entry(entry))
    return _sort_skill_items(items)


def skill_item_from_vfs_entry(entry: VfsFileEntry) -> SkillProjectionItem:
    """Parse one verified managed SKILL.md VFS entry."""
    parts = _managed_skill_uri_parts(entry.canonical_uri)
    if parts is None:
        raise ValueError("VFS entry is not a managed Skill entrypoint")
    namespace, slug = parts
    if entry.size_bytes > _SKILL_READ_MAX_BYTES:
        raise ValueError(
            f"Managed SKILL.md exceeds {_SKILL_READ_MAX_BYTES} bytes: "
            f"{entry.canonical_uri}"
        )
    try:
        body = entry.decode_body().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"Managed SKILL.md is not UTF-8: {entry.canonical_uri}"
        ) from exc
    metadata = _parse_frontmatter(body)
    description = _metadata_string(metadata, "description")
    if not description:
        raise ValueError(
            f"Managed SKILL.md requires a description: {entry.canonical_uri}"
        )
    return SkillProjectionItem(
        id=_stable_item_id(entry.canonical_uri),
        source_kind="azents",
        project_id=None,
        project_path=None,
        skill_dir_path=posixpath.dirname(entry.canonical_uri),
        skill_path=entry.canonical_uri,
        slug=slug,
        name=_metadata_string(metadata, "name") or slug,
        description=description,
        frontmatter=metadata,
        body=body,
        content_hash=entry.content_hash,
        source_label=namespace,
        relative_hint=f"{namespace}/{slug}",
    )


def make_load_skill_tool(
    *,
    store: SkillStateStore,
    vfs_projection_service: VfsProjectionService | None,
    agent_id: str,
    session_id: str,
    workspace_id: str,
    run_id: str,
) -> FunctionTool:
    """Create load_skill FunctionTool for filesystem and managed Skills."""

    async def load_skill(args: LoadSkillInput) -> str:
        """Load a Skill by exact active filesystem path or current-run VFS URI."""
        if args.skill_path.startswith("azents://"):
            if vfs_projection_service is None:
                raise FunctionToolError("Managed Skill resolution is unavailable.")
            try:
                canonical_uri = canonicalize_vfs_uri(args.skill_path)
                resolved = await vfs_projection_service.resolve_file(
                    run_id=run_id,
                    agent_id=agent_id,
                    session_id=session_id,
                    workspace_id=workspace_id,
                    uri=canonical_uri,
                )
                item = skill_item_from_vfs_entry(resolved.entry)
            except (VfsUriError, ValueError) as exc:
                raise FunctionToolError(str(exc)) from None
            except VfsFileResolutionError as exc:
                raise FunctionToolError(exc.message) from None
            metadata = {
                "name": item.name,
                "slug": item.slug,
                "skill_path": item.skill_path,
                "source_kind": item.source_kind,
                "source_label": item.source_label,
                "relative_hint": item.relative_hint,
                "projection_revision_id": resolved.projection_revision_id,
                "projection_hash": resolved.projection_hash,
                "source_id": resolved.entry.source_id,
                "source_revision_id": resolved.entry.source_revision_id,
                "content_hash": item.content_hash,
            }
            return _loaded_skill_output(item, metadata=metadata)

        if not args.skill_path.startswith("/"):
            raise FunctionToolError(
                "Skill path must be an absolute filesystem path or canonical "
                "azents:// Skill URI."
            )
        state = await store.load(agent_id, session_id)
        matches = [
            item
            for item in state.active.items
            if _normalize_path(item.skill_path) == _normalize_path(args.skill_path)
        ]
        if not matches:
            raise FunctionToolError(
                "Skill not found in the active projection. Use an exact SKILL.md "
                "path from the current Skills prompt."
            )
        if len(matches) > 1:
            logger.warning(
                "Duplicate Skill path entries found in active projection",
                extra={
                    "agent_id": agent_id,
                    "session_id": session_id,
                    "skill_path": args.skill_path,
                    "match_count": len(matches),
                    "projection_revision_id": state.active.revision_id,
                },
            )
        item = matches[0]
        metadata = {
            "name": item.name,
            "slug": item.slug,
            "skill_path": item.skill_path,
            "source_kind": item.source_kind,
            "source_label": item.source_label,
            "relative_hint": item.relative_hint,
            "projection_revision_id": state.active.revision_id,
            "content_hash": item.content_hash,
        }
        return _loaded_skill_output(item, metadata=metadata)

    return make_tool(load_skill, input_model=LoadSkillInput)


def skill_actions_from_snapshot(
    snapshot: SkillProjectionSnapshot,
) -> list[SkillProjectionItem]:
    """Return valid Skill items for action rendering."""
    return _dedupe_items_by_skill_path(snapshot.items)


async def load_skill_projection_for_actions(
    store: SkillStateStore,
    *,
    vfs_projection_service: VfsProjectionService | None,
    agent_id: str,
    session_id: str,
    workspace_id: str,
    run_state: AgentSessionRunState,
    active_run_id: str | None,
) -> SkillProjectionSnapshot:
    """Combine filesystem actions with an idle preview or exact run VFS view."""
    state = await store.load(agent_id, session_id)
    filesystem = (
        state.active if run_state == AgentSessionRunState.RUNNING else state.latest
    )
    if vfs_projection_service is None:
        return filesystem
    try:
        projection = await vfs_projection_service.projection_for_actions(
            agent_id=agent_id,
            session_id=session_id,
            workspace_id=workspace_id,
            running=run_state == AgentSessionRunState.RUNNING,
            active_run_id=active_run_id,
        )
    except VfsFileResolutionError as exc:
        if exc.code != "storage_unavailable":
            raise
        logger.warning(
            "Managed Skill actions unavailable because the VFS projection is not ready",
            extra={
                "agent_id": agent_id,
                "session_id": session_id,
                "workspace_id": workspace_id,
                "run_state": run_state.value,
                "active_run_id": active_run_id,
                "vfs_error_code": exc.code,
            },
        )
        return filesystem
    return filesystem.model_copy(
        update={
            "items": [
                *filesystem.items,
                *skill_items_from_vfs_projection(projection),
            ]
        }
    )


def _loaded_skill_output(
    item: SkillProjectionItem,
    *,
    metadata: Mapping[str, object],
) -> str:
    """Render one loaded Skill result with bounded projection metadata."""
    return (
        "Skill loaded from the active projection.\n"
        f"Metadata: {json.dumps(metadata, ensure_ascii=False, sort_keys=True)}\n\n"
        f"{item.body}"
    )


def _managed_skill_uri_parts(uri: str) -> tuple[str, str] | None:
    """Return namespace and slug for a canonical managed Skill entrypoint."""
    try:
        canonical_uri = canonicalize_vfs_uri(uri)
    except VfsUriError:
        return None
    prefix = f"azents://{AZENTS_VFS_SKILLS_MOUNT}/"
    if not canonical_uri.startswith(prefix):
        return None
    segments = canonical_uri[len(prefix) :].split("/")
    if len(segments) != 3 or segments[2] != SKILL_MARKDOWN_FILENAME:
        return None
    namespace, slug, _ = segments
    return namespace, slug


def skill_action_id(skill_path: str) -> str:
    """Return stable action definition ID for Skill path."""
    return f"skill:{_stable_item_id(skill_path)}"


def resolve_active_skill(
    state: SkillProjectionState,
    *,
    skill_path: str,
) -> SkillProjectionItem | None:
    """Resolve exact Skill path from active projection."""
    normalized = _normalize_path(skill_path)
    for item in state.active.items:
        if _normalize_path(item.skill_path) == normalized:
            return item
    return None


def _dedupe_skill_path_candidates(
    candidates: Sequence[_SkillPathCandidate],
) -> list[_SkillPathCandidate]:
    """Keep one candidate per normalized path, preferring direct source roots."""
    deduped: dict[str, _SkillPathCandidate] = {}
    ordered = sorted(
        candidates,
        key=lambda candidate: (
            _normalize_path(candidate.skill_path),
            not _path_is_within(
                candidate.skill_path,
                candidate.source.root_path,
            ),
            _source_priority(candidate.source.source_kind),
            candidate.source.project_path or "",
            _normalize_path(candidate.source.root_path),
        ),
    )
    for candidate in ordered:
        normalized = _normalize_path(candidate.skill_path)
        deduped.setdefault(normalized, candidate)
    return list(deduped.values())


def _path_is_within(path: str, root_path: str) -> bool:
    """Return whether a normalized path is inside a normalized source root."""
    normalized_path = PurePosixPath(_normalize_path(path))
    normalized_root = PurePosixPath(_normalize_path(root_path))
    return normalized_path.is_relative_to(normalized_root)


def _skill_source_roots(
    projects: Sequence[SessionWorkspaceProject],
) -> list[SkillSourceRoot]:
    roots = [
        SkillSourceRoot(
            source_kind="agent",
            root_path=AGENT_SKILL_ROOT,
            source_label="Agent",
            relative_prefix=".azents/skills",
        )
    ]
    for project in sorted(projects, key=lambda item: item.path):
        source_label = (
            posixpath.basename(posixpath.normpath(project.path)) or project.path
        )
        roots.append(
            SkillSourceRoot(
                source_kind="project_agents",
                root_path=posixpath.join(project.path, ".agents", "skills"),
                source_label=source_label,
                relative_prefix=".agents/skills",
                project_id=project.id,
                project_path=project.path,
            )
        )
        roots.append(
            SkillSourceRoot(
                source_kind="project_claude",
                root_path=posixpath.join(project.path, ".claude", "skills"),
                source_label=source_label,
                relative_prefix=".claude/skills",
                project_id=project.id,
                project_path=project.path,
            )
        )
    return roots


def _filter_snapshot_project(
    snapshot: SkillProjectionSnapshot,
    *,
    project_id: str,
    project_path: str,
    reason: SyncReason,
) -> SkillProjectionSnapshot:
    items = [
        item
        for item in snapshot.items
        if item.project_id != project_id and item.project_path != project_path
    ]
    if len(items) == len(snapshot.items):
        return snapshot
    return _make_snapshot(items, reason=reason)


def _make_snapshot(
    items: Sequence[SkillProjectionItem],
    *,
    reason: SyncReason,
) -> SkillProjectionSnapshot:
    ordered = _sort_skill_items(_dedupe_items_by_skill_path(items))
    return SkillProjectionSnapshot(
        revision_id=uuid7().hex,
        projection_hash=_projection_hash(ordered),
        synced_at=datetime.datetime.now(datetime.UTC).isoformat(),
        sync_reason=reason,
        items=list(ordered),
    )


def _sort_skill_items(
    items: Sequence[SkillProjectionItem],
) -> list[SkillProjectionItem]:
    """Return Skill items in deterministic projection/rendering order."""
    return sorted(
        items,
        key=lambda item: (
            _source_priority(item.source_kind),
            item.project_path or "",
            item.slug,
            item.skill_path,
        ),
    )


def _dedupe_items_by_skill_path(
    items: Sequence[SkillProjectionItem],
) -> list[SkillProjectionItem]:
    """Keep one projection item per exact normalized SKILL.md path."""
    deduped: dict[str, SkillProjectionItem] = {}
    for item in _sort_skill_items(items):
        normalized = _normalize_path(item.skill_path)
        if normalized in deduped:
            logger.warning(
                "Duplicate Skill path entry ignored",
                extra={
                    "skill_path": item.skill_path,
                    "kept_skill_path": deduped[normalized].skill_path,
                    "source_kind": item.source_kind,
                    "project_id": item.project_id,
                    "project_path": item.project_path,
                },
            )
            continue
        deduped[normalized] = item
    return list(deduped.values())


def _projection_hash(items: Sequence[SkillProjectionItem]) -> str:
    payload = [
        {
            "source_kind": item.source_kind,
            "project_id": item.project_id,
            "project_path": item.project_path,
            "skill_path": item.skill_path,
            "content_hash": item.content_hash,
        }
        for item in items
    ]
    return _sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _parse_frontmatter(body: str) -> dict[str, Any]:
    try:
        post = frontmatter.loads(body)
    except ValueError, yaml.YAMLError:
        return {}
    return {str(key): value for key, value in post.metadata.items()}


def _metadata_string(metadata: dict[str, Any], key: str) -> str:
    value = metadata.get(key)
    if value is None:
        return ""
    return str(value).strip()


def _relative_hint(source: SkillSourceRoot, skill_dir_path: str) -> str:
    if source.project_path and skill_dir_path.startswith(f"{source.project_path}/"):
        return skill_dir_path[len(source.project_path) + 1 :]
    if source.source_kind == "agent" and skill_dir_path.startswith(
        f"{AGENT_WORKSPACE_ROOT}/"
    ):
        return skill_dir_path[len(AGENT_WORKSPACE_ROOT) + 1 :]
    return posixpath.join(source.relative_prefix, posixpath.basename(skill_dir_path))


def _stable_item_id(skill_path: str) -> str:
    return hashlib.sha256(_normalize_path(skill_path).encode("utf-8")).hexdigest()[:24]


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_path(path: str) -> str:
    if path.startswith("azents://"):
        return canonicalize_vfs_uri(path)
    return PurePosixPath(posixpath.normpath(path)).as_posix()


def _source_priority(source_kind: SkillSourceKind) -> int:
    match source_kind:
        case "agent":
            return 0
        case "project_agents":
            return 1
        case "project_claude":
            return 2
        case "azents":
            return 3
        case _:
            assert_never(source_kind)


def _runner_file_operation_deadline() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC) + datetime.timedelta(
        seconds=_RUNNER_FILE_OPERATION_TIMEOUT_SECONDS
    )
