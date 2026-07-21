"""Builtin tool factory.

Creates runtime process/file tools injected into agents with Builtin Toolkit.
Each runtime-backed tool runs through Agent Runtime Runner operation.
"""

import asyncio
import dataclasses
import logging
import shlex
import time
from collections.abc import Awaitable, Callable, Sequence
from collections.abc import Set as AbstractSet
from contextvars import ContextVar, Token
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from textwrap import dedent
from typing import NoReturn, Protocol

from azcommon.types import JSONObject
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeDesiredState,
    RuntimeLifecycleCommandType,
    RuntimeProviderConnectionState,
    RuntimeProviderObservedState,
    RuntimeRunnerState,
)
from azents.core.tools import (
    ProfiledToolkitPrompt,
    ResolveContext,
    ShellToolkitConfig,
    Toolkit,
    ToolkitProvider,
    ToolkitState,
    ToolkitStatus,
    TurnContext,
)
from azents.engine.events.engine_events import (
    EngineEvent,
    RuntimeProcessOutputDeltaEvent,
    RuntimeReadyEvent,
)
from azents.engine.io.attachments import RuntimeAttachment
from azents.engine.run.client_tool_compatibility import ClientToolProfile
from azents.engine.run.types import (
    FunctionTool,
    FunctionToolCancelRequest,
    FunctionToolError,
    FunctionToolResult,
)
from azents.engine.tooling.make_tool import make_tool
from azents.engine.tools.apply_patch import (
    GPT_V4A_APPLY_PATCH_PROMPT,
    GPT_V4A_PLAINTEXT_CUSTOM_APPLY_PATCH_PROMPT,
    RuntimePatchTarget,
    make_apply_patch_tool,
)
from azents.engine.tools.builtin_agents import (
    AgentsAppendixDedupeStateStore,
    AgentsAppendixMixin,
)
from azents.engine.tools.delete_file import make_delete_file_tool
from azents.engine.tools.edit import RuntimeEditTarget, make_edit_tool
from azents.engine.tools.glob import make_glob_tool
from azents.engine.tools.grep import make_grep_tool
from azents.engine.tools.import_file import make_import_file_tool
from azents.engine.tools.memory import (
    make_delete_memory_tool,
    make_get_memory_tool,
    make_list_memories_tool,
    make_save_memory_tool,
    make_search_memories_tool,
)
from azents.engine.tools.present_file import make_present_file_tool
from azents.engine.tools.read_image import make_read_image_tool
from azents.engine.tools.read_text import make_read_text_tool
from azents.engine.tools.runtime_instruction_context import (
    RuntimeInstructionContext,
    RuntimeInstructionContextStore,
)
from azents.engine.tools.runtime_io import (
    RuntimeFileListEntry,
    RuntimeFileStatResult,
    RuntimeGrepFileMatch,
    RuntimeGrepLineMatch,
    RuntimeProcessOutputDelta,
    RuntimeProcessResult,
    RuntimeRunnerOperationClient,
    RuntimeRunnerOperationFailedError,
    RuntimeRunnerOperationGenerationError,
    RuntimeRunnerOperationUnavailable,
)
from azents.engine.tools.write import make_write_tool
from azents.rdb.session import SessionManager
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.memory import MemoryRepository
from azents.repos.memory.data import MemorySummary
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.session_workspace_project.data import SessionWorkspaceProject
from azents.runtime.types import RuntimeDomainConfig
from azents.services.artifact import ArtifactService
from azents.services.exchange_file import ExchangeFileService
from azents.services.file_storage import (
    FileStorage,
    GrepFileMatch,
    GrepLineMatch,
    GrepResult,
)
from azents.services.model_file import ModelFileService
from azents.services.runtime_storage_error import (
    RuntimeStorageError,
)
from azents.services.session_storage import guess_media_type
from azents.services.vfs import VfsProjectionService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Memory prompt
# ---------------------------------------------------------------------------

_MEMORY_READ_RULES_PROMPT = dedent("""\
    ### Memory Rules

    Use the loaded memory summaries as the primary index. Call `get_memory` directly when a likely candidate is visible; use `list_memories` or `search_memories` only for discovery.

    #### Memory lookup

    `search_memories` returns exact all-term matches when possible and otherwise returns ranked partial matches.

    #### Types of memory

    **user** — User's role, expertise, preferences.
    - Scope: Always `user`.

    **feedback** — Behavioral corrections AND confirmations.
    - Scope: Personal preference → `user`. Team rule → `agent`.
    - Body: Lead with the rule, then **Why:** and **When to apply:** lines.

    **project** — Ongoing work, decisions, deadlines.
    - Scope: Team context → `agent`. Personal work → `user`.
    - Always convert relative dates to absolute dates.

    **reference** — Pointers to external systems.
    - Scope: Almost always `agent`.

    #### Scope selection

    - `agent` scope: team-wide knowledge shared with ALL users of this agent.
    - `user` scope: personal preferences and context only for this specific user.

    When Agent and User memories conflict on the same topic, follow the User memory because it represents this user's specific preference.

    Memories are snapshots from when they were written. Before acting on a memory, verify it against current state. If stale, avoid relying on it.""")  # noqa: E501

_MEMORY_WRITE_RULES_PROMPT = dedent("""\
    ### Memory Write Rules

    Use `save_memory` to store durable information and `delete_memory` to remove stale or unwanted memories.

    If the user explicitly asks you to remember something, save it immediately using the memory type and scope guidance from Memory Rules. If they ask you to forget something, use `delete_memory` to remove the relevant entry.

    #### What NOT to save

    - Code patterns, architecture, file paths — read from code directly
    - Git history — use git log/blame
    - Ephemeral task details only useful in this conversation

    #### Duplicate prevention

    Before saving, compare against the loaded summaries and search candidates. Reuse the same `name` when existing memory represents the same information. An empty search result alone does not prove that no memory exists.""")  # noqa: E501

_MAX_MEMORY_SUMMARIES = 100


async def collect_memory_prompt(
    repo: MemoryRepository,
    session: AsyncSession,
    agent_id: str,
    user_id: str,
    rules_prompt: str,
) -> str:
    """Look up memory summaries from DB and create prompt string.

    When index is absent, return only rules. When agent_id or user_id is empty,
    omit that section.
    """
    parts: list[str] = [
        "## Memories",
        "",
        "You have a persistent memory system. Memories persist across conversations.",
        "",
    ]

    agent_summaries: list[MemorySummary] = []
    user_summaries: list[MemorySummary] = []

    if agent_id:
        agent_summaries = await repo.list_summaries(
            session,
            agent_id=agent_id,
            user_id=None,
        )
    if user_id:
        user_summaries = await repo.list_summaries(
            session,
            agent_id=agent_id,
            user_id=user_id,
        )

    if agent_summaries:
        parts.extend(["### Agent Memories (shared with all users)", ""])
        parts.extend(_format_summaries(agent_summaries))
        if len(agent_summaries) >= _MAX_MEMORY_SUMMARIES:
            parts.append(
                f"(Showing {_MAX_MEMORY_SUMMARIES} memories. "
                "Consider cleaning up old memories with delete_memory.)"
            )
        parts.append("")

    if user_summaries:
        parts.extend(["### Your Memories about this User", ""])
        parts.extend(_format_summaries(user_summaries))
        if len(user_summaries) >= _MAX_MEMORY_SUMMARIES:
            parts.append(
                f"(Showing {_MAX_MEMORY_SUMMARIES} memories. "
                "Consider cleaning up old memories with delete_memory.)"
            )
        parts.append("")

    parts.append(rules_prompt)
    return "\n".join(parts)


def _format_summaries(summaries: list[MemorySummary]) -> list[str]:
    """Group by type and create text similar to the existing MEMORIES.md format."""
    by_type: dict[str, list[MemorySummary]] = {}
    for s in summaries:
        by_type.setdefault(s.type, []).append(s)

    lines: list[str] = []
    for mem_type in sorted(by_type):
        group = by_type.get(mem_type)
        if not group:
            continue
        lines.append(f"#### {mem_type.title()}")
        for m in group:
            lines.append(f"- **{m.name}** — {m.description}")
        lines.append("")
    return lines


# Error message passed to agent on Runtime connection failure
_RUNTIME_UNAVAILABLE_MSG = (
    "Runtime is temporarily unavailable. Please try again in a moment."
)
_RUNTIME_STARTING_MSG = "Runtime is still starting. Please try again in a moment."
_RUNTIME_PROVIDER_DISCONNECTED_MSG = (
    "Runtime Provider is disconnected. Please try again in a moment."
)
_RUNNABLE_PROVIDER_STATES = frozenset(
    {
        RuntimeProviderObservedState.RUNNING,
    }
)

_RUNTIME_READY_WAIT_TIMEOUT_SECONDS = 120.0
_RUNTIME_READY_POLL_INTERVAL_SECONDS = 1.0
_RUNTIME_OPERATION_RESULT_GRACE_SECONDS = 10
_RUNTIME_FILE_OPERATION_TIMEOUT_SECONDS = 120
_RUNTIME_PROCESS_TERMINATE_TIMEOUT_SECONDS = 10
_MIN_PROCESS_YIELD_TIME_MS = 250
_DEFAULT_PROCESS_YIELD_TIME_MS = 10_000
_MAX_PROCESS_YIELD_TIME_MS = 30_000
_DEFAULT_PROCESS_WRITE_YIELD_TIME_MS = 250
_DEFAULT_PROCESS_EMPTY_POLL_YIELD_TIME_MS = 5_000
_MAX_PROCESS_EMPTY_POLL_YIELD_TIME_MS = 300_000
_DEFAULT_PROCESS_MAX_OUTPUT_BYTES = 64 * 1024
_MAX_PROCESS_MAX_OUTPUT_BYTES = 4 * 1024 * 1024


# ---------------------------------------------------------------------------
# Input models
# ---------------------------------------------------------------------------


class ExecCommandInput(BaseModel):
    """exec_command tool input."""

    command: str = Field(description="Shell command to execute")
    workdir: str | None = Field(
        default=None,
        description="Working directory. Defaults to /workspace/agent/.",
    )
    yield_time_ms: int = Field(
        default=_DEFAULT_PROCESS_YIELD_TIME_MS,
        ge=_MIN_PROCESS_YIELD_TIME_MS,
        le=_MAX_PROCESS_YIELD_TIME_MS,
        description=(
            "How long to wait for process output before yielding, in milliseconds. "
            "Defaults to 10000 ms; accepted range is 250-30000 ms."
        ),
    )
    max_output_bytes: int = Field(
        default=_DEFAULT_PROCESS_MAX_OUTPUT_BYTES,
        ge=1,
        le=_MAX_PROCESS_MAX_OUTPUT_BYTES,
        description="Maximum stdout/stderr bytes to return in this tool result.",
    )


class WriteStdinInput(BaseModel):
    """write_stdin tool input."""

    process_id: str = Field(description="Process ID returned by exec_command")
    chars: str = Field(
        default="",
        description="Characters to write to stdin. Empty string polls for output.",
    )
    yield_time_ms: int = Field(
        default=_DEFAULT_PROCESS_WRITE_YIELD_TIME_MS,
        ge=0,
        le=_MAX_PROCESS_EMPTY_POLL_YIELD_TIME_MS,
        description=(
            "How long to wait for process output before yielding, in milliseconds. "
            "Zero returns currently buffered output immediately. Non-empty writes "
            "default to 250 ms and cap at 30000 ms; empty polls default to 5000 ms "
            "and cap at 300000 ms."
        ),
    )
    max_output_bytes: int = Field(
        default=_DEFAULT_PROCESS_MAX_OUTPUT_BYTES,
        ge=1,
        le=_MAX_PROCESS_MAX_OUTPUT_BYTES,
        description="Maximum stdout/stderr bytes to return in this tool result.",
    )

    @model_validator(mode="before")
    @classmethod
    def _default_empty_poll_yield_time(cls, data: object) -> object:
        if not isinstance(data, dict) or "yield_time_ms" in data:
            return data
        if data.get("chars", "") != "":
            return data
        return {**data, "yield_time_ms": _DEFAULT_PROCESS_EMPTY_POLL_YIELD_TIME_MS}

    @model_validator(mode="after")
    def _validate_yield_time_range(self) -> "WriteStdinInput":
        if self.chars != "" and self.yield_time_ms > _MAX_PROCESS_YIELD_TIME_MS:
            msg = "non-empty write yield_time_ms must be at most 30000"
            raise ValueError(msg)
        return self


# ---------------------------------------------------------------------------
# Toolkit Provider
# ---------------------------------------------------------------------------


class MemoryReadToolkit(Toolkit[ShellToolkitConfig]):
    """Auto-bound memory read capability."""

    def __init__(
        self,
        config: ShellToolkitConfig,
        agent_id: str,
        session_manager: SessionManager[AsyncSession],
        memory_repo: MemoryRepository,
    ) -> None:
        self._config = config
        self._agent_id = agent_id
        self._session_id = ""
        self.session_manager = session_manager
        self.memory_repo = memory_repo

    def set_agent_id(self, agent_id: str) -> None:
        """Inject agent_id.

        :param agent_id: Agent ID
        """
        self._agent_id = agent_id

    def set_session_id(self, session_id: str) -> None:
        """Inject session ID.

        :param session_id: Current session ID
        """
        self._session_id = session_id

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Return memory read tools."""
        user_id = context.user_id
        tools: list[FunctionTool] = []
        if self._config.memory_enabled:
            tools.extend(
                [
                    make_list_memories_tool(
                        self.memory_repo,
                        self._agent_id,
                        user_id,
                        self.session_manager,
                    ),
                    make_get_memory_tool(
                        self.memory_repo,
                        self._agent_id,
                        user_id,
                        self.session_manager,
                    ),
                    make_search_memories_tool(
                        self.memory_repo,
                        self._agent_id,
                        user_id,
                        self.session_manager,
                    ),
                ]
            )
        return ToolkitState(status=ToolkitStatus.ENABLED, tools=tools)

    async def get_dynamic_prompt(self, context: TurnContext) -> str:
        """Return dynamic memory read prompt for the current turn."""
        if not self._config.memory_enabled:
            return ""
        async with self.session_manager() as mem_session:
            return await collect_memory_prompt(
                self.memory_repo,
                mem_session,
                self._agent_id,
                context.user_id or "",
                _MEMORY_READ_RULES_PROMPT,
            )


class MemoryWriteToolkit(Toolkit[ShellToolkitConfig]):
    """Auto-bound memory write capability."""

    def __init__(
        self,
        config: ShellToolkitConfig,
        agent_id: str,
        session_manager: SessionManager[AsyncSession],
        memory_repo: MemoryRepository,
    ) -> None:
        self._config = config
        self._agent_id = agent_id
        self._session_id = ""
        self.session_manager = session_manager
        self.memory_repo = memory_repo

    def set_agent_id(self, agent_id: str) -> None:
        """Inject agent_id.

        :param agent_id: Agent ID
        """
        self._agent_id = agent_id

    def set_session_id(self, session_id: str) -> None:
        """Inject session ID.

        :param session_id: Current session ID
        """
        self._session_id = session_id

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Return memory write tools."""
        user_id = context.user_id
        tools: list[FunctionTool] = []
        if self._config.memory_enabled:
            tools.extend(
                [
                    make_save_memory_tool(
                        self.memory_repo,
                        self._agent_id,
                        user_id,
                        self.session_manager,
                    ),
                    make_delete_memory_tool(
                        self.memory_repo,
                        self._agent_id,
                        user_id,
                        self.session_manager,
                    ),
                ]
            )
        return ToolkitState(status=ToolkitStatus.ENABLED, tools=tools)

    async def get_dynamic_prompt(self, context: TurnContext) -> str:
        """Return memory write rules for the current turn."""
        del context
        if not self._config.memory_enabled:
            return ""
        return _MEMORY_WRITE_RULES_PROMPT


class BuiltinToolkit(Toolkit[ShellToolkitConfig]):
    """Default builtin tool execution instance independent of Runtime Runner.

    Currently responsible for persistent memory tools and memory prompt. Tools
    depending on Runtime Runner, such as shell/file, are handled by
    :class:`RuntimeToolkit`.
    """

    def __init__(
        self,
        config: ShellToolkitConfig,
        agent_id: str,
        session_manager: SessionManager[AsyncSession],
        memory_repo: MemoryRepository,
    ) -> None:
        self._config = config
        self._agent_id = agent_id
        self._session_id = ""
        self.session_manager = session_manager
        self.memory_repo = memory_repo

    def set_agent_id(self, agent_id: str) -> None:
        """Inject agent_id.

        :param agent_id: Agent ID
        """
        self._agent_id = agent_id

    def set_session_id(self, session_id: str) -> None:
        """Inject session ID.

        :param session_id: Current session ID
        """
        self._session_id = session_id

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Return builtin tools independent of Runtime Runner."""
        config = self._config
        agent_id = self._agent_id
        user_id = context.user_id

        tools: list[FunctionTool] = []
        if config.memory_enabled:
            tools.extend(
                [
                    make_save_memory_tool(
                        self.memory_repo,
                        agent_id,
                        user_id,
                        self.session_manager,
                    ),
                    make_list_memories_tool(
                        self.memory_repo,
                        agent_id,
                        user_id,
                        self.session_manager,
                    ),
                    make_get_memory_tool(
                        self.memory_repo,
                        agent_id,
                        user_id,
                        self.session_manager,
                    ),
                    make_search_memories_tool(
                        self.memory_repo,
                        agent_id,
                        user_id,
                        self.session_manager,
                    ),
                    make_delete_memory_tool(
                        self.memory_repo,
                        agent_id,
                        user_id,
                        self.session_manager,
                    ),
                ]
            )

        return ToolkitState(status=ToolkitStatus.ENABLED, tools=tools)

    async def get_dynamic_prompt(self, context: TurnContext) -> str:
        """Return dynamic memory prompt for the current turn."""
        config = self._config
        if not config.memory_enabled:
            return ""
        async with self.session_manager() as mem_session:
            return await collect_memory_prompt(
                self.memory_repo,
                mem_session,
                self._agent_id,
                context.user_id or "",
                f"{_MEMORY_READ_RULES_PROMPT}\n\n{_MEMORY_WRITE_RULES_PROMPT}",
            )


class RuntimeEnvProvider(Protocol):
    """Runtime shell env provider protocol."""

    async def expose_env(self) -> dict[str, str]:
        """Return env vars to inject into runtime shell commands."""
        ...


class RuntimeToolkit(AgentsAppendixMixin, Toolkit[ShellToolkitConfig]):
    """Runtime Runner dependent shell/file tool execution instance."""

    def __init__(
        self,
        config: ShellToolkitConfig,
        exchange_file_service: ExchangeFileService,
        artifact_service: ArtifactService,
        model_file_service: ModelFileService,
        vfs_projection_service: VfsProjectionService | None,
        agent_id: str,
        agents_store: AgentsAppendixDedupeStateStore,
        runner_operations: RuntimeRunnerOperationClient,
        session_manager: SessionManager[AsyncSession],
        agent_runtime_repo: AgentRuntimeRepository,
        project_repo: SessionWorkspaceProjectRepository,
    ) -> None:
        self._config = config
        self.runner_operations = runner_operations
        self.exchange_file_service = exchange_file_service
        self.artifact_service = artifact_service
        self.model_file_service = model_file_service
        self.vfs_projection_service = vfs_projection_service
        self._agent_id = agent_id
        self._runtime_agent_id = agent_id
        self._session_id: str = ""
        self._runtime_session_id: str = ""
        self._excluded_tools: AbstractSet[str] = frozenset()
        self._peer_toolkits: Sequence[RuntimeEnvProvider] = ()
        self.session_manager = session_manager
        self.agent_runtime_repo = agent_runtime_repo
        self.project_repo = project_repo
        self.agents_store = agents_store
        self._agents_context: RuntimeInstructionContext | None = None
        self._agents_appendix_lock = asyncio.Lock()
        self._agents_missing_cache: dict[str, float] = {}
        self.instruction_context_store: RuntimeInstructionContextStore | None = None

    def set_instruction_context_store(
        self, store: RuntimeInstructionContextStore
    ) -> None:
        """Register shared Runtime instruction context store."""
        self.instruction_context_store = store

    def set_peer_toolkits(self, peers: Sequence[RuntimeEnvProvider]) -> None:
        """Register peer toolkits that collect env during Shell execution.

        :param peers: Active toolkit instance list, excluding RuntimeToolkit itself
        """
        self._peer_toolkits = peers

    def set_agent_id(self, agent_id: str) -> None:
        """Inject agent_id.

        ResolveContext has no agent_id, so separate injection is needed after resolve.
        runtime_agent_id is also updated.

        :param agent_id: Agent ID
        """
        self._agent_id = agent_id
        self._runtime_agent_id = agent_id

    def set_runtime_agent_id(self, agent_id: str) -> None:
        """Specify separate agent_id for Runtime operation.

        Shell/file tools find runtime by this ID.

        :param agent_id: Agent ID for runtime operation (parent agent_id)
        """
        self._runtime_agent_id = agent_id

    def set_session_id(self, session_id: str) -> None:
        """Inject session ID.

        :param session_id: Current session ID
        """
        self._session_id = session_id
        self._runtime_session_id = session_id

    def set_runtime_session_id(self, session_id: str) -> None:
        """Specify separate session_id for Runtime operation.

        Use when runtime operations need a separate session identifier.
        """
        self._runtime_session_id = session_id

    def set_excluded_tools(self, names: AbstractSet[str]) -> None:
        """Set tool names to exclude from update_context().

        :param names: Set of tool names to exclude (set or frozenset)
        """
        self._excluded_tools = names

    def get_runtime_domain_config(self) -> RuntimeDomainConfig:
        """Return Runtime domain settings.

        Used by shell/file tools to reuse the same domain policy.

        :return: Domain allow/block settings
        """
        return RuntimeDomainConfig(
            allowed_domains=tuple(self._config.allowed_domains),
            denied_domains=tuple(self._config.denied_domains),
        )

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Create shell and file tools and return prompt.

        :param context: Context passed each turn
        :return: Current state (tools + prompt)
        """
        agent_id = self._agent_id
        runtime_agent_id = self._runtime_agent_id
        user_id = context.user_id

        file_ss = RuntimeRunnerFileStorage(
            runner_operations=self.runner_operations,
            agent_runtime_repo=self.agent_runtime_repo,
            session_manager=self.session_manager,
            runtime_agent_id=runtime_agent_id,
            owner_session_id=self._runtime_session_id,
        )

        async def resolve_patch_target() -> RuntimePatchTarget:
            runtime = await _ready_runtime_for_agent(
                agent_runtime_repo=self.agent_runtime_repo,
                session_manager=self.session_manager,
                agent_id=runtime_agent_id,
            )
            return RuntimePatchTarget(
                runtime_id=runtime.id,
                runner_generation=runtime.runner_generation,
            )

        async def resolve_edit_target() -> RuntimeEditTarget:
            runtime = await _ready_runtime_for_agent(
                agent_runtime_repo=self.agent_runtime_repo,
                session_manager=self.session_manager,
                agent_id=runtime_agent_id,
            )
            return RuntimeEditTarget(
                runtime_id=runtime.id,
                runner_generation=runtime.runner_generation,
            )

        apply_patch_tool = make_apply_patch_tool(
            runner_operations=self.runner_operations,
            resolve_runtime_target=resolve_patch_target,
            owner_session_id=self._runtime_session_id,
            agent_id=runtime_agent_id,
        )
        edit_tool = make_edit_tool(
            runner_operations=self.runner_operations,
            resolve_runtime_target=resolve_edit_target,
            owner_session_id=self._runtime_session_id,
            agent_id=runtime_agent_id,
        )
        file_tools = [
            make_read_image_tool(
                session_storage=file_ss,
                model_file_service=self.model_file_service,
                session_id=self._session_id,
                agent_id=agent_id,
                user_id=user_id or "",
                run_index=context.run_index,
            ),
            make_import_file_tool(
                session_storage=file_ss,
                exchange_file_service=self.exchange_file_service,
                artifact_service=self.artifact_service,
                vfs_projection_service=self.vfs_projection_service,
                session_id=self._session_id,
                agent_id=agent_id,
                workspace_id=context.workspace_id,
                run_id=context.run_id,
                user_id=user_id or "",
            ),
            make_present_file_tool(
                session_storage=file_ss,
                exchange_file_service=self.exchange_file_service,
                session_id=self._session_id,
                agent_id=agent_id,
                user_id=user_id or "",
            ),
            make_read_text_tool(
                session_storage=file_ss,
                agent_id=agent_id,
                user_id=user_id or "",
            ),
            make_delete_file_tool(
                session_storage=file_ss,
                agent_id=agent_id,
                user_id=user_id or "",
            ),
            make_write_tool(
                session_storage=file_ss,
                agent_id=agent_id,
                user_id=user_id or "",
            ),
            make_glob_tool(
                session_storage=file_ss,
                agent_id=agent_id,
                user_id=user_id or "",
            ),
            make_grep_tool(
                session_storage=file_ss,
                agent_id=agent_id,
                user_id=user_id or "",
            ),
        ]
        tools = [
            make_exec_command_tool(
                self.runner_operations,
                agent_runtime_repo=self.agent_runtime_repo,
                session_manager=self.session_manager,
                agent_id=runtime_agent_id,
                publish_event=context.publish_event,
                owner_session_id=self._session_id,
                peer_toolkits=self._peer_toolkits,
            ),
            make_write_stdin_tool(
                self.runner_operations,
                agent_runtime_repo=self.agent_runtime_repo,
                session_manager=self.session_manager,
                agent_id=runtime_agent_id,
                publish_event=context.publish_event,
                owner_session_id=self._session_id,
            ),
            apply_patch_tool,
            _with_runtime_native_file_tool_diagnostics(
                edit_tool,
                agent_id=runtime_agent_id,
                owner_session_id=self._runtime_session_id,
            ),
            *[
                _with_runtime_file_tool_diagnostics(
                    tool,
                    file_storage=file_ss,
                    agent_id=runtime_agent_id,
                    owner_session_id=self._runtime_session_id,
                )
                for tool in file_tools
            ],
        ]
        # Filter tools requested by the runtime context.
        if self._excluded_tools:
            tools = [t for t in tools if t.spec.name not in self._excluded_tools]

        instruction_context = await self._make_instruction_context(file_ss)
        self.register_agents_context(instruction_context)
        if self.instruction_context_store is not None:
            self.instruction_context_store.set(instruction_context)
        return ToolkitState(status=ToolkitStatus.ENABLED, tools=tools)

    async def get_static_prompt(self, context: TurnContext) -> str:
        """Return static runtime/files prompt for the current run."""
        projects = sorted(
            await self._load_projects(session_id=self._session_id),
            key=lambda project: project.path,
        )
        return self._render_config_prompt(
            has_agent_id=bool(self._agent_id),
            user_id=context.user_id,
            projects=projects,
        )

    async def get_profiled_static_prompts(
        self,
        context: TurnContext,
    ) -> list[ProfiledToolkitPrompt]:
        """Return model-profile-gated Runtime tool guidance."""
        del context
        if "apply_patch" in self._excluded_tools:
            return []
        return [
            ProfiledToolkitPrompt(
                required_client_tool_profile=(
                    ClientToolProfile.V4A_APPLY_PATCH_FUNCTION
                ),
                content=GPT_V4A_APPLY_PATCH_PROMPT,
            ),
            ProfiledToolkitPrompt(
                required_client_tool_profile=(
                    ClientToolProfile.V4A_APPLY_PATCH_PLAINTEXT_CUSTOM
                ),
                content=GPT_V4A_PLAINTEXT_CUSTOM_APPLY_PATCH_PROMPT,
            ),
        ]

    async def _make_instruction_context(
        self,
        file_storage: FileStorage,
    ) -> RuntimeInstructionContext:
        """Build shared Runtime context for instruction appendix providers."""
        projects = sorted(
            await self._load_projects(session_id=self._session_id),
            key=lambda project: project.path,
        )
        return RuntimeInstructionContext(
            file_storage=file_storage,
            projects=tuple(projects),
        )

    async def _load_projects(
        self,
        *,
        session_id: str,
    ) -> list[SessionWorkspaceProject]:
        """Fetch Project list registered to AgentSession."""
        if not session_id:
            return []
        async with self.session_manager() as session:
            return await self.project_repo.list_projects(
                session,
                session_id=session_id,
            )

    def _render_config_prompt(
        self,
        *,
        has_agent_id: bool,
        user_id: str | None,
        projects: list[SessionWorkspaceProject],
    ) -> str:
        """Return domain allow/block settings and accessible scope prompt.

        :param has_agent_id: Whether agent_id is present
        :param user_id: User ID. When None, do not display user folder path
        :return: Settings prompt
        """
        parts: list[str] = []
        scope_lines = [
            "## Runtime Files",
            "",
            "Use absolute filesystem paths inside the runtime workspace.",
            "Prefer the dedicated file tools for filesystem operations: use `read` "
            "instead of `cat`, `grep` instead of shell `grep`/`rg`, and "
            "`write`/`edit` instead of shell redirection or `sed` whenever "
            "possible. Use `exec_command` for command execution, package "
            "installation, and cases where no dedicated tool fits. Use "
            "`write_stdin` with empty chars to poll a running process.",
            "Tool results may include `<system-reminder>` blocks with relevant "
            "AGENTS.md instructions for files you read. Follow those instructions "
            "for the paths they apply to.",
            "Recommended locations:",
            "- `/workspace/agent/` — Durable working files for this agent runtime",
            "- `/tmp/` — Temporary scratch space for the current runtime instance",
        ]
        if user_id:
            scope_lines.append(
                "Use `import_file` for user uploads and `present_file` to share "
                "new or edited files back to the user."
            )
            if "import_file" not in self._excluded_tools:
                scope_lines.extend(
                    [
                        "Files shared through `exchange://` or `artifact://` URIs "
                        "are temporary and may expire.",
                        "Do not rely on those URIs for long-term storage across "
                        "future turns. If a file is needed for later work, use "
                        "`import_file` and continue from the returned local path "
                        "inside the runtime workspace.",
                        "Managed `azents://` resources are read-only and immutable "
                        "for the current run. Use `import_file` to materialize one "
                        "into the runtime workspace before reading or editing it.",
                    ]
                )
        if projects:
            scope_lines.extend(
                [
                    "",
                    "Registered Projects:",
                    *[f"- `{project.path}`" for project in projects],
                    "",
                    "`/workspace/agent` itself is not a Project. Project-scoped "
                    "instructions only apply inside registered Projects.",
                ]
            )
        parts.append("\n".join(scope_lines))

        config = self._config
        if config.allowed_domains:
            parts.append(
                f"Allowed domains: {', '.join(sorted(config.allowed_domains))}"
            )
        if config.denied_domains:
            parts.append(f"Denied domains: {', '.join(sorted(config.denied_domains))}")
        return "\n".join(parts)


class BuiltinToolkitProvider(ToolkitProvider[ShellToolkitConfig]):
    """Builtin/runtime toolkit provider.

    Create Runtime Runner independent default tools as BuiltinToolkit, and runner
    dependent shell/file tools as RuntimeToolkit.
    """

    slug = "shell"
    name = "Shell"
    description = "Execute code in the agent runtime"
    system_prompt = dedent("""\
        You have access to an agent runtime shell environment.
        You can execute commands, install packages, and run code.
        The runtime workspace persists across calls for this agent.

        ### File Storage

        Your runtime working directory is `/workspace/agent/`. It persists across turns for this agent runtime and is the default place for files you create or edit.

        Use absolute filesystem paths inside the runtime workspace. `/workspace/agent/` is the durable working directory for this agent runtime. `/tmp/` is temporary scratch space. `/tmp/agent/imports/` is where `import_file` places attached files by default; this location is transient, so copy important files to a durable working directory before presenting them.

        Prefer the dedicated file tools for filesystem operations: use `read` instead of `cat`, `grep` instead of shell `grep`/`rg`, and `write`/`edit` instead of shell redirection or `sed` whenever possible. Use `exec_command` for command execution, package installation, and cases where no dedicated tool fits. Use `write_stdin` with empty chars to poll a running process.

        | Path | Persistence | Usage |
        |------|-------------|-------|
        | `/workspace/agent/` | Durable for this agent runtime | Working files, outputs, edited imports |
        | `/tmp/` | Ephemeral | Temporary files |
        | `/tmp/agent/imports/` | Ephemeral | Default destination for imported exchange files |

        To share files with the user, use `present_file` with absolute paths:

        ```bash
        cp ./output.csv /workspace/agent/output.csv
        # Then use present_file with the full path
        ```

        Files shared through `exchange://` or `artifact://` URIs are temporary and may expire. Do not rely on those URIs for long-term storage across future turns. If a file should be kept for later work, use `import_file` and continue from the returned local path inside the runtime workspace.

        Managed `azents://` resources are read-only and immutable for the current run. Use `import_file` to materialize a managed resource into the runtime workspace before reading or editing it.

        When the user attaches an `exchange://...` or `artifact://...` file-location URI, use `import_file` to copy it into the runtime workspace before reading or editing it.

        After creating files, use `present_file` to export them as `exchange://...` attachments for the user.""")  # noqa: E501
    config_model = ShellToolkitConfig

    def __init__(
        self,
        exchange_file_service: ExchangeFileService,
        artifact_service: ArtifactService,
        model_file_service: ModelFileService,
        vfs_projection_service: VfsProjectionService | None,
        agents_store: AgentsAppendixDedupeStateStore,
        session_manager: SessionManager[AsyncSession],
        memory_repo: MemoryRepository,
        agent_runtime_repo: AgentRuntimeRepository,
        runner_operations: RuntimeRunnerOperationClient,
        project_repo: SessionWorkspaceProjectRepository,
    ) -> None:
        self.exchange_file_service = exchange_file_service
        self.artifact_service = artifact_service
        self.model_file_service = model_file_service
        self.vfs_projection_service = vfs_projection_service
        self.session_manager = session_manager
        self.memory_repo = memory_repo
        self.agent_runtime_repo = agent_runtime_repo
        self.runner_operations = runner_operations
        self.project_repo = project_repo
        self.agents_store = agents_store

    async def resolve(
        self,
        config: ShellToolkitConfig,
        context: ResolveContext,
    ) -> Toolkit[ShellToolkitConfig]:
        """Return RuntimeToolkit.

        ``config`` contains runtime domain policy, so separate injection is not needed.
        Caller (``resolve_agent_tools``) must receive ``runtime_domain_config``
        and build ``ShellToolkitConfig``.

        :param config: Shell settings (memory_enabled, allowed/denied_domains, etc.)
        :param context: Resolve context
        :return: RuntimeToolkit instance
        """
        return RuntimeToolkit(
            config=config,
            runner_operations=self.runner_operations,
            exchange_file_service=self.exchange_file_service,
            artifact_service=self.artifact_service,
            model_file_service=self.model_file_service,
            vfs_projection_service=self.vfs_projection_service,
            agent_id=context.agent_id,
            session_manager=self.session_manager,
            agent_runtime_repo=self.agent_runtime_repo,
            project_repo=self.project_repo,
            agents_store=self.agents_store,
        )

    async def resolve_builtin(
        self,
        config: ShellToolkitConfig,
        context: ResolveContext,
    ) -> Toolkit[ShellToolkitConfig]:
        """Return Runtime Runner independent default BuiltinToolkit.

        :param config: Shell settings (memory_enabled, etc.)
        :param context: Resolve context
        :return: BuiltinToolkit instance
        """
        return BuiltinToolkit(
            config=config,
            agent_id=context.agent_id,
            session_manager=self.session_manager,
            memory_repo=self.memory_repo,
        )

    async def resolve_memory_read(
        self,
        config: ShellToolkitConfig,
        context: ResolveContext,
    ) -> Toolkit[ShellToolkitConfig]:
        """Return the auto-bound memory read capability."""
        return MemoryReadToolkit(
            config=config,
            agent_id=context.agent_id,
            session_manager=self.session_manager,
            memory_repo=self.memory_repo,
        )

    async def resolve_memory_write(
        self,
        config: ShellToolkitConfig,
        context: ResolveContext,
    ) -> Toolkit[ShellToolkitConfig]:
        """Return the auto-bound memory write capability."""
        return MemoryWriteToolkit(
            config=config,
            agent_id=context.agent_id,
            session_manager=self.session_manager,
            memory_repo=self.memory_repo,
        )


async def _collect_secret_env(
    peer_toolkits: Sequence[RuntimeEnvProvider],
    agent_id: str,
) -> dict[str, str]:
    """Collect env by merging ``expose_env()`` from bundled peer toolkits.

    When multiple toolkits expose the same key, later toolkit value overwrites it.
    In this case, only warning is logged and execution continues. Platform-level
    allowlist or priority should be decided later; Phase 1 uses simple override.

    :param peer_toolkits: Active toolkit instance list of current session
    :param agent_id: Agent ID for logging
    :return: Merged env mapping. Empty dict when empty.
    """
    merged: dict[str, str] = {}
    for toolkit in peer_toolkits:
        env_part = await toolkit.expose_env()
        for key, value in env_part.items():
            if key in merged:
                logger.warning(
                    "Env var overridden by later toolkit",
                    extra={"var_name": key, "agent_id": agent_id},
                )
            merged[key] = value
    return merged


async def _ready_runtime_for_agent(
    *,
    agent_runtime_repo: AgentRuntimeRepository,
    session_manager: SessionManager[AsyncSession] | None,
    agent_id: str,
    wait_timeout_seconds: float | None = None,
    poll_interval_seconds: float = _RUNTIME_READY_POLL_INTERVAL_SECONDS,
) -> AgentRuntime:
    """Load the active Runtime and verify that its Runner can accept operations."""
    if session_manager is None:
        raise RuntimeStorageError("Runtime database session is not configured")
    wait_timeout_seconds = (
        _RUNTIME_READY_WAIT_TIMEOUT_SECONDS
        if wait_timeout_seconds is None
        else wait_timeout_seconds
    )
    deadline = time.monotonic() + max(wait_timeout_seconds, 0.0)
    last_runtime: AgentRuntime | None = None
    while True:
        async with session_manager() as session:
            runtime = await agent_runtime_repo.get_by_agent_id(session, agent_id)
        last_runtime = runtime
        if (
            runtime is not None
            and runtime.provider_observed_state in _RUNNABLE_PROVIDER_STATES
            and runtime.runner_state == RuntimeRunnerState.READY
        ):
            return runtime
        if runtime is None:
            raise RuntimeStorageError("Runtime is not running")
        if runtime.provider_observed_state == RuntimeProviderObservedState.FAILED:
            failure_message = getattr(runtime, "failure_message", None)
            failure_code = getattr(runtime, "failure_code", None)
            detail = failure_message or failure_code
            message = "Runtime failed"
            if detail:
                message = f"{message}: {detail}"
            raise RuntimeStorageError(message)
        if (
            runtime.provider_connection_state
            == RuntimeProviderConnectionState.DISCONNECTED
        ):
            raise RuntimeStorageError(_RUNTIME_PROVIDER_DISCONNECTED_MSG)
        if runtime.desired_state != RuntimeDesiredState.RUNNING:
            async with session_manager() as session:
                await agent_runtime_repo.set_desired_state(
                    session,
                    runtime.id,
                    RuntimeLifecycleCommandType.START,
                    RuntimeDesiredState.RUNNING,
                )
        if time.monotonic() >= deadline:
            break
        await asyncio.sleep(poll_interval_seconds)

    if last_runtime is None:
        raise RuntimeStorageError("Runtime is not running")
    if last_runtime.provider_observed_state not in _RUNNABLE_PROVIDER_STATES:
        raise RuntimeStorageError(_RUNTIME_STARTING_MSG)
    raise RuntimeStorageError("Runtime runner is not ready")


def _raise_storage_error(error: RuntimeRunnerOperationFailedError) -> NoReturn:
    """Convert Runner operation failure to file-storage-compatible error."""
    message = str(error)
    normalized = message.lower()
    if (
        "no such file" in normalized
        or "not found" in normalized
        or "not a directory" in normalized
    ):
        raise FileNotFoundError(message) from error
    raise RuntimeStorageError(message) from error


def _runtime_file_operation_deadline() -> datetime:
    """Return Runtime file operation round-trip deadline."""
    return datetime.now(UTC) + timedelta(
        seconds=(
            _RUNTIME_FILE_OPERATION_TIMEOUT_SECONDS
            + _RUNTIME_OPERATION_RESULT_GRACE_SECONDS
        )
    )


class RuntimeRunnerFileStorage:
    """FileStorage implementation backed by Runtime Runner operations."""

    def __init__(
        self,
        *,
        runner_operations: RuntimeRunnerOperationClient,
        agent_runtime_repo: AgentRuntimeRepository,
        session_manager: SessionManager[AsyncSession] | None,
        runtime_agent_id: str,
        owner_session_id: str | None,
    ) -> None:
        self.runner_operations = runner_operations
        self.agent_runtime_repo = agent_runtime_repo
        self.session_manager = session_manager
        self.runtime_agent_id = runtime_agent_id
        self.owner_session_id = owner_session_id
        self._runtime: AgentRuntime | None = None
        self._runtime_lock = asyncio.Lock()
        self._runtime_operation_count: ContextVar[int | None] = ContextVar(
            "runtime_runner_file_storage_operation_count",
            default=None,
        )

    async def get(self, path: str, *, agent_id: str) -> bytes:
        """Read file bytes through the Runtime Runner."""
        runtime = await self._ready_runtime(agent_id)
        try:
            self._count_runtime_operation()
            result = await self.runner_operations.read_file(
                runtime_id=runtime.id,
                runner_generation=runtime.runner_generation,
                owner_session_id=self.owner_session_id,
                path=path,
                offset=0,
                max_bytes=None,
                deadline_at=_runtime_file_operation_deadline(),
            )
            return result.data
        except RuntimeRunnerOperationFailedError as exc:
            _raise_storage_error(exc)

    async def stat(self, path: str, *, agent_id: str) -> dict[str, object]:
        """Fetch Runtime path metadata with file.stat."""
        runtime = await self._ready_runtime(agent_id)
        try:
            self._count_runtime_operation()
            result = await self.runner_operations.stat_file(
                runtime_id=runtime.id,
                runner_generation=runtime.runner_generation,
                owner_session_id=self.owner_session_id,
                path=path,
                deadline_at=_runtime_file_operation_deadline(),
            )
        except RuntimeRunnerOperationFailedError as exc:
            _raise_storage_error(exc)
        except (
            RuntimeRunnerOperationUnavailable,
            RuntimeRunnerOperationGenerationError,
        ) as exc:
            raise RuntimeStorageError(str(exc)) from exc
        return _stat_metadata(result)

    async def put(
        self,
        path: str,
        data: bytes,
        media_type: str = "",
        *,
        agent_id: str,
    ) -> RuntimeAttachment:
        """Write file bytes through the Runtime Runner."""
        runtime = await self._ready_runtime(agent_id)
        try:
            self._count_runtime_operation()
            result = await self.runner_operations.write_file(
                runtime_id=runtime.id,
                runner_generation=runtime.runner_generation,
                owner_session_id=self.owner_session_id,
                path=path,
                data=data,
                deadline_at=_runtime_file_operation_deadline(),
            )
        except RuntimeRunnerOperationFailedError as exc:
            _raise_storage_error(exc)
        return RuntimeAttachment(
            uri=path,
            media_type=media_type,
            size=result.bytes_written,
            name=PurePosixPath(path).name,
            text_preview=None,
        )

    async def delete(self, path: str, *, agent_id: str) -> None:
        """Delete a Runtime path through a shell operation."""
        runtime = await self._ready_runtime(agent_id)
        try:
            self._count_runtime_operation()
            result = await self.runner_operations.run_bash(
                runtime_id=runtime.id,
                runner_generation=runtime.runner_generation,
                owner_session_id=self.owner_session_id,
                command=f"rm -rf -- {shlex.quote(path)}",
                timeout_seconds=30,
                env=None,
                deadline_at=datetime.now(UTC)
                + timedelta(seconds=30 + _RUNTIME_OPERATION_RESULT_GRACE_SECONDS),
            )
        except RuntimeRunnerOperationFailedError as exc:
            _raise_storage_error(exc)
        if result.exit_code != 0:
            raise RuntimeStorageError(result.stderr or "Failed to delete file")

    async def exists(self, path: str, *, agent_id: str) -> bool:
        """Return whether a Runtime path exists."""
        try:
            await self.stat(path, agent_id=agent_id)
        except FileNotFoundError:
            return False
        return True

    async def list(
        self,
        path: str,
        *,
        agent_id: str,
        recursive: bool = False,
        exclude_patterns: list[str] | None = None,
        include_directories: bool = False,
    ) -> list[RuntimeAttachment]:
        """List file entries under a Runtime path."""
        runtime = await self._ready_runtime(agent_id)
        entries = await self._list_entries(
            runtime,
            path,
            recursive=recursive,
            exclude_patterns=exclude_patterns,
        )
        return [
            RuntimeAttachment(
                uri=entry.path,
                media_type=(
                    "inode/directory"
                    if entry.type == "directory"
                    else guess_media_type(entry.path)
                ),
                size=entry.size_bytes or 0,
                name=PurePosixPath(entry.path).name,
                text_preview=None,
            )
            for entry in entries
            if (
                entry.type == "file"
                or (include_directories and entry.type == "directory")
            )
        ]

    async def glob(
        self,
        pattern: str,
        *,
        agent_id: str,
        exclude_patterns: list[str] | None,
    ) -> list[RuntimeAttachment]:
        """Match Runtime file entries through one native Runner operation."""
        runtime = await self._ready_runtime(agent_id)
        try:
            self._count_runtime_operation()
            result = await self.runner_operations.glob_files(
                runtime_id=runtime.id,
                runner_generation=runtime.runner_generation,
                owner_session_id=self.owner_session_id,
                pattern=pattern,
                exclude_patterns=exclude_patterns,
                deadline_at=_runtime_file_operation_deadline(),
            )
        except RuntimeRunnerOperationFailedError as exc:
            _raise_storage_error(exc)
        except (
            RuntimeRunnerOperationUnavailable,
            RuntimeRunnerOperationGenerationError,
        ) as exc:
            raise RuntimeStorageError(str(exc)) from exc
        return [
            RuntimeAttachment(
                uri=entry.path,
                media_type=(
                    "inode/directory"
                    if entry.type == "directory"
                    else guess_media_type(entry.path)
                ),
                size=entry.size_bytes or 0,
                name=PurePosixPath(entry.path).name,
                text_preview=None,
            )
            for entry in result.entries
            if entry.type in {"file", "directory"}
        ]

    async def list_dirs(self, path: str, *, agent_id: str) -> list[str]:
        """List directory names below a Runtime directory."""
        runtime = await self._ready_runtime(agent_id)
        entries = await self._list_entries(runtime, path)
        return [
            PurePosixPath(entry.path).name
            for entry in entries
            if entry.type == "directory"
        ]

    async def grep(
        self,
        path: str,
        *,
        agent_id: str,
        pattern: str,
        recursive: bool = True,
        exclude_patterns: list[str] | None = None,
        max_matching_files: int = 50,
        max_lines_per_file: int = 10,
        max_searched_files: int | None = None,
        max_scanned_bytes: int | None = None,
    ) -> GrepResult:
        """Search Runtime files through a single Runner grep operation."""
        runtime = await self._ready_runtime(agent_id)
        try:
            self._count_runtime_operation()
            result = await self.runner_operations.grep_files(
                runtime_id=runtime.id,
                runner_generation=runtime.runner_generation,
                owner_session_id=self.owner_session_id,
                path=path,
                pattern=pattern,
                recursive=recursive,
                exclude_patterns=exclude_patterns,
                max_matching_files=max_matching_files,
                max_lines_per_file=max_lines_per_file,
                max_searched_files=max_searched_files,
                max_scanned_bytes=max_scanned_bytes,
                deadline_at=_runtime_file_operation_deadline(),
            )
        except RuntimeRunnerOperationFailedError as exc:
            _raise_storage_error(exc)
        except (
            RuntimeRunnerOperationUnavailable,
            RuntimeRunnerOperationGenerationError,
        ) as exc:
            raise RuntimeStorageError(str(exc)) from exc
        return GrepResult(
            files=tuple(_grep_file_match(file_match) for file_match in result.files),
            searched_file_count=result.searched_file_count,
            matched_file_count=result.matched_file_count,
            truncated=result.truncated,
            stopped_reason=getattr(result, "stopped_reason", None),
        )

    def begin_runtime_operation_count(self) -> Token[int | None]:
        """Start task-local Runner operation counting for one visible tool."""
        return self._runtime_operation_count.set(0)

    def finish_runtime_operation_count(self, token: Token[int | None]) -> int:
        """Return task-local Runner operation count and restore prior state."""
        count = self._runtime_operation_count.get()
        self._runtime_operation_count.reset(token)
        return count or 0

    def _count_runtime_operation(self) -> None:
        """Record one Runner operation in the active task-local counter."""
        count = self._runtime_operation_count.get()
        if count is not None:
            self._runtime_operation_count.set(count + 1)

    async def _ready_runtime(self, agent_id: str) -> AgentRuntime:
        del agent_id
        runtime = self._runtime
        if runtime is not None:
            return runtime
        async with self._runtime_lock:
            runtime = self._runtime
            if runtime is None:
                runtime = await _ready_runtime_for_agent(
                    agent_runtime_repo=self.agent_runtime_repo,
                    session_manager=self.session_manager,
                    agent_id=self.runtime_agent_id,
                )
                self._runtime = runtime
            return runtime

    async def _list_entries(
        self,
        runtime: AgentRuntime,
        path: str,
        *,
        recursive: bool = False,
        exclude_patterns: list[str] | None = None,
    ) -> tuple[RuntimeFileListEntry, ...]:
        try:
            self._count_runtime_operation()
            result = await self.runner_operations.list_files(
                runtime_id=runtime.id,
                runner_generation=runtime.runner_generation,
                owner_session_id=self.owner_session_id,
                path=path,
                recursive=recursive,
                exclude_patterns=exclude_patterns,
                deadline_at=_runtime_file_operation_deadline(),
            )
            return result.entries
        except RuntimeRunnerOperationFailedError as exc:
            _raise_storage_error(exc)
        except (
            RuntimeRunnerOperationUnavailable,
            RuntimeRunnerOperationGenerationError,
        ) as exc:
            raise RuntimeStorageError(str(exc)) from exc


def _with_runtime_file_tool_diagnostics(
    tool: FunctionTool,
    *,
    file_storage: RuntimeRunnerFileStorage,
    agent_id: str,
    owner_session_id: str | None,
) -> FunctionTool:
    """Wrap one model-visible file tool with structured latency diagnostics."""
    original_handler = tool.handler

    async def handler(args_json: str) -> str | FunctionToolResult:
        started_at = time.perf_counter()
        count_token = file_storage.begin_runtime_operation_count()
        status = "completed"
        try:
            return await original_handler(args_json)
        except asyncio.CancelledError:
            status = "cancelled"
            raise
        except Exception:
            status = "failed"
            raise
        finally:
            operation_count = file_storage.finish_runtime_operation_count(count_token)
            logger.info(
                "Processed Runtime file tool",
                extra={
                    "agent_id": agent_id,
                    "session_id": owner_session_id,
                    "tool_name": tool.spec.name,
                    "tool_status": status,
                    "tool_duration_ms": (time.perf_counter() - started_at) * 1000,
                    "runtime_operation_count": operation_count,
                },
            )

    return dataclasses.replace(tool, handler=handler)


def _with_runtime_native_file_tool_diagnostics(
    tool: FunctionTool,
    *,
    agent_id: str,
    owner_session_id: str | None,
) -> FunctionTool:
    """Wrap a one-shot Runner-native file tool with latency diagnostics."""
    original_handler = tool.handler

    async def handler(args_json: str) -> str | FunctionToolResult:
        started_at = time.perf_counter()
        status = "completed"
        try:
            return await original_handler(args_json)
        except asyncio.CancelledError:
            status = "cancelled"
            raise
        except Exception:
            status = "failed"
            raise
        finally:
            logger.info(
                "Processed Runtime native file tool",
                extra={
                    "agent_id": agent_id,
                    "session_id": owner_session_id,
                    "tool_name": tool.spec.name,
                    "tool_status": status,
                    "tool_duration_ms": (time.perf_counter() - started_at) * 1000,
                    "runtime_operation_count": 1,
                },
            )

    return dataclasses.replace(tool, handler=handler)


def _stat_metadata(result: RuntimeFileStatResult) -> dict[str, object]:
    """Convert RuntimeFileStatResult to FileStorage.stat dict."""
    return {
        "is_file": result.kind == "file",
        "is_directory": result.kind == "directory",
        "is_symlink": result.symlink,
        "size": result.size_bytes or 0,
        "path": result.path,
        "real_path": result.real_path,
        "resolved_kind": result.resolved_kind,
    }


def _grep_file_match(file_match: RuntimeGrepFileMatch) -> GrepFileMatch:
    return GrepFileMatch(
        path=file_match.path,
        lines=tuple(_grep_line_match(line_match) for line_match in file_match.lines),
        truncated=file_match.truncated,
    )


def _grep_line_match(line_match: RuntimeGrepLineMatch) -> GrepLineMatch:
    return GrepLineMatch(
        line_number=line_match.line_number,
        text=line_match.text,
    )


def make_exec_command_tool(
    runner_operations: RuntimeRunnerOperationClient,
    *,
    agent_runtime_repo: AgentRuntimeRepository,
    session_manager: SessionManager[AsyncSession] | None,
    agent_id: str,
    publish_event: Callable[[EngineEvent], Awaitable[None]],
    owner_session_id: str,
    peer_toolkits: Sequence[RuntimeEnvProvider] = (),
) -> FunctionTool:
    """Create an exec_command tool backed by Runtime Runner process operations."""

    async def handler(args: ExecCommandInput) -> FunctionToolResult:
        secret_env = await _collect_secret_env(peer_toolkits, agent_id)
        try:
            runtime = await _ready_runtime_for_agent(
                agent_runtime_repo=agent_runtime_repo,
                session_manager=session_manager,
                agent_id=agent_id,
            )
            await publish_event(RuntimeReadyEvent())
            result = await runner_operations.start_process(
                runtime_id=runtime.id,
                runner_generation=runtime.runner_generation,
                command=args.command,
                workdir=args.workdir,
                yield_time_ms=args.yield_time_ms,
                max_output_bytes=args.max_output_bytes,
                env=secret_env or None,
                owner_session_id=owner_session_id,
                deadline_at=_runtime_process_operation_deadline(args.yield_time_ms),
                process_output_callback=_publish_process_output_delta(publish_event),
            )
        except (
            RuntimeRunnerOperationUnavailable,
            RuntimeRunnerOperationGenerationError,
            RuntimeRunnerOperationFailedError,
            RuntimeStorageError,
        ) as exc:
            message = str(exc)
            logger.warning(
                "Runtime Runner process start operation failed",
                extra={"agent_id": agent_id, "error": message},
            )
            raise FunctionToolError(message) from None

        return FunctionToolResult(
            output=_format_process_result(result),
            metadata=_process_result_metadata(result, kind="exec_command_result"),
        )

    tool = make_tool(
        handler,
        name="exec_command",
        description=(
            "Start a shell process in the Agent Runtime workspace. Returns output "
            "and exit_code when it exits within yield_time_ms; otherwise returns a "
            "running process_id for write_stdin polling or input. yield_time_ms "
            "defaults to 10000 ms and accepts 250-30000 ms."
        ),
    )
    return dataclasses.replace(
        tool,
        cancel_handler=_make_process_cancel_handler(
            runner_operations=runner_operations,
            agent_runtime_repo=agent_runtime_repo,
            session_manager=session_manager,
            agent_id=agent_id,
            owner_session_id=owner_session_id,
        ),
    )


def make_write_stdin_tool(
    runner_operations: RuntimeRunnerOperationClient,
    *,
    agent_runtime_repo: AgentRuntimeRepository,
    session_manager: SessionManager[AsyncSession] | None,
    agent_id: str,
    publish_event: Callable[[EngineEvent], Awaitable[None]],
    owner_session_id: str,
) -> FunctionTool:
    """Create a write_stdin tool backed by Runtime Runner process operations."""

    async def handler(args: WriteStdinInput) -> FunctionToolResult:
        try:
            runtime = await _ready_runtime_for_agent(
                agent_runtime_repo=agent_runtime_repo,
                session_manager=session_manager,
                agent_id=agent_id,
            )
            await publish_event(RuntimeReadyEvent())
            result = await runner_operations.write_process_stdin(
                runtime_id=runtime.id,
                runner_generation=runtime.runner_generation,
                process_id=args.process_id,
                stdin=args.chars,
                yield_time_ms=args.yield_time_ms,
                max_output_bytes=args.max_output_bytes,
                owner_session_id=owner_session_id,
                deadline_at=_runtime_process_operation_deadline(args.yield_time_ms),
                process_output_callback=_publish_process_output_delta(publish_event),
            )
        except (
            RuntimeRunnerOperationUnavailable,
            RuntimeRunnerOperationGenerationError,
            RuntimeRunnerOperationFailedError,
            RuntimeStorageError,
        ) as exc:
            message = str(exc)
            logger.warning(
                "Runtime Runner process write operation failed",
                extra={"agent_id": agent_id, "error": message},
            )
            raise FunctionToolError(message) from None

        return FunctionToolResult(
            output=_format_process_result(result),
            metadata=_process_result_metadata(result, kind="write_stdin_result"),
        )

    tool = make_tool(
        handler,
        name="write_stdin",
        description=(
            "Write characters to a running exec_command process. Pass an empty "
            "chars string to poll for unread output without sending input. A zero "
            "yield returns currently buffered output immediately. Non-empty writes "
            "default to 250 ms and cap at 30000 ms; empty polls default to 5000 ms "
            "and cap at 300000 ms."
        ),
    )
    return dataclasses.replace(
        tool,
        cancel_handler=_make_process_cancel_handler(
            runner_operations=runner_operations,
            agent_runtime_repo=agent_runtime_repo,
            session_manager=session_manager,
            agent_id=agent_id,
            owner_session_id=owner_session_id,
        ),
    )


def _make_process_cancel_handler(
    *,
    runner_operations: RuntimeRunnerOperationClient,
    agent_runtime_repo: AgentRuntimeRepository,
    session_manager: SessionManager[AsyncSession] | None,
    agent_id: str,
    owner_session_id: str,
) -> Callable[[FunctionToolCancelRequest], Awaitable[None]]:
    """Return user-stop cancellation hook for session-owned exec processes."""

    async def cancel_handler(request: FunctionToolCancelRequest) -> None:
        del request
        try:
            runtime = await _ready_runtime_for_agent(
                agent_runtime_repo=agent_runtime_repo,
                session_manager=session_manager,
                agent_id=agent_id,
            )
            await runner_operations.terminate_session_processes(
                runtime_id=runtime.id,
                runner_generation=runtime.runner_generation,
                owner_session_id=owner_session_id,
                deadline_at=datetime.now(UTC)
                + timedelta(seconds=_RUNTIME_PROCESS_TERMINATE_TIMEOUT_SECONDS),
            )
        except (
            RuntimeRunnerOperationUnavailable,
            RuntimeRunnerOperationGenerationError,
            RuntimeRunnerOperationFailedError,
            RuntimeStorageError,
        ):
            logger.debug(
                "Runtime Runner process cancellation failed during user stop",
                extra={"agent_id": agent_id},
                exc_info=True,
            )

    return cancel_handler


def _publish_process_output_delta(
    publish_event: Callable[[EngineEvent], Awaitable[None]],
) -> Callable[[RuntimeProcessOutputDelta], Awaitable[None]]:
    """Return callback that publishes Runtime process live output deltas."""

    async def callback(delta: RuntimeProcessOutputDelta) -> None:
        await publish_event(
            RuntimeProcessOutputDeltaEvent(
                process_id=delta.process_id,
                stream=delta.stream,
                chunk_id=delta.chunk_id,
                text=delta.text,
                truncated=delta.truncated,
                omitted_bytes=delta.omitted_bytes,
            )
        )

    return callback


def _runtime_process_operation_deadline(yield_time_ms: int) -> datetime:
    """Return Runtime process operation round-trip deadline."""
    return datetime.now(UTC) + timedelta(
        seconds=yield_time_ms / 1000 + _RUNTIME_OPERATION_RESULT_GRACE_SECONDS
    )


def _process_result_metadata(
    result: RuntimeProcessResult,
    *,
    kind: str,
) -> JSONObject:
    """Build generic tool-result metadata for process snapshots."""
    metadata: JSONObject = {
        "kind": kind,
        "process_id": result.process_id,
        "status": result.status,
        "exit_code": result.exit_code,
        "stdout_truncated": result.stdout_truncated,
        "stderr_truncated": result.stderr_truncated,
        "stdout_omitted_bytes": result.stdout_omitted_bytes,
        "stderr_omitted_bytes": result.stderr_omitted_bytes,
        "missing_reason": result.missing_reason,
        "final_cursor": result.final_cursor,
    }
    return metadata


def _format_process_result(result: RuntimeProcessResult) -> str:
    """Render process snapshot as model-visible tool output text."""
    parts: list[str] = [
        f"status: {result.status}",
        f"process_id: {result.process_id}",
    ]
    if result.exit_code is not None:
        parts.append(f"exit_code: {result.exit_code}")
    if result.missing_reason:
        parts.append(f"missing_reason: {result.missing_reason}")
    truncation = _format_process_truncation(result)
    if truncation:
        parts.append(truncation)
    output_parts: list[str] = []
    if result.stdout:
        output_parts.append(f"stdout:\n{result.stdout}")
    if result.stderr:
        output_parts.append(f"stderr:\n{result.stderr}")
    if output_parts:
        parts.append("\n\n".join(output_parts))
    else:
        parts.append("(no output)")
    return "\n\n".join(parts)


def _format_process_truncation(result: RuntimeProcessResult) -> str:
    """Return process truncation line or empty string."""
    facts: list[str] = []
    if result.stdout_truncated:
        facts.append(f"stdout omitted {result.stdout_omitted_bytes} byte(s)")
    if result.stderr_truncated:
        facts.append(f"stderr omitted {result.stderr_omitted_bytes} byte(s)")
    if not facts:
        return ""
    return "truncated: " + "; ".join(facts)
