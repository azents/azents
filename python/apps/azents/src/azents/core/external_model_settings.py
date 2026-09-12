"""Provider-neutral private shared-model settings contracts."""

import datetime
import enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from azents.core.enums import ExternalChannelProvider
from azents.core.inference_profile import RequestedInferenceProfile
from azents.core.llm_catalog import ModelReasoningEffort
from azents.core.model_execution_options import (
    ModelExecutionOptionDefinition,
    ModelExecutionOptionId,
)


class ExternalModelSettingsRejectionCode(enum.StrEnum):
    """Safe reason codes for unavailable private model settings."""

    ACTOR_MISMATCH = "actor_mismatch"
    DRAFT_EXPIRED = "draft_expired"
    DRAFT_NOT_FOUND = "draft_not_found"
    LINK_REQUIRED = "link_required"
    ACCOUNT_UNAVAILABLE = "account_unavailable"
    MEMBERSHIP_REQUIRED = "membership_required"
    PARTICIPATION_DENIED = "participation_denied"
    TARGET_UNAVAILABLE = "target_unavailable"
    MODEL_OPTION_UNAVAILABLE = "model_option_unavailable"


class ExternalModelNoticeOutcome(enum.StrEnum):
    """Observed outcome of the one permitted post-commit notice attempt."""

    UNKNOWN = "unknown"
    DELIVERED = "delivered"
    FAILED = "failed"


class ExternalModelActorContext(BaseModel):
    """Verified provider actor identity accepted from signed ingress."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: ExternalChannelProvider
    connection_id: str = Field(min_length=1, max_length=32)
    configuration_generation: int = Field(ge=1)
    principal_id: str = Field(min_length=1, max_length=32)
    provider_tenant_id: str = Field(min_length=1, max_length=255)
    provider_user_id: str = Field(min_length=1, max_length=255)
    provider_display_name: str = Field(min_length=1, max_length=255)


class ExternalModelTargetContext(BaseModel):
    """Exact connected conversation target selected by provider settings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    binding_id: str = Field(min_length=1, max_length=32)
    session_id: str = Field(min_length=1, max_length=32)
    agent_id: str = Field(min_length=1, max_length=32)


class ExternalModelOption(BaseModel):
    """One authorized Agent option represented by a draft-scoped opaque ID."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    option_id: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=80)
    model_display_name: str = Field(min_length=1, max_length=255)
    reasoning_efforts: list[ModelReasoningEffort]
    execution_options: list[ModelExecutionOptionDefinition]


class ExternalModelOptionPage(BaseModel):
    """Bounded private page of currently authorized model options."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    items: list[ExternalModelOption]
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=25)
    total_count: int = Field(ge=0)


class ExternalModelDraftSelection(BaseModel):
    """Typed private draft selection submitted by a provider control."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    option_id: str = Field(min_length=1, max_length=64)
    reasoning_effort: ModelReasoningEffort | None
    enabled_execution_options: list[ModelExecutionOptionId]


class ExternalModelDraft(BaseModel):
    """Actor- and interaction-owned private model selection draft."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=32)
    owner_interaction_key: str = Field(min_length=1, max_length=128)
    target: ExternalModelTargetContext
    expected_generation: int = Field(ge=0)
    selection: ExternalModelDraftSelection
    selection_fingerprint: str = Field(min_length=16, max_length=16)
    expires_at: datetime.datetime


class ExternalModelEditor(BaseModel):
    """Complete private editor state safe for one verified actor."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    draft: ExternalModelDraft
    scope_label: str = Field(min_length=1, max_length=255)
    current_profile: RequestedInferenceProfile | None
    current_generation: int = Field(ge=0)
    selected_option: ExternalModelOption
    options: ExternalModelOptionPage
    effect_notice: str = Field(
        default=(
            "Saving changes the model for this whole conversation. "
            "New model calls use the saved settings; calls already started "
            "continue unchanged."
        )
    )


class ExternalModelNoticePlan(BaseModel):
    """Committed process-local public notice without private account state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mutation_id: str = Field(min_length=1, max_length=32)
    provider: ExternalChannelProvider
    connection_id: str = Field(min_length=1, max_length=32)
    provider_conversation_id: str = Field(min_length=1, max_length=512)
    provider_thread_id: str | None = Field(max_length=512)
    actor_display_name: str = Field(min_length=1, max_length=255)
    model_label: str = Field(min_length=1, max_length=80)
    model_display_name: str = Field(min_length=1, max_length=255)
    reasoning_effort: ModelReasoningEffort | None
    enabled_execution_option_labels: list[str]


class ExternalModelApplied(BaseModel):
    """Committed Apply or authorized idempotent replay result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["applied"] = "applied"
    editor: ExternalModelEditor
    created: bool
    mutation_id: str = Field(min_length=1, max_length=32)
    notice_outcome: ExternalModelNoticeOutcome


class ExternalModelStale(BaseModel):
    """Rejected stale Apply with authoritative current editor state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["stale"] = "stale"
    editor: ExternalModelEditor


class ExternalModelRejected(BaseModel):
    """Safe domain rejection that did not change the shared setting."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["rejected"] = "rejected"
    code: ExternalModelSettingsRejectionCode


class ExternalModelBusy(BaseModel):
    """Retryable infrastructure contention after the bounded retry budget."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["busy"] = "busy"
    retryable: Literal[True] = True


class ExternalModelEditorReady(BaseModel):
    """Available actor-private editor state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["ready"] = "ready"
    editor: ExternalModelEditor


class ExternalModelDraftCancelled(BaseModel):
    """Idempotent actor-owned draft cancellation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["cancelled"] = "cancelled"
    draft_id: str = Field(min_length=1, max_length=32)


ExternalModelEditorResult = Annotated[
    ExternalModelEditorReady | ExternalModelRejected | ExternalModelBusy,
    Field(discriminator="kind"),
]

ExternalModelCancelResult = Annotated[
    ExternalModelDraftCancelled | ExternalModelRejected | ExternalModelBusy,
    Field(discriminator="kind"),
]

ExternalModelApplyResult = Annotated[
    ExternalModelApplied
    | ExternalModelStale
    | ExternalModelRejected
    | ExternalModelBusy,
    Field(discriminator="kind"),
]
