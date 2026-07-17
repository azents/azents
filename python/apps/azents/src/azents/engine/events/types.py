"""Event transcript types."""

import datetime
from typing import Annotated, Literal, TypeAlias

from azcommon.types import JSONObject
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SkipValidation,
    TypeAdapter,
    model_validator,
)

from azents.core.enums import AgentRunPhase, AgentRunStatus, EventKind
from azents.core.inference_profile import (
    AppliedInferenceProfile,
    RequestedInferenceProfile,
)
from azents.engine.events.action_messages import ActionMessagePayload
from azents.engine.run.failure import (
    FailedRunFailureMetadata,
    FailedRunRetryState,
    RunRecoveryState,
)

RawDict: TypeAlias = Annotated[dict[str, object], SkipValidation]


def build_native_compat_key(
    *,
    adapter: str,
    native_format: str,
    provider: str,
    model: str,
    schema_version: str,
) -> str:
    """Create native artifact compat key."""
    return f"{adapter}:{native_format}:{provider}:{model}:{schema_version}"


class NativeArtifact(BaseModel):
    """Adapter-native opaque payload."""

    model_config = ConfigDict(frozen=True)

    compat_key: str = Field(min_length=1, description="Native replay compat key")
    adapter: str = Field(min_length=1, description="Adapter name")
    native_format: str = Field(min_length=1, description="Native format")
    provider: str = Field(min_length=1, description="Provider name")
    model: str = Field(min_length=1, description="Model name")
    schema_version: str = Field(min_length=1, description="Native schema version")
    item: RawDict = Field(description="Adapter-native opaque payload")

    @model_validator(mode="after")
    def validate_compat_key(self) -> "NativeArtifact":
        """Validate that stored compat key matches component fields."""
        expected = build_native_compat_key(
            adapter=self.adapter,
            native_format=self.native_format,
            provider=self.provider,
            model=self.model,
            schema_version=self.schema_version,
        )
        if self.compat_key != expected:
            raise ValueError("native artifact compat_key does not match fields")
        return self

    def compatible_with(self, compat_key: str) -> bool:
        """Return whether pass-through is possible with target lowerer compat key."""
        return self.compat_key == compat_key


class Attachment(BaseModel):
    """Event attachment."""

    model_config = ConfigDict(frozen=True)

    attachment_id: str = Field(min_length=1, description="Attachment ID")
    uri: str = Field(min_length=1, description="File-location URI")
    name: str = Field(min_length=1, description="Display name")
    media_type: str = Field(min_length=1, description="MIME type")
    size: int = Field(ge=0, description="Size in bytes")
    created_at: datetime.datetime = Field(description="Creation timestamp")
    source: str | None = Field(default=None, description="Attachment source")
    availability: Literal["available", "expired", "unavailable"] = "available"
    preview_title: str | None = Field(default=None)
    preview_summary: str | None = Field(default=None)
    preview_thumbnail_uri: str | None = Field(default=None)
    preview_thumbnail_media_type: str | None = Field(default=None)
    preview_thumbnail_width: int | None = Field(default=None, ge=0)
    preview_thumbnail_height: int | None = Field(default=None, ge=0)
    preview_generated_at: datetime.datetime | None = Field(default=None)


class InputTextPart(BaseModel):
    """User input text part."""

    model_config = ConfigDict(frozen=True)

    type: Literal["input_text"] = "input_text"
    text: str = Field(description="Text")


InputContentPart: TypeAlias = InputTextPart


class OutputTextPart(BaseModel):
    """Model/tool output text part."""

    model_config = ConfigDict(frozen=True)

    type: Literal["text", "output_text"] = "text"
    text: str = Field(description="Text")


class AttachmentOutputPart(BaseModel):
    """User-agent delivery envelope output part."""

    model_config = ConfigDict(frozen=True)

    type: Literal["attachment"] = "attachment"
    attachment_id: str | None = Field(default=None, description="Attachment ID")
    uri: str = Field(min_length=1, description="Exchange URI")
    name: str = Field(min_length=1, description="Display name")
    media_type: str = Field(min_length=1, description="MIME type")
    size: int = Field(ge=0, description="Size in bytes")
    preview_title: str | None = Field(default=None)
    preview_summary: str | None = Field(default=None)
    preview_thumbnail_uri: str | None = Field(default=None)
    preview_thumbnail_media_type: str | None = Field(default=None)
    preview_thumbnail_width: int | None = Field(default=None, ge=0)
    preview_thumbnail_height: int | None = Field(default=None, ge=0)
    preview_generated_at: datetime.datetime | None = Field(default=None)
    availability: Literal["available", "expired", "unavailable"] = "available"


class ArtifactOutputPart(BaseModel):
    """Agent/tool file artifact output part."""

    model_config = ConfigDict(frozen=True)

    type: Literal["artifact"] = "artifact"
    artifact_id: str = Field(min_length=1, description="Artifact ID")
    uri: str = Field(min_length=1, description="artifact:// URI")
    name: str = Field(min_length=1, description="Display name")
    media_type: str = Field(min_length=1, description="MIME type")
    size: int = Field(ge=0, description="Size in bytes")
    status: Literal["available", "expired"] = "available"
    expires_at: datetime.datetime | None = Field(default=None)


class FileOutputPart(BaseModel):
    """File part lowerable to LLM rich input."""

    model_config = ConfigDict(frozen=True)

    type: Literal["file"] = "file"
    model_file_id: str = Field(min_length=1, description="ModelFile ID")
    media_type: str = Field(min_length=1, description="MIME type")
    name: str | None = Field(default=None, description="Display name")
    size: int | None = Field(default=None, ge=0, description="Size in bytes")
    kind: Literal["image", "document", "text", "binary"] | None = Field(
        default=None,
        description="Broad file kind",
    )
    detail: str | None = Field(default=None)
    caption: str | None = Field(default=None)
    alt_text: str | None = Field(default=None)
    metadata: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def drop_provider_specific_payload(cls, data: object) -> object:
        """Remove provider-specific payload fields from persistent FilePart."""
        if not isinstance(data, dict):
            return data
        sanitized = dict(data)
        for key in ("file_data", "file_id", "base64", "data", "provider_payload"):
            sanitized.pop(key, None)
        metadata = sanitized.get("metadata")
        if isinstance(metadata, dict):
            sanitized["metadata"] = {
                str(key): str(value)
                for key, value in metadata.items()
                if key
                not in {"file_data", "file_id", "base64", "data", "provider_payload"}
            }
        return sanitized


OutputContentPart = Annotated[
    OutputTextPart | AttachmentOutputPart | ArtifactOutputPart | FileOutputPart,
    Field(discriminator="type"),
]
ToolOutputPart = OutputContentPart
ToolOutput = str | list[ToolOutputPart]
UserContentPart = Annotated[
    InputTextPart | FileOutputPart,
    Field(discriminator="type"),
]


class UserMessagePayload(BaseModel):
    """User input payload."""

    model_config = ConfigDict(frozen=True)

    content: str | list[UserContentPart] = Field(description="User content")
    attachments: list[Attachment] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)
    requested_inference_profile: RequestedInferenceProfile | None = Field(
        default=None,
        description="Immutable inference intent requested for this input",
    )
    applied_inference_profile: AppliedInferenceProfile | None = Field(
        default=None,
        description="Resolved inference settings applied by this message",
    )


class AgentMessagePayload(BaseModel):
    """Agent-to-agent mailbox message payload."""

    model_config = ConfigDict(frozen=True)

    message_kind: Literal["spawn_agent", "send_message", "followup_task"] = Field(
        description="Mailbox message kind",
    )
    source_session_agent_id: str = Field(description="Source SessionAgent ID")
    source_path: str = Field(description="Source SessionAgent path")
    target_session_agent_id: str = Field(description="Target SessionAgent ID")
    target_path: str = Field(description="Target SessionAgent path")
    content: str = Field(description="Message content")


class AssistantMessagePayload(BaseModel):
    """Assistant message payload."""

    model_config = ConfigDict(frozen=True)

    content: str | list[OutputContentPart] = Field(description="Assistant content")
    attachments: list[Attachment] = Field(default_factory=list)
    native_artifact: NativeArtifact = Field(description="Native artifact")


class ReasoningPayload(BaseModel):
    """Reasoning payload."""

    model_config = ConfigDict(frozen=True)

    text: str | None = Field(default=None)
    summary: str | None = Field(default=None)
    native_artifact: NativeArtifact = Field(description="Native artifact")


class ClientToolCallPayload(BaseModel):
    """Client tool call payload executed by Azents."""

    model_config = ConfigDict(frozen=True)

    call_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: str = Field(description="JSON string arguments")
    native_artifact: NativeArtifact = Field(description="Native artifact")


class ProviderToolCallPayload(BaseModel):
    """Provider hosted tool call payload."""

    model_config = ConfigDict(frozen=True)

    call_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: str | None = Field(default=None)
    status: Literal["running", "completed", "failed"] | None = Field(default=None)
    native_artifact: NativeArtifact = Field(description="Native artifact")


class ClientToolResultPayload(BaseModel):
    """Client tool result payload."""

    model_config = ConfigDict(frozen=True)

    call_id: str = Field(min_length=1)
    name: str | None = Field(default=None)
    status: Literal["completed", "failed", "cancelled", "interrupted"]
    output: ToolOutput = Field(default_factory=list)
    attachments: list[Attachment] = Field(default_factory=list)
    metadata: JSONObject = Field(default_factory=dict)


class ProviderToolResultPayload(BaseModel):
    """Provider hosted tool result payload."""

    model_config = ConfigDict(frozen=True)

    call_id: str = Field(min_length=1)
    name: str | None = Field(default=None)
    status: Literal["completed", "failed", "cancelled", "interrupted"]
    output: ToolOutput = Field(default_factory=list)
    attachments: list[Attachment] = Field(default_factory=list)
    native_artifact: NativeArtifact = Field(description="Native artifact")


class TokenUsagePayload(BaseModel):
    """Model token usage with adapter raw payload preserved."""

    model_config = ConfigDict(frozen=True)

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    raw: RawDict = Field(description="Adapter-native usage payload")
    cached_tokens: int | None = Field(default=None)
    cache_creation_tokens: int | None = Field(default=None)
    reasoning_tokens: int | None = Field(default=None)
    cost_usd: float | None = Field(default=None)
    raw_hidden_params: RawDict | None = Field(default=None)


class TurnMarkerPayload(BaseModel):
    """Turn marker payload."""

    model_config = ConfigDict(frozen=True)

    run_id: str = Field(min_length=1)
    usage: TokenUsagePayload
    applied_inference_profile: AppliedInferenceProfile | None = Field(default=None)
    effective_context_window_tokens: int | None = Field(default=None, gt=0)
    effective_auto_compaction_threshold_tokens: int | None = Field(
        default=None,
        gt=0,
    )
    system_prompt: "SystemPromptAnalysisPayload | None" = Field(default=None)


class SystemPromptFragmentPayload(BaseModel):
    """System prompt fragment analysis payload."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    source: Literal["agent", "toolkit", "turn_injected", "final"]
    label: str = Field(min_length=1)
    content: str
    preview: str
    length: int = Field(ge=0)
    metadata: dict[str, str] = Field(default_factory=dict)


class SystemPromptAnalysisPayload(BaseModel):
    """System prompt analysis payload for one run."""

    model_config = ConfigDict(frozen=True)

    agent_prompt: SystemPromptFragmentPayload | None = None
    toolkit_prompts: list[SystemPromptFragmentPayload] = Field(default_factory=list)
    injected_prompts: list[SystemPromptFragmentPayload] = Field(default_factory=list)
    final_prompt: SystemPromptFragmentPayload | None = None


class RunMarkerPayload(BaseModel):
    """Run marker payload."""

    model_config = ConfigDict(frozen=True)

    run_id: str = Field(min_length=1)
    status: Literal["completed", "stopped", "failed", "interrupted"]
    error: str | None = Field(default=None)


class InterruptedPayload(BaseModel):
    """User interrupt payload."""

    model_config = ConfigDict(frozen=True)

    run_id: str = Field(min_length=1)
    reason: Literal["user_requested"]


class CompactionMarkerPayload(BaseModel):
    """Compaction marker payload."""

    model_config = ConfigDict(frozen=True)

    compaction_id: str = Field(min_length=1)
    status: Literal["started", "failed"]
    reason: str | None = Field(default=None)
    error: str | None = Field(default=None)


class CompactionSummaryPayload(BaseModel):
    """Compaction summary payload."""

    model_config = ConfigDict(frozen=True)

    compaction_id: str = Field(min_length=1)
    content: str = Field(description="Summary content")
    covered_until_event_id: str | None = Field(default=None)
    reason: str | None = Field(default=None)


class GoalBriefingPayload(BaseModel):
    """Goal completion briefing payload."""

    model_config = ConfigDict(frozen=True)

    objective: str = Field(min_length=1, description="Completed goal objective")
    created_at: str = Field(min_length=1, description="Goal created timestamp")
    completed_at: str = Field(min_length=1, description="Goal completed timestamp")
    duration_seconds: int | None = Field(
        default=None,
        ge=0,
        description="Goal duration in seconds",
    )


class ActionExecutionResultPayload(BaseModel):
    """Durable action execution result payload."""

    model_config = ConfigDict(frozen=True)

    action_execution: RawDict = Field(description="Action execution projection")


class SkillLoadedPayload(BaseModel):
    """Loaded Skill payload."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, description="Skill display name")
    skill_path: str = Field(min_length=1, description="Exact SKILL.md path")
    body: str = Field(description="Full SKILL.md body")
    user_message: str = Field(description="User-authored action input")
    content_hash: str = Field(min_length=1, description="SHA-256 content hash")
    source_label: str = Field(min_length=1, description="Compact source label")
    relative_hint: str = Field(min_length=1, description="Compact relative path hint")


class SystemReminderPayload(BaseModel):
    """System reminder payload."""

    model_config = ConfigDict(frozen=True)

    text: str = Field(description="Reminder text")


class SystemErrorPayload(BaseModel):
    """System error payload."""

    model_config = ConfigDict(frozen=True)

    content: str = Field(description="Error content")
    severity: Literal["info", "warning", "error"] | None = Field(default=None)
    recoverable: bool | None = Field(default=None)
    reset_suggested: bool | None = Field(default=None)
    failure: FailedRunFailureMetadata | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )


class UnknownAdapterOutputPayload(BaseModel):
    """Unknown adapter output payload."""

    model_config = ConfigDict(frozen=True)

    native_artifact: NativeArtifact = Field(description="Native artifact")
    reason: str | None = Field(default=None)


EventPayload = (
    UserMessagePayload
    | AgentMessagePayload
    | AssistantMessagePayload
    | ReasoningPayload
    | ClientToolCallPayload
    | ClientToolResultPayload
    | ProviderToolCallPayload
    | ProviderToolResultPayload
    | TurnMarkerPayload
    | RunMarkerPayload
    | InterruptedPayload
    | CompactionMarkerPayload
    | CompactionSummaryPayload
    | GoalBriefingPayload
    | ActionMessagePayload
    | ActionExecutionResultPayload
    | SkillLoadedPayload
    | SystemReminderPayload
    | SystemErrorPayload
    | UnknownAdapterOutputPayload
)

PAYLOAD_BY_KIND: dict[EventKind, type[BaseModel]] = {
    EventKind.USER_MESSAGE: UserMessagePayload,
    EventKind.GOAL_CONTINUATION: UserMessagePayload,
    EventKind.GOAL_UPDATED: UserMessagePayload,
    EventKind.ACTION_MESSAGE: ActionMessagePayload,
    EventKind.AGENT_MESSAGE: AgentMessagePayload,
    EventKind.ACTION_EXECUTION_RESULT: ActionExecutionResultPayload,
    EventKind.SKILL_LOADED: SkillLoadedPayload,
    EventKind.GOAL_BRIEFING: GoalBriefingPayload,
    EventKind.ASSISTANT_MESSAGE: AssistantMessagePayload,
    EventKind.REASONING: ReasoningPayload,
    EventKind.CLIENT_TOOL_CALL: ClientToolCallPayload,
    EventKind.CLIENT_TOOL_RESULT: ClientToolResultPayload,
    EventKind.PROVIDER_TOOL_CALL: ProviderToolCallPayload,
    EventKind.PROVIDER_TOOL_RESULT: ProviderToolResultPayload,
    EventKind.TURN_MARKER: TurnMarkerPayload,
    EventKind.RUN_MARKER: RunMarkerPayload,
    EventKind.INTERRUPTED: InterruptedPayload,
    EventKind.COMPACTION_MARKER: CompactionMarkerPayload,
    EventKind.COMPACTION_SUMMARY: CompactionSummaryPayload,
    EventKind.SYSTEM_REMINDER: SystemReminderPayload,
    EventKind.SYSTEM_ERROR: SystemErrorPayload,
    EventKind.UNKNOWN_ADAPTER_OUTPUT: UnknownAdapterOutputPayload,
}

PAYLOAD_ADAPTER_BY_KIND: dict[EventKind, TypeAdapter[EventPayload]] = {
    kind: TypeAdapter[EventPayload](payload_type)
    for kind, payload_type in PAYLOAD_BY_KIND.items()
}


def validate_event_payload(
    kind: EventKind,
    payload: object,
) -> EventPayload:
    """Validate JSON payload with the payload model for the event kind."""
    return PAYLOAD_ADAPTER_BY_KIND[kind].validate_python(payload)


NATIVE_ARTIFACT_REQUIRED_KINDS = frozenset(
    {
        EventKind.ASSISTANT_MESSAGE,
        EventKind.REASONING,
        EventKind.CLIENT_TOOL_CALL,
        EventKind.PROVIDER_TOOL_CALL,
        EventKind.PROVIDER_TOOL_RESULT,
        EventKind.UNKNOWN_ADAPTER_OUTPUT,
    }
)
NATIVE_ARTIFACT_ABSENT_KINDS = frozenset(EventKind) - NATIVE_ARTIFACT_REQUIRED_KINDS


class Event(BaseModel):
    """Event transcript event."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=32, max_length=32)
    session_id: str = Field(min_length=1)
    kind: EventKind
    payload: EventPayload
    model_order: int = Field(default=0, description="Model input logical order")
    external_id: str | None = Field(default=None)
    adapter: str | None = Field(default=None)
    provider: str | None = Field(default=None)
    model: str | None = Field(default=None)
    native_format: str | None = Field(default=None)
    schema_version: str = Field(default="1")
    created_at: datetime.datetime

    @model_validator(mode="after")
    def validate_payload_shape(self) -> "Event":
        """Validate kind, payload type, and native artifact invariant."""
        payload_type = PAYLOAD_BY_KIND[self.kind]
        if not isinstance(self.payload, payload_type):
            raise ValueError("event payload does not match event kind")

        has_artifact = isinstance(
            self.payload,
            AssistantMessagePayload
            | ReasoningPayload
            | ClientToolCallPayload
            | ProviderToolCallPayload
            | ProviderToolResultPayload
            | UnknownAdapterOutputPayload,
        )
        if self.kind in NATIVE_ARTIFACT_REQUIRED_KINDS and not has_artifact:
            raise ValueError("event payload requires native_artifact")
        if self.kind in NATIVE_ARTIFACT_ABSENT_KINDS and has_artifact:
            raise ValueError("event payload must not include native_artifact")
        return self


class ActiveToolCall(BaseModel):
    """Active tool call exposed to UI activity."""

    model_config = ConfigDict(frozen=True)

    call_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: str | None = Field(default=None)
    started_at: datetime.datetime
    owner_generation: int = Field(ge=1)


class AgentRunState(BaseModel):
    """Durable agent run state."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=32, max_length=32)
    session_id: str = Field(min_length=1)
    run_index: int = Field(ge=1)
    phase: AgentRunPhase
    status: AgentRunStatus
    parent_agent_run_id: str | None
    retry_source_run_id: str | None = Field(default=None)
    active_tool_calls: list[ActiveToolCall] = Field(default_factory=list)
    retry_state: FailedRunRetryState | None = Field(default=None)
    recovery_state: RunRecoveryState | None = Field(default=None)
    last_completed_event_id: str | None = Field(default=None)
    terminal_result_event_id: str | None = Field(default=None)
    terminal_result_message: str | None = Field(default=None)
    stop_requested_at: datetime.datetime | None = Field(default=None)
    created_at: datetime.datetime
    started_at: datetime.datetime | None
    model_call_started_at: datetime.datetime | None
    ended_at: datetime.datetime | None = Field(default=None)
    updated_at: datetime.datetime
