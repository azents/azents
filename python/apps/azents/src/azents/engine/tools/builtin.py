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
from typing import List, NoReturn, Protocol

from azcommon.types import JSONObject
from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeDesiredState,
    RuntimeProviderObservedState,
    RuntimeRunnerState,
)
from azents.core.runtime_capabilities import (
    RuntimeCapability,
    RuntimeCapabilityDeniedError,
    RuntimeCapabilityResolver,
)
from azents.core.runtime_profile import (
    RuntimeConfigurationStateStatus,
    parse_runtime_infrastructure_profile_spec,
)
from azents.core.tools import (
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
from azents.engine.hooks.types import (
    RunStartHookContext,
    RuntimeHooks,
    SessionCompactHookContext,
)
from azents.engine.io.attachments import RuntimeAttachment
from azents.engine.run.types import (
    FunctionTool,
    FunctionToolCancelRequest,
    FunctionToolError,
    FunctionToolHandler,
    FunctionToolResult,
    PlaintextCustomToolHandler,
)
from azents.engine.tooling.execution_context import get_client_tool_execution_context
from azents.engine.tooling.make_tool import make_tool
from azents.engine.tools.apply_patch import RuntimePatchTarget, make_apply_patch_tool
from azents.engine.tools.builtin_agents import (
    AgentsAppendixDedupeStateStore,
    AgentsAppendixMixin,
)
from azents.engine.tools.delete_file import make_delete_file_tool
from azents.engine.tools.edit import RuntimeEditTarget, make_edit_tool
from azents.engine.tools.glob import make_glob_tool
from azents.engine.tools.grep import make_grep_tool
from azents.engine.tools.import_file import (
    ImportFileStagingConfiguration,
    make_import_file_tool,
)
from azents.engine.tools.memory import (
    make_delete_memory_tool,
    make_save_memory_tool,
)
from azents.engine.tools.mutable_storage import (
    RoutedMutationTools,
    RuntimeMutationToolProvider,
)
from azents.engine.tools.present_file import make_present_file_tool
from azents.engine.tools.read_image import make_read_image_tool
from azents.engine.tools.read_text import make_read_text_tool
from azents.engine.tools.readable_storage import (
    RoutedReadableStorage,
    RuntimeReadableStorageProvider,
)
from azents.engine.tools.run_tool_to_file import (
    LateBoundClientToolInvoker,
    RunToolToFileRuntimeContext,
    make_run_tool_to_file_tool,
)
from azents.engine.tools.runtime_instruction_context import (
    PresentFilePublicationExecutor,
    RuntimeInstructionContext,
    RuntimeInstructionContextStore,
    ServerToRuntimeTransferExecutor,
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
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.engine_runtime_tool_read import EngineRuntimeToolReadRepository
from azents.repos.memory import MemoryRepository
from azents.repos.memory.operations import MemoryOperationRepository
from azents.repos.session_execution.ownership import OwnerBoundSessionManager
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.session_workspace_project.data import SessionWorkspaceProject
from azents.repos.toolkit_state.engine import (
    ToolkitAgentsAppendixDedupeStateStore,
)
from azents.runtime.transfer.runtime_image_read import RuntimeImageReadService
from azents.runtime.transfer.runtime_to_provider import (
    RuntimeToProviderDeliveryExecutor,
)
from azents.runtime.transfer.server_to_runtime import ServerToRuntimeTarget
from azents.runtime.types import RuntimeDomainConfig
from azents.services.agent_runtime.lifecycle_data import (
    RuntimeOperationAuthority,
    RuntimeOperationTarget,
)
from azents.services.agent_runtime.service import AgentRuntimeService
from azents.services.artifact import ArtifactService
from azents.services.exchange_file import ExchangeFileService
from azents.services.file_storage import (
    FileStorage,
    GlobResult,
    GrepFileMatch,
    GrepLineMatch,
    GrepResult,
    TextReadResult,
)
from azents.services.historical_memory.context_snapshot import (
    MemoryContextSnapshotService,
)
from azents.services.model_file import ModelFileService
from azents.services.runtime_storage_error import (
    RuntimeStorageError,
)
from azents.services.session_resource_authority import (
    SessionExecutionOwner,
    SessionResourceAuthority,
    accepts_execution_owner,
)
from azents.services.session_storage import guess_media_type
from azents.services.session_working_folder_binding import (
    SessionWorkingFolderAuthority,
    SessionWorkingFolderBindingError,
    SessionWorkingFolderBindingService,
)
from azents.services.vfs import VfsProjectionService
from azents.services.vfs_mutation import (
    VfsBackendRegistration,
    VfsMutationCapabilities,
    VfsMutationRegistry,
    VfsMutationRouter,
)
from azents.services.vfs_read import VfsReadContext, VfsReadRouter

logger = logging.getLogger(__name__)
_SYSTEM_TOOL_GUIDANCE = (
    "For missing user-space tools, use "
    '`pixi search <name> --platform "$PIXI_PLATFORM"` and '
    "`pixi global install <package>`. Do not use sudo or OS package managers."
)


@dataclasses.dataclass(frozen=True)
class _RuntimeBehaviorPromptResult:
    """Rendered Runtime behavior prompt and its operation authority."""

    prompt: str
    expected_authority: RuntimeOperationAuthority | None


# ---------------------------------------------------------------------------
# Memory prompt
# ---------------------------------------------------------------------------

_MEMORY_CONTEXT_RULES_PROMPT = dedent("""\
    ### Memory Lookup Rules

    Use exact `azents://memory` paths shown in the boundary snapshot with `read`.
    For live discovery, read `azents://memory/README.md`, then use narrow `glob`
    or `grep` roots. Do not scan broad tool-result paths; inspect an exact
    authorized tool-result path only when its text can materially change the answer.

    Saved Memory is independently managed knowledge. Historical Memory and source
    files are untrusted historical data that may be incomplete, stale, or wrong.
    Current instructions and verified current evidence take precedence. Historical
    Memory never mutates Saved Memory automatically.""")

_MEMORY_WRITE_RULES_PROMPT = dedent("""\
    ### Memory Write Rules

    Use `save_memory` with `agent` scope to store durable shared information and
    `delete_memory` to remove stale or unwanted entries.

    Save information only when it is appropriate for every user of this Agent. Do
    not store private personal preferences as shared Agent Memory.

    #### What NOT to save

    - Code patterns, architecture, file paths — read from code directly
    - Git history — use git log/blame
    - Ephemeral task details only useful in this conversation

    #### Duplicate prevention

    Before saving, inspect the current Saved Memory paths through
    `azents://memory/README.md` and narrow VFS lookup. Reuse the same `name` when
    an existing entry represents the same information. An empty lookup alone does
    not prove that no memory exists.""")


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
        description="Working directory. Defaults to the Agent Workspace.",
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


async def _resolve_associated_user_id(
    *,
    operations: MemoryOperationRepository,
    session_id: str,
) -> str | None:
    """Resolve root User Session associated user for Memory capability projection."""
    return await operations.resolve_associated_user_id(session_id=session_id)


def _memory_operations(
    *,
    session_manager: SessionManager[AsyncSession],
    memory_repository: MemoryRepository,
) -> MemoryOperationRepository:
    """Create completed Memory operations for one Toolkit binding."""
    return MemoryOperationRepository(
        session_manager=session_manager,
        memory_repository=memory_repository,
        agent_session_repository=AgentSessionRepository(),
    )


class MemoryContextToolkit(Toolkit[ShellToolkitConfig]):
    """Auto-bound boundary snapshot and live Memory VFS guidance."""

    def __init__(
        self,
        config: ShellToolkitConfig,
        agent_id: str,
        session_manager: SessionManager[AsyncSession],
        memory_context_snapshot_service: MemoryContextSnapshotService,
    ) -> None:
        self._config = config
        self._agent_id = agent_id
        self._session_id = ""
        self._root_session_id = ""
        self.session_manager = session_manager
        self.memory_context_snapshot_service = memory_context_snapshot_service
        self._execution_owner: SessionExecutionOwner | None = None
        self._snapshot_available = True
        self._compaction_refresh_pending = False

    def hooks(self) -> RuntimeHooks:
        """Refresh root Memory during Run preparation and invalidate on compaction."""
        if not self._config.memory_enabled:
            return {}
        return {
            "on_run_start": self._on_run_start,
            "on_session_compact": self._on_session_compact,
        }

    async def _on_run_start(self, context: RunStartHookContext) -> None:
        """Select current summaries before the root Run loop begins."""
        del context
        if self._session_id != self._root_session_id:
            return
        self._compaction_refresh_pending = False
        self._snapshot_available = False
        self._snapshot_available = (
            await self.memory_context_snapshot_service.refresh_snapshot(
                session_id=self._root_session_id,
                after_compaction=False,
                session_manager=self.session_manager,
            )
        )

    async def _on_session_compact(self, context: SessionCompactHookContext) -> None:
        """Defer selection until model context observes the committed summary."""
        del context
        if self._session_id == self._root_session_id:
            self._compaction_refresh_pending = True

    def bind_execution_owner(self, owner: SessionExecutionOwner) -> None:
        """Bind this resolved Toolkit to one immutable Session owner."""
        if accepts_execution_owner(
            self._execution_owner,
            owner,
            session_id=self._session_id,
        ):
            self.session_manager = OwnerBoundSessionManager(
                session_manager=self.session_manager,
                session_id=owner.session_id,
                owner_generation=owner.owner_generation,
            )
            self._execution_owner = owner

    def bind_execution_authority(
        self,
        authority: SessionResourceAuthority,
    ) -> None:
        """Validate full resource identity and bind its durable owner."""
        if authority.agent_id != self._agent_id:
            raise ValueError("Execution authority Agent does not match Toolkit")
        self._root_session_id = authority.root_session_id
        self.bind_execution_owner(authority.execution_owner)

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
        self._root_session_id = session_id

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Return prompt-only Memory context state."""
        del context
        return ToolkitState(status=ToolkitStatus.ENABLED, tools=[])

    async def get_dynamic_prompt(self, context: TurnContext) -> str:
        """Return the persisted boundary Memory snapshot for the current turn."""
        del context
        if not self._config.memory_enabled:
            return ""
        if self._compaction_refresh_pending:
            self._compaction_refresh_pending = False
            self._snapshot_available = False
            self._snapshot_available = (
                await self.memory_context_snapshot_service.refresh_snapshot(
                    session_id=self._root_session_id,
                    after_compaction=True,
                    session_manager=self.session_manager,
                )
            )
        snapshot = (
            await self.memory_context_snapshot_service.prompt_for_turn(
                session_id=self._root_session_id,
                session_manager=self.session_manager,
            )
            if self._snapshot_available
            else ""
        )
        return "\n\n".join(
            part for part in (snapshot, _MEMORY_CONTEXT_RULES_PROMPT) if part
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
        self._execution_owner: SessionExecutionOwner | None = None

    def bind_execution_owner(self, owner: SessionExecutionOwner) -> None:
        """Bind this resolved Toolkit to one immutable Session owner."""
        if accepts_execution_owner(
            self._execution_owner,
            owner,
            session_id=self._session_id,
        ):
            self.session_manager = OwnerBoundSessionManager(
                session_manager=self.session_manager,
                session_id=owner.session_id,
                owner_generation=owner.owner_generation,
            )
            self._execution_owner = owner

    def bind_execution_authority(
        self,
        authority: SessionResourceAuthority,
    ) -> None:
        """Validate full resource identity and bind its durable owner."""
        if authority.agent_id != self._agent_id:
            raise ValueError("Execution authority Agent does not match Toolkit")
        self.bind_execution_owner(authority.execution_owner)

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
        tools: list[FunctionTool] = []
        if self._config.memory_enabled:
            operations = _memory_operations(
                session_manager=self.session_manager,
                memory_repository=self.memory_repo,
            )
            associated_user_id = await _resolve_associated_user_id(
                operations=operations,
                session_id=self._session_id,
            )
            tools.extend(
                [
                    make_save_memory_tool(
                        self.memory_repo,
                        self._agent_id,
                        self.session_manager,
                        associated_user_id=associated_user_id,
                    ),
                    make_delete_memory_tool(
                        self.memory_repo,
                        self._agent_id,
                        self.session_manager,
                        associated_user_id=associated_user_id,
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


class ReadableStorageToolkit(Toolkit[ShellToolkitConfig]):
    """Runtime-independent generic read, grep, and glob capability."""

    def __init__(
        self,
        config: ShellToolkitConfig,
        agent_id: str,
        session_id: str,
        session_manager: SessionManager[AsyncSession],
        memory_repo: MemoryRepository,
        vfs_read_router: VfsReadRouter,
    ) -> None:
        self._config = config
        self._agent_id = agent_id
        self._session_id = session_id
        self.session_manager = session_manager
        self.memory_repo = memory_repo
        self.vfs_read_router = vfs_read_router
        self.runtime_capability_resolver: RuntimeCapabilityResolver | None = None
        self.runtime_storage_provider: RuntimeReadableStorageProvider | None = None
        self._execution_owner: SessionExecutionOwner | None = None
        self._execution_authority: SessionResourceAuthority | None = None

    def bind_execution_owner(self, owner: SessionExecutionOwner) -> None:
        """Bind execution-owned read state to one concrete Session owner."""
        if accepts_execution_owner(
            self._execution_owner,
            owner,
            session_id=self._session_id,
        ):
            self.session_manager = OwnerBoundSessionManager(
                session_manager=self.session_manager,
                session_id=owner.session_id,
                owner_generation=owner.owner_generation,
            )
            self._execution_owner = owner

    def bind_execution_authority(
        self,
        authority: SessionResourceAuthority,
    ) -> None:
        """Bind the exact current Run and durable Session execution owner."""
        if authority.agent_id != self._agent_id:
            raise ValueError("Execution authority Agent does not match Toolkit")
        if authority.session_id != self._session_id:
            raise ValueError("Execution authority Session does not match Toolkit")
        self.bind_execution_owner(authority.execution_owner)
        self._execution_authority = authority

    def set_runtime_capability_resolver(
        self,
        resolver: RuntimeCapabilityResolver,
    ) -> None:
        """Set Runtime filesystem capability admission for absolute paths."""
        self.runtime_capability_resolver = resolver

    def set_runtime_storage_provider(
        self,
        provider: RuntimeReadableStorageProvider,
    ) -> None:
        """Attach the Runtime Toolkit bridge when Runtime tools are available."""
        self.runtime_storage_provider = provider

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Return generic read tools independently of Runtime availability."""
        if context.resource_authority is not None:
            self.bind_execution_authority(context.resource_authority)
        authority = context.resource_authority or self._execution_authority
        resolver = self.runtime_capability_resolver
        if authority is None or resolver is None:
            return ToolkitState(status=ToolkitStatus.DISABLED, tools=[])
        operations = _memory_operations(
            session_manager=self.session_manager,
            memory_repository=self.memory_repo,
        )
        associated_user_id = await _resolve_associated_user_id(
            operations=operations,
            session_id=authority.root_session_id,
        )
        vfs_context = VfsReadContext(
            run_id=authority.run_id,
            session_id=authority.session_id,
            root_session_id=authority.root_session_id,
            agent_id=authority.agent_id,
            workspace_id=authority.workspace_id,
            associated_user_id=associated_user_id,
            owner_generation=authority.owner_generation,
            memory_enabled=self._config.memory_enabled,
        )
        provider = self.runtime_storage_provider
        storage = RoutedReadableStorage(
            agent_id=self._agent_id,
            vfs_router=self.vfs_read_router,
            vfs_context=vfs_context,
            runtime_storage_factory=(
                provider.make_readable_storage if provider is not None else None
            ),
            runtime_capability_resolver=resolver,
        )
        runtime_mutations = (
            provider.make_mutation_tools()
            if isinstance(provider, RuntimeMutationToolProvider)
            else []
        )
        mutation_router = VfsMutationRouter(
            registry=VfsMutationRegistry(
                [
                    VfsBackendRegistration(
                        read_backend=self.vfs_read_router.registry.get(mount),
                        mutation_backend=None,
                        patch_backend=None,
                        capabilities=VfsMutationCapabilities(False, False),
                    )
                    for mount in self.vfs_read_router.registry.mounts
                ]
            ),
            authority_validator=self.vfs_read_router.authority_validator,
        )
        mutation_tools = RoutedMutationTools(
            principal=vfs_context,
            router=mutation_router,
            runtime_tools={tool.spec.name: tool for tool in runtime_mutations},
            execution_context_provider=get_client_tool_execution_context,
        ).tools()
        return ToolkitState(
            status=ToolkitStatus.ENABLED,
            tools=[
                make_read_text_tool(
                    session_storage=storage,
                    agent_id=self._agent_id,
                ),
                make_glob_tool(
                    session_storage=storage,
                    agent_id=self._agent_id,
                ),
                make_grep_tool(
                    session_storage=storage,
                    agent_id=self._agent_id,
                ),
                *mutation_tools,
            ],
        )


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
        self._execution_owner: SessionExecutionOwner | None = None

    def bind_execution_owner(self, owner: SessionExecutionOwner) -> None:
        """Bind this resolved Toolkit to one immutable Session owner."""
        if accepts_execution_owner(
            self._execution_owner,
            owner,
            session_id=self._session_id,
        ):
            self.session_manager = OwnerBoundSessionManager(
                session_manager=self.session_manager,
                session_id=owner.session_id,
                owner_generation=owner.owner_generation,
            )
            self._execution_owner = owner

    def bind_execution_authority(
        self,
        authority: SessionResourceAuthority,
    ) -> None:
        """Validate full resource identity and bind its durable owner."""
        if authority.agent_id != self._agent_id:
            raise ValueError("Execution authority Agent does not match Toolkit")
        self.bind_execution_owner(authority.execution_owner)

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

        tools: list[FunctionTool] = []
        if config.memory_enabled:
            tools.extend(
                [
                    make_save_memory_tool(
                        self.memory_repo,
                        agent_id,
                        self.session_manager,
                    ),
                    make_delete_memory_tool(
                        self.memory_repo,
                        agent_id,
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
        return "\n\n".join(
            (
                _MEMORY_CONTEXT_RULES_PROMPT,
                _MEMORY_WRITE_RULES_PROMPT,
            )
        )


class RuntimeEnvProvider(Protocol):
    """Runtime shell env provider protocol."""

    async def expose_env(self) -> dict[str, str]:
        """Return env vars to inject into runtime shell commands."""
        ...


_RUNTIME_OPERATIONS_UNAVAILABLE_PROMPT = (
    "Runtime-dependent operations are currently unavailable."
)


@dataclasses.dataclass(frozen=True)
class _RuntimeCapabilityGuardedPlaintextHandler:
    """Preserve plaintext-custom execution while enforcing Runtime admission."""

    original_handler: FunctionToolHandler
    require_capability: Callable[[], Awaitable[None]]

    async def __call__(self, arguments: str) -> str | FunctionToolResult:
        """Enforce capability admission before JSON-function execution."""
        await self.require_capability()
        return await self.original_handler(arguments)

    async def execute_plaintext_custom(
        self,
        arguments: str,
    ) -> str | FunctionToolResult:
        """Enforce capability admission before plaintext-custom execution."""
        await self.require_capability()
        if not isinstance(self.original_handler, PlaintextCustomToolHandler):
            raise RuntimeError(
                "Plaintext-custom Runtime guard requires a compatible handler"
            )
        return await self.original_handler.execute_plaintext_custom(arguments)


class RuntimeToolkit(AgentsAppendixMixin, Toolkit[ShellToolkitConfig]):
    """Runtime Runner dependent shell/file tool execution instance."""

    def __init__(
        self,
        config: ShellToolkitConfig,
        exchange_file_service: ExchangeFileService,
        artifact_service: ArtifactService,
        model_file_service: ModelFileService,
        vfs_projection_service: VfsProjectionService[AsyncSession] | None,
        agent_id: str,
        agents_store: AgentsAppendixDedupeStateStore,
        runner_operations: RuntimeRunnerOperationClient,
        session_manager: SessionManager[AsyncSession],
        agent_runtime_repo: AgentRuntimeRepository,
        agent_runtime_service: AgentRuntimeService,
        agent_session_repository: AgentSessionRepository,
        session_working_folder_binding_service: SessionWorkingFolderBindingService,
        project_repo: SessionWorkspaceProjectRepository,
        server_to_runtime_transfer_service: ServerToRuntimeTransferExecutor,
        runtime_image_read_service: RuntimeImageReadService | None,
        runtime_to_server_publication_service: PresentFilePublicationExecutor,
        runtime_to_provider_delivery_service: RuntimeToProviderDeliveryExecutor,
        import_file_staging_configuration: ImportFileStagingConfiguration,
        runtime_capability_resolver: RuntimeCapabilityResolver | None = None,
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
        self.agent_runtime_service = agent_runtime_service
        self.agent_session_repository = agent_session_repository
        self.session_working_folder_binding_service = (
            session_working_folder_binding_service
        )
        self.project_repo = project_repo
        self.agents_store = agents_store
        self.server_to_runtime_transfer_service = server_to_runtime_transfer_service
        self.runtime_image_read_service = runtime_image_read_service
        self.runtime_to_server_publication_service = (
            runtime_to_server_publication_service
        )
        self.runtime_to_provider_delivery_service = runtime_to_provider_delivery_service
        self.import_file_staging_configuration = import_file_staging_configuration
        self.runtime_capability_resolver = runtime_capability_resolver
        self._agents_context: RuntimeInstructionContext | None = None
        self._agents_appendix_lock = asyncio.Lock()
        self._agents_missing_cache: dict[str, float] = {}
        self.instruction_context_store: RuntimeInstructionContextStore | None = None
        self._expected_runtime_authority: RuntimeOperationAuthority | None = None
        self._run_tool_to_file_context: RunToolToFileRuntimeContext | None = None
        self._execution_owner: SessionExecutionOwner | None = None
        self._readable_file_storage: RuntimeRunnerFileStorage | None = None

    def bind_execution_owner(self, owner: SessionExecutionOwner) -> None:
        """Bind execution-owned Runtime Toolkit state to one Session owner."""
        if accepts_execution_owner(
            self._execution_owner,
            owner,
            session_id=self._session_id,
        ):
            self.session_manager = OwnerBoundSessionManager(
                session_manager=self.session_manager,
                session_id=owner.session_id,
                owner_generation=owner.owner_generation,
            )
            if isinstance(
                self.agents_store,
                ToolkitAgentsAppendixDedupeStateStore,
            ):
                self.agents_store = self.agents_store.for_execution(owner)
            self._execution_owner = owner

    def bind_execution_authority(
        self,
        authority: SessionResourceAuthority,
    ) -> None:
        """Validate full resource identity and bind its durable owner."""
        if authority.agent_id != self._agent_id:
            raise ValueError("Execution authority Agent does not match Toolkit")
        self.bind_execution_owner(authority.execution_owner)

    def set_instruction_context_store(
        self, store: RuntimeInstructionContextStore
    ) -> None:
        """Register shared Runtime instruction context store."""
        self.instruction_context_store = store

    def set_runtime_capability_resolver(
        self,
        resolver: RuntimeCapabilityResolver,
    ) -> None:
        """Set the shared Agent Runtime capability resolver."""
        self.runtime_capability_resolver = resolver

    def make_readable_storage(self) -> RuntimeRunnerFileStorage:
        """Return one lazy native Runtime storage adapter for generic file tools."""
        if self._readable_file_storage is not None:
            return self._readable_file_storage
        return RuntimeRunnerFileStorage(
            runner_operations=self.runner_operations,
            agent_runtime_repo=self.agent_runtime_repo,
            agent_runtime_service=self.agent_runtime_service,
            session_manager=self.session_manager,
            runtime_agent_id=self._runtime_agent_id,
            owner_session_id=self._runtime_session_id,
            expected_authority_provider=self._required_runtime_authority,
        )

    def make_mutation_tools(self) -> list[FunctionTool]:
        """Build native guarded adapters; storage owns generic registration."""
        storage = self.make_readable_storage()

        async def resolve_operation_target() -> RuntimeOperationTarget:
            return await _ready_runtime_for_agent(
                agent_runtime_repo=self.agent_runtime_repo,
                agent_runtime_service=self.agent_runtime_service,
                session_manager=self.session_manager,
                agent_id=self._runtime_agent_id,
                expected_authority=self._required_runtime_authority(),
            )

        async def resolve_edit_target() -> RuntimeEditTarget:
            runtime = await resolve_operation_target()
            return RuntimeEditTarget(
                runtime_id=runtime.id, runner_generation=runtime.runner_generation
            )

        async def resolve_patch_target() -> RuntimePatchTarget:
            runtime = await resolve_operation_target()
            return RuntimePatchTarget(
                runtime_id=runtime.id, runner_generation=runtime.runner_generation
            )

        tools = [
            make_apply_patch_tool(
                runner_operations=self.runner_operations,
                resolve_runtime_target=resolve_patch_target,
                owner_session_id=self._runtime_session_id,
                agent_id=self._runtime_agent_id,
            ),
            _with_runtime_native_file_tool_diagnostics(
                make_edit_tool(
                    runner_operations=self.runner_operations,
                    resolve_runtime_target=resolve_edit_target,
                    owner_session_id=self._runtime_session_id,
                    agent_id=self._runtime_agent_id,
                ),
                agent_id=self._runtime_agent_id,
                owner_session_id=self._runtime_session_id,
            ),
            *[
                _with_runtime_file_tool_diagnostics(
                    tool,
                    file_storage=storage,
                    agent_id=self._runtime_agent_id,
                    owner_session_id=self._runtime_session_id,
                )
                for tool in [
                    make_write_tool(session_storage=storage, agent_id=self._agent_id),
                    make_delete_file_tool(
                        session_storage=storage, agent_id=self._agent_id
                    ),
                ]
            ],
        ]
        return [
            self._guard_runtime_tool(tool, RuntimeCapability.RUNTIME_FILESYSTEM)
            for tool in tools
            if tool.spec.name not in self._excluded_tools
        ]

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

    async def _runtime_toolkit_allowed(self) -> bool:
        """Return whether the complete Runtime Toolkit may be projected."""
        resolver = self.runtime_capability_resolver
        if resolver is None:
            return False
        try:
            for capability in (
                RuntimeCapability.WORKSPACE,
                RuntimeCapability.RUNTIME_FILESYSTEM,
                RuntimeCapability.PROCESS_EXECUTION,
            ):
                await resolver.require(capability)
        except RuntimeCapabilityDeniedError:
            return False
        return True

    def _guard_runtime_tool(
        self,
        tool: FunctionTool,
        capability: RuntimeCapability,
    ) -> FunctionTool:
        """Guard one Runtime tool before any handler side effect."""
        resolver = self.runtime_capability_resolver
        original_handler = tool.handler
        original_cancel_handler = tool.cancel_handler

        async def require_capability() -> None:
            if resolver is None:
                raise FunctionToolError(
                    "Runtime capability context is unavailable.",
                    metadata={
                        "kind": "runtime_capability_denied",
                        "capability": capability.value,
                        "reason_code": "runtime_capability_context_missing",
                    },
                )
            try:
                await resolver.require(capability)
            except RuntimeCapabilityDeniedError as exc:
                raise FunctionToolError(
                    "Runtime capability is unavailable.",
                    metadata={
                        "kind": "runtime_capability_denied",
                        "capability": capability.value,
                        "reason_code": exc.reason_code,
                    },
                ) from None

        async def guarded_handler(
            arguments: str,
        ) -> str | FunctionToolResult:
            await require_capability()
            return await original_handler(arguments)

        async def guarded_cancel_handler(
            request: FunctionToolCancelRequest,
        ) -> None:
            if original_cancel_handler is None or resolver is None:
                return
            try:
                await resolver.require(capability)
            except RuntimeCapabilityDeniedError:
                return
            await original_cancel_handler(request)

        handler: FunctionToolHandler = guarded_handler
        if isinstance(original_handler, PlaintextCustomToolHandler):
            handler = _RuntimeCapabilityGuardedPlaintextHandler(
                original_handler=original_handler,
                require_capability=require_capability,
            )

        return dataclasses.replace(
            tool,
            handler=handler,
            cancel_handler=(
                guarded_cancel_handler if original_cancel_handler is not None else None
            ),
        )

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Create shell and file tools and return prompt.

        :param context: Context passed each turn
        :return: Current state (tools + prompt)
        """
        self._run_tool_to_file_context = None
        if not await self._runtime_toolkit_allowed():
            return ToolkitState(status=ToolkitStatus.DISABLED, tools=[])

        capability_resolver = self.runtime_capability_resolver
        if capability_resolver is None:
            return ToolkitState(status=ToolkitStatus.DISABLED, tools=[])
        runtime_agent_id = self._runtime_agent_id
        projection_target = await self._resolve_projection_runtime_target()
        workspace_root = (
            projection_target.workspace_path if projection_target is not None else None
        )
        projection_binding = await self._resolve_projection_binding(projection_target)
        projects = (
            sorted(
                await self._load_projects(session_id=self._session_id),
                key=lambda project: project.path,
            )
            if projection_binding is not None
            else []
        )

        file_ss = RuntimeRunnerFileStorage(
            runner_operations=self.runner_operations,
            agent_runtime_repo=self.agent_runtime_repo,
            agent_runtime_service=(self.agent_runtime_service),
            session_manager=self.session_manager,
            runtime_agent_id=runtime_agent_id,
            owner_session_id=self._runtime_session_id,
            expected_authority_provider=self._required_runtime_authority,
        )
        self._readable_file_storage = file_ss

        async def resolve_exact_runtime_target() -> RuntimeOperationTarget:
            return await _ready_runtime_for_agent(
                agent_runtime_repo=self.agent_runtime_repo,
                agent_runtime_service=(self.agent_runtime_service),
                session_manager=self.session_manager,
                agent_id=runtime_agent_id,
                expected_authority=self._required_runtime_authority(),
            )

        async def resolve_runtime_target() -> ServerToRuntimeTarget:
            runtime = await resolve_exact_runtime_target()
            return ServerToRuntimeTarget(
                runtime_id=runtime.id,
                desired_generation=runtime.desired_generation,
            )

        async def resolve_image_target() -> ServerToRuntimeTarget:
            runtime = await resolve_exact_runtime_target()
            return ServerToRuntimeTarget(
                runtime_id=runtime.id,
                desired_generation=runtime.desired_generation,
            )

        async def revalidate_resource_authority() -> bool:
            authority = context.resource_authority
            if authority is None:
                return False
            return await self.model_file_service.validate_resource_authority(authority)

        file_tools: list[FunctionTool] = []
        if context.resource_authority is not None:
            authority = context.resource_authority
            self._run_tool_to_file_context = RunToolToFileRuntimeContext(
                session_storage=file_ss,
                exchange_file_service=self.exchange_file_service,
                artifact_service=self.artifact_service,
                model_file_service=self.model_file_service,
                authority=authority,
                transfer_service=self.server_to_runtime_transfer_service,
                resolve_runtime_target=resolve_runtime_target,
                staging_configuration=self.import_file_staging_configuration,
                revalidate_authority=revalidate_resource_authority,
            )
            file_tools.extend(
                [
                    make_import_file_tool(
                        session_storage=file_ss,
                        exchange_file_service=self.exchange_file_service,
                        artifact_service=self.artifact_service,
                        vfs_projection_service=self.vfs_projection_service,
                        authority=authority,
                        transfer_service=self.server_to_runtime_transfer_service,
                        resolve_runtime_target=resolve_runtime_target,
                        staging_configuration=self.import_file_staging_configuration,
                    ),
                    make_present_file_tool(
                        session_storage=file_ss,
                        publication_service=self.runtime_to_server_publication_service,
                        resolve_runtime_target=resolve_runtime_target,
                        authority=authority,
                        workspace_root=workspace_root,
                    ),
                    make_read_image_tool(
                        session_storage=file_ss,
                        model_file_service=self.model_file_service,
                        authority=authority,
                        runtime_image_read_service=self.runtime_image_read_service,
                        resolve_runtime_target=resolve_image_target,
                    ),
                ]
            )
        tools = [
            make_exec_command_tool(
                self.runner_operations,
                agent_runtime_repo=self.agent_runtime_repo,
                agent_runtime_service=(self.agent_runtime_service),
                session_manager=self.session_manager,
                agent_id=runtime_agent_id,
                publish_event=context.publish_event,
                owner_session_id=self._session_id,
                peer_toolkits=self._peer_toolkits,
                runtime_capability_resolver=capability_resolver,
                expected_authority_provider=self._required_runtime_authority,
                resolve_working_folder_authority=(
                    self._resolve_operation_working_folder_authority
                ),
            ),
            make_write_stdin_tool(
                self.runner_operations,
                agent_runtime_repo=self.agent_runtime_repo,
                agent_runtime_service=(self.agent_runtime_service),
                session_manager=self.session_manager,
                agent_id=runtime_agent_id,
                publish_event=context.publish_event,
                owner_session_id=self._session_id,
                expected_authority_provider=self._required_runtime_authority,
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

        tools = [
            self._guard_runtime_tool(
                tool,
                (
                    RuntimeCapability.PROCESS_EXECUTION
                    if tool.spec.name in {"exec_command", "write_stdin"}
                    else (
                        RuntimeCapability.RUNTIME_TRANSFER
                        if tool.spec.name
                        in {"import_file", "present_file", "read_image"}
                        else RuntimeCapability.RUNTIME_FILESYSTEM
                    )
                ),
            )
            for tool in tools
        ]

        instruction_context = await self._make_instruction_context(
            file_ss,
            workspace_root=workspace_root,
            projects=projects,
            resolve_runtime_target=resolve_runtime_target,
        )
        self.register_agents_context(instruction_context)
        if self.instruction_context_store is not None:
            self.instruction_context_store.set(instruction_context)
        return ToolkitState(status=ToolkitStatus.ENABLED, tools=tools)

    def make_run_tool_to_file(
        self,
        binding: LateBoundClientToolInvoker,
    ) -> FunctionTool | None:
        """Build the Engine-assembled Runtime output materialization Tool."""
        context = self._run_tool_to_file_context
        if context is None:
            return None
        return self._guard_runtime_tool(
            make_run_tool_to_file_tool(binding=binding, runtime=context),
            RuntimeCapability.RUNTIME_TRANSFER,
        )

    async def get_static_prompt(self, context: TurnContext) -> str:
        """Return static runtime/files prompt for the current run."""
        if not await self._runtime_toolkit_allowed():
            return ""
        behavior = await self._load_runtime_behavior_prompt()
        self._expected_runtime_authority = behavior.expected_authority
        projection_target = await self._resolve_projection_runtime_target()
        projection_binding = await self._resolve_projection_binding(projection_target)
        projects = (
            sorted(
                await self._load_projects(session_id=self._session_id),
                key=lambda project: project.path,
            )
            if projection_binding is not None
            else []
        )
        del context
        prompt = self._render_config_prompt(
            projects=projects,
            workspace_root=(
                projection_target.workspace_path
                if projection_binding is not None and projection_target is not None
                else None
            ),
            working_folder_path=(
                projection_binding.working_folder_path
                if projection_binding is not None
                else None
            ),
        )
        if behavior.prompt:
            return f"{prompt}\n\n{behavior.prompt}"
        return prompt

    def _required_runtime_authority(self) -> RuntimeOperationAuthority:
        """Return the prompt-selected Runtime authority or fail closed."""
        authority = self._expected_runtime_authority
        if authority is None:
            raise RuntimeStorageError(_RUNTIME_OPERATIONS_UNAVAILABLE_PROMPT)
        return authority

    async def _load_runtime_behavior_prompt(
        self,
    ) -> _RuntimeBehaviorPromptResult:
        """Render behavior for the configuration serving Runtime operations."""
        loaded = await self._runtime_read_repository().load_behavior(
            agent_id=self._runtime_agent_id,
        )
        if loaded is None:
            return _RuntimeBehaviorPromptResult(
                prompt=_RUNTIME_OPERATIONS_UNAVAILABLE_PROMPT,
                expected_authority=None,
            )
        runtime = loaded.runtime
        state = loaded.configuration
        if state is None:
            return _RuntimeBehaviorPromptResult(
                prompt=_RUNTIME_OPERATIONS_UNAVAILABLE_PROMPT,
                expected_authority=None,
            )
        desired = state.desired
        applied = state.applied
        operation_configuration = desired
        if (
            applied is not None
            and applied.target_generation == runtime.desired_generation
            and runtime.desired_state is RuntimeDesiredState.RUNNING
            and runtime.runner_state is RuntimeRunnerState.READY
            and runtime.runner_generation > 0
            and runtime.workspace_path is not None
        ):
            operation_configuration = applied
        expected_authority = RuntimeOperationAuthority(
            configuration_sequence=operation_configuration.sequence,
            configuration_digest=operation_configuration.digest or "",
            desired_generation=operation_configuration.target_generation,
        )
        if (
            operation_configuration is desired
            and desired.status is not RuntimeConfigurationStateStatus.READY
        ) or (
            operation_configuration.document is None
            or operation_configuration.digest is None
            or operation_configuration.document.resolved_configuration is None
        ):
            return _RuntimeBehaviorPromptResult(
                prompt=_RUNTIME_OPERATIONS_UNAVAILABLE_PROMPT,
                expected_authority=expected_authority,
            )
        effective_profile = operation_configuration.document.resolved_configuration.get(
            "effective_profile"
        )
        if not isinstance(effective_profile, dict):
            return _RuntimeBehaviorPromptResult(
                prompt=_RUNTIME_OPERATIONS_UNAVAILABLE_PROMPT,
                expected_authority=expected_authority,
            )
        try:
            parse_runtime_infrastructure_profile_spec(effective_profile)
        except ValidationError:
            return _RuntimeBehaviorPromptResult(
                prompt=_RUNTIME_OPERATIONS_UNAVAILABLE_PROMPT,
                expected_authority=expected_authority,
            )
        return _RuntimeBehaviorPromptResult(
            prompt="",
            expected_authority=expected_authority,
        )

    async def _make_instruction_context(
        self,
        file_storage: FileStorage,
        *,
        workspace_root: str | None,
        projects: list[SessionWorkspaceProject],
        resolve_runtime_target: Callable[[], Awaitable[ServerToRuntimeTarget]],
    ) -> RuntimeInstructionContext:
        """Build shared Runtime context for instruction appendix providers."""
        return RuntimeInstructionContext(
            file_storage=file_storage,
            workspace_root=workspace_root,
            projects=tuple(projects),
            transfer_service=self.server_to_runtime_transfer_service,
            publication_service=self.runtime_to_server_publication_service,
            provider_delivery_service=self.runtime_to_provider_delivery_service,
            resolve_runtime_target=resolve_runtime_target,
        )

    async def _load_projects(
        self,
        *,
        session_id: str,
    ) -> list[SessionWorkspaceProject]:
        """Fetch Project list registered to AgentSession."""
        return await self._runtime_read_repository().list_projects(
            session_id=session_id,
        )

    def _runtime_read_repository(self) -> EngineRuntimeToolReadRepository:
        """Create completed Runtime Toolkit reads for this bound execution."""
        return EngineRuntimeToolReadRepository(
            session_manager=self.session_manager,
            agent_runtime_repository=self.agent_runtime_repo,
            runtime_profile_repository=(
                self.agent_runtime_service.runtime_profile_repository
            ),
            project_repository=self.project_repo,
        )

    async def _resolve_projection_runtime_target(
        self,
    ) -> RuntimeOperationTarget | None:
        """Return current qualified Runtime evidence without starting compute."""
        try:
            return await _ready_runtime_for_agent(
                agent_runtime_repo=self.agent_runtime_repo,
                agent_runtime_service=self.agent_runtime_service,
                session_manager=self.session_manager,
                agent_id=self._runtime_agent_id,
                wait_timeout_seconds=0.0,
                poll_interval_seconds=0.0,
                expected_authority=self._expected_runtime_authority,
                start_if_stopped=False,
            )
        except RuntimeStorageError:
            return None

    async def _resolve_projection_binding(
        self,
        runtime_target: RuntimeOperationTarget | None,
    ) -> SessionWorkingFolderAuthority | None:
        """Return existing current binding without mutating pending state."""
        resolver = self.runtime_capability_resolver
        if resolver is None or runtime_target is None or not self._runtime_session_id:
            return None
        try:
            await resolver.require(RuntimeCapability.WORKSPACE)
            return await (
                self.session_working_folder_binding_service.resolve_bound_authority(
                    agent_id=self._runtime_agent_id,
                    session_id=self._runtime_session_id,
                    capability_snapshot=resolver.snapshot,
                    runtime_target=runtime_target,
                )
            )
        except RuntimeCapabilityDeniedError, SessionWorkingFolderBindingError:
            return None

    async def _resolve_operation_working_folder_authority(
        self,
        runtime_target: RuntimeOperationTarget,
    ) -> SessionWorkingFolderAuthority:
        """Resolve or bind the exact Session folder for an admitted operation."""
        resolver = self.runtime_capability_resolver
        if resolver is None or not self._runtime_session_id:
            raise RuntimeStorageError(
                "Session working-folder authority is unavailable."
            )
        try:
            await resolver.require(RuntimeCapability.WORKSPACE)
            return await self.session_working_folder_binding_service.resolve_authority(
                agent_id=self._runtime_agent_id,
                session_id=self._runtime_session_id,
                capability_snapshot=resolver.snapshot,
                runtime_target=runtime_target,
            )
        except (
            RuntimeCapabilityDeniedError,
            SessionWorkingFolderBindingError,
        ) as exc:
            raise RuntimeStorageError(
                "Session working-folder authority is unavailable."
            ) from exc

    def _render_config_prompt(
        self,
        *,
        projects: list[SessionWorkspaceProject],
        workspace_root: str | None,
        working_folder_path: str | None,
    ) -> str:
        """Return domain allow/block settings and accessible scope prompt."""
        parts: list[str] = []
        scope_lines = [
            _SYSTEM_TOOL_GUIDANCE,
            "",
            "## Runtime Workspace",
            "",
            "Use absolute filesystem paths inside the runtime workspace.",
            "Prefer dedicated file tools for workspace operations: use `read`, "
            "`write`, `delete`, `glob`, `grep`, `edit`, or `apply_patch` as "
            "appropriate. Use `exec_command` for command execution and "
            "`write_stdin` to interact with a running process.",
        ]
        if working_folder_path is None or workspace_root is None:
            scope_lines.extend(
                [
                    "",
                    "Runtime paths are resolved only when a current Session binding "
                    "and Runner workspace are authorized.",
                ]
            )
        else:
            scope_lines.extend(
                [
                    "Storage locations:",
                    f"- `{working_folder_path}` — Current Session working folder. "
                    "Use this as the default workdir and for ordinary Session output.",
                    "- Project directories — Durable project-specific files and "
                    "instructions.",
                    "- `/tmp/` — Temporary scratch space for the current runtime "
                    "instance",
                    f"- `{workspace_root}/` — Agent Workspace shared across "
                    "Sessions. Use it explicitly for cross-Session or Agent-level "
                    "files.",
                    "",
                    "If the Session working folder is missing, run "
                    f"`mkdir -p {working_folder_path}` with `workdir` set "
                    f"explicitly to `{workspace_root}` before retrying.",
                ]
            )
        if projects:
            scope_lines.extend(
                [
                    "",
                    "Registered Projects:",
                    *[f"- `{project.path}`" for project in projects],
                    "",
                    "The Agent Workspace root itself is not a Project. "
                    "Project-scoped instructions only apply inside registered "
                    "Projects.",
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

    Create Runtime-independent memory and readable-storage capabilities separately
    from Runtime-dependent process, mutation, and transfer tools.
    """

    slug = "shell"
    name = "Shell"
    description = "Execute code in the agent runtime"
    system_prompt = dedent("""\
        You have access to an agent runtime shell environment.
        You can execute commands and run code.
        The runtime workspace persists across calls for this agent.

        ### Runtime Workspace

        The Agent Workspace persists across turns and is the default place for files you create or edit. `/tmp/` is temporary scratch space.

        Prefer dedicated file tools for filesystem operations: use `read`, `write`, `delete`, `glob`, `grep`, `edit`, or `apply_patch` as appropriate. Use `exec_command` for command execution, package installation, and cases where no dedicated tool fits. Use `write_stdin` with empty chars to poll a running process.

        Use the dynamic Runtime Workspace prompt for the current Agent Workspace path.""")  # noqa: E501
    config_model = ShellToolkitConfig

    def __init__(
        self,
        exchange_file_service: ExchangeFileService,
        artifact_service: ArtifactService,
        model_file_service: ModelFileService,
        vfs_projection_service: VfsProjectionService[AsyncSession] | None,
        vfs_read_router: VfsReadRouter,
        agents_store: AgentsAppendixDedupeStateStore,
        session_manager: SessionManager[AsyncSession],
        memory_repo: MemoryRepository,
        memory_context_snapshot_service: MemoryContextSnapshotService,
        agent_runtime_repo: AgentRuntimeRepository,
        agent_runtime_service: AgentRuntimeService,
        runner_operations: RuntimeRunnerOperationClient,
        agent_session_repository: AgentSessionRepository,
        session_working_folder_binding_service: SessionWorkingFolderBindingService,
        project_repo: SessionWorkspaceProjectRepository,
        server_to_runtime_transfer_service: ServerToRuntimeTransferExecutor,
        runtime_image_read_service: RuntimeImageReadService | None,
        runtime_to_server_publication_service: PresentFilePublicationExecutor,
        runtime_to_provider_delivery_service: RuntimeToProviderDeliveryExecutor,
        import_file_staging_configuration: ImportFileStagingConfiguration,
    ) -> None:
        self.exchange_file_service = exchange_file_service
        self.artifact_service = artifact_service
        self.model_file_service = model_file_service
        self.vfs_projection_service = vfs_projection_service
        self.vfs_read_router = vfs_read_router
        self.session_manager = session_manager
        self.memory_repo = memory_repo
        self.memory_context_snapshot_service = memory_context_snapshot_service
        self.agent_runtime_repo = agent_runtime_repo
        self.agent_runtime_service = agent_runtime_service
        self.runner_operations = runner_operations
        self.agent_session_repository = agent_session_repository
        self.session_working_folder_binding_service = (
            session_working_folder_binding_service
        )
        self.project_repo = project_repo
        self.agents_store = agents_store
        self.server_to_runtime_transfer_service = server_to_runtime_transfer_service
        self.runtime_image_read_service = runtime_image_read_service
        self.runtime_to_server_publication_service = (
            runtime_to_server_publication_service
        )
        self.runtime_to_provider_delivery_service = runtime_to_provider_delivery_service
        self.import_file_staging_configuration = import_file_staging_configuration

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
            agent_runtime_service=(self.agent_runtime_service),
            agent_session_repository=self.agent_session_repository,
            session_working_folder_binding_service=(
                self.session_working_folder_binding_service
            ),
            project_repo=self.project_repo,
            agents_store=self.agents_store,
            server_to_runtime_transfer_service=self.server_to_runtime_transfer_service,
            runtime_image_read_service=self.runtime_image_read_service,
            runtime_to_server_publication_service=(
                self.runtime_to_server_publication_service
            ),
            runtime_to_provider_delivery_service=(
                self.runtime_to_provider_delivery_service
            ),
            import_file_staging_configuration=self.import_file_staging_configuration,
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

    async def resolve_memory_context(
        self,
        config: ShellToolkitConfig,
        context: ResolveContext,
    ) -> Toolkit[ShellToolkitConfig]:
        """Return the auto-bound Memory context capability."""
        return MemoryContextToolkit(
            config=config,
            agent_id=context.agent_id,
            session_manager=self.session_manager,
            memory_context_snapshot_service=self.memory_context_snapshot_service,
        )

    async def resolve_readable_storage(
        self,
        config: ShellToolkitConfig,
        context: ResolveContext,
    ) -> Toolkit[ShellToolkitConfig]:
        """Return the auto-bound Runtime-independent generic read capability."""
        return ReadableStorageToolkit(
            config=config,
            agent_id=context.agent_id,
            session_id=context.session_id,
            session_manager=self.session_manager,
            memory_repo=self.memory_repo,
            vfs_read_router=self.vfs_read_router,
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
    agent_runtime_service: AgentRuntimeService,
    session_manager: SessionManager[AsyncSession] | None,
    agent_id: str,
    wait_timeout_seconds: float | None = None,
    poll_interval_seconds: float = _RUNTIME_READY_POLL_INTERVAL_SECONDS,
    expected_authority: RuntimeOperationAuthority | None = None,
    start_if_stopped: bool = True,
) -> RuntimeOperationTarget:
    """Resolve one exact qualified Runtime operation target."""
    if session_manager is None:
        raise RuntimeStorageError("Runtime database session is not configured")
    del agent_runtime_repo
    wait_timeout_seconds = (
        _RUNTIME_READY_WAIT_TIMEOUT_SECONDS
        if wait_timeout_seconds is None
        else wait_timeout_seconds
    )
    return await agent_runtime_service.resolve_operation_target(
        agent_id,
        wait_timeout_seconds=wait_timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        expected_authority=expected_authority,
        start_if_stopped=start_if_stopped,
    )


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
        agent_runtime_service: AgentRuntimeService,
        session_manager: SessionManager[AsyncSession] | None,
        runtime_agent_id: str,
        owner_session_id: str | None,
        expected_authority_provider: Callable[[], RuntimeOperationAuthority | None]
        | None = None,
    ) -> None:
        self.runner_operations = runner_operations
        self.agent_runtime_repo = agent_runtime_repo
        self.agent_runtime_service = agent_runtime_service
        self.session_manager = session_manager
        self.runtime_agent_id = runtime_agent_id
        self.owner_session_id = owner_session_id
        self.expected_authority_provider = expected_authority_provider or (lambda: None)
        self._runtime: RuntimeOperationTarget | None = None
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

    async def get_text(
        self,
        path: str,
        *,
        agent_id: str,
        offset: int,
        limit: int,
        encoding: str,
    ) -> TextReadResult:
        """Read one bounded decoded character range through the Runtime Runner."""
        runtime = await self._ready_runtime(agent_id)
        try:
            self._count_runtime_operation()
            result = await self.runner_operations.read_text_file(
                runtime_id=runtime.id,
                runner_generation=runtime.runner_generation,
                owner_session_id=self.owner_session_id,
                path=path,
                character_offset=offset,
                max_characters=limit,
                encoding=encoding,
                deadline_at=_runtime_file_operation_deadline(),
            )
            return TextReadResult(
                text=result.text,
                start_character=result.start_character,
                end_character=result.end_character,
                truncated=result.truncated,
            )
        except RuntimeRunnerOperationFailedError as exc:
            if exc.code == "FILE_READ_TEXT_DECODE_ERROR":
                raise UnicodeDecodeError(
                    encoding,
                    b"",
                    0,
                    0,
                    "Runtime file range cannot be decoded",
                ) from exc
            if exc.code == "FILE_READ_TEXT_UNSUPPORTED_ENCODING":
                raise LookupError(f"Unsupported text encoding: {encoding}") from exc
            _raise_storage_error(exc)
        except (
            RuntimeRunnerOperationUnavailable,
            RuntimeRunnerOperationGenerationError,
        ) as exc:
            raise RuntimeStorageError(str(exc)) from exc

    async def read_range(
        self,
        path: str,
        *,
        agent_id: str,
        offset: int,
        max_bytes: int,
    ) -> bytes:
        """Read one bounded file range through the Runtime Runner."""
        if offset < 0 or max_bytes <= 0:
            raise ValueError("Runtime file range must be positive and non-negative.")
        runtime = await self._ready_runtime(agent_id)
        try:
            self._count_runtime_operation()
            result = await self.runner_operations.read_file(
                runtime_id=runtime.id,
                runner_generation=runtime.runner_generation,
                owner_session_id=self.owner_session_id,
                path=path,
                offset=offset,
                max_bytes=max_bytes,
                deadline_at=_runtime_file_operation_deadline(),
            )
            return result.data
        except RuntimeRunnerOperationFailedError as exc:
            _raise_storage_error(exc)
        except (
            RuntimeRunnerOperationUnavailable,
            RuntimeRunnerOperationGenerationError,
        ) as exc:
            raise RuntimeStorageError(str(exc)) from exc

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
        media_type: str | None = None,
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
            media_type=media_type or guess_media_type(path),
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
        exclude_patterns: List[str] | None = None,
        include_directories: bool = False,
    ) -> List[RuntimeAttachment]:
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
        exclude_patterns: List[str] | None,
    ) -> GlobResult:
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
        return GlobResult(
            files=tuple(
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
            ),
            truncated=False,
        )

    async def list_dirs(self, path: str, *, agent_id: str) -> List[str]:
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
        exclude_patterns: List[str] | None = None,
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
            stopped_reason=result.stopped_reason,
        )

    def begin_runtime_operation_count(self) -> Token[int | None]:
        """Start one visible tool with a freshly fenced Runtime snapshot."""
        self._runtime = None
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

    async def _ready_runtime(self, agent_id: str) -> RuntimeOperationTarget:
        del agent_id
        runtime = self._runtime
        if runtime is not None:
            return runtime
        async with self._runtime_lock:
            runtime = self._runtime
            if runtime is None:
                runtime = await _ready_runtime_for_agent(
                    agent_runtime_repo=self.agent_runtime_repo,
                    agent_runtime_service=(self.agent_runtime_service),
                    session_manager=self.session_manager,
                    agent_id=self.runtime_agent_id,
                    expected_authority=self.expected_authority_provider(),
                )
                self._runtime = runtime
            return runtime

    async def _list_entries(
        self,
        runtime: RuntimeOperationTarget,
        path: str,
        *,
        recursive: bool = False,
        exclude_patterns: List[str] | None = None,
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
    agent_runtime_service: AgentRuntimeService,
    session_manager: SessionManager[AsyncSession] | None,
    agent_id: str,
    publish_event: Callable[[EngineEvent], Awaitable[None]],
    owner_session_id: str,
    runtime_capability_resolver: RuntimeCapabilityResolver,
    expected_authority_provider: Callable[[], RuntimeOperationAuthority | None],
    resolve_working_folder_authority: Callable[
        [RuntimeOperationTarget],
        Awaitable[SessionWorkingFolderAuthority],
    ],
    peer_toolkits: Sequence[RuntimeEnvProvider] = (),
) -> FunctionTool:
    """Create an exec_command tool backed by Runtime Runner process operations."""

    async def handler(args: ExecCommandInput) -> FunctionToolResult:
        try:
            runtime = await _ready_runtime_for_agent(
                agent_runtime_repo=agent_runtime_repo,
                agent_runtime_service=(agent_runtime_service),
                session_manager=session_manager,
                agent_id=agent_id,
                expected_authority=expected_authority_provider(),
            )
            workdir = args.workdir
            if workdir is None:
                binding = await resolve_working_folder_authority(runtime)
                workdir = binding.working_folder_path
            try:
                await runtime_capability_resolver.require(
                    RuntimeCapability.RUNTIME_CREDENTIALS
                )
            except RuntimeCapabilityDeniedError as exc:
                raise FunctionToolError(
                    "Runtime credential capability is unavailable.",
                    metadata={
                        "kind": "runtime_capability_denied",
                        "capability": RuntimeCapability.RUNTIME_CREDENTIALS.value,
                        "reason_code": exc.reason_code,
                    },
                ) from None
            secret_env = await _collect_secret_env(peer_toolkits, agent_id)
            await publish_event(RuntimeReadyEvent())
            result = await runner_operations.start_process(
                runtime_id=runtime.id,
                runner_generation=runtime.runner_generation,
                command=args.command,
                workdir=workdir,
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
                exc_info=True,
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
            agent_runtime_service=agent_runtime_service,
            session_manager=session_manager,
            agent_id=agent_id,
            owner_session_id=owner_session_id,
        ),
    )


def make_write_stdin_tool(
    runner_operations: RuntimeRunnerOperationClient,
    *,
    agent_runtime_repo: AgentRuntimeRepository,
    agent_runtime_service: AgentRuntimeService,
    session_manager: SessionManager[AsyncSession] | None,
    agent_id: str,
    publish_event: Callable[[EngineEvent], Awaitable[None]],
    owner_session_id: str,
    expected_authority_provider: Callable[[], RuntimeOperationAuthority | None],
) -> FunctionTool:
    """Create a write_stdin tool backed by Runtime Runner process operations."""

    async def handler(args: WriteStdinInput) -> FunctionToolResult:
        try:
            runtime = await _ready_runtime_for_agent(
                agent_runtime_repo=agent_runtime_repo,
                agent_runtime_service=(agent_runtime_service),
                session_manager=session_manager,
                agent_id=agent_id,
                expected_authority=expected_authority_provider(),
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
                exc_info=True,
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
            agent_runtime_service=agent_runtime_service,
            session_manager=session_manager,
            agent_id=agent_id,
            owner_session_id=owner_session_id,
        ),
    )


def _make_process_cancel_handler(
    *,
    runner_operations: RuntimeRunnerOperationClient,
    agent_runtime_repo: AgentRuntimeRepository,
    agent_runtime_service: AgentRuntimeService,
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
                agent_runtime_service=(agent_runtime_service),
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
