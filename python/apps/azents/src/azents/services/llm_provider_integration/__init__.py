"""LLM Provider Integration service."""

import dataclasses
from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.crypto import CredentialCipher
from azents.core.deps import get_credential_cipher
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import (
    LLMProviderIntegrationCreate,
    NotFound,
)

from .data import (
    LLMProviderIntegrationCreateInput,
    LLMProviderIntegrationListOutput,
    LLMProviderIntegrationOutput,
    LLMProviderIntegrationUpdateInput,
    NotBelongToWorkspace,
)


def _get_repo(
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)],
) -> LLMProviderIntegrationRepository:
    """LLMProviderIntegrationRepository dependency."""
    return LLMProviderIntegrationRepository(cipher=cipher)


@dataclasses.dataclass
class LLMProviderIntegrationService:
    """LLM Provider Integration CRUD service."""

    repository: Annotated[LLMProviderIntegrationRepository, Depends(_get_repo)]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]

    async def create(
        self, create: LLMProviderIntegrationCreateInput
    ) -> LLMProviderIntegrationOutput:
        """Create LLM Provider Integration."""
        repo_create = LLMProviderIntegrationCreate(
            workspace_id=create.workspace_id,
            provider=create.provider,
            name=create.name,
            secrets=create.secrets,
            config=create.config,
            enabled=create.enabled,
        )
        async with self.session_manager() as session:
            integration = await self.repository.create(session, repo_create)
        return LLMProviderIntegrationOutput.convert_from(integration)

    async def list_by_workspace(
        self, workspace_id: str
    ) -> LLMProviderIntegrationListOutput:
        """Fetch LLM Provider Integration list in workspace."""
        async with self.session_manager() as session:
            result = await self.repository.list_by_workspace(session, workspace_id)
        return LLMProviderIntegrationListOutput(
            items=[LLMProviderIntegrationOutput.convert_from(i) for i in result.items]
        )

    async def get_by_id(
        self, integration_id: str, *, workspace_id: str
    ) -> Result[LLMProviderIntegrationOutput, NotFound | NotBelongToWorkspace]:
        """Fetch LLM Provider Integration by ID."""
        async with self.session_manager() as session:
            integration = await self.repository.get_by_id(session, integration_id)
        if integration is None:
            return Failure(NotFound(integration_id=integration_id))
        if integration.workspace_id != workspace_id:
            return Failure(NotBelongToWorkspace(integration_id=integration_id))
        return Success(LLMProviderIntegrationOutput.convert_from(integration))

    async def update_by_id(
        self,
        integration_id: str,
        update: LLMProviderIntegrationUpdateInput,
        *,
        workspace_id: str,
    ) -> Result[LLMProviderIntegrationOutput, NotFound | NotBelongToWorkspace]:
        """Update LLM Provider Integration by ID."""
        async with self.session_manager() as session:
            existing = await self.repository.get_by_id(session, integration_id)
        if existing is None:
            return Failure(NotFound(integration_id=integration_id))
        if existing.workspace_id != workspace_id:
            return Failure(NotBelongToWorkspace(integration_id=integration_id))

        async with self.session_manager() as session:
            result = await self.repository.update_by_id(session, integration_id, update)

        match result:
            case Success(value):
                return Success(LLMProviderIntegrationOutput.convert_from(value))
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(result)

    async def delete_by_id(
        self, integration_id: str, *, workspace_id: str
    ) -> Result[None, NotFound | NotBelongToWorkspace]:
        """Delete LLM Provider Integration by ID."""
        async with self.session_manager() as session:
            existing = await self.repository.get_by_id(session, integration_id)
        if existing is None:
            return Failure(NotFound(integration_id=integration_id))
        if existing.workspace_id != workspace_id:
            return Failure(NotBelongToWorkspace(integration_id=integration_id))

        async with self.session_manager() as session:
            await self.repository.delete_by_id(session, integration_id)
        return Success(None)
