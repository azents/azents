"""Runtime Provider discovery v1 Public API schemas."""

from typing import Any

from pydantic import BaseModel

from azents.repos.runtime_provider.data import RuntimeProvider


class RuntimeProviderOptionResponse(BaseModel):
    """Safe Provider option for Workspace and Agent preference surfaces."""

    provider_id: str
    display_name: str
    kind: str
    scope: str
    availability_mode: str
    capabilities: dict[str, Any]
    accepted_contract_revision_id: str | None
    active_config_revision_id: str | None

    @classmethod
    def convert_from(
        cls,
        provider: RuntimeProvider,
    ) -> "RuntimeProviderOptionResponse":
        """Convert a Provider aggregate without exposing credentials or secrets."""
        return cls(
            provider_id=provider.provider_id,
            display_name=provider.display_name,
            kind=provider.kind.value,
            scope=provider.scope.value,
            availability_mode=provider.availability_mode.value,
            capabilities=provider.capabilities,
            accepted_contract_revision_id=provider.accepted_contract_revision_id,
            active_config_revision_id=provider.active_config_revision_id,
        )


class RuntimeProviderOptionListResponse(BaseModel):
    """Eligible Provider options response."""

    items: list[RuntimeProviderOptionResponse]
