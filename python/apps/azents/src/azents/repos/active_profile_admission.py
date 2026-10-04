"""Two-phase exact active capability validation for new public admissions."""

import dataclasses
from typing import Annotated

from fastapi import Depends

from azents.core.active_model_capabilities import (
    CompiledActiveChoices,
    apply_to_options,
    compile_capture,
    identities_for_options,
    require_selection,
)
from azents.core.agent import SelectableModelOption
from azents.core.inference_profile import (
    RequestedInferenceProfile,
    validate_requested_profile_against_options,
)
from azents.rdb.session_capabilities import WriteSession
from azents.repos.active_model_capabilities import ActiveModelCapabilitiesRepository
from azents.repos.active_model_capabilities_data import CapturedActiveChoiceInputs
from azents.repos.agent.data import Agent


@dataclasses.dataclass(frozen=True)
class AdmissionChoice:
    """Exact requested/default option plus raw identity/settings admission authority."""

    workspace_id: str
    agent_id: str
    profile: RequestedInferenceProfile
    option: SelectableModelOption
    configuration: str


class ActiveProfileCaptureRequired(Exception):
    """Exit a write-free authorization/replay transaction for a completed capture."""

    def __init__(self, choice: AdmissionChoice) -> None:
        self.choice = choice
        super().__init__("Active profile admission requires a completed capture.")


@dataclasses.dataclass(frozen=True)
class CapturedProfileAdmission:
    choice: AdmissionChoice
    inputs: CapturedActiveChoiceInputs
    compiled: CompiledActiveChoices


def _choice(agent: Agent, profile: RequestedInferenceProfile) -> AdmissionChoice:
    option = next(
        (
            item
            for item in agent.selectable_model_options
            if item.label == profile.model_target_label
        ),
        None,
    )
    if option is None:
        raise ValueError("Model target label is not available")
    # Metadata is an overlay; raw identity/order/settings and selected labels remain
    # user configuration. Never persist the projected metadata to the Agent.
    configuration = repr(
        (
            agent.workspace_id,
            agent.id,
            agent.main_model_label,
            agent.lightweight_model_label,
            option.label,
            tuple(
                (
                    candidate.model_selection.llm_provider_integration_id,
                    candidate.model_selection.provider.value,
                    candidate.model_selection.model_identifier,
                    candidate.settings.model_dump_json(),
                )
                for candidate in option.candidates
            ),
            profile.model_dump_json(),
        )
    )
    return AdmissionChoice(agent.workspace_id, agent.id, profile, option, configuration)


@dataclasses.dataclass(frozen=True)
class ActiveProfileAdmissionRepository:
    """Complete compilation outside SQL, then recheck under the owner's transaction."""

    active_repository: Annotated[
        ActiveModelCapabilitiesRepository, Depends(ActiveModelCapabilitiesRepository)
    ]

    async def capture(self, choice: AdmissionChoice) -> CapturedProfileAdmission:
        inputs = await self.active_repository.capture_exact_choices(
            workspace_id=choice.workspace_id,
            identities=identities_for_options([choice.option]),
        )
        compiled = compile_capture(
            inputs,
            selections=[
                candidate.model_selection for candidate in choice.option.candidates
            ],
        )
        return CapturedProfileAdmission(choice, inputs, compiled)

    async def validate_in_session(
        self,
        session: WriteSession,
        *,
        agent: Agent,
        profile: RequestedInferenceProfile,
        captured: CapturedProfileAdmission | None,
    ) -> None:
        choice = _choice(agent, profile)
        if captured is None:
            raise ActiveProfileCaptureRequired(choice)
        if choice.configuration != captured.choice.configuration:
            raise ValueError("Model configuration changed before input admission")
        if not await self.active_repository.inputs_match_in_session(
            session, captured=captured.inputs
        ):
            raise ValueError("Model metadata changed before input admission")
        require_selection(
            captured.compiled, choice.option.candidates[0].model_selection
        )
        options = apply_to_options([choice.option], captured.compiled)
        validate_requested_profile_against_options(options, profile)
