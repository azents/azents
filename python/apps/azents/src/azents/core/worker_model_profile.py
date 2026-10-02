"""Pure Worker model profile selection and deterministic failure contracts."""

import dataclasses

from azents.core.inference_profile import (
    InferenceProfileFailureCode,
    InferenceProfileSource,
    RequestedInferenceProfile,
)
from azents.core.llm_catalog import ModelReasoningEffort
from azents.core.model_execution_options import ModelExecutionOptionId
from azents.core.model_operation import ModelOperationSnapshot
from azents.engine.run.errors import UserVisibleRuntimeError
from azents.repos.agent.data import Agent


@dataclasses.dataclass(frozen=True)
class ModelTargetNotFound:
    """Requested Agent-owned model target label no longer exists."""

    model_target_label: str


@dataclasses.dataclass(frozen=True)
class ReasoningEffortUnsupported:
    """Requested effort is unsupported by the selected model target."""

    model_target_label: str
    reasoning_effort: ModelReasoningEffort


@dataclasses.dataclass(frozen=True)
class ExecutionOptionUnsupported:
    """Requested execution option is unsupported by the selected model target."""

    model_target_label: str
    enabled_execution_options: tuple[ModelExecutionOptionId, ...]


@dataclasses.dataclass(frozen=True)
class RequestedProfileSelection:
    """Requested profile and its durable source for a new run."""

    profile: RequestedInferenceProfile
    source: InferenceProfileSource


def agent_default_inference_profile(agent: Agent) -> RequestedInferenceProfile:
    """Build the Agent default profile from its current main option."""
    if not agent.selectable_model_options:
        raise ValueError("Agent has no selectable model options")
    option = next(
        (
            candidate
            for candidate in agent.selectable_model_options
            if candidate.label == agent.main_model_label
        ),
        agent.selectable_model_options[0],
    )
    return RequestedInferenceProfile(
        model_target_label=option.label,
        reasoning_effort=(
            agent.model_parameters.reasoning_effort
            if agent.model_parameters is not None
            else None
        ),
        enabled_execution_options=[],
    )


def agent_fallback_inference_profile(agent: Agent) -> RequestedInferenceProfile:
    """Build a fallback profile with only reasoning supported by the fallback model."""
    profile = agent_default_inference_profile(agent)
    option = next(
        option
        for option in agent.selectable_model_options
        if option.label == profile.model_target_label
    )
    reasoning = option.candidates[0].model_selection.normalized_capabilities.reasoning
    if profile.reasoning_effort is not None and (
        not reasoning.supported
        or profile.reasoning_effort not in reasoning.effort_levels
    ):
        return profile.model_copy(update={"reasoning_effort": None})
    return profile


def normalize_profile_selection_for_agent(
    agent: Agent,
    selected: RequestedProfileSelection,
) -> RequestedProfileSelection:
    """Fallback stale Agent-owned labels to the current Agent default."""
    if any(
        option.label == selected.profile.model_target_label
        for option in agent.selectable_model_options
    ):
        return selected
    fallback = agent_fallback_inference_profile(agent)
    if selected.source in {
        InferenceProfileSource.PARENT_RUN,
        InferenceProfileSource.SPAWN_OVERRIDE,
        InferenceProfileSource.RETRY_ORIGINAL,
    }:
        return dataclasses.replace(selected, profile=fallback)
    return RequestedProfileSelection(
        profile=fallback,
        source=InferenceProfileSource.AGENT_DEFAULT,
    )


@dataclasses.dataclass(frozen=True)
class ProfileResolutionFailure:
    """Safe durable profile-resolution failure projection."""

    code: InferenceProfileFailureCode
    message: str


@dataclasses.dataclass(frozen=True)
class ModelCandidateChainExhausted:
    """No compatible candidate remains in one frozen model operation."""

    operation: ModelOperationSnapshot


class ProfileResolutionRuntimeError(UserVisibleRuntimeError):
    """Deterministic profile failure that must not enter automatic retry."""

    def __init__(self, failure: ProfileResolutionFailure) -> None:
        super().__init__(failure.message)
        self.failure_code = failure.code.value


@dataclasses.dataclass(frozen=True)
class ModelQuotaAdvanceResult:
    """Durable quota progression result for one Run operation slot."""

    operation: ModelOperationSnapshot
    exhausted: bool


def profile_resolution_failure(error: object) -> ProfileResolutionFailure:
    """Map internal routing errors to safe durable failure details."""
    if isinstance(error, ModelCandidateChainExhausted):
        return ProfileResolutionFailure(
            code=InferenceProfileFailureCode.MODEL_CANDIDATE_CHAIN_EXHAUSTED,
            message="All compatible model candidates are temporarily unavailable.",
        )
    if isinstance(error, ModelTargetNotFound):
        return ProfileResolutionFailure(
            code=InferenceProfileFailureCode.MODEL_TARGET_NOT_FOUND,
            message="The selected model is no longer available.",
        )
    if isinstance(error, ReasoningEffortUnsupported):
        return ProfileResolutionFailure(
            code=InferenceProfileFailureCode.REASONING_EFFORT_UNSUPPORTED,
            message="The selected reasoning effort is not supported by this model.",
        )
    if isinstance(error, ExecutionOptionUnsupported):
        return ProfileResolutionFailure(
            code=InferenceProfileFailureCode.EXECUTION_OPTION_UNSUPPORTED,
            message="The selected execution option is not supported by this model.",
        )
    return ProfileResolutionFailure(
        code=InferenceProfileFailureCode.MODEL_TARGET_RESOLUTION_FAILED,
        message="The selected model could not be prepared for this run.",
    )
