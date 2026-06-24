"""LLM Provider Integration repository data models."""

import dataclasses
import datetime
from typing import Annotated

from pydantic import BaseModel, Field
from typing_extensions import Self, TypedDict

from azents.core.credentials import ProviderConfig, ProviderSecrets
from azents.core.enums import LLMProvider


class LLMProviderIntegration(BaseModel):
    """LLM Provider Integration domain model."""

    id: str = Field(description="Integration ID")
    workspace_id: str = Field(description="Workspace ID")
    provider: LLMProvider = Field(description="Hosting provider")
    name: str = Field(description="Display name")
    config: ProviderConfig | None = Field(default=None, description="Plaintext config")
    enabled: bool = Field(description="Enabled flag")
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")

    @classmethod
    def convert_from(cls, data: "LLMProviderIntegration") -> Self:
        return cls.model_validate(data, from_attributes=True)


class LLMProviderIntegrationWithSecrets(LLMProviderIntegration):
    """LLM Provider Integration domain model including secrets."""

    secrets: ProviderSecrets = Field(description="Decrypted secrets")


class LLMProviderIntegrationCreate(BaseModel):
    """LLM Provider Integration create schema."""

    workspace_id: str = Field(description="Workspace ID")
    provider: LLMProvider = Field(description="Hosting provider")
    name: str = Field(description="Display name")
    secrets: ProviderSecrets = Field(description="Secrets before encryption")
    config: ProviderConfig | None = Field(default=None, description="Plaintext config")
    enabled: bool = Field(default=True, description="Enabled flag")


class LLMProviderIntegrationUpdate(TypedDict, total=False):
    """LLM Provider Integration update schema (partial update)."""

    name: Annotated[str, Field(description="Display name")]
    secrets: Annotated[ProviderSecrets, Field(description="Secrets before encryption")]
    config: Annotated[ProviderConfig | None, Field(description="Plaintext config")]
    enabled: Annotated[bool, Field(description="Enabled flag")]


class LLMProviderIntegrationList(BaseModel):
    """LLM Provider Integration list."""

    items: list[LLMProviderIntegration] = Field(description="Integration list")


@dataclasses.dataclass(frozen=True)
class NotFound:
    """Integration not found."""

    integration_id: str
