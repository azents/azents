"""Runtime AGENTS.md read-result appendix helpers."""

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
from azents.engine.tools.runtime_instruction_context import RuntimeInstructionContext
from azents.rdb.session import SessionManager
from azents.repos.session_workspace_project.data import SessionWorkspaceProject
from azents.services.file_storage import FileStorage

logger = logging.getLogger(__name__)

SESSION_WORKSPACE_ROOT = "/workspace/agent"
AGENTS_FILENAME = "AGENTS.md"
ROOT_AGENTS_PATH = f"{SESSION_WORKSPACE_ROOT}/{AGENTS_FILENAME}"
MAX_AGENTS_BYTES = 64 * 1024
AGENTS_TOOLKIT_NAMESPACE = "builtin"
AGENTS_APPENDIX_DEDUPE_TOOLKIT_STATE_NAME = "agents_md_appendix_dedupe"
AGENTS_MISSING_CACHE_TTL_SECONDS = 5.0


class AgentsAppendixDedupeState(ToolkitStateModel):
    """AGENTS.md read-result appendix dedupe Toolkit State payload."""

    schema_version: int = 1
    appended_paths: list[str] = Field(default_factory=list)


class AgentsAppendixDedupeStateStore(Protocol):
    """AGENTS.md appendix dedupe state store interface."""

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


class ToolkitAgentsAppendixDedupeStateStore:
    """AGENTS.md appendix dedupe store based on Toolkit State."""

    def __init__(
        self,
        *,
        session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Create AGENTS.md appendix dedupe store."""
        self.session_manager = session_manager

    async def load_appendix_dedupe(
        self, agent_id: str, session_id: str
    ) -> AgentsAppendixDedupeState:
        """Fetch AGENTS.md appendix dedupe state."""
        async with self.session_manager() as session:
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
        async with self.session_manager() as session:
            handle = self._make_appendix_dedupe_handle(session, agent_id, session_id)
            if handle is None:
                return
            await handle.update(
                default_factory=AgentsAppendixDedupeState,
                mutator=mutator,
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
    if tool_name == "read":
        value = raw.get("path")
        if isinstance(value, str):
            refs.append(_ToolPathRef(value, False))
    return [
        _ToolPathRef(path, ref.directory)
        for ref in refs
        if (path := _normalize_runtime_path(ref.path)) is not None
    ]


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


def truncate_agents_content(content: bytes) -> str:
    """Limit AGENTS.md content to prompt-safe size."""
    data = content[:MAX_AGENTS_BYTES]
    text = data.decode("utf-8", errors="replace")
    if len(content) > MAX_AGENTS_BYTES:
        text += "\n\n... (truncated)"
    return text


class AgentsAppendixMixin:
    """Append AGENTS.md instructions to successful read tool results."""

    agents_store: AgentsAppendixDedupeStateStore
    _agents_context: RuntimeInstructionContext | None
    _agents_appendix_lock: asyncio.Lock
    _agents_missing_cache: dict[str, float]
    _runtime_agent_id: str
    _runtime_session_id: str

    def hooks(self) -> RuntimeHooks:
        """Register AGENTS.md appendix hook mapping."""
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
        async with self._agents_appendix_lock:
            self._agents_missing_cache.clear()
            await self._update_appendix_dedupe_state(
                lambda state: state.model_copy(update={"appended_paths": []})
            )

    async def append_agents_after_read(
        self,
        context: ToolCallHookContext,
        outcome: ToolCallHookOutcome,
    ) -> ToolOutputReplace | None:
        """Append applicable AGENTS.md instructions to successful read results."""
        if outcome.error is not None or not isinstance(outcome.output, str):
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
        instruction_context = self._agents_context
        if instruction_context is None:
            return None

        async with self._agents_appendix_lock:
            return await self._append_agents_after_read_locked(
                target_path=target_path,
                directory=refs[0].directory,
                output=outcome.output,
                instruction_context=instruction_context,
            )

    async def _append_agents_after_read_locked(
        self,
        *,
        target_path: str,
        directory: bool,
        output: str,
        instruction_context: RuntimeInstructionContext,
    ) -> ToolOutputReplace | None:
        """Discover and append AGENTS.md while holding the Session lock."""
        dedupe = await self._load_appendix_dedupe_state()
        already_appended = set(dedupe.appended_paths)
        candidates = _agents_appendix_candidates_for_path(
            target_path,
            instruction_context.projects,
            directory=directory,
        )
        dedupe_skipped_count = sum(1 for path in candidates if path in already_appended)
        candidates = [
            path
            for path in candidates
            if path != target_path and path not in already_appended
        ]
        files = await self._read_existing_agents_files(
            instruction_context.file_storage,
            candidates,
        )
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
                "dedupe_skipped_path_count": dedupe_skipped_count,
            },
        )
        return ToolOutputReplace(
            output_text=f"{output}\n\n{render_agents_appendix(files)}"
        )

    def register_agents_context(self, context: RuntimeInstructionContext) -> None:
        """Register runtime context for read-result appendices."""
        self._agents_context = context

    async def _read_existing_agents_files(
        self,
        file_storage: FileStorage,
        paths: Sequence[str],
    ) -> list[tuple[str, str]]:
        """Read existing AGENTS.md files in deterministic order."""
        files: list[tuple[str, str]] = []
        for path in paths:
            content = await self._read_agents_file(file_storage, path)
            if content is not None:
                files.append((path, content))
        return files

    async def _read_agents_file(
        self,
        file_storage: FileStorage,
        path: str,
    ) -> str | None:
        """Read AGENTS.md regular file from Runtime storage."""
        now = time.monotonic()
        missing_until = self._agents_missing_cache.get(path)
        if missing_until is not None:
            if missing_until > now:
                return None
            self._agents_missing_cache.pop(path, None)
        try:
            metadata = await file_storage.stat(path, agent_id=self._runtime_agent_id)
            if metadata.get("is_file") is not True:
                self._agents_missing_cache[path] = (
                    now + AGENTS_MISSING_CACHE_TTL_SECONDS
                )
                return None
            content = await file_storage.get(path, agent_id=self._runtime_agent_id)
        except FileNotFoundError:
            self._agents_missing_cache[path] = now + AGENTS_MISSING_CACHE_TTL_SECONDS
            return None
        return truncate_agents_content(content)

    async def _load_appendix_dedupe_state(self) -> AgentsAppendixDedupeState:
        """Fetch persistent AGENTS.md appendix dedupe state."""
        return await self.agents_store.load_appendix_dedupe(
            self._runtime_agent_id,
            self._runtime_session_id,
        )

    async def _update_appendix_dedupe_state(
        self,
        mutator: Callable[[AgentsAppendixDedupeState], AgentsAppendixDedupeState],
    ) -> None:
        """Retry-update persistent appendix dedupe state."""
        await self.agents_store.update_appendix_dedupe(
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
