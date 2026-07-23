"""Trusted Runtime Provider bootstrap reconciliation contracts."""

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from azents.core.enums import (
    RuntimeProviderAuthMethod,
    RuntimeProviderAvailabilityMode,
    RuntimeProviderBootstrapAdapterKind,
    RuntimeProviderKind,
)


class RuntimeProviderBootstrapAuthenticationInput(BaseModel):
    """Typed non-secret authentication binding declaration."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    method: RuntimeProviderAuthMethod
    subject: str = Field(min_length=1, max_length=255)
    namespace: str = Field(min_length=1, max_length=253)
    service_account_name: str = Field(
        min_length=1,
        max_length=253,
        alias="serviceAccountName",
    )
    audience: str = Field(min_length=1, max_length=255)

    @model_validator(mode="after")
    def validate_service_account_identity(
        self,
    ) -> "RuntimeProviderBootstrapAuthenticationInput":
        """Require an exact Kubernetes ServiceAccount identity declaration."""
        if self.method != RuntimeProviderAuthMethod.KUBERNETES_SERVICE_ACCOUNT:
            raise ValueError("Bootstrap authentication method is unsupported.")
        if ":" in self.namespace or ":" in self.service_account_name:
            raise ValueError(
                "Bootstrap ServiceAccount identity components cannot contain colons."
            )
        expected_subject = (
            f"system:serviceaccount:{self.namespace}:{self.service_account_name}"
        )
        if self.subject != expected_subject:
            raise ValueError(
                "Bootstrap authentication subject does not match identity."
            )
        return self


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
    authentication: RuntimeProviderBootstrapAuthenticationInput | None = None

    @model_validator(mode="after")
    def validate_authentication(self) -> "RuntimeProviderBootstrapDeclarationInput":
        """Require typed authentication for Kubernetes Provider declarations."""
        if self.kind == RuntimeProviderKind.KUBERNETES and self.authentication is None:
            raise ValueError(
                "Kubernetes bootstrap declarations require authentication."
            )
        return self


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
