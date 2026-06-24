"""LLM Provider Integration service data models."""

import dataclasses

from pydantic import BaseModel, Field

from azents.core.credentials import ProviderConfig, ProviderSecrets
from azents.core.enums import LLMProvider
from azents.repos.llm_provider_integration.data import (
    LLMProviderIntegration,
    LLMProviderIntegrationUpdate,
)


class LLMProviderIntegrationOutput(LLMProviderIntegration):
    """LLM Provider Integration output model."""

    pass


class LLMProviderIntegrationCreateInput(BaseModel):
    """LLM Provider Integration create input model."""

    workspace_id: str = Field(description="Workspace ID")
    provider: LLMProvider = Field(description="Hosting provider")
    name: str = Field(description="Display name")
    secrets: ProviderSecrets = Field(description="Secrets (encrypted storage)")
    config: ProviderConfig | None = Field(default=None, description="Plaintext config")
    enabled: bool = Field(default=True, description="Enabled flag")


class LLMProviderIntegrationUpdateInput(LLMProviderIntegrationUpdate):
    """LLM Provider Integration update input model."""

    pass


class LLMProviderIntegrationListOutput(BaseModel):
    """LLM Provider Integration list output model."""

    items: list[LLMProviderIntegrationOutput] = Field(description="Integration list")


@dataclasses.dataclass(frozen=True)
class NotBelongToWorkspace:
    """Resource does not belong to requested workspace."""

    integration_id: str
