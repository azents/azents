"""Session title operation repository data models."""

import dataclasses

from azents.core.agent import AgentModelSelection
from azents.repos.llm_provider_integration.data import LLMProviderIntegrationWithSecrets


@dataclasses.dataclass(frozen=True)
class SessionTitleGenerationSnapshot:
    """Completed database snapshot needed for one automatic title generation."""

    agent_id: str
    selection: AgentModelSelection
    integration: LLMProviderIntegrationWithSecrets
