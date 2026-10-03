"""Concrete provider token orchestration over completed persistence dependencies."""

from dataclasses import dataclass
from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends

from azents.core.enums import LLMProvider
from azents.repos.chatgpt_oauth_runtime import ChatGPTOAuthRuntimeRepository
from azents.repos.kimi_oauth_runtime import KimiOAuthRuntimeRepository
from azents.repos.llm_provider_integration.data import LLMProviderIntegrationWithSecrets
from azents.repos.xai_oauth_runtime import XaiOAuthRuntimeRepository
from azents.services.chatgpt_oauth.data import ProviderRejected as ChatGPTRejected
from azents.services.chatgpt_oauth.data import ProviderUnavailable as ChatGPTUnavailable
from azents.services.chatgpt_oauth.runtime import (
    ensure_runtime_tokens as ensure_chatgpt,
)
from azents.services.kimi_oauth.data import ProviderRejected as KimiRejected
from azents.services.kimi_oauth.data import ProviderUnavailable as KimiUnavailable
from azents.services.kimi_oauth.runtime import ensure_runtime_tokens as ensure_kimi
from azents.services.oauth_runtime_clients import (
    RuntimeOAuthClientFactories,
    create_runtime_oauth_client_factories,
)
from azents.services.xai_oauth.data import (
    ProviderEntitlementDenied as XaiEntitlementDenied,
)
from azents.services.xai_oauth.data import ProviderRejected as XaiRejected
from azents.services.xai_oauth.data import ProviderUnavailable as XaiUnavailable
from azents.services.xai_oauth.runtime import ensure_runtime_tokens as ensure_xai

RuntimeTokenRefreshError = (
    ChatGPTRejected
    | ChatGPTUnavailable
    | KimiRejected
    | KimiUnavailable
    | XaiRejected
    | XaiUnavailable
    | XaiEntitlementDenied
)


@dataclass(frozen=True)
class EngineRuntimeTokenResolver:
    """Retain provider dispatch while leaving all DB lifetimes in repositories."""

    chatgpt_repository: Annotated[
        ChatGPTOAuthRuntimeRepository, Depends(ChatGPTOAuthRuntimeRepository)
    ]
    xai_repository: Annotated[
        XaiOAuthRuntimeRepository, Depends(XaiOAuthRuntimeRepository)
    ]
    kimi_repository: Annotated[
        KimiOAuthRuntimeRepository, Depends(KimiOAuthRuntimeRepository)
    ]
    oauth_clients: Annotated[
        RuntimeOAuthClientFactories, Depends(create_runtime_oauth_client_factories)
    ]

    async def ensure(
        self, integration: LLMProviderIntegrationWithSecrets
    ) -> Result[LLMProviderIntegrationWithSecrets, RuntimeTokenRefreshError]:
        """Resolve fresh credentials using the same provider branch and outcomes."""
        if integration.provider == LLMProvider.XAI_OAUTH:
            result = await ensure_xai(
                integration=integration,
                persistence_repository=self.xai_repository,
                client_factory=self.oauth_clients.xai,
            )
        elif integration.provider == LLMProvider.KIMI_OAUTH:
            result = await ensure_kimi(
                integration=integration,
                persistence_repository=self.kimi_repository,
                client_factory=self.oauth_clients.kimi,
            )
        else:
            result = await ensure_chatgpt(
                integration=integration,
                persistence_repository=self.chatgpt_repository,
                client_factory=self.oauth_clients.chatgpt,
            )
        match result:
            case Success(value):
                return Success(value)
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(result)
