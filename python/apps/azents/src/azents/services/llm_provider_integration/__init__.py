"""LLM Provider Integration service."""

import dataclasses
from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.credentials import PROVIDER_SECRET_TYPES, PROVIDERS_WITH_CONFIG
from azents.core.crypto import CredentialCipher
from azents.core.deps import get_credential_cipher
from azents.core.enums import LLMCatalogLowererTarget, LLMProvider
from azents.core.llm_catalog import INTEGRATION_SCOPED_CATALOG_PROVIDERS
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.llm_catalog import LLMCatalogRepository
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import (
    LLMProviderIntegrationCreate,
    NotFound,
)

from .data import (
    InvalidProviderUpdate,
    LLMProviderIntegrationCreateInput,
    LLMProviderIntegrationListOutput,
    LLMProviderIntegrationOutput,
    LLMProviderIntegrationUpdateInput,
    LLMProviderIntegrationUpdateOutput,
    NotBelongToWorkspace,
)


def _get_repo(
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)],
) -> LLMProviderIntegrationRepository:
    """LLMProviderIntegrationRepository dependency."""
    return LLMProviderIntegrationRepository(cipher=cipher)


def catalog_sync_required_for_update(
    update: LLMProviderIntegrationUpdateInput,
    *,
    previously_enabled: bool,
) -> bool:
    """Return whether an update changed catalog-affecting integration state."""
    return (
        "secrets" in update
        or "config" in update
        or (update.get("enabled") is True and not previously_enabled)
    )


def validate_provider_update(
    provider: LLMProvider,
    update: LLMProviderIntegrationUpdateInput,
) -> InvalidProviderUpdate | None:
    """Return an error when credentials or config do not match the provider."""
    expected_type = PROVIDER_SECRET_TYPES[provider]
    secrets = update.get("secrets")
    if secrets is not None and secrets.type != expected_type:
        return InvalidProviderUpdate(
            reason=(
                f"Provider '{provider.value}' requires '{expected_type}' secret type."
            )
        )
    if "config" not in update:
        return None
    config = update["config"]
    if provider in PROVIDERS_WITH_CONFIG:
        if config is None or config.type != expected_type:
            return InvalidProviderUpdate(
                reason=(
                    f"Provider '{provider.value}' requires "
                    f"'{expected_type}' config type."
                )
            )
    elif config is not None:
        return InvalidProviderUpdate(
            reason=f"Provider '{provider.value}' does not accept config settings."
        )
    return None


@dataclasses.dataclass
class LLMProviderIntegrationService:
    """LLM Provider Integration CRUD service."""

    repository: Annotated[LLMProviderIntegrationRepository, Depends(_get_repo)]
    catalog_repository: Annotated[LLMCatalogRepository, Depends(LLMCatalogRepository)]
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
            if integration.provider in INTEGRATION_SCOPED_CATALOG_PROVIDERS:
                await self.catalog_repository.ensure_integration_catalog(
                    session,
                    integration_id=integration.id,
                    provider=integration.provider,
                    lowerer_target=LLMCatalogLowererTarget.LITELLM,
                )
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
    ) -> Result[
        LLMProviderIntegrationUpdateOutput,
        NotFound | NotBelongToWorkspace | InvalidProviderUpdate,
    ]:
        """Update LLM Provider Integration by ID."""
        async with self.session_manager() as session:
            existing = await self.repository.get_by_id(session, integration_id)
        if existing is None:
            return Failure(NotFound(integration_id=integration_id))
        if existing.workspace_id != workspace_id:
            return Failure(NotBelongToWorkspace(integration_id=integration_id))
        invalid_update = validate_provider_update(existing.provider, update)
        if invalid_update is not None:
            return Failure(invalid_update)
        catalog_sync_required = catalog_sync_required_for_update(
            update,
            previously_enabled=existing.enabled,
        )

        async with self.session_manager() as session:
            result = await self.repository.update_by_id(session, integration_id, update)
            match result:
                case Success(value):
                    if value.provider in INTEGRATION_SCOPED_CATALOG_PROVIDERS:
                        await self.catalog_repository.ensure_integration_catalog(
                            session,
                            integration_id=value.id,
                            provider=value.provider,
                            lowerer_target=LLMCatalogLowererTarget.LITELLM,
                        )
                case Failure():
                    pass
                case _:
                    assert_never(result)

        match result:
            case Success(value):
                return Success(
                    LLMProviderIntegrationUpdateOutput(
                        integration=LLMProviderIntegrationOutput.convert_from(value),
                        catalog_sync_required=catalog_sync_required,
                    )
                )
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
