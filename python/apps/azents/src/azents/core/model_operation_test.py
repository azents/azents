"""Durable model operation state tests."""

import datetime

import pytest
from pydantic import ValidationError

from azents.core.agent import (
    AgentModelSelection,
    SelectableModelCandidate,
    SelectableModelOption,
    SelectableModelSettings,
)
from azents.core.enums import LLMProvider, ModelCandidateClaimKind
from azents.core.inference_profile import RequestedInferenceProfile
from azents.core.model_operation import (
    ModelOperationCandidateOutcome,
    ModelOperationCandidateOutcomeReason,
    ModelOperationCandidateOutcomeStatus,
    ModelOperationCandidateRole,
    ModelOperationCandidateSnapshot,
    ModelOperationChainExhaustedError,
    ModelOperationKind,
    ModelOperationSnapshot,
    ModelOperationState,
    ModelOperationTerminalReason,
    TransferredModelCandidateClaim,
    build_model_operation,
    clear_transferred_probe_claim,
    mark_current_candidate_active,
    mark_current_candidate_quota_and_advance,
    mark_model_operation_succeeded,
    set_transferred_probe_claim,
)
from azents.testing.model_selection import make_test_model_selection_dict

_RECORDED_AT = datetime.datetime(2026, 9, 13, tzinfo=datetime.UTC)


def _candidate(ordinal: int) -> ModelOperationCandidateSnapshot:
    selection = AgentModelSelection.model_validate(
        make_test_model_selection_dict(
            integration_id=f"{ordinal:032d}",
            provider=LLMProvider.ANTHROPIC,
            model_identifier=f"model-{ordinal}",
        )
    )
    return ModelOperationCandidateSnapshot(
        ordinal=ordinal,
        model_selection=selection,
        settings=SelectableModelSettings(
            context_window_tokens=None,
            max_output_tokens=None,
            builtin_tools=[],
        ),
    )


def _outcome(
    candidate: ModelOperationCandidateSnapshot,
) -> ModelOperationCandidateOutcome:
    selection = candidate.model_selection
    return ModelOperationCandidateOutcome(
        candidate_ordinal=candidate.ordinal,
        candidate_role=candidate.role,
        provider=selection.provider,
        llm_provider_integration_id=selection.llm_provider_integration_id,
        model_identifier=selection.model_identifier,
        model_display_name=selection.model_display_name,
        status=ModelOperationCandidateOutcomeStatus.PENDING,
        reason=None,
        recorded_at=_RECORDED_AT,
    )


def _operation(
    *,
    kind: ModelOperationKind = ModelOperationKind.FOREGROUND,
    candidate_count: int = 2,
    claim: TransferredModelCandidateClaim | None = None,
) -> ModelOperationSnapshot:
    candidates = [_candidate(index) for index in range(1, candidate_count + 1)]
    return ModelOperationSnapshot(
        operation_id="1" * 32,
        kind=kind,
        semantic_label="default",
        requested_reasoning_effort=None,
        requested_execution_options=[],
        candidates=candidates,
        cursor=0,
        outcomes=[_outcome(candidate) for candidate in candidates],
        transferred_probe_claim=claim,
    )


def _option(candidate_count: int = 2) -> SelectableModelOption:
    """Create one selectable label with ordered physical candidates."""
    candidates = [_candidate(index) for index in range(1, candidate_count + 1)]
    return SelectableModelOption(
        label="default",
        candidates=[
            SelectableModelCandidate(
                model_selection=candidate.model_selection,
                settings=candidate.settings,
            )
            for candidate in candidates
        ],
        subagent_enabled=True,
        subagent_guidance=None,
    )


def _profile() -> RequestedInferenceProfile:
    """Create one semantic requested profile."""
    return RequestedInferenceProfile(
        model_target_label="default",
        reasoning_effort=None,
        enabled_execution_options=[],
    )


def test_model_operation_state_round_trips_strict_json() -> None:
    """Decode canonical nullable-slot JSON without compatibility paths."""
    state = ModelOperationState(
        foreground=_operation(),
        compaction=None,
    )

    decoded = ModelOperationState.model_validate(state.model_dump(mode="json"))

    assert decoded == state
    assert decoded.foreground is not None
    assert decoded.foreground.current_candidate.ordinal == 1


@pytest.mark.parametrize("candidate_count", [0, 6])
def test_model_operation_rejects_unbounded_candidate_count(
    candidate_count: int,
) -> None:
    """Operation chains contain one through five frozen candidates."""
    with pytest.raises(ValidationError):
        _operation(candidate_count=candidate_count)


def test_model_operation_rejects_duplicate_physical_identity() -> None:
    """A frozen operation cannot revisit one physical identity in its chain."""
    first = _candidate(1)
    duplicate = first.model_copy(update={"ordinal": 2})

    with pytest.raises(ValidationError, match="unique physical identities"):
        ModelOperationSnapshot(
            operation_id="1" * 32,
            kind=ModelOperationKind.FOREGROUND,
            semantic_label="default",
            requested_reasoning_effort=None,
            requested_execution_options=[],
            candidates=[first, duplicate],
            cursor=0,
            outcomes=[_outcome(first), _outcome(duplicate)],
            transferred_probe_claim=None,
        )


def test_model_operation_rejects_mismatched_outcome_identity() -> None:
    """Candidate outcome identity must remain tied to its frozen snapshot."""
    operation = _operation()
    payload = operation.model_dump(mode="json")
    outcomes = payload["outcomes"]
    assert isinstance(outcomes, list)
    first_outcome = outcomes[0]
    assert isinstance(first_outcome, dict)
    first_outcome["model_identifier"] = "other"

    with pytest.raises(ValidationError, match="outcome identity"):
        ModelOperationSnapshot.model_validate(payload)


def test_compaction_operation_rejects_transferred_probe_claim() -> None:
    """Background compaction cannot own a foreground recovery claim."""
    claim = TransferredModelCandidateClaim(
        kind=ModelCandidateClaimKind.PROBE,
        candidate_ordinal=1,
        health_generation=2,
        claim_owner_id="1" * 32,
        claim_token="2" * 32,
        claim_until=datetime.datetime(2026, 9, 13, 0, 5, tzinfo=datetime.UTC),
        transferred_at=_RECORDED_AT,
    )

    with pytest.raises(ValidationError, match="Only foreground"):
        _operation(kind=ModelOperationKind.COMPACTION, claim=claim)


def test_active_outcome_requires_typed_active_reason() -> None:
    """Outcome state cannot be paired with an unrelated reason."""
    candidate = _candidate(1)
    selection = candidate.model_selection

    with pytest.raises(ValidationError, match="reason does not match"):
        ModelOperationCandidateOutcome(
            candidate_ordinal=1,
            candidate_role=ModelOperationCandidateRole.PRIMARY,
            provider=selection.provider,
            llm_provider_integration_id=selection.llm_provider_integration_id,
            model_identifier=selection.model_identifier,
            model_display_name=selection.model_display_name,
            status=ModelOperationCandidateOutcomeStatus.ACTIVE,
            reason=ModelOperationCandidateOutcomeReason.QUOTA_OR_BILLING,
            recorded_at=_RECORDED_AT,
        )


def test_operation_helpers_build_advance_and_complete_frozen_chain() -> None:
    """Pure helpers replace immutable snapshots through candidate progression."""
    pending = build_model_operation(
        option=_option(),
        profile=_profile(),
        kind=ModelOperationKind.FOREGROUND,
        operation_id="1" * 32,
        recorded_at=_RECORDED_AT,
    )
    primary_active = mark_current_candidate_active(
        pending,
        reason=ModelOperationCandidateOutcomeReason.SELECTED,
        recorded_at=datetime.datetime(2026, 9, 13, 0, 0, 1, tzinfo=datetime.UTC),
    )
    fallback_pending = mark_current_candidate_quota_and_advance(
        primary_active,
        recorded_at=datetime.datetime(2026, 9, 13, 0, 0, 2, tzinfo=datetime.UTC),
    )
    fallback_active = mark_current_candidate_active(
        fallback_pending,
        reason=ModelOperationCandidateOutcomeReason.SELECTED,
        recorded_at=datetime.datetime(2026, 9, 13, 0, 0, 3, tzinfo=datetime.UTC),
    )
    succeeded = mark_model_operation_succeeded(
        fallback_active,
        recorded_at=datetime.datetime(2026, 9, 13, 0, 0, 4, tzinfo=datetime.UTC),
    )

    assert pending.cursor == 0
    assert pending.outcomes[0].status is ModelOperationCandidateOutcomeStatus.PENDING
    assert fallback_pending.cursor == 1
    assert (
        fallback_pending.outcomes[0].status
        is ModelOperationCandidateOutcomeStatus.QUOTA_OR_BILLING
    )
    assert (
        succeeded.outcomes[1].status is ModelOperationCandidateOutcomeStatus.SUCCEEDED
    )


def test_quota_helper_raises_typed_exhaustion_with_final_snapshot() -> None:
    """The last quota result retains its final record on typed exhaustion."""
    active = mark_current_candidate_active(
        build_model_operation(
            option=_option(candidate_count=1),
            profile=_profile(),
            kind=ModelOperationKind.FOREGROUND,
            operation_id="1" * 32,
            recorded_at=_RECORDED_AT,
        ),
        reason=ModelOperationCandidateOutcomeReason.SELECTED,
        recorded_at=datetime.datetime(2026, 9, 13, 0, 0, 1, tzinfo=datetime.UTC),
    )

    with pytest.raises(ModelOperationChainExhaustedError) as raised:
        mark_current_candidate_quota_and_advance(
            active,
            recorded_at=datetime.datetime(
                2026,
                9,
                12,
                0,
                0,
                2,
                tzinfo=datetime.UTC,
            ),
        )

    assert (
        raised.value.operation.outcomes[0].status
        is ModelOperationCandidateOutcomeStatus.QUOTA_OR_BILLING
    )
    assert (
        raised.value.operation.terminal_reason
        is ModelOperationTerminalReason.CHAIN_EXHAUSTED
    )


def test_claim_helpers_set_and_clear_current_foreground_claim() -> None:
    """Claim helpers retain fencing data without mutating the source snapshot."""
    operation = _operation(candidate_count=1)
    claim = TransferredModelCandidateClaim(
        kind=ModelCandidateClaimKind.PROBE,
        candidate_ordinal=1,
        health_generation=2,
        claim_owner_id=operation.operation_id,
        claim_token="2" * 32,
        claim_until=datetime.datetime(2026, 9, 13, 0, 5, tzinfo=datetime.UTC),
        transferred_at=_RECORDED_AT,
    )

    claimed = set_transferred_probe_claim(operation, claim)
    cleared = clear_transferred_probe_claim(claimed)

    assert operation.transferred_probe_claim is None
    assert claimed.transferred_probe_claim == claim
    assert cleared.transferred_probe_claim is None


def test_title_operation_is_standalone_not_a_run_slot() -> None:
    """Title uses the shared snapshot but not an AgentRun operation slot."""
    title = build_model_operation(
        option=_option(candidate_count=1),
        profile=_profile(),
        kind=ModelOperationKind.TITLE,
        operation_id="1" * 32,
        recorded_at=_RECORDED_AT,
    )

    assert title.kind is ModelOperationKind.TITLE
    with pytest.raises(ValidationError, match="Foreground slot"):
        ModelOperationState(foreground=title, compaction=None)
