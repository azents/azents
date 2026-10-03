"""Adapter-owned public model requests and attempt-local native observations."""

from __future__ import annotations

import dataclasses
import json
from typing import TYPE_CHECKING, Literal, Protocol

from pydantic import TypeAdapter
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    ModelResponseStreamEvent,
    SystemPromptPart,
)
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.settings import ModelSettings

from azents.engine.events.native_replay import native_replay_schema_version
from azents.engine.model_assembly import ModelAssemblyMetadata

if TYPE_CHECKING:
    from azents.engine.model_stream import ModelStreamCallContext
    from azents.engine.run.provider_failure import (
        ModelProviderFailure,
        UnclassifiedModelProviderError,
    )

NativeModelProtocol = Literal[
    "responses", "anthropic", "google", "bedrock", "chat_completions"
]
NativeTerminal = Literal["success", "failed", "incomplete"]

_REQUEST_PARAMETERS_ADAPTER = TypeAdapter(ModelRequestParameters)


@dataclasses.dataclass(frozen=True, repr=False)
class PydanticAIRequest:
    """One logical model request without credential or client ownership."""

    provider: str
    model: str
    messages: list[ModelMessage]
    settings: ModelSettings
    parameters: ModelRequestParameters
    assembly_metadata: ModelAssemblyMetadata | None
    native_replay_context: str | None

    def native_replay_schema_version(self) -> str:
        """Inspect the actual prepared system prefix without changing wire text."""
        instructions = None
        if self.messages and isinstance(self.messages[0], ModelRequest):
            prefixes = [
                part.content
                for part in self.messages[0].parts
                if isinstance(part, SystemPromptPart)
            ]
            if len(prefixes) == 1:
                instructions = prefixes[0]
        return native_replay_schema_version(
            instructions, native_replay_context=self.native_replay_context
        )

    def native_request_input_chars(self) -> int:
        """Inspect all logical input before any physical request is planned."""
        return (
            len(ModelMessagesTypeAdapter.dump_json(self.messages).decode("utf-8"))
            + len(json.dumps(self.settings, ensure_ascii=False, default=str))
            + len(
                _REQUEST_PARAMETERS_ADAPTER.dump_json(self.parameters).decode("utf-8")
            )
        )


@dataclasses.dataclass(frozen=True, repr=False)
class NativeErrorEvidence:
    """Typed provider-authored scalar evidence, never a raw error body."""

    message: str | None
    code: str | None
    error_type: str | None
    parameter: str | None
    status_code: int | None


@dataclasses.dataclass(frozen=True, repr=False)
class NativeModelObservation:
    """Supplementary evidence from the same single-consumed SDK stream."""

    protocol: NativeModelProtocol
    event_type: str
    parsed_activity: bool
    terminal: NativeTerminal | None
    end_turn: bool | None
    native_usage: dict[str, object] | None
    reported_cost_usd: float | None
    service_tier: str | None
    native_items: tuple[dict[str, object], ...]
    annotations: tuple[dict[str, object], ...]
    error: NativeErrorEvidence | None


@dataclasses.dataclass(frozen=True, repr=False)
class PydanticAIStreamEvent:
    """Common assembly or native progress for one authorized model dispatch."""

    event: ModelResponseStreamEvent | None
    response: ModelResponse | None
    observation: NativeModelObservation | None


class SDKFailureMapper(Protocol):
    """Normalize only SDK/provider failures at their existing safe boundary."""

    def __call__(
        self,
        error: Exception,
        *,
        call_context: ModelStreamCallContext,
    ) -> ModelProviderFailure | UnclassifiedModelProviderError:
        """Return the credential-safe original failure for one physical call."""
        ...
