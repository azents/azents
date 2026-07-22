"""Trusted Runtime Provider bootstrap reconciliation contracts."""

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from azents.core.enums import (
    RuntimeProviderAvailabilityMode,
    RuntimeProviderBootstrapAdapterKind,
    RuntimeProviderKind,
)


class RuntimeProviderBootstrapDeclarationInput(BaseModel):
    """One non-secret Provider declaration from an authoritative source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    declaration_key: str = Field(min_length=1, max_length=255)
    provider_logical_id: str = Field(min_length=1, max_length=120)
    kind: RuntimeProviderKind
    display_name: str = Field(min_length=1, max_length=120)
    enabled: bool
    availability_mode: RuntimeProviderAvailabilityMode
    capabilities: dict[str, Any]
    config_schema: dict[str, Any] | None
    metadata: dict[str, Any] | None
    creation_seeds: dict[str, Any] | None


class RuntimeProviderBootstrapSnapshot(BaseModel):
    """Complete successful read of one authoritative bootstrap source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_key: str = Field(min_length=1, max_length=255)
    adapter_kind: RuntimeProviderBootstrapAdapterKind
    source_revision: str = Field(min_length=1, max_length=255)
    source_digest: str = Field(min_length=1, max_length=64)
    declarations: tuple[RuntimeProviderBootstrapDeclarationInput, ...]

    @model_validator(mode="after")
    def validate_identity_uniqueness(self) -> "RuntimeProviderBootstrapSnapshot":
        """Reject ambiguous snapshots before any declaration can be withdrawn."""
        declaration_keys = [
            declaration.declaration_key for declaration in self.declarations
        ]
        provider_ids = [
            declaration.provider_logical_id for declaration in self.declarations
        ]
        if len(declaration_keys) != len(set(declaration_keys)):
            raise ValueError("Bootstrap snapshot contains duplicate declaration keys.")
        if len(provider_ids) != len(set(provider_ids)):
            raise ValueError("Bootstrap snapshot contains duplicate Provider IDs.")
        return self


@dataclass(frozen=True)
class RuntimeProviderBootstrapReconcileResult:
    """Outcome summary for one authoritative source reconciliation."""

    source_id: str
    created_provider_ids: tuple[str, ...]
    reconciled_provider_ids: tuple[str, ...]
    withdrawn_provider_ids: tuple[str, ...]
    conflicted_declaration_keys: tuple[str, ...]


@dataclass(frozen=True)
class RuntimeProviderBootstrapSourceError:
    """Sanitized error produced while an adapter cannot read its source."""

    source_key: str
    adapter_kind: RuntimeProviderBootstrapAdapterKind
    error_code: str
    error_message: str
