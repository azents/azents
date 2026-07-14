"""Runtime Claude rules read-result appendix Toolkit."""

from __future__ import annotations

import dataclasses
import fnmatch
import logging
import posixpath
from collections.abc import Callable, Sequence
from typing import Any, Literal, Protocol

import frontmatter
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from yaml import YAMLError

from azents.core.tools import (
    ResolveContext,
    Toolkit,
    ToolkitProvider,
    ToolkitState,
    ToolkitStatus,
    TurnContext,
)
from azents.engine.hooks.types import (
    AfterToolCallHookContext,
    RuntimeHooks,
    SessionCompactHookContext,
    ToolOutputReplace,
)
from azents.engine.tooling.toolkit_state import (
    RunFencedToolkitStateStore,
    ToolkitStateHandle,
    ToolkitStateIdentity,
    ToolkitStateModel,
    ToolkitStateRunAuthority,
    ToolkitStateStore,
)
from azents.engine.tools.builtin_agents import (
    SESSION_WORKSPACE_ROOT,
    extract_tool_path_refs,
    project_for_path,
)
from azents.engine.tools.runtime_instruction_context import (
    RuntimeInstructionContext,
    RuntimeInstructionContextStore,
)
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.session_workspace_project.data import SessionWorkspaceProject
from azents.repos.toolkit_state import ToolkitStateRepository
from azents.services.file_storage import FileStorage
from azents.services.runtime_storage_error import RuntimeStorageError

logger = logging.getLogger(__name__)

CLAUDE_RULES_TOOLKIT_NAMESPACE = "claude_rules"
CLAUDE_RULES_APPENDIX_DEDUPE_TOOLKIT_STATE_NAME = "claude_rules_appendix_dedupe"
CLAUDE_RULES_DIR = ".claude/rules"
MAX_CLAUDE_RULE_BYTES = 64 * 1024


class ClaudeRulesAppendixDedupeState(ToolkitStateModel):
    """Claude rules read-result appendix dedupe Toolkit State payload."""

    schema_version: int = 1
    appended_paths: list[str] = Field(default_factory=list)


class ClaudeRulesAppendixDedupeStateStore(Protocol):
    """Claude rules appendix dedupe state store interface."""

    async def load_appendix_dedupe(
        self, agent_id: str, session_id: str
    ) -> ClaudeRulesAppendixDedupeState:
        """Fetch Claude rules appendix dedupe state."""
        ...

    async def update_appendix_dedupe(
        self,
        agent_id: str,
        session_id: str,
        *,
        run_id: str,
        owner_generation: int,
        mutator: Callable[
            [ClaudeRulesAppendixDedupeState], ClaudeRulesAppendixDedupeState
        ],
    ) -> None:
        """Retry-apply mutator to latest appendix dedupe state."""
        ...


class ToolkitClaudeRulesAppendixDedupeStateStore:
    """Claude rules appendix dedupe store based on Toolkit State."""

    def __init__(
        self,
        *,
        session_manager: SessionManager[AsyncSession],
        agent_run_repository: AgentRunRepository,
        agent_session_repository: AgentSessionRepository,
        toolkit_state_repository: ToolkitStateRepository,
    ) -> None:
        """Create Claude rules appendix dedupe store."""
        self._session_manager = session_manager
        self._agent_run_repository = agent_run_repository
        self._agent_session_repository = agent_session_repository
        self._toolkit_state_repository = toolkit_state_repository

    async def load_appendix_dedupe(
        self, agent_id: str, session_id: str
    ) -> ClaudeRulesAppendixDedupeState:
        """Fetch Claude rules appendix dedupe state."""
        async with self._session_manager() as session:
            handle = self._make_appendix_dedupe_handle(session, agent_id, session_id)
            if handle is None:
                return ClaudeRulesAppendixDedupeState()
            return await handle.load(default_factory=ClaudeRulesAppendixDedupeState)

    async def update_appendix_dedupe(
        self,
        agent_id: str,
        session_id: str,
        *,
        run_id: str,
        owner_generation: int,
        mutator: Callable[
            [ClaudeRulesAppendixDedupeState], ClaudeRulesAppendixDedupeState
        ],
    ) -> None:
        """Retry-apply mutator to latest appendix dedupe state."""
        async with self._session_manager() as session:
            handle = self._make_run_fenced_appendix_dedupe_handle(
                session,
                agent_id,
                session_id,
                ToolkitStateRunAuthority(
                    run_id=run_id,
                    owner_generation=owner_generation,
                ),
            )
            if handle is None:
                return
            await handle.update(
                default_factory=ClaudeRulesAppendixDedupeState,
                mutator=mutator,
            )

    def _make_appendix_dedupe_handle(
        self,
        session: AsyncSession,
        agent_id: str,
        session_id: str,
    ) -> ToolkitStateHandle[ClaudeRulesAppendixDedupeState] | None:
        """Create Claude rules appendix dedupe handle for agent/session identity."""
        if not agent_id or not session_id:
            return None
        identity = ToolkitStateIdentity(
            agent_id=agent_id,
            session_id=session_id,
            toolkit_namespace=CLAUDE_RULES_TOOLKIT_NAMESPACE,
            state_name=CLAUDE_RULES_APPENDIX_DEDUPE_TOOLKIT_STATE_NAME,
        )
        return ToolkitStateStore(
            session=session,
            repository=self._toolkit_state_repository,
        ).handle(
            identity,
            ClaudeRulesAppendixDedupeState,
        )

    def _make_run_fenced_appendix_dedupe_handle(
        self,
        session: AsyncSession,
        agent_id: str,
        session_id: str,
        run_authority: ToolkitStateRunAuthority,
    ) -> ToolkitStateHandle[ClaudeRulesAppendixDedupeState] | None:
        """Create an appendix handle that rejects stale runtime writes."""
        if not agent_id or not session_id:
            return None
        identity = ToolkitStateIdentity(
            agent_id=agent_id,
            session_id=session_id,
            toolkit_namespace=CLAUDE_RULES_TOOLKIT_NAMESPACE,
            state_name=CLAUDE_RULES_APPENDIX_DEDUPE_TOOLKIT_STATE_NAME,
        )
        return RunFencedToolkitStateStore(
            session=session,
            repository=self._toolkit_state_repository,
            run_authority=run_authority,
            agent_run_repository=self._agent_run_repository,
            agent_session_repository=self._agent_session_repository,
        ).handle(identity, ClaudeRulesAppendixDedupeState)


@dataclasses.dataclass(frozen=True)
class ClaudeRuleRoot:
    """Supported Claude rules source root."""

    owner_root: str
    rules_root: str
    kind: Literal["workspace", "project"]


@dataclasses.dataclass(frozen=True)
class ClaudeRuleFile:
    """Loaded Claude rule file ready for rendering."""

    path: str
    real_path: str
    content: str


class ClaudeRulesToolkitConfig(BaseModel):
    """Claude rules Toolkit settings model."""


class ClaudeRulesToolkit(Toolkit[ClaudeRulesToolkitConfig]):
    """Auto-bound Toolkit that appends matching Claude rules after reads."""

    def __init__(
        self,
        *,
        store: ClaudeRulesAppendixDedupeStateStore,
        agent_id: str = "",
        session_id: str = "",
    ) -> None:
        """Create Claude rules Toolkit."""
        self._store = store
        self._agent_id = agent_id
        self._session_id = session_id
        self._runtime_agent_id = agent_id
        self._runtime_session_id = session_id
        self._instruction_context_store: RuntimeInstructionContextStore | None = None

    def set_agent_id(self, agent_id: str) -> None:
        """Inject agent_id."""
        self._agent_id = agent_id
        self._runtime_agent_id = agent_id

    def set_session_id(self, session_id: str) -> None:
        """Inject session_id."""
        self._session_id = session_id
        self._runtime_session_id = session_id

    def set_runtime_agent_id(self, agent_id: str) -> None:
        """Specify agent_id used for Runtime file operations."""
        self._runtime_agent_id = agent_id

    def set_runtime_session_id(self, session_id: str) -> None:
        """Specify session_id used for Runtime-scoped dedupe state."""
        self._runtime_session_id = session_id

    def set_instruction_context_store(
        self, store: RuntimeInstructionContextStore
    ) -> None:
        """Register shared Runtime instruction context store."""
        self._instruction_context_store = store

    def hooks(self) -> RuntimeHooks:
        """Register Claude rules appendix hooks."""
        return {
            "on_after_tool_call": self._on_after_tool_call_hook,
            "on_session_compact": self._on_session_compact_hook,
        }

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Expose no model-visible tools while keeping hooks active."""
        del context
        return ToolkitState(status=ToolkitStatus.ENABLED, tools=[])

    async def _on_after_tool_call_hook(
        self, context: AfterToolCallHookContext
    ) -> ToolOutputReplace | None:
        """Append applicable Claude rules after successful read."""
        if context.error_message is not None or context.output_text is None:
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
        instruction_context = self._instruction_context()
        if instruction_context is None:
            return None

        try:
            files = await self._matching_not_yet_appended_rules(
                instruction_context,
                target_path,
            )
        except RuntimeStorageError:
            logger.exception(
                "Failed to load Claude rules appendix candidates",
                extra={
                    "agent_id": self._runtime_agent_id,
                    "session_id": self._runtime_session_id,
                },
            )
            return None
        if not files:
            return None
        await self._update_appendix_dedupe_state(
            run_id=context.run_id,
            owner_generation=context.owner_generation,
            mutator=lambda state: state.model_copy(
                update={
                    "appended_paths": sorted(
                        set(state.appended_paths) | {rule.path for rule in files}
                    )
                }
            ),
        )
        logger.info(
            "Appended Claude rules to read result",
            extra={
                "agent_id": self._runtime_agent_id,
                "session_id": self._runtime_session_id,
                "appended_path_count": len(files),
            },
        )
        return ToolOutputReplace(
            output_text=(
                f"{context.output_text}\n\n{render_claude_rules_appendix(files)}"
            )
        )

    async def _on_session_compact_hook(
        self, context: SessionCompactHookContext
    ) -> None:
        """Clear Claude rules appendix dedupe on compaction."""
        await self._update_appendix_dedupe_state(
            run_id=context.run_id,
            owner_generation=context.owner_generation,
            mutator=lambda state: state.model_copy(update={"appended_paths": []}),
        )

    def _instruction_context(self) -> RuntimeInstructionContext | None:
        store = self._instruction_context_store
        if store is None:
            return None
        return store.get()

    async def _matching_not_yet_appended_rules(
        self,
        instruction_context: RuntimeInstructionContext,
        target_path: str,
    ) -> list[ClaudeRuleFile]:
        dedupe = await self._load_appendix_dedupe_state()
        already_appended = set(dedupe.appended_paths)
        roots = claude_rule_roots_for_path(target_path, instruction_context.projects)
        discovered = await discover_claude_rule_files(
            instruction_context.file_storage,
            roots,
            agent_id=self._runtime_agent_id,
        )
        return [
            rule
            for rule in discovered
            if rule.path != target_path
            and rule.path not in already_appended
            and rule_matches_target(rule.content, rule.path, roots, target_path)
        ]

    async def _load_appendix_dedupe_state(self) -> ClaudeRulesAppendixDedupeState:
        """Fetch persistent Claude rules appendix dedupe state."""
        return await self._store.load_appendix_dedupe(
            self._runtime_agent_id,
            self._runtime_session_id,
        )

    async def _update_appendix_dedupe_state(
        self,
        *,
        run_id: str,
        owner_generation: int,
        mutator: Callable[
            [ClaudeRulesAppendixDedupeState], ClaudeRulesAppendixDedupeState
        ],
    ) -> None:
        """Retry-update persistent appendix dedupe state."""
        await self._store.update_appendix_dedupe(
            self._runtime_agent_id,
            self._runtime_session_id,
            run_id=run_id,
            owner_generation=owner_generation,
            mutator=mutator,
        )


class ClaudeRulesToolkitProvider(ToolkitProvider[ClaudeRulesToolkitConfig]):
    """Claude rules Toolkit provider always injected with runtime tools."""

    slug = CLAUDE_RULES_TOOLKIT_NAMESPACE
    name = "Claude Rules"
    description = "Append matching .claude/rules instructions after reads"
    system_prompt = ""
    config_model = ClaudeRulesToolkitConfig

    def __init__(self, *, store: ClaudeRulesAppendixDedupeStateStore) -> None:
        """Create Claude rules Toolkit provider."""
        self._store = store

    async def resolve(
        self,
        config: ClaudeRulesToolkitConfig,
        context: ResolveContext,
    ) -> Toolkit[ClaudeRulesToolkitConfig]:
        """Return executable Claude rules Toolkit."""
        del config
        return ClaudeRulesToolkit(
            store=self._store,
            agent_id=context.agent_id,
            session_id=context.session_id,
        )


def claude_rule_roots_for_path(
    target_path: str,
    projects: Sequence[SessionWorkspaceProject],
) -> list[ClaudeRuleRoot]:
    """Return supported Claude rule roots applicable to target path."""
    normalized = _normalize_runtime_path(target_path)
    if normalized is None or not _is_under_workspace_root(normalized):
        return []
    roots = [
        ClaudeRuleRoot(
            owner_root=SESSION_WORKSPACE_ROOT,
            rules_root=posixpath.join(SESSION_WORKSPACE_ROOT, CLAUDE_RULES_DIR),
            kind="workspace",
        )
    ]
    project = project_for_path(normalized, projects)
    if project is not None:
        project_path = posixpath.normpath(project.path)
        roots.append(
            ClaudeRuleRoot(
                owner_root=project_path,
                rules_root=posixpath.join(project_path, CLAUDE_RULES_DIR),
                kind="project",
            )
        )
    return roots


async def discover_claude_rule_files(
    file_storage: FileStorage,
    roots: Sequence[ClaudeRuleRoot],
    *,
    agent_id: str,
) -> list[ClaudeRuleFile]:
    """Discover and load Claude rules under supported roots."""
    files: list[ClaudeRuleFile] = []
    seen_real_paths: set[str] = set()
    for root in roots:
        paths = await _list_rule_paths(file_storage, root, agent_id=agent_id)
        for path in paths:
            rule = await _read_rule_file(file_storage, root, path, agent_id=agent_id)
            if rule is None or rule.real_path in seen_real_paths:
                continue
            seen_real_paths.add(rule.real_path)
            files.append(rule)
    return files


async def _list_rule_paths(
    file_storage: FileStorage,
    root: ClaudeRuleRoot,
    *,
    agent_id: str,
) -> list[str]:
    try:
        entries = await file_storage.list(
            root.rules_root,
            agent_id=agent_id,
            recursive=True,
            include_directories=False,
        )
    except FileNotFoundError:
        return []
    paths: list[str] = []
    for entry in entries:
        path = _normalize_runtime_path(entry.uri)
        if path is None or not path.endswith(".md"):
            continue
        paths.append(path)
    return sorted(paths)


async def _read_rule_file(
    file_storage: FileStorage,
    root: ClaudeRuleRoot,
    path: str,
    *,
    agent_id: str,
) -> ClaudeRuleFile | None:
    try:
        metadata = await file_storage.stat(path, agent_id=agent_id)
        if metadata.get("is_file") is not True:
            return None
        real_path = _metadata_real_path(metadata, path)
        if not _is_under_root(real_path, root.owner_root):
            return None
        content = await file_storage.get(path, agent_id=agent_id)
    except FileNotFoundError:
        return None
    try:
        rendered = truncate_claude_rule_content(content)
    except UnicodeDecodeError:
        return None
    return ClaudeRuleFile(path=path, real_path=real_path, content=rendered)


def _metadata_real_path(metadata: dict[str, object], path: str) -> str:
    value = metadata.get("real_path")
    if isinstance(value, str) and value.strip():
        return posixpath.normpath(value)
    return posixpath.normpath(path)


def truncate_claude_rule_content(content: bytes) -> str:
    """Limit Claude rule content to prompt-safe size."""
    content.decode("utf-8")
    data = content[:MAX_CLAUDE_RULE_BYTES]
    text = data.decode("utf-8", errors="replace")
    if len(content) > MAX_CLAUDE_RULE_BYTES:
        text += "\n\n... (Claude rule truncated)"
    return text


def rule_matches_target(
    content: str,
    rule_path: str,
    roots: Sequence[ClaudeRuleRoot],
    target_path: str,
) -> bool:
    """Return whether one rule file applies to target path."""
    root = _root_for_rule_path(rule_path, roots)
    if root is None:
        return False
    metadata = _parse_frontmatter(content)
    if metadata is None:
        return False
    paths_value = metadata.get("paths")
    if paths_value is None:
        return _is_under_root(target_path, root.owner_root)
    patterns = _coerce_paths_value(paths_value)
    if patterns is None:
        return False
    return any(
        _glob_matches(pattern, target_path, owner_root=root.owner_root)
        for pattern in patterns
    )


def _root_for_rule_path(
    rule_path: str,
    roots: Sequence[ClaudeRuleRoot],
) -> ClaudeRuleRoot | None:
    for root in roots:
        if _is_under_root(rule_path, root.rules_root):
            return root
    return None


def _parse_frontmatter(content: str) -> dict[str, Any] | None:
    try:
        post = frontmatter.loads(content)
    except YAMLError:
        return None
    return {str(key): value for key, value in post.metadata.items()}


def _coerce_paths_value(value: object) -> list[str] | None:
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else None
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        patterns = [item.strip() for item in value if item.strip()]
        return patterns or None
    return None


def _glob_matches(pattern: str, target_path: str, *, owner_root: str) -> bool:
    normalized_target = posixpath.normpath(target_path)
    normalized_owner = posixpath.normpath(owner_root)
    if pattern.startswith("/"):
        pattern_path = posixpath.normpath(pattern)
        pattern_segments = _path_segments(pattern_path.lstrip("/"))
        target_segments = _path_segments(normalized_target.lstrip("/"))
        return _match_segments(pattern_segments, target_segments)
    if not _is_under_root(normalized_target, normalized_owner):
        return False
    rel_target = _relative_to_root(normalized_target, normalized_owner)
    pattern_segments = _path_segments(posixpath.normpath(pattern))
    target_segments = _path_segments(rel_target)
    return _match_segments(pattern_segments, target_segments)


def _match_segments(
    pattern_segments: Sequence[str], target_segments: Sequence[str]
) -> bool:
    if not pattern_segments:
        return not target_segments
    head = pattern_segments[0]
    rest = pattern_segments[1:]
    if head == "**":
        if _match_segments(rest, target_segments):
            return True
        return bool(target_segments) and _match_segments(
            pattern_segments, target_segments[1:]
        )
    if not target_segments:
        return False
    if not fnmatch.fnmatchcase(target_segments[0], head):
        return False
    return _match_segments(rest, target_segments[1:])


def _path_segments(path: str) -> tuple[str, ...]:
    if path in ("", "."):
        return ()
    return tuple(segment for segment in path.split("/") if segment and segment != ".")


def _relative_to_root(path: str, root: str) -> str:
    normalized = posixpath.normpath(path)
    normalized_root = posixpath.normpath(root)
    if normalized == normalized_root:
        return ""
    return normalized[len(normalized_root) + 1 :]


def _is_under_root(path: str, root: str) -> bool:
    normalized = posixpath.normpath(path)
    normalized_root = posixpath.normpath(root)
    return normalized == normalized_root or normalized.startswith(f"{normalized_root}/")


def _base_tool_name(tool_name: str) -> str:
    """Return unprefixed tool name."""
    if "__" not in tool_name:
        return tool_name
    return tool_name.split("__", 1)[1]


def _is_under_workspace_root(path: str) -> bool:
    """Return whether path is inside the agent workspace root."""
    return _is_under_root(path, SESSION_WORKSPACE_ROOT)


def _normalize_runtime_path(path: str) -> str | None:
    """POSIX-normalize runtime absolute path."""
    stripped = path.strip()
    if not stripped:
        return None
    normalized = posixpath.normpath(stripped)
    if not normalized.startswith("/"):
        return None
    return normalized


def render_claude_rules_appendix(files: Sequence[ClaudeRuleFile]) -> str:
    """Render Claude rules as a read result appendix."""
    if not files:
        return ""
    parts = [
        "<system-reminder>",
        "Relevant Claude rules for the accessed path:",
    ]
    for file in files:
        parts.extend(["", f"### {file.path}", "", file.content])
    parts.append("</system-reminder>")
    return "\n".join(parts)
