"""Completed LLM integration reads and atomic catalog-aware mutations."""

from dataclasses import dataclass
from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends

from azents.core.enums import LLMCatalogPurpose
from azents.core.llm_catalog import INTEGRATION_SCOPED_CATALOG_PROVIDERS
from azents.rdb.deps import get_read_only_session_manager, get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.llm_catalog import LLMCatalogRepository
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import (
    LLMProviderIntegration,
    LLMProviderIntegrationCreate,
    LLMProviderIntegrationList,
    LLMProviderIntegrationUpdate,
    NotFound,
)
from azents.repos.llm_provider_integration.deps import (
    get_llm_provider_integration_repository,
)


@dataclass
class LLMProviderIntegrationOperations:
    """Own database lifetimes without moving service credential validation."""

    repository: Annotated[
        LLMProviderIntegrationRepository,
        Depends(get_llm_provider_integration_repository),
    ]
    catalog_repository: Annotated[LLMCatalogRepository, Depends(LLMCatalogRepository)]
    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    read_session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]

    async def create(
        self, create: LLMProviderIntegrationCreate
    ) -> LLMProviderIntegration:
        """Create an integration and its account-scoped catalog in one transaction."""
        async with self.session_manager() as session:
            integration = await self.repository.create(session, create)
            if integration.provider in INTEGRATION_SCOPED_CATALOG_PROVIDERS:
                await self.catalog_repository.ensure_integration_catalog(
                    session,
                    integration_id=integration.id,
                    provider=integration.provider,
                    purpose=LLMCatalogPurpose.CONVERSATION,
                )
        return integration

    async def list_by_workspace(self, workspace_id: str) -> LLMProviderIntegrationList:
        """Return a detached workspace integration listing."""
        async with self.read_session_manager() as session:
            result = await self.repository.list_by_workspace(session, workspace_id)
        return result

    async def get_by_id(self, integration_id: str) -> LLMProviderIntegration | None:
        """Return the current integration before service ownership/credential checks."""
        async with self.read_session_manager() as session:
            result = await self.repository.get_by_id(session, integration_id)
        return result

    async def update_by_id(
        self, integration_id: str, update: LLMProviderIntegrationUpdate
    ) -> Result[LLMProviderIntegration, NotFound]:
        """Complete one prevalidated integration update and its catalog atomically."""
        async with self.session_manager() as session:
            result = await self.repository.update_by_id(session, integration_id, update)
            match result:
                case Success(value):
                    if value.provider in INTEGRATION_SCOPED_CATALOG_PROVIDERS:
                        await self.catalog_repository.ensure_integration_catalog(
                            session,
                            integration_id=value.id,
                            provider=value.provider,
                            purpose=LLMCatalogPurpose.CONVERSATION,
                        )
                case Failure():
                    pass
                case _:
                    assert_never(result)
        return result

    async def delete_by_id(self, integration_id: str, *, workspace_id: str) -> None:
        """Complete the existing workspace-conditioned deletion after service checks."""
        async with self.session_manager() as session:
            await self.repository.delete_by_id(
                session, integration_id, workspace_id=workspace_id
            )
