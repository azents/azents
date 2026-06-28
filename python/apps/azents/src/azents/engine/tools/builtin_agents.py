"""Builtin Toolkit AGENTS.md instruction state and prompt helpers."""

import asyncio
import json
import logging
import posixpath
import time
from collections.abc import Callable, Sequence
from typing import NamedTuple, Protocol

from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.tools import ToolCallHookContext, ToolCallHookOutcome
from azents.engine.hooks.types import (
    AfterToolCallHookContext,
    BeforeToolCallHookContext,
    RuntimeHooks,
    SessionCompactHookContext,
    ToolOutputReplace,
)
from azents.engine.tooling.toolkit_state import (
    ToolkitStateHandle,
    ToolkitStateIdentity,
    ToolkitStateModel,
    ToolkitStateStore,
)
from azents.rdb.session import SessionManager
from azents.repos.session_workspace_project.data import SessionWorkspaceProject
from azents.runtime.types import RuntimeDomainConfig
from azents.services.file_storage import FileStorage

logger = logging.getLogger(__name__)

SESSION_WORKSPACE_ROOT = "/workspace/agent"
AGENTS_FILENAME = "AGENTS.md"
ROOT_AGENTS_PATH = f"{SESSION_WORKSPACE_ROOT}/{AGENTS_FILENAME}"
MAX_AGENTS_BYTES = 64 * 1024
MAX_PROJECT_AGENTS_FILES = 20
MAX_PROJECT_AGENTS_PROMPT_CHARS = 64 * 1024
AGENTS_LIVE_READ_INTERVAL_TURNS = 5
AGENTS_BACKGROUND_REFRESH_WARN_SECONDS = 10.0
AGENTS_TOOLKIT_NAMESPACE = "builtin"
ROOT_AGENTS_TOOLKIT_STATE_NAME = "root_agents_instruction"
PROJECT_AGENTS_TOOLKIT_STATE_NAME = "project_agents_instructions"
AGENTS_APPENDIX_DEDUPE_TOOLKIT_STATE_NAME = "agents_md_appendix_dedupe"


class RootAgentsInstructionState(ToolkitStateModel):
    """Root AGENTS.md instruction Toolkit State payload."""

    schema_version: int = 1
    root_content: str | None = None


class ProjectAgentsInstructionState(ToolkitStateModel):
    """Project AGENTS.md instruction Toolkit State payload."""

    schema_version: int = 1
    project_contents: dict[str, str] = Field(default_factory=dict)
    active_project_paths: set[str] = Field(default_factory=set)


class AgentsAppendixDedupeState(ToolkitStateModel):
    """AGENTS.md read-result appendix dedupe Toolkit State payload."""

    schema_version: int = 1
    appended_paths: list[str] = Field(default_factory=list)


class AgentsInstructionStateStore(Protocol):
    """AGENTS.md instruction state store interface."""

    async def load_root(
        self, agent_id: str, session_id: str
    ) -> RootAgentsInstructionState:
        """Fetch session root AGENTS.md instruction state."""
        ...

    async def save_root(
        self, agent_id: str, session_id: str, state: RootAgentsInstructionState
    ) -> None:
        """Store session root AGENTS.md instruction state."""
        ...

    async def update_root(
        self,
        agent_id: str,
        session_id: str,
        mutator: Callable[[RootAgentsInstructionState], RootAgentsInstructionState],
    ) -> None:
        """Retry-apply mutator to latest root AGENTS.md state."""
        ...

    async def load_project(
        self, agent_id: str, session_id: str
    ) -> ProjectAgentsInstructionState:
        """Fetch AgentSession Project AGENTS.md instruction state."""
        ...

    async def save_project(
        self, agent_id: str, session_id: str, state: ProjectAgentsInstructionState
    ) -> None:
        """Store AgentSession Project AGENTS.md instruction state."""
        ...

    async def update_project(
        self,
        agent_id: str,
        session_id: str,
        mutator: Callable[
            [ProjectAgentsInstructionState], ProjectAgentsInstructionState
        ],
    ) -> None:
        """Retry-apply mutator to latest Project AGENTS.md state."""
        ...

    async def load_appendix_dedupe(
        self, agent_id: str, session_id: str
    ) -> AgentsAppendixDedupeState:
        """Fetch AGENTS.md appendix dedupe state."""
        ...

    async def update_appendix_dedupe(
        self,
        agent_id: str,
        session_id: str,
        mutator: Callable[[AgentsAppendixDedupeState], AgentsAppendixDedupeState],
    ) -> None:
        """Retry-apply mutator to latest appendix dedupe state."""
        ...


class ToolkitAgentsInstructionStateStore:
    """AGENTS.md instruction state store based on Toolkit State."""

    def __init__(
        self,
        *,
        session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Create AGENTS.md instruction state store."""
        self._session_manager = session_manager

    async def load_root(
        self, agent_id: str, session_id: str
    ) -> RootAgentsInstructionState:
        """Fetch session root AGENTS.md instruction state."""
        async with self._session_manager() as session:
            handle = self._make_root_handle(session, agent_id, session_id)
            if handle is None:
                return RootAgentsInstructionState()
            return await handle.load(default_factory=RootAgentsInstructionState)

    async def save_root(
        self, agent_id: str, session_id: str, state: RootAgentsInstructionState
    ) -> None:
        """Store session root AGENTS.md instruction state."""
        async with self._session_manager() as session:
            handle = self._make_root_handle(session, agent_id, session_id)
            if handle is None:
                return
            await handle.load(default_factory=RootAgentsInstructionState)
            await handle.save(state)

    async def update_root(
        self,
        agent_id: str,
        session_id: str,
        mutator: Callable[[RootAgentsInstructionState], RootAgentsInstructionState],
    ) -> None:
        """Retry-apply mutator to latest root AGENTS.md state."""
        async with self._session_manager() as session:
            handle = self._make_root_handle(session, agent_id, session_id)
            if handle is None:
                return
            await handle.update(
                default_factory=RootAgentsInstructionState,
                mutator=mutator,
            )

    async def load_project(
        self, agent_id: str, session_id: str
    ) -> ProjectAgentsInstructionState:
        """Fetch AgentSession Project AGENTS.md instruction state."""
        async with self._session_manager() as session:
            handle = self._make_project_handle(session, agent_id, session_id)
            if handle is None:
                return ProjectAgentsInstructionState()
            return await handle.load(default_factory=ProjectAgentsInstructionState)

    async def save_project(
        self, agent_id: str, session_id: str, state: ProjectAgentsInstructionState
    ) -> None:
        """Store AgentSession Project AGENTS.md instruction state."""
        async with self._session_manager() as session:
            handle = self._make_project_handle(session, agent_id, session_id)
            if handle is None:
                return
            await handle.load(default_factory=ProjectAgentsInstructionState)
            await handle.save(state)

    async def update_project(
        self,
        agent_id: str,
        session_id: str,
        mutator: Callable[
            [ProjectAgentsInstructionState], ProjectAgentsInstructionState
        ],
    ) -> None:
        """Retry-apply mutator to latest Project AGENTS.md state."""
        async with self._session_manager() as session:
            handle = self._make_project_handle(session, agent_id, session_id)
            if handle is None:
                return
            await handle.update(
                default_factory=ProjectAgentsInstructionState,
                mutator=mutator,
            )

    async def load_appendix_dedupe(
        self, agent_id: str, session_id: str
    ) -> AgentsAppendixDedupeState:
        """Fetch AGENTS.md appendix dedupe state."""
        async with self._session_manager() as session:
            handle = self._make_appendix_dedupe_handle(session, agent_id, session_id)
            if handle is None:
                return AgentsAppendixDedupeState()
            return await handle.load(default_factory=AgentsAppendixDedupeState)

    async def update_appendix_dedupe(
        self,
        agent_id: str,
        session_id: str,
        mutator: Callable[[AgentsAppendixDedupeState], AgentsAppendixDedupeState],
    ) -> None:
        """Retry-apply mutator to latest appendix dedupe state."""
        async with self._session_manager() as session:
            handle = self._make_appendix_dedupe_handle(session, agent_id, session_id)
            if handle is None:
                return
            await handle.update(
                default_factory=AgentsAppendixDedupeState,
                mutator=mutator,
            )

    def _make_project_handle(
        self,
        session: AsyncSession,
        agent_id: str,
        session_id: str,
    ) -> ToolkitStateHandle[ProjectAgentsInstructionState] | None:
        """Create project Toolkit State handle for agent/session identity."""
        if not agent_id or not session_id:
            return None
        identity = ToolkitStateIdentity(
            agent_id=agent_id,
            session_id=session_id,
            toolkit_namespace=AGENTS_TOOLKIT_NAMESPACE,
            state_name=PROJECT_AGENTS_TOOLKIT_STATE_NAME,
        )
        return ToolkitStateStore(session=session).handle(
            identity,
            ProjectAgentsInstructionState,
        )

    def _make_root_handle(
        self,
        session: AsyncSession,
        agent_id: str,
        session_id: str,
    ) -> ToolkitStateHandle[RootAgentsInstructionState] | None:
        """Create root Toolkit State handle for agent/session identity."""
        if not agent_id or not session_id:
            return None
        identity = ToolkitStateIdentity(
            agent_id=agent_id,
            session_id=session_id,
            toolkit_namespace=AGENTS_TOOLKIT_NAMESPACE,
            state_name=ROOT_AGENTS_TOOLKIT_STATE_NAME,
        )
        return ToolkitStateStore(session=session).handle(
            identity,
            RootAgentsInstructionState,
        )

    def _make_appendix_dedupe_handle(
        self,
        session: AsyncSession,
        agent_id: str,
        session_id: str,
    ) -> ToolkitStateHandle[AgentsAppendixDedupeState] | None:
        """Create AGENTS.md appendix dedupe handle for agent/session identity."""
        if not agent_id or not session_id:
            return None
        identity = ToolkitStateIdentity(
            agent_id=agent_id,
            session_id=session_id,
            toolkit_namespace=AGENTS_TOOLKIT_NAMESPACE,
            state_name=AGENTS_APPENDIX_DEDUPE_TOOLKIT_STATE_NAME,
        )
        return ToolkitStateStore(session=session).handle(
            identity,
            AgentsAppendixDedupeState,
        )


class _ToolPathRef(NamedTuple):
    """Path and directory flag extracted from tool arguments."""

    path: str
    directory: bool


def extract_tool_path_refs(tool_name: str, args_json: str) -> list[_ToolPathRef]:
    """Extract runtime path candidate and directory flag from tool arguments."""
    try:
        raw = json.loads(args_json)
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, dict):
        return []

    refs: list[_ToolPathRef] = []
    if tool_name in {"read", "read_image", "write", "edit", "delete", "grep"}:
        value = raw.get("path")
        if isinstance(value, str):
            refs.append(_ToolPathRef(value, tool_name == "grep"))
    elif tool_name == "glob":
        value = raw.get("pattern")
        if isinstance(value, str):
            refs.append(_ToolPathRef(_glob_base_path(value), True))
    elif tool_name == "import_file":
        value = raw.get("path")
        if isinstance(value, str):
            refs.append(_ToolPathRef(value, False))
    elif tool_name == "present_file":
        value = raw.get("paths")
        if isinstance(value, list):
            refs.extend(
                _ToolPathRef(item, False) for item in value if isinstance(item, str)
            )
    return [
        _ToolPathRef(path, ref.directory)
        for ref in refs
        if (path := _normalize_runtime_path(ref.path)) is not None
    ]


def extract_tool_paths(tool_name: str, args_json: str) -> list[str]:
    """Extract only runtime path candidates from tool arguments."""
    return [ref.path for ref in extract_tool_path_refs(tool_name, args_json)]


def project_for_path(
    path: str,
    projects: Sequence[SessionWorkspaceProject],
) -> SessionWorkspaceProject | None:
    """Return registered Project containing path."""
    for project in projects:
        project_path = posixpath.normpath(project.path)
        if path == project_path or path.startswith(f"{project_path}/"):
            return project
    return None


def agents_candidates_for_path(
    path: str,
    projects: Sequence[SessionWorkspaceProject],
    *,
    directory: bool = False,
) -> list[str]:
    """Return Project-scoped AGENTS.md candidates applicable to target path."""
    normalized = _normalize_runtime_path(path)
    if normalized is None:
        return []
    project = project_for_path(normalized, projects)
    if project is None:
        return []

    target_dir = normalized if directory else posixpath.dirname(normalized)
    project_path = posixpath.normpath(project.path)
    candidates: list[str] = []
    current = project_path
    while True:
        candidates.append(posixpath.join(current, AGENTS_FILENAME))
        if current == target_dir:
            break
        if not target_dir.startswith(f"{current}/"):
            break
        rel = target_dir[len(current) + 1 :]
        next_part = rel.split("/", 1)[0]
        current = posixpath.join(current, next_part)
    return candidates


def render_agents_block(title: str, files: Sequence[tuple[str, str]]) -> str:
    """Render AGENTS.md prompt block."""
    if not files:
        return ""
    parts = [f"## {title}"]
    for path, content in files:
        parts.extend(["", f"### {path}", "", content])
    return "\n".join(parts)


def render_project_agents_block(files: Sequence[tuple[str, str]]) -> str:
    """Render Project AGENTS.md prompt block within budget."""
    rendered: list[tuple[str, str]] = []
    used_chars = 0
    omitted = 0
    for path, content in files:
        entry_chars = len(path) + len(content)
        if (
            len(rendered) >= MAX_PROJECT_AGENTS_FILES
            or used_chars + entry_chars > MAX_PROJECT_AGENTS_PROMPT_CHARS
        ):
            omitted += 1
            continue
        rendered.append((path, content))
        used_chars += entry_chars
    block = render_agents_block("Project Instructions", rendered)
    if omitted == 0:
        return block
    omitted_line = (
        f"{omitted} additional AGENTS.md instruction file(s) were omitted "
        "because the project instruction prompt budget was reached."
    )
    if not block:
        return "\n".join(["## Project Instructions", "", omitted_line])
    return f"{block}\n\n{omitted_line}"


def truncate_agents_content(content: bytes) -> str:
    """Limit AGENTS.md content to prompt-safe size."""
    data = content[:MAX_AGENTS_BYTES]
    text = data.decode("utf-8", errors="replace")
    if len(content) > MAX_AGENTS_BYTES:
        text += "\n\n... (truncated)"
    return text


def apply_root_agents_tool_update(
    state: RootAgentsInstructionState,
    tool_name: str,
    args_json: str,
) -> RootAgentsInstructionState:
    """Reflect root AGENTS.md write/delete hook result in state."""
    try:
        raw = json.loads(args_json)
    except json.JSONDecodeError:
        return state
    if not isinstance(raw, dict):
        return state
    if tool_name == "write" and isinstance(raw.get("content"), str):
        return state.model_copy(
            update={
                "root_content": truncate_agents_content(raw["content"].encode("utf-8"))
            }
        )
    if (
        tool_name == "edit"
        and isinstance(raw.get("old_string"), str)
        and isinstance(raw.get("new_string"), str)
    ):
        current = state.root_content
        if current is None:
            return state
        old_string = raw["old_string"]
        new_string = raw["new_string"]
        replace_all = raw.get("replace_all") is True
        if replace_all:
            updated = current.replace(old_string, new_string)
        else:
            updated = current.replace(old_string, new_string, 1)
        return state.model_copy(
            update={"root_content": truncate_agents_content(updated.encode("utf-8"))}
        )
    if tool_name == "delete":
        return state.model_copy(update={"root_content": None})
    return state


def apply_project_agents_tool_update(
    state: ProjectAgentsInstructionState,
    path: str,
    tool_name: str,
    args_json: str,
) -> ProjectAgentsInstructionState:
    """Reflect Project AGENTS.md write/delete hook result in state."""
    try:
        raw = json.loads(args_json)
    except json.JSONDecodeError:
        return state
    if not isinstance(raw, dict):
        return state
    project_contents = dict(state.project_contents)
    if tool_name == "write" and isinstance(raw.get("content"), str):
        project_contents[path] = truncate_agents_content(raw["content"].encode("utf-8"))
    elif (
        tool_name == "edit"
        and isinstance(raw.get("old_string"), str)
        and isinstance(raw.get("new_string"), str)
    ):
        current = project_contents.get(path)
        if current is None:
            return state
        replace_all = raw.get("replace_all") is True
        if replace_all:
            updated = current.replace(raw["old_string"], raw["new_string"])
        else:
            updated = current.replace(raw["old_string"], raw["new_string"], 1)
        project_contents[path] = truncate_agents_content(updated.encode("utf-8"))
    elif tool_name == "delete":
        project_contents.pop(path, None)
    return state.model_copy(update={"project_contents": project_contents})


class RootAgentsPromptMixin:
    """Root AGENTS.md prompt loading behavior."""

    _agents_store: AgentsInstructionStateStore | None
    _agent_id: str
    _session_id: str
    _session_manager: SessionManager[AsyncSession] | None

    async def _load_root_agents_prompt(
        self,
        *,
        workspace_id: str,
        domain_config: RuntimeDomainConfig,
        user_id: str | None,
    ) -> str:
        """Do not inject root AGENTS.md into Toolkit prompts."""
        del workspace_id, domain_config, user_id
        return ""

    async def _load_root_agents_state(self) -> RootAgentsInstructionState:
        """Fetch persistent root AGENTS.md instruction state."""
        if self._agents_store is None:
            return RootAgentsInstructionState()
        return await self._agents_store.load_root(self._agent_id, self._session_id)

    async def _update_root_agents_state(
        self,
        mutator: Callable[[RootAgentsInstructionState], RootAgentsInstructionState],
    ) -> None:
        """Retry-update persistent root AGENTS.md instruction state."""
        if self._agents_store is None:
            return
        await self._agents_store.update_root(self._agent_id, self._session_id, mutator)


class ProjectAgentsPromptMixin:
    """Project-scoped AGENTS.md prompt loading behavior."""

    _agents_store: AgentsInstructionStateStore | None
    _active_agents_paths: set[str]
    _agents_turns_since_live_read: int
    _last_projects: list[SessionWorkspaceProject]
    _agents_refresh_task: asyncio.Task[None] | None
    _pending_agents_refresh_paths: set[str]
    _agents_file_storage: FileStorage | None
    _runtime_agent_id: str
    _runtime_session_id: str

    def hooks(self) -> RuntimeHooks:
        """Register AGENTS.md state observer as runtime hook mapping."""
        return {
            "on_before_tool_call": self._on_before_tool_call_hook,
            "on_after_tool_call": self._on_after_tool_call_hook,
            "on_session_compact": self._on_session_compact_hook,
        }

    async def _on_before_tool_call_hook(
        self, context: BeforeToolCallHookContext
    ) -> None:
        """AGENTS.md discovery is not performed before tool execution."""
        del context

    async def _on_after_tool_call_hook(
        self, context: AfterToolCallHookContext
    ) -> ToolOutputReplace | None:
        """Append applicable AGENTS.md instructions after successful read."""
        return await self.append_agents_after_read(
            ToolCallHookContext(
                tool_name=context.tool_name,
                toolkit_slug=context.toolkit_slug,
                args_json=context.args_json,
                session_id=context.session_id,
                agent_id=context.agent_id,
                workspace_id=context.workspace_id,
                run_id=context.run_id,
            ),
            ToolCallHookOutcome(
                output=context.output_text, error=context.error_message
            ),
        )

    async def _on_session_compact_hook(
        self, context: SessionCompactHookContext
    ) -> None:
        """Clear AGENTS.md appendix dedupe on compaction."""
        del context
        self._active_agents_paths = set()
        self._pending_agents_refresh_paths = set()
        await self._update_appendix_dedupe_state(
            lambda state: state.model_copy(update={"appended_paths": []})
        )

    async def on_before_tool_call(self, context: ToolCallHookContext) -> None:
        """Do not live-discover AGENTS.md before tool execution."""
        del context

    async def append_agents_after_read(
        self,
        context: ToolCallHookContext,
        outcome: ToolCallHookOutcome,
    ) -> ToolOutputReplace | None:
        """Append applicable AGENTS.md instructions to successful read results."""
        if outcome.error is not None or outcome.output is None:
            return None
        tool_name = _base_tool_name(context.tool_name)
        if tool_name != "read":
            return None
        refs = extract_tool_path_refs(tool_name, context.args_json)
        if not refs:
            return None
        target_path = refs[0].path
        if not _is_under_workspace_root(target_path):
            return None
        file_storage = self._agents_file_storage
        if file_storage is None:
            return None
        dedupe = await self._load_appendix_dedupe_state()
        already_appended = set(dedupe.appended_paths)
        candidates = _agents_appendix_candidates_for_path(
            target_path,
            self._last_projects,
            directory=refs[0].directory,
        )
        candidates = [
            path
            for path in candidates
            if path != target_path and path not in already_appended
        ]
        files = await self._read_existing_agents_files(file_storage, candidates)
        if not files:
            return None
        appended_paths = sorted(already_appended | {path for path, _ in files})
        await self._update_appendix_dedupe_state(
            lambda state: state.model_copy(update={"appended_paths": appended_paths})
        )
        logger.info(
            "Appended AGENTS.md instructions to read result",
            extra={
                "agent_id": self._runtime_agent_id,
                "session_id": self._runtime_session_id,
                "appended_path_count": len(files),
                "dedupe_skipped_path_count": len(candidates) - len(files),
            },
        )
        return ToolOutputReplace(
            output_text=f"{outcome.output}\n\n{render_agents_appendix(files)}"
        )

    async def _load_project_agents_prompt(
        self,
        file_storage: FileStorage,
        projects: list[SessionWorkspaceProject],
    ) -> str:
        """Register storage/projects without injecting AGENTS.md into prompt."""
        self._agents_file_storage = file_storage
        self._last_projects = sorted(projects, key=lambda project: project.path)
        return ""

    async def _read_existing_agents_files(
        self,
        file_storage: FileStorage,
        paths: Sequence[str],
    ) -> list[tuple[str, str]]:
        """Read existing AGENTS.md files in deterministic order."""
        files: list[tuple[str, str]] = []
        for path in paths:
            content = await self._read_agents_file(file_storage, path, fallback=None)
            if content is not None:
                files.append((path, content))
        return files

    def _schedule_project_agents_refresh(
        self,
        *,
        file_storage: FileStorage,
        paths: set[str],
    ) -> None:
        """Schedule Project AGENTS.md live refresh as background task."""
        if not paths:
            return
        self._pending_agents_refresh_paths.update(paths)
        task = self._agents_refresh_task
        if task is not None and not task.done():
            return
        self._agents_refresh_task = asyncio.create_task(
            self._drain_project_agents_refresh(file_storage=file_storage)
        )

    async def _drain_project_agents_refresh(
        self,
        *,
        file_storage: FileStorage,
    ) -> None:
        """Handle accumulated Project AGENTS.md refresh candidates sequentially."""
        while self._pending_agents_refresh_paths:
            paths = set(self._pending_agents_refresh_paths)
            self._pending_agents_refresh_paths.difference_update(paths)
            state = await self._load_project_agents_state()
            await self._refresh_project_agents_files(
                file_storage=file_storage,
                paths=paths,
                active_paths=set(state.active_project_paths),
                fallback_contents=dict(state.project_contents),
            )

    async def _refresh_project_agents_files(
        self,
        *,
        file_storage: FileStorage,
        paths: set[str],
        active_paths: set[str],
        fallback_contents: dict[str, str],
    ) -> None:
        """Live-read Project AGENTS.md files and store in toolkit state cache."""
        started = time.monotonic()
        project_contents = dict(fallback_contents)
        next_active_paths = set(active_paths)
        try:
            for path in sorted(paths):
                content = await self._read_agents_file(
                    file_storage,
                    path,
                    fallback=project_contents.get(path),
                )
                if content is None:
                    project_contents.pop(path, None)
                    next_active_paths.discard(path)
                    continue
                project_contents[path] = content
                next_active_paths.add(path)
            self._active_agents_paths = next_active_paths
            await self._update_project_agents_state(
                lambda state: state.model_copy(
                    update={
                        "project_contents": project_contents,
                        "active_project_paths": next_active_paths,
                    }
                )
            )
        except Exception:
            logger.exception(
                "Project AGENTS.md background refresh failed",
                extra={
                    "agent_id": self._runtime_agent_id,
                    "session_id": self._runtime_session_id,
                    "path_count": len(paths),
                },
            )
        finally:
            duration = time.monotonic() - started
            if duration >= AGENTS_BACKGROUND_REFRESH_WARN_SECONDS:
                logger.warning(
                    "Project AGENTS.md background refresh slow",
                    extra={
                        "agent_id": self._runtime_agent_id,
                        "session_id": self._runtime_session_id,
                        "path_count": len(paths),
                        "duration_seconds": round(duration, 3),
                        "threshold_seconds": AGENTS_BACKGROUND_REFRESH_WARN_SECONDS,
                    },
                )

    async def _read_agents_file(
        self,
        file_storage: FileStorage,
        path: str,
        *,
        fallback: str | None,
    ) -> str | None:
        """Read AGENTS.md regular file from Runtime storage."""
        try:
            metadata = await file_storage.stat(path, agent_id=self._runtime_agent_id)
            if metadata.get("is_file") is not True:
                return None
            content = await file_storage.get(path, agent_id=self._runtime_agent_id)
        except FileNotFoundError:
            return None
        except Exception:
            logger.warning(
                "Failed to read project AGENTS.md",
                extra={"agent_id": self._runtime_agent_id, "path": path},
                exc_info=True,
            )
            return fallback
        return truncate_agents_content(content)

    async def _load_project_agents_state(self) -> ProjectAgentsInstructionState:
        """Fetch persistent Project AGENTS.md instruction state."""
        if self._agents_store is None:
            return ProjectAgentsInstructionState()
        return await self._agents_store.load_project(
            self._runtime_agent_id,
            self._runtime_session_id,
        )

    async def _update_root_agents_state(
        self,
        mutator: Callable[[RootAgentsInstructionState], RootAgentsInstructionState],
    ) -> None:
        """Retry-update persistent root AGENTS.md instruction state."""
        if self._agents_store is None:
            return
        await self._agents_store.update_root(
            self._runtime_agent_id,
            self._runtime_session_id,
            mutator,
        )

    async def _update_project_agents_state(
        self,
        mutator: Callable[
            [ProjectAgentsInstructionState], ProjectAgentsInstructionState
        ],
    ) -> None:
        """Retry-update persistent Project AGENTS.md instruction state."""
        if self._agents_store is None:
            return
        await self._agents_store.update_project(
            self._runtime_agent_id,
            self._runtime_session_id,
            mutator,
        )

    async def _load_appendix_dedupe_state(self) -> AgentsAppendixDedupeState:
        """Fetch persistent AGENTS.md appendix dedupe state."""
        if self._agents_store is None:
            return AgentsAppendixDedupeState()
        return await self._agents_store.load_appendix_dedupe(
            self._runtime_agent_id,
            self._runtime_session_id,
        )

    async def _update_appendix_dedupe_state(
        self,
        mutator: Callable[[AgentsAppendixDedupeState], AgentsAppendixDedupeState],
    ) -> None:
        """Retry-update persistent AGENTS.md appendix dedupe state."""
        if self._agents_store is None:
            return
        await self._agents_store.update_appendix_dedupe(
            self._runtime_agent_id,
            self._runtime_session_id,
            mutator,
        )


def render_agents_appendix(files: Sequence[tuple[str, str]]) -> str:
    """Render AGENTS.md instructions as a read result appendix."""
    if not files:
        return ""
    parts = [
        "<system-reminder>",
        "Relevant AGENTS.md instructions for the accessed path:",
    ]
    for path, content in files:
        parts.extend(["", f"### {path}", "", content])
    parts.append("</system-reminder>")
    return "\n".join(parts)


def _agents_appendix_candidates_for_path(
    path: str,
    projects: Sequence[SessionWorkspaceProject],
    *,
    directory: bool = False,
) -> list[str]:
    """Return root/project AGENTS.md candidates applicable to target path."""
    normalized = _normalize_runtime_path(path)
    if normalized is None or not _is_under_workspace_root(normalized):
        return []
    candidates = [ROOT_AGENTS_PATH]
    candidates.extend(
        agents_candidates_for_path(normalized, projects, directory=directory)
    )
    seen: set[str] = set()
    ordered: list[str] = []
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        ordered.append(candidate)
    return ordered


def _base_tool_name(tool_name: str) -> str:
    """Return unprefixed tool name."""
    if "__" not in tool_name:
        return tool_name
    return tool_name.split("__", 1)[1]


def _is_under_workspace_root(path: str) -> bool:
    """Return whether path is inside the agent workspace root."""
    normalized = posixpath.normpath(path)
    return normalized == SESSION_WORKSPACE_ROOT or normalized.startswith(
        f"{SESSION_WORKSPACE_ROOT}/"
    )


def _normalize_runtime_path(path: str) -> str | None:
    """POSIX-normalize runtime absolute path."""
    stripped = path.strip()
    if not stripped:
        return None
    normalized = posixpath.normpath(stripped)
    if not normalized.startswith("/"):
        return None
    return normalized


def _glob_base_path(pattern: str) -> str:
    """Extract directory prefix before wildcard from glob pattern."""
    wildcard_positions = [
        index for marker in "*?[" if (index := pattern.find(marker)) >= 0
    ]
    if not wildcard_positions:
        return pattern
    prefix = pattern[: min(wildcard_positions)]
    if prefix.endswith("/"):
        return prefix.rstrip("/") or "/"
    return posixpath.dirname(prefix) or "/"
