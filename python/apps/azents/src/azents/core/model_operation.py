"""Durable model candidate operation state."""

from __future__ import annotations

import datetime
import enum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from azents.core.agent import (
    MAX_SELECTABLE_MODEL_CANDIDATES,
    MAX_SELECTABLE_MODEL_LABEL_LENGTH,
    AgentModelSelection,
    SelectableModelOption,
    SelectableModelSettings,
)
from azents.core.enums import LLMProvider, ModelCandidateClaimKind
from azents.core.llm_catalog import ModelReasoningEffort
from azents.core.model_execution_options import ModelExecutionOptionId

if TYPE_CHECKING:
    from azents.core.inference_profile import RequestedInferenceProfile


class ModelOperationKind(enum.StrEnum):
    """Run-owned model operation kind."""

    FOREGROUND = "foreground"
    COMPACTION = "compaction"
    TITLE = "title"


class ModelOperationCandidateRole(enum.StrEnum):
    """Candidate position role inside one frozen chain."""

    PRIMARY = "primary"
    FALLBACK = "fallback"


class ModelOperationCandidateOutcomeStatus(enum.StrEnum):
    """Current or final candidate outcome inside one model operation."""

    PENDING = "pending"
    ACTIVE = "active"
    SUCCEEDED = "succeeded"
    QUOTA_OR_BILLING = "quota_or_billing"
    COOLDOWN = "cooldown"
    PROBE_BUSY = "probe_busy"
    INCOMPATIBLE = "incompatible"


class ModelOperationCandidateOutcomeReason(enum.StrEnum):
    """Typed reason for one candidate outcome transition."""

    SELECTED = "selected"
    PRIMARY_RESERVATION = "primary_reservation"
    HALF_OPEN_PROBE = "half_open_probe"
    LOGICAL_OPERATION_COMPLETED = "logical_operation_completed"
    QUOTA_OR_BILLING = "quota_or_billing"
    ACTIVE_COOLDOWN = "active_cooldown"
    PROBE_CLAIM_BUSY = "probe_claim_busy"
    BACKGROUND_PROBE_REQUIRED = "background_probe_required"
    DUPLICATE_QUOTA_IDENTITY = "duplicate_quota_identity"
    REASONING_EFFORT_UNSUPPORTED = "reasoning_effort_unsupported"
    EXECUTION_OPTION_UNSUPPORTED = "execution_option_unsupported"


class ModelOperationTerminalReason(enum.StrEnum):
    """Operation-level terminal reason independent from candidate outcomes."""

    CHAIN_EXHAUSTED = "chain_exhausted"


_OUTCOME_REASONS: dict[
    ModelOperationCandidateOutcomeStatus,
    frozenset[ModelOperationCandidateOutcomeReason | None],
] = {
    ModelOperationCandidateOutcomeStatus.PENDING: frozenset({None}),
    ModelOperationCandidateOutcomeStatus.ACTIVE: frozenset(
        {
            ModelOperationCandidateOutcomeReason.SELECTED,
            ModelOperationCandidateOutcomeReason.PRIMARY_RESERVATION,
            ModelOperationCandidateOutcomeReason.HALF_OPEN_PROBE,
        }
    ),
    ModelOperationCandidateOutcomeStatus.SUCCEEDED: frozenset(
        {ModelOperationCandidateOutcomeReason.LOGICAL_OPERATION_COMPLETED}
    ),
    ModelOperationCandidateOutcomeStatus.QUOTA_OR_BILLING: frozenset(
        {ModelOperationCandidateOutcomeReason.QUOTA_OR_BILLING}
    ),
    ModelOperationCandidateOutcomeStatus.COOLDOWN: frozenset(
        {ModelOperationCandidateOutcomeReason.ACTIVE_COOLDOWN}
    ),
    ModelOperationCandidateOutcomeStatus.PROBE_BUSY: frozenset(
        {
            ModelOperationCandidateOutcomeReason.PROBE_CLAIM_BUSY,
            ModelOperationCandidateOutcomeReason.BACKGROUND_PROBE_REQUIRED,
        }
    ),
    ModelOperationCandidateOutcomeStatus.INCOMPATIBLE: frozenset(
        {
            ModelOperationCandidateOutcomeReason.DUPLICATE_QUOTA_IDENTITY,
            ModelOperationCandidateOutcomeReason.REASONING_EFFORT_UNSUPPORTED,
            ModelOperationCandidateOutcomeReason.EXECUTION_OPTION_UNSUPPORTED,
        }
    ),
}


def _require_aware(value: datetime.datetime) -> datetime.datetime:
    """Require a timezone-aware durable timestamp."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Durable model operation timestamps must be timezone-aware.")
    return value


class ModelOperationCandidateSnapshot(BaseModel):
    """Frozen physical model candidate used by one operation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ordinal: int = Field(ge=1, le=MAX_SELECTABLE_MODEL_CANDIDATES)
    model_selection: AgentModelSelection
    settings: SelectableModelSettings

    @property
    def role(self) -> ModelOperationCandidateRole:
        """Return the role derived from the frozen ordinal."""
        if self.ordinal == 1:
            return ModelOperationCandidateRole.PRIMARY
        return ModelOperationCandidateRole.FALLBACK


class ModelOperationCandidateOutcome(BaseModel):
    """Bounded current or final record for one candidate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_ordinal: int = Field(ge=1, le=MAX_SELECTABLE_MODEL_CANDIDATES)
    candidate_role: ModelOperationCandidateRole
    provider: LLMProvider
    llm_provider_integration_id: str = Field(min_length=1, max_length=32)
    model_identifier: str = Field(min_length=1, max_length=500)
    model_display_name: str = Field(min_length=1, max_length=500)
    status: ModelOperationCandidateOutcomeStatus
    reason: ModelOperationCandidateOutcomeReason | None
    recorded_at: datetime.datetime

    _validate_recorded_at = field_validator("recorded_at")(_require_aware)

    @model_validator(mode="after")
    def validate_reason(self) -> "ModelOperationCandidateOutcome":
        """Require the reason allowed by this outcome status."""
        if self.reason not in _OUTCOME_REASONS[self.status]:
            raise ValueError("Candidate outcome reason does not match its status.")
        return self


class TransferredModelCandidateClaim(BaseModel):
    """Fenced candidate-health claim transferred to one operation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: ModelCandidateClaimKind
    candidate_ordinal: int = Field(ge=1, le=MAX_SELECTABLE_MODEL_CANDIDATES)
    health_generation: int = Field(ge=1)
    claim_owner_id: str = Field(min_length=32, max_length=32)
    claim_token: str = Field(min_length=32, max_length=32)
    claim_until: datetime.datetime
    transferred_at: datetime.datetime

    _validate_claim_until = field_validator("claim_until")(_require_aware)
    _validate_transferred_at = field_validator("transferred_at")(_require_aware)


class ModelOperationSnapshot(BaseModel):
    """Frozen candidate chain and bounded progress for one logical operation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(default=1, ge=1, le=1)
    operation_id: str = Field(min_length=32, max_length=32)
    kind: ModelOperationKind
    semantic_label: str = Field(
        min_length=1,
        max_length=MAX_SELECTABLE_MODEL_LABEL_LENGTH,
    )
    requested_reasoning_effort: ModelReasoningEffort | None
    requested_execution_options: list[ModelExecutionOptionId]
    candidates: list[ModelOperationCandidateSnapshot] = Field(
        min_length=1,
        max_length=MAX_SELECTABLE_MODEL_CANDIDATES,
    )
    cursor: int = Field(ge=0, lt=MAX_SELECTABLE_MODEL_CANDIDATES)
    outcomes: list[ModelOperationCandidateOutcome] = Field(
        min_length=1,
        max_length=MAX_SELECTABLE_MODEL_CANDIDATES,
    )
    transferred_probe_claim: TransferredModelCandidateClaim | None
    terminal_reason: ModelOperationTerminalReason | None = None

    @field_validator("requested_execution_options")
    @classmethod
    def validate_requested_execution_options(
        cls,
        options: list[ModelExecutionOptionId],
    ) -> list[ModelExecutionOptionId]:
        """Require unique canonical execution-option ordering."""
        if len(options) != len(set(options)):
            raise ValueError("Requested execution options must be unique.")
        return sorted(options, key=lambda option: option.value)

    @model_validator(mode="after")
    def validate_chain(self) -> "ModelOperationSnapshot":
        """Validate canonical ordinals, outcomes, cursor, identities, and claim."""
        expected_ordinals = list(range(1, len(self.candidates) + 1))
        candidate_ordinals = [candidate.ordinal for candidate in self.candidates]
        if candidate_ordinals != expected_ordinals:
            raise ValueError("Model operation candidate ordinals must be contiguous.")
        if self.cursor >= len(self.candidates):
            raise ValueError("Model operation cursor is outside the candidate chain.")

        physical_identities = [
            (
                candidate.model_selection.llm_provider_integration_id,
                candidate.model_selection.model_identifier,
            )
            for candidate in self.candidates
        ]
        if len(physical_identities) != len(set(physical_identities)):
            raise ValueError(
                "Model operation candidates must have unique physical identities."
            )

        outcome_ordinals = [outcome.candidate_ordinal for outcome in self.outcomes]
        if outcome_ordinals != expected_ordinals:
            raise ValueError(
                "Model operation outcomes must match every candidate in order."
            )
        for candidate, outcome in zip(self.candidates, self.outcomes, strict=True):
            selection = candidate.model_selection
            if (
                outcome.candidate_role is not candidate.role
                or outcome.provider is not selection.provider
                or outcome.llm_provider_integration_id
                != selection.llm_provider_integration_id
                or outcome.model_identifier != selection.model_identifier
                or outcome.model_display_name != selection.model_display_name
            ):
                raise ValueError(
                    "Model operation outcome identity must match its candidate."
                )

        claim = self.transferred_probe_claim
        if claim is not None:
            if self.kind is not ModelOperationKind.FOREGROUND:
                raise ValueError(
                    "Only foreground model operations may retain a probe claim."
                )
            if claim.claim_owner_id != self.operation_id:
                raise ValueError("Transferred claim owner must match operation ID.")
            if claim.candidate_ordinal != self.cursor + 1:
                raise ValueError(
                    "Transferred claim must belong to the current candidate."
                )
        if self.terminal_reason is not None:
            if self.cursor != len(self.candidates) - 1:
                raise ValueError(
                    "Terminal model operation must remain on its final candidate."
                )
            if (
                self.terminal_reason is ModelOperationTerminalReason.CHAIN_EXHAUSTED
                and self.outcomes[self.cursor].status
                in {
                    ModelOperationCandidateOutcomeStatus.PENDING,
                    ModelOperationCandidateOutcomeStatus.ACTIVE,
                    ModelOperationCandidateOutcomeStatus.SUCCEEDED,
                }
            ):
                raise ValueError(
                    "Chain exhaustion requires a closed unsuccessful final outcome."
                )
            if self.transferred_probe_claim is not None:
                raise ValueError("Terminal model operation cannot retain a claim.")
        return self

    @property
    def current_candidate(self) -> ModelOperationCandidateSnapshot:
        """Return the candidate selected by the durable cursor."""
        return self.candidates[self.cursor]


class ModelOperationState(BaseModel):
    """Run-owned foreground and compaction operation slots."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    foreground: ModelOperationSnapshot | None
    compaction: ModelOperationSnapshot | None

    @model_validator(mode="after")
    def validate_slot_kinds(self) -> "ModelOperationState":
        """Keep each operation kind in its dedicated durable slot."""
        if (
            self.foreground is not None
            and self.foreground.kind is not ModelOperationKind.FOREGROUND
        ):
            raise ValueError("Foreground slot requires a foreground operation.")
        if (
            self.compaction is not None
            and self.compaction.kind is not ModelOperationKind.COMPACTION
        ):
            raise ValueError("Compaction slot requires a compaction operation.")
        return self


class ModelOperationChainExhaustedError(Exception):
    """Signal quota exhaustion while retaining the final operation snapshot."""

    operation: ModelOperationSnapshot

    def __init__(self, operation: ModelOperationSnapshot) -> None:
        self.operation = operation
        super().__init__(
            f"Model operation candidate chain exhausted: {operation.operation_id}"
        )


def build_model_operation(
    *,
    option: SelectableModelOption,
    profile: RequestedInferenceProfile,
    kind: ModelOperationKind,
    operation_id: str,
    recorded_at: datetime.datetime,
) -> ModelOperationSnapshot:
    """Build a frozen operation and one pending record for every candidate."""
    if option.label != profile.model_target_label:
        raise ValueError("Model operation option must match the requested label.")
    candidates = [
        ModelOperationCandidateSnapshot(
            ordinal=ordinal,
            model_selection=candidate.model_selection,
            settings=candidate.settings,
        )
        for ordinal, candidate in enumerate(option.candidates, start=1)
    ]
    outcomes = [
        _candidate_outcome(
            candidate,
            status=ModelOperationCandidateOutcomeStatus.PENDING,
            reason=None,
            recorded_at=recorded_at,
        )
        for candidate in candidates
    ]
    return ModelOperationSnapshot(
        operation_id=operation_id,
        kind=kind,
        semantic_label=option.label,
        requested_reasoning_effort=profile.reasoning_effort,
        requested_execution_options=profile.enabled_execution_options,
        candidates=candidates,
        cursor=0,
        outcomes=outcomes,
        transferred_probe_claim=None,
        terminal_reason=None,
    )


def mark_current_candidate_active(
    operation: ModelOperationSnapshot,
    *,
    reason: ModelOperationCandidateOutcomeReason,
    recorded_at: datetime.datetime,
) -> ModelOperationSnapshot:
    """Mark the current pending candidate active."""
    if reason not in _OUTCOME_REASONS[ModelOperationCandidateOutcomeStatus.ACTIVE]:
        raise ValueError("Active candidate requires an active outcome reason.")
    current = operation.outcomes[operation.cursor]
    if current.status is not ModelOperationCandidateOutcomeStatus.PENDING:
        raise ValueError("Only a pending candidate may become active.")
    return _replace_current_outcome(
        operation,
        status=ModelOperationCandidateOutcomeStatus.ACTIVE,
        reason=reason,
        recorded_at=recorded_at,
        clear_claim=False,
    )


def mark_current_candidate_quota_and_advance(
    operation: ModelOperationSnapshot,
    *,
    recorded_at: datetime.datetime,
) -> ModelOperationSnapshot:
    """Record current quota and advance or raise typed chain exhaustion."""
    current = operation.outcomes[operation.cursor]
    if current.status is not ModelOperationCandidateOutcomeStatus.ACTIVE:
        raise ValueError("Only an active candidate may record quota.")
    quota = _replace_current_outcome(
        operation,
        status=ModelOperationCandidateOutcomeStatus.QUOTA_OR_BILLING,
        reason=ModelOperationCandidateOutcomeReason.QUOTA_OR_BILLING,
        recorded_at=recorded_at,
        clear_claim=True,
    )
    if quota.cursor + 1 >= len(quota.candidates):
        exhausted = _replace_operation(
            quota,
            cursor=quota.cursor,
            outcomes=quota.outcomes,
            transferred_probe_claim=None,
            terminal_reason=ModelOperationTerminalReason.CHAIN_EXHAUSTED,
        )
        raise ModelOperationChainExhaustedError(exhausted)
    return _replace_operation(
        quota,
        cursor=quota.cursor + 1,
        outcomes=quota.outcomes,
        transferred_probe_claim=None,
        terminal_reason=None,
    )


def mark_current_candidate_skipped_and_advance(
    operation: ModelOperationSnapshot,
    *,
    status: ModelOperationCandidateOutcomeStatus,
    reason: ModelOperationCandidateOutcomeReason,
    recorded_at: datetime.datetime,
) -> ModelOperationSnapshot:
    """Close one pending unusable candidate and advance the durable cursor."""
    if status not in {
        ModelOperationCandidateOutcomeStatus.COOLDOWN,
        ModelOperationCandidateOutcomeStatus.PROBE_BUSY,
        ModelOperationCandidateOutcomeStatus.INCOMPATIBLE,
    }:
        raise ValueError("Skipped candidate requires a closed skip outcome.")
    if reason not in _OUTCOME_REASONS[status]:
        raise ValueError("Skipped candidate reason does not match its status.")
    current = operation.outcomes[operation.cursor]
    if current.status is not ModelOperationCandidateOutcomeStatus.PENDING:
        raise ValueError("Only a pending candidate may be skipped.")
    skipped = _replace_current_outcome(
        operation,
        status=status,
        reason=reason,
        recorded_at=recorded_at,
        clear_claim=True,
    )
    if skipped.cursor + 1 >= len(skipped.candidates):
        exhausted = _replace_operation(
            skipped,
            cursor=skipped.cursor,
            outcomes=skipped.outcomes,
            transferred_probe_claim=None,
            terminal_reason=ModelOperationTerminalReason.CHAIN_EXHAUSTED,
        )
        raise ModelOperationChainExhaustedError(exhausted)
    return _replace_operation(
        skipped,
        cursor=skipped.cursor + 1,
        outcomes=skipped.outcomes,
        transferred_probe_claim=None,
        terminal_reason=None,
    )


def mark_model_operation_succeeded(
    operation: ModelOperationSnapshot,
    *,
    recorded_at: datetime.datetime,
) -> ModelOperationSnapshot:
    """Mark the current active candidate as the logical operation success."""
    current = operation.outcomes[operation.cursor]
    if current.status is not ModelOperationCandidateOutcomeStatus.ACTIVE:
        raise ValueError("Only an active candidate may complete an operation.")
    return _replace_current_outcome(
        operation,
        status=ModelOperationCandidateOutcomeStatus.SUCCEEDED,
        reason=ModelOperationCandidateOutcomeReason.LOGICAL_OPERATION_COMPLETED,
        recorded_at=recorded_at,
        clear_claim=True,
    )


def set_transferred_probe_claim(
    operation: ModelOperationSnapshot,
    claim: TransferredModelCandidateClaim,
) -> ModelOperationSnapshot:
    """Attach one current-candidate claim to a foreground operation."""
    if operation.transferred_probe_claim is not None:
        raise ValueError("Model operation already owns a transferred claim.")
    return _replace_operation(
        operation,
        cursor=operation.cursor,
        outcomes=operation.outcomes,
        transferred_probe_claim=claim,
        terminal_reason=operation.terminal_reason,
    )


def clear_transferred_probe_claim(
    operation: ModelOperationSnapshot,
) -> ModelOperationSnapshot:
    """Remove a transferred claim without mutating other operation progress."""
    if operation.transferred_probe_claim is None:
        return operation
    return _replace_operation(
        operation,
        cursor=operation.cursor,
        outcomes=operation.outcomes,
        transferred_probe_claim=None,
        terminal_reason=operation.terminal_reason,
    )


def _replace_current_outcome(
    operation: ModelOperationSnapshot,
    *,
    status: ModelOperationCandidateOutcomeStatus,
    reason: ModelOperationCandidateOutcomeReason | None,
    recorded_at: datetime.datetime,
    clear_claim: bool,
) -> ModelOperationSnapshot:
    candidate = operation.current_candidate
    outcomes = list(operation.outcomes)
    outcomes[operation.cursor] = _candidate_outcome(
        candidate,
        status=status,
        reason=reason,
        recorded_at=recorded_at,
    )
    return _replace_operation(
        operation,
        cursor=operation.cursor,
        outcomes=outcomes,
        transferred_probe_claim=(
            None if clear_claim else operation.transferred_probe_claim
        ),
        terminal_reason=operation.terminal_reason,
    )


def _replace_operation(
    operation: ModelOperationSnapshot,
    *,
    cursor: int,
    outcomes: list[ModelOperationCandidateOutcome],
    transferred_probe_claim: TransferredModelCandidateClaim | None,
    terminal_reason: ModelOperationTerminalReason | None,
) -> ModelOperationSnapshot:
    return ModelOperationSnapshot(
        schema_version=operation.schema_version,
        operation_id=operation.operation_id,
        kind=operation.kind,
        semantic_label=operation.semantic_label,
        requested_reasoning_effort=operation.requested_reasoning_effort,
        requested_execution_options=operation.requested_execution_options,
        candidates=operation.candidates,
        cursor=cursor,
        outcomes=outcomes,
        transferred_probe_claim=transferred_probe_claim,
        terminal_reason=terminal_reason,
    )


def _candidate_outcome(
    candidate: ModelOperationCandidateSnapshot,
    *,
    status: ModelOperationCandidateOutcomeStatus,
    reason: ModelOperationCandidateOutcomeReason | None,
    recorded_at: datetime.datetime,
) -> ModelOperationCandidateOutcome:
    selection = candidate.model_selection
    return ModelOperationCandidateOutcome(
        candidate_ordinal=candidate.ordinal,
        candidate_role=candidate.role,
        provider=selection.provider,
        llm_provider_integration_id=selection.llm_provider_integration_id,
        model_identifier=selection.model_identifier,
        model_display_name=selection.model_display_name,
        status=status,
        reason=reason,
        recorded_at=recorded_at,
    )
