"""Explicit SDK constructor boundaries shared by operation composition."""

import dataclasses
from typing import TYPE_CHECKING, Protocol

from azents.core.enums import LLMProvider
from azents.core.openai_client_config import OpenAIResponsesClientConfig

if TYPE_CHECKING:
    from azents.engine.events.openai_responses import OpenAIResponsesClient
    from azents.engine.providers.model_factory import ProviderModelFactory


class OpenAIResponsesClientFactory(Protocol):
    """Construct an owned official Responses client from resolved settings."""

    def __call__(
        self, *, config: OpenAIResponsesClientConfig
    ) -> "OpenAIResponsesClient":
        """Create a client without changing logical endpoint or credentials."""
        ...


class ProviderModelFactoryBuilder(Protocol):
    """Construct the provider's official SDK model factory for one operation."""

    def __call__(
        self,
        *,
        provider: LLMProvider,
        credential_kwargs: dict[str, object],
    ) -> "ProviderModelFactory":
        """Retain the authorized credential view and public SDK boundaries."""
        ...


@dataclasses.dataclass(frozen=True)
class ModelSDKFactories:
    """Process-composition dependencies, never request or product settings."""

    openai_responses: OpenAIResponsesClientFactory
    provider_model: ProviderModelFactoryBuilder
