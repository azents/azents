"""Completed read-only subscription integration ingress."""

import dataclasses
from typing import Annotated

from fastapi import Depends

from azents.rdb.deps import get_read_only_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import LLMProviderIntegrationWithSecrets
from azents.repos.llm_provider_integration.deps import (
    get_llm_provider_integration_repository,
)


@dataclasses.dataclass
class SubscriptionUsageReadRepository:
    """Own the exact completed integration/secrets read before external usage work."""

    repository: Annotated[
        LLMProviderIntegrationRepository,
        Depends(get_llm_provider_integration_repository),
    ]
    read_session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]

    async def load(
        self, integration_id: str
    ) -> LLMProviderIntegrationWithSecrets | None:
        """Return a detached snapshot preserving Workspace error ordering."""
        async with self.read_session_manager() as session:
            return await self.repository.get_by_id_with_secrets(session, integration_id)
