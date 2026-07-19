"""ReAct loop engine.

Receives session events and tools, loops over model adapter and tool execution,
and returns final response. Conversation history is managed as event transcript,
and a streaming interface is provided.
"""

import dataclasses
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, NamedTuple, Protocol, TypeVar

from azents.core.enums import LLMModelDeveloper, LLMProvider
from azents.core.inference_profile import SessionInferenceState
from azents.core.llm_catalog import ModelCapabilities
from azents.core.tools import PublishEventFn, Toolkit
from azents.engine.context.window import compute_effective_context_window_tokens
from azents.engine.events.types import Event
from azents.engine.io.user_input import RunUserMessage
from azents.engine.run.emit import Emit
from azents.engine.run.model_transport import ModelTransportState
from azents.engine.run.types import (
    BuiltinToolSpec,
    CheckStop,
    PollMessages,
)

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

# ---------------------------------------------------------------------------
# Request/response
# ---------------------------------------------------------------------------


class ToolkitBinding(NamedTuple):
    """Toolkit binding injected into Engine.

    :param toolkit: Toolkit instance
    :param slug: Logging/toolkit_prompts label identifier; may be empty
    :param use_prefix: When True, apply ``{slug}__`` prefix to tool names.
        Single-instance builtin toolkits use False;
        DB-registered MCP toolkits where the same user can connect multiple
        instances use True to prevent namespace collisions.
    :param toolkit_type: ``toolkit_type`` of DB-registered toolkit
        (``at.toolkit_type``). Builtin,
        schedule and other worker dynamic or auto-bound toolkits use None.
    """

    toolkit: Toolkit[Any]
    slug: str
    use_prefix: bool
    toolkit_type: str | None = None


@dataclasses.dataclass(frozen=True)
class RunRequest:
    """Engine run request.

    Describes what to run, such as model/session/tools.
    Runtime context is separated into RunContext.
    """

    session_id: str
    user_messages: list[RunUserMessage]
    agent_prompt: str | None
    toolkits: list[ToolkitBinding]
    """List of (toolkit, slug, use_prefix). config is bound to toolkit."""
    model: str
    credential_kwargs: dict[str, object]
    workspace_id: str
    agent_id: str
    tool_search_enabled: bool
    auto_compaction_threshold_tokens: int | None
    """Exact auto-compaction threshold, or None to derive it from input limits."""
    inference_state: SessionInferenceState | None
    """Exact Session inference snapshot applied to this model-call turn."""
    compaction_provider_integration_id: str | None
    """Provider integration used by the compaction model, when configured."""
    model_capabilities: ModelCapabilities = dataclasses.field(
        default_factory=ModelCapabilities,
    )
    provider: LLMProvider = LLMProvider.OPENAI
    """LLM provider. Received explicitly instead of inferring from prefix in ``model``.

    Used for Event model adapter branching and builtin tools compatibility decisions.
    Default ``OPENAI`` preserves compatibility with legacy tests; real call path
    (resolve.py) sets this explicitly.
    """
    model_developer: LLMModelDeveloper | None = None
    """Upstream LLM model developer, not provider-specific host."""
    temperature: float | None = None
    max_output_tokens: int | None = None
    top_p: float | None = None
    stop: list[str] | None = None
    reasoning_effort: str | None = None
    builtin_tools: list[BuiltinToolSpec] = dataclasses.field(
        default_factory=list[BuiltinToolSpec],
    )
    max_input_tokens: int = 128_000
    context_window_tokens: int | None = None
    """Selected model option context cap. None means no override."""
    max_turns: int | None = None
    """SDK Runner max_turns. None means no turn limit."""
    compaction_model: str | None = None
    """LiteLLM model string for compaction summary. None uses main model."""
    compaction_provider: LLMProvider | None = None
    """Provider for compaction summary. None uses main provider."""
    compaction_credential_kwargs: dict[str, object] | None = None
    """Credentials for compaction summary. None uses main credentials."""
    compaction_max_input_tokens: int | None = None
    """max_input_tokens of compaction model. None uses main model basis."""
    storage_session_id: str | None = None
    """session_id for file storage. None uses session_id.

    Alternate storage boundaries can specify a different session_id.
    """
    storage_agent_id: str | None = None
    """agent_id for file storage. None uses agent_id.

    Alternate storage boundaries can specify a different agent_id.
    """
    storage_path_prefix: str = ""
    """Path prefix prepended to file names during file storage.

    Used to distinguish files for alternate storage boundaries.
    """

    @property
    def effective_max_input_tokens(self) -> int:
        """max_input_tokens used to calculate compaction threshold.

        Use the smallest context window among main model, compaction model, and
        optional Agent context window cap.
        """
        return compute_effective_context_window_tokens(
            main_max_input_tokens=self.max_input_tokens,
            compaction_max_input_tokens=self.compaction_max_input_tokens,
            context_window_tokens=self.context_window_tokens,
        ).effective_max_input_tokens

    @property
    def effective_storage_session_id(self) -> str:
        """session_id to use for file storage."""
        if self.storage_session_id is not None:
            return self.storage_session_id
        return self.session_id

    @property
    def effective_storage_agent_id(self) -> str:
        """agent_id to use for file storage."""
        if self.storage_agent_id is not None:
            return self.storage_agent_id
        return self.agent_id


class ToolAdmissionBarrier(Protocol):
    """Serialize foreground tool admission against worker shutdown."""

    @property
    def closed(self) -> bool:
        """Return whether TERM has closed foreground admission."""
        ...

    async def run_if_open(self, action: Callable[[], Awaitable[None]]) -> bool:
        """Run one admission action unless shutdown already closed the barrier."""
        ...


@dataclasses.dataclass(frozen=True)
class RunContext:
    """Runtime context.

    Describes "who runs and how events are published".
    Separated from RunRequest (what to run) so worker can inject runtime information
    not yet decided at resolve time.

    :param user_id: User ID; None for unlinked user or system context
    :param run_id: Unique ID for message processing unit
    :param publish_event: Engine event publish callback
    """

    user_id: str | None
    run_id: str
    owner_generation: int
    tool_admission_barrier: ToolAdmissionBarrier
    model_transport_state: ModelTransportState
    publish_event: PublishEventFn


class AgentEngineProtocol(Protocol):
    """Agent engine contract depended on by worker/service."""

    async def save_error_message(
        self,
        session_id: str,
        content: str,
    ) -> Event:
        """Save error message to session."""
        ...

    def compact(self, request: RunRequest, context: RunContext) -> AsyncIterator[Emit]:
        """Run manual compaction."""
        ...

    def run(
        self,
        request: RunRequest,
        context: RunContext,
        *,
        poll_messages: PollMessages | None = None,
        check_stop: CheckStop | None = None,
    ) -> AsyncIterator[Emit]:
        """Run Agent run."""
        ...
