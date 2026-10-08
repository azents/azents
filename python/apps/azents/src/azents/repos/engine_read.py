"""Completed database reads used by Engine request resolution."""

import dataclasses

from azcommon.result import Failure, Result, Success

from azents.core.agent import (
    AgentModelSelection,
    SelectableModelOption,
    SelectableModelSettings,
)
from azents.core.inference_profile import RequestedInferenceProfile
from azents.core.llm_catalog import ModelReasoningEffort
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import LLMProviderIntegrationWithSecrets
from azents.repos.toolkit import ToolkitRepository
from azents.repos.toolkit.data import EffectiveToolkitConfig


@dataclasses.dataclass(frozen=True)
class EngineAgentNotFound:
    """Requested Engine Agent snapshot does not exist."""

    agent_id: str


@dataclasses.dataclass(frozen=True)
class EngineAgentDisabled:
    """Requested Engine Agent snapshot is disabled."""

    agent_id: str


@dataclasses.dataclass(frozen=True)
class EngineModelTargetNotFound:
    """Requested Agent-owned model target label does not exist."""

    model_target_label: str


@dataclasses.dataclass(frozen=True)
class EngineReasoningEffortUnsupported:
    """Requested reasoning effort is unsupported by the selected target."""

    model_target_label: str
    reasoning_effort: ModelReasoningEffort


@dataclasses.dataclass(frozen=True)
class EngineIntegrationNotFound:
    """Selected model integration does not exist."""

    integration_id: str


@dataclasses.dataclass(frozen=True)
class EngineIntegrationDisabled:
    """Selected model integration is disabled."""

    integration_id: str


EngineInvokeModelReadError = (
    EngineAgentNotFound
    | EngineAgentDisabled
    | EngineModelTargetNotFound
    | EngineReasoningEffortUnsupported
    | EngineIntegrationNotFound
    | EngineIntegrationDisabled
)


@dataclasses.dataclass(frozen=True)
class EngineInvokeModelSnapshot:
    """Detached Agent and integration snapshot for one Engine invocation."""

    agent: Agent
    main_model_target_label: str
    main_selection: AgentModelSelection
    main_settings: SelectableModelSettings
    lightweight_selection: AgentModelSelection
    lightweight_settings: SelectableModelSettings
    main_integration: LLMProviderIntegrationWithSecrets
    lightweight_integration: LLMProviderIntegrationWithSecrets


@dataclasses.dataclass
class EngineModelReadRepository:
    """Own completed model integration reads."""

    session_manager: SessionManager[WriteSession]
    integration_repository: LLMProviderIntegrationRepository

    async def get_integration(
        self,
        integration_id: str,
    ) -> LLMProviderIntegrationWithSecrets | None:
        """Return one detached integration after completing the read transaction."""
        async with self.session_manager() as session:
            return await self.integration_repository.get_by_id_with_secrets(
                session,
                integration_id,
            )


@dataclasses.dataclass
class EngineInvokeReadRepository:
    """Own the atomic Agent, model-selection, and integration snapshot read."""

    session_manager: SessionManager[WriteSession]
    agent_repository: AgentRepository
    integration_repository: LLMProviderIntegrationRepository

    async def load_model_source(
        self,
        *,
        agent_id: str,
        model_source_agent_id: str,
        requested_profile: RequestedInferenceProfile | None,
        resolved_model_selection: AgentModelSelection | None,
        resolved_model_settings: SelectableModelSettings | None,
    ) -> Result[EngineInvokeModelSnapshot, EngineInvokeModelReadError]:
        """Return one detached invocation snapshot from a single transaction."""
        async with self.session_manager() as session:
            agent = await self.agent_repository.get_by_id(session, agent_id)
            if agent is None:
                return Failure(EngineAgentNotFound(agent_id=agent_id))
            if not agent.enabled:
                return Failure(EngineAgentDisabled(agent_id=agent_id))

            if model_source_agent_id == agent_id:
                model_agent = agent
            else:
                model_agent = await self.agent_repository.get_by_id(
                    session,
                    model_source_agent_id,
                )
                if model_agent is None:
                    return Failure(EngineAgentNotFound(agent_id=model_source_agent_id))

            main_option = _find_model_option(
                model_agent.selectable_model_options,
                model_agent.main_model_label,
            )
            if main_option is None:
                return Failure(
                    EngineModelTargetNotFound(
                        model_target_label=model_agent.main_model_label
                    )
                )
            main_selection = main_option.candidates[0].model_selection
            main_settings = main_option.candidates[0].settings
            if resolved_model_selection is not None:
                if resolved_model_settings is None:
                    raise ValueError("Resolved model settings are required")
                main_selection = resolved_model_selection
                main_settings = resolved_model_settings
            elif requested_profile is not None:
                selected_option = _find_model_option(
                    model_agent.selectable_model_options,
                    requested_profile.model_target_label,
                )
                if selected_option is None:
                    return Failure(
                        EngineModelTargetNotFound(
                            model_target_label=requested_profile.model_target_label
                        )
                    )
                main_selection = selected_option.candidates[0].model_selection
                main_settings = selected_option.candidates[0].settings
                requested_effort = requested_profile.reasoning_effort
                if requested_effort is not None:
                    capabilities = main_selection.normalized_capabilities
                    if (
                        requested_effort
                        not in capabilities.configurable_reasoning_efforts()
                    ):
                        return Failure(
                            EngineReasoningEffortUnsupported(
                                model_target_label=(
                                    requested_profile.model_target_label
                                ),
                                reasoning_effort=requested_effort,
                            )
                        )

            lightweight_option = _find_model_option(
                model_agent.selectable_model_options,
                model_agent.lightweight_model_label,
            )
            if lightweight_option is None:
                return Failure(
                    EngineModelTargetNotFound(
                        model_target_label=model_agent.lightweight_model_label
                    )
                )
            lightweight_selection = lightweight_option.candidates[0].model_selection
            lightweight_settings = lightweight_option.candidates[0].settings

            main_integration = await self.integration_repository.get_by_id_with_secrets(
                session,
                main_selection.llm_provider_integration_id,
            )
            if main_integration is None:
                return Failure(
                    EngineIntegrationNotFound(
                        integration_id=main_selection.llm_provider_integration_id
                    )
                )
            lightweight_integration = main_integration
            if lightweight_selection.llm_provider_integration_id != main_integration.id:
                loaded_lightweight_integration = (
                    await self.integration_repository.get_by_id_with_secrets(
                        session,
                        lightweight_selection.llm_provider_integration_id,
                    )
                )
                if loaded_lightweight_integration is None:
                    return Failure(
                        EngineIntegrationNotFound(
                            integration_id=(
                                lightweight_selection.llm_provider_integration_id
                            )
                        )
                    )
                if not loaded_lightweight_integration.enabled:
                    return Failure(
                        EngineIntegrationDisabled(
                            integration_id=(
                                lightweight_selection.llm_provider_integration_id
                            )
                        )
                    )
                lightweight_integration = loaded_lightweight_integration

            return Success(
                EngineInvokeModelSnapshot(
                    agent=agent,
                    main_model_target_label=main_option.label,
                    main_selection=main_selection,
                    main_settings=main_settings,
                    lightweight_selection=lightweight_selection,
                    lightweight_settings=lightweight_settings,
                    main_integration=main_integration,
                    lightweight_integration=lightweight_integration,
                )
            )


@dataclasses.dataclass
class EngineToolkitReadRepository:
    """Own completed effective Toolkit reads."""

    session_manager: SessionManager[WriteSession]
    toolkit_repository: ToolkitRepository

    async def list_effective_for_agent(
        self,
        agent_id: str,
        *,
        workspace_id: str,
    ) -> list[EffectiveToolkitConfig]:
        """Return detached effective Toolkits after the read transaction closes."""
        async with self.session_manager() as session:
            return await self.toolkit_repository.list_effective_for_agent(
                session,
                agent_id,
                workspace_id=workspace_id,
            )


def _find_model_option(
    options: list[SelectableModelOption],
    label: str,
) -> SelectableModelOption | None:
    """Return one Agent-owned selectable option by label."""
    return next((option for option in options if option.label == label), None)
