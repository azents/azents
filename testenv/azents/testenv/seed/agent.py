"""Seed Agents with explicit canonical model options through the public API."""

from dataclasses import dataclass

from azentspublicclient.api.agent_v1_api import AgentV1Api
from azentspublicclient.models.agent_create_request import AgentCreateRequest
from azentspublicclient.models.agent_model_selection_input import AgentModelSelectionInput
from azentspublicclient.models.agent_type import AgentType
from azentspublicclient.models.selectable_model_candidate_input import SelectableModelCandidateInput
from azentspublicclient.models.selectable_model_option_input import SelectableModelOptionInput
from azentspublicclient.models.selectable_model_settings_input import SelectableModelSettingsInput

from testenv.runtime_config import TestenvConfig

from .client import public_client
from .types import Agent, Integration, User, Workspace
from .unique import unique

_SEED_MODEL_LABEL = "Testenv model"


@dataclass(frozen=True)
class AgentService:
    """Create exact seed selections without inheriting unrelated Workspace defaults."""

    config: TestenvConfig

    def create(
        self,
        user: User,
        workspace: Workspace,
        integration: Integration,
        model: str,
        *,
        name: str | None = None,
        agent_type: str = "public",
        memory_enabled: bool = True,
    ) -> Agent:
        """Create one explicit option for both model roles.

        The server resolves the exact integration/model pair and copies its current
        capabilities and pricing. Seed callers provide no authoritative model facts
        or rates, and a missing model fails the ordinary public selection boundary.
        """
        if integration.workspace.handle != workspace.handle:
            raise ValueError("The seed integration must belong to the selected Workspace.")
        if not model.strip():
            raise ValueError("The seed model identifier must not be blank.")
        actual_name = name if name is not None else f"Test Agent {unique()}"
        api = AgentV1Api(public_client(self.config))
        agent_resp = api.agent_v1_create_agent(
            handle=workspace.handle,
            agent_create_request=AgentCreateRequest(
                name=actual_name,
                selectable_model_options=[
                    SelectableModelOptionInput(
                        label=_SEED_MODEL_LABEL,
                        candidates=[
                            SelectableModelCandidateInput(
                                model_selection=AgentModelSelectionInput(
                                    llm_provider_integration_id=integration.id,
                                    model_identifier=model,
                                ),
                                settings=SelectableModelSettingsInput(),
                            )
                        ],
                    )
                ],
                main_model_label=_SEED_MODEL_LABEL,
                lightweight_model_label=_SEED_MODEL_LABEL,
                memory_enabled=memory_enabled,
                type=AgentType(agent_type),
            ),
            _headers={"Authorization": f"Bearer {user.access_token}"},
        )
        return Agent(
            id=agent_resp.id,
            workspace=workspace,
            integration=integration,
            name=actual_name,
            model_slug=model,
        )
