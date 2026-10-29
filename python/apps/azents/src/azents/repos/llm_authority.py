"""Current Agent/configuration authority over completed DB-only scopes."""

from dataclasses import dataclass
from typing import Annotated

from azents_llm_contract.authority import AuthenticatedIdentity, ModelListResponse
from azents_llm_contract.target import InferenceTarget
from fastapi import Depends

from azents.core.agent import SelectableModelCandidate
from azents.core.llm_access import LLMAccessDenied, LLMTargetDenied
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.llm_access import LLMAccessRepository
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import LLMProviderIntegrationWithSecrets
from azents.repos.llm_provider_integration.deps import (
    get_llm_provider_integration_repository,
)


@dataclass(frozen=True, repr=False)
class PreparedLLMAuthority:
    identity: AuthenticatedIdentity
    candidate: SelectableModelCandidate
    integration: LLMProviderIntegrationWithSecrets
    agent: Agent


def select_target(
    agent: Agent, *, model: str, target_id: str
) -> SelectableModelCandidate:
    matches = [
        candidate
        for option in agent.selectable_model_options
        for candidate in option.candidates
        if InferenceTarget(
            option.label,
            candidate.model_selection.llm_provider_integration_id,
            candidate.model_selection.model_identifier,
        ).target_id
        == target_id
        and candidate.model_selection.model_identifier == model
    ]
    if len(matches) != 1:
        raise LLMTargetDenied("Target is not authorized.")
    return matches[0]


@dataclass
class LLMAuthorityRepository:
    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    integrations: Annotated[
        LLMProviderIntegrationRepository,
        Depends(get_llm_provider_integration_repository),
    ]
    agents: Annotated[AgentRepository, Depends(AgentRepository)]

    async def list_models(self, *, digest: str) -> ModelListResponse:
        async with self.session_manager() as scope:
            identity = await LLMAccessRepository.authenticate_in_session(
                scope, digest=digest
            )
            agent = await self.agents.get_by_id(scope, identity.agent_id)
            if agent is None:
                raise LLMAccessDenied("Agent is unavailable.")
            names = tuple(
                dict.fromkeys(
                    candidate.model_selection.model_identifier
                    for option in agent.selectable_model_options
                    for candidate in option.candidates
                )
            )
            return ModelListResponse(identity=identity, models=names)

    async def prepare(
        self, *, digest: str, model: str, target_id: str
    ) -> PreparedLLMAuthority:
        async with self.session_manager() as scope:
            return await self._load(
                scope, digest=digest, model=model, target_id=target_id
            )

    async def finalize(
        self,
        *,
        digest: str,
        model: str,
        target_id: str,
        prepared: PreparedLLMAuthority,
        refreshed: LLMProviderIntegrationWithSecrets,
    ) -> PreparedLLMAuthority:
        async with self.session_manager() as scope:
            latest = await self._load(
                scope, digest=digest, model=model, target_id=target_id
            )
            # Refresh may legitimately change credentials; compare against its returned
            # current state, not the superseded pre-refresh secret snapshot.
            if (
                latest.identity != prepared.identity
                or latest.candidate != prepared.candidate
                or latest.agent.model_parameters != prepared.agent.model_parameters
                or latest.integration.secrets != refreshed.secrets
                or latest.integration.config != refreshed.config
                or latest.integration.catalog_configuration_version
                != refreshed.catalog_configuration_version
                or refreshed.catalog_configuration_version
                != prepared.integration.catalog_configuration_version
            ):
                raise LLMTargetDenied("Target changed during preparation.")
            return latest

    async def _load(
        self, scope: WriteSession, *, digest: str, model: str, target_id: str
    ) -> PreparedLLMAuthority:
        identity = await LLMAccessRepository.authenticate_in_session(
            scope, digest=digest
        )
        agent = await self.agents.get_by_id(scope, identity.agent_id)
        if agent is None:
            raise LLMAccessDenied("Agent is unavailable.")
        candidate = select_target(agent, model=model, target_id=target_id)
        integration = await self.integrations.get_by_id_with_secrets_for_update(
            scope, candidate.model_selection.llm_provider_integration_id
        )
        if (
            integration is None
            or integration.workspace_id != identity.workspace_id
            or not integration.enabled
            or integration.provider != candidate.model_selection.provider
        ):
            raise LLMTargetDenied("Target is not authorized.")
        # Integration locking may have waited across the token expiry boundary.
        await LLMAccessRepository.authenticate_in_session(scope, digest=digest)
        return PreparedLLMAuthority(identity, candidate, integration, agent)
