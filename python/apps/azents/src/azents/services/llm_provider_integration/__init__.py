"""LLM Provider Integration service."""

import dataclasses
from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends

from azents.core.credentials import PROVIDER_SECRET_TYPES, PROVIDERS_WITH_CONFIG
from azents.core.enums import LLMProvider
from azents.repos.llm_provider_integration.data import (
    LLMProviderIntegrationCreate,
    NotFound,
)
from azents.repos.llm_provider_integration.operations import (
    LLMProviderIntegrationOperations,
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

    operations: Annotated[
        LLMProviderIntegrationOperations, Depends(LLMProviderIntegrationOperations)
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
        integration = await self.operations.create(repo_create)
        return LLMProviderIntegrationOutput.convert_from(integration)

    async def list_by_workspace(
        self, workspace_id: str
    ) -> LLMProviderIntegrationListOutput:
        """Fetch LLM Provider Integration list in workspace."""
        result = await self.operations.list_by_workspace(workspace_id)
        return LLMProviderIntegrationListOutput(
            items=[LLMProviderIntegrationOutput.convert_from(i) for i in result.items]
        )

    async def get_by_id(
        self, integration_id: str, *, workspace_id: str
    ) -> Result[LLMProviderIntegrationOutput, NotFound | NotBelongToWorkspace]:
        """Fetch LLM Provider Integration by ID."""
        integration = await self.operations.get_by_id(integration_id)
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
        existing = await self.operations.get_by_id(integration_id)
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

        result = await self.operations.update_by_id(integration_id, update)

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
        existing = await self.operations.get_by_id(integration_id)
        if existing is None:
            return Failure(NotFound(integration_id=integration_id))
        if existing.workspace_id != workspace_id:
            return Failure(NotBelongToWorkspace(integration_id=integration_id))

        await self.operations.delete_by_id(integration_id, workspace_id=workspace_id)
        return Success(None)
