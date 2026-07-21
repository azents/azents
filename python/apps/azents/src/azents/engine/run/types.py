"""Runtime type definitions.

Defines tools, token usage, and engine callback types.
"""

import dataclasses
from collections.abc import Awaitable, Callable
from typing import Annotated, Literal, Protocol, TypeAlias

from azcommon.types import JSONObject
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SkipValidation,
)

from azents.engine.events.generated_files import GeneratedFileOutput
from azents.engine.io.attachments import RuntimeAttachment
from azents.engine.io.user_input import RunUserMessage
from azents.engine.run.client_tool_compatibility import ClientToolProfile

# ---------------------------------------------------------------------------
# Internal helper: raw passthrough dict fields.
# ---------------------------------------------------------------------------
# Pydantic creates new dicts by default when validating dict fields, breaking
# identity (`is`). Raw passthrough fields such as raw / reasoning / input_schema
# require identity preservation for LLM round-trip / tool prefix sharing behavior,
# so wrap with ``SkipValidation`` to keep dataclass-like reference behavior.
RawDict: TypeAlias = Annotated[dict[str, object], SkipValidation]

# ---------------------------------------------------------------------------
# Common types
# ---------------------------------------------------------------------------


class FunctionToolCall(BaseModel):
    """Historical client tool call projected through the legacy message API."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    arguments: str
    wire_dialect: Literal["json_function", "plaintext_custom"]


# ---------------------------------------------------------------------------
# Tool abstraction
# ---------------------------------------------------------------------------


class FunctionToolSpec(BaseModel):
    """Tool spec, schema passed to LLM.

    Three core fields shared by every LLM API:
    name, description, input_schema (JSON Schema).
    """

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    # SkipValidation because input_schema must be shared with original on
    # ``with_prefix`` call.
    input_schema: RawDict  # JSON Schema


class BuiltinToolSpec(BaseModel):
    """Selected semantic built-in capability.

    Runtime resolution decides whether the provider or an Azents client handler executes
    the capability.
    """

    model_config = ConfigDict(frozen=True)

    name: str  # "web_search", "image_generation"
    config: RawDict


class FunctionToolResult(BaseModel):
    """Structured return value from function tool handler.

    Structured tool output returns event output part list directly.
    """

    model_config = ConfigDict(frozen=True)

    output: str | list[RawDict]
    metadata: JSONObject = Field(default_factory=dict)
    generated_files: list[GeneratedFileOutput] = Field(
        default_factory=list,
        exclude=True,
        repr=False,
    )


# Async function taking JSON string args and returning string or ToolResult
FunctionToolHandler: TypeAlias = Callable[[str], Awaitable[str | FunctionToolResult]]


@dataclasses.dataclass(frozen=True)
class FunctionToolCancelRequest:
    """Cancellation request for running function tool."""

    call_id: str
    name: str
    arguments: str


FunctionToolCancelHandler: TypeAlias = Callable[
    [FunctionToolCancelRequest], Awaitable[None]
]


class SessionDataSaver(Protocol):
    """Agent data file storage interface.

    Used by engine to store LLM-generated images and similar data in storage.
    Compatible with Exchange artifact storage adapter.
    """

    async def put(
        self,
        path: str,
        data: bytes,
        media_type: str = "",
        *,
        agent_id: str,
    ) -> RuntimeAttachment:
        """Store file in storage and return RuntimeAttachment."""
        ...


@dataclasses.dataclass(frozen=True)
class FunctionTool:
    """Function tool = spec + handler.

    Combines schema seen by LLM (spec) with actual execution logic (handler).
    Unified interface independent of execution backend such as MCP or HTTP.

    handler is callable, so it is not serializable and remains dataclass.
    """

    spec: FunctionToolSpec
    handler: FunctionToolHandler
    cancel_handler: FunctionToolCancelHandler | None = None
    required_client_tool_profile: ClientToolProfile | None = None

    def with_prefix(self, prefix: str) -> "FunctionTool":
        """Return shallow copy with prefix added to name.

        Used to prevent namespace collision.
        handler and input_schema are shared with original.

        :param prefix: Prefix to prepend to name
        :return: New FunctionTool instance with prefix applied
        """
        return FunctionTool(
            spec=FunctionToolSpec(
                name=f"{prefix}{self.spec.name}",
                description=self.spec.description,
                input_schema=self.spec.input_schema,
            ),
            handler=self.handler,
            cancel_handler=self.cancel_handler,
            required_client_tool_profile=self.required_client_tool_profile,
        )

    def with_required_client_tool_profile(
        self,
        profile: ClientToolProfile,
    ) -> "FunctionTool":
        """Return a copy gated by one client tool compatibility profile."""
        return dataclasses.replace(self, required_client_tool_profile=profile)


class FunctionToolError(Exception):
    """Used by function tool to deliver error message to agent and stop call.

    Message of this exception is delivered to agent as tool result.
    For information that should not be exposed to agent, such as infra errors, raise
    a normal exception instead (engine replaces it with a generic message).
    """

    def __init__(
        self,
        message: str,
        *,
        metadata: JSONObject | None = None,
    ) -> None:
        """Create one model-visible failed tool result."""
        super().__init__(message)
        self.metadata = {} if metadata is None else dict(metadata)


class ShutdownInterruptError(Exception):
    """Raised when tool detects shutdown to prevent output storage.

    Caught before except Exception in engine.run() tool execution loop and emits
    RunStopped. Because output remains None, it is re-executed on resume. This is
    a general pattern, generic: if any tool raises this exception
    on shutdown, output is not stored and it is re-executed on resume.
    """


class TokenUsage(BaseModel):
    """Per-turn token usage.

    Stores normalized common fields together with provider raw data.

    ``cached_tokens`` are cache read tokens with discount, and ``cache_creation_tokens``
    are cache write tokens with surcharge. Anthropic pricing is create 1.25x and
    read 0.1x, so separate storage is required.

    ``cost_usd`` is call cost in USD calculated by LiteLLM
    (``_hidden_params.response_cost``), and ``raw_hidden_params`` is original
    ``_hidden_params`` used for post-analysis such as model ID, latency, provider.
    """

    model_config = ConfigDict(frozen=True)

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cached_tokens: int | None = None
    cache_creation_tokens: int | None = None
    reasoning_tokens: int | None = None
    cost_usd: float | None = None
    raw: RawDict | None = None
    raw_hidden_params: RawDict | None = None


# ---------------------------------------------------------------------------
# Message Queueing
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class PollMessagesResult:
    """Input polled at a model-call turn boundary."""

    user_messages: list[RunUserMessage]
    context_invalidated: bool
    complete_run: bool


PollMessages: TypeAlias = Callable[[], Awaitable[PollMessagesResult]]
"""Poll callback injected into engine.run(); returns turn-boundary input."""

CheckStop: TypeAlias = Callable[[], Awaitable[bool]]
"""Stop check callback injected into engine.run(). Stops execution when True."""

USER_STOP_CANCEL_MESSAGE = "azents:user_stop"
"""asyncio task cancel message identifying user stop cancellation."""

SHUTDOWN_CANCEL_MESSAGE = "azents:shutdown"
"""asyncio task cancel message identifying shutdown/handover cancellation."""
