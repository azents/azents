"""Restricted Runtime Provider capability contract domain models."""

import enum
import hashlib
import json
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RuntimeProviderPolicyScope(enum.StrEnum):
    """Policy layer at which a Provider contract accepts values."""

    PLATFORM = "platform"
    AGENT = "agent"


class RuntimeProviderApplicationImpact(enum.StrEnum):
    """Declared effect of a policy value change on existing Runtime state."""

    IMMEDIATE = "immediate"
    NEXT_INCARNATION = "next_incarnation"
    REPLACEMENT_REQUIRED = "replacement_required"
    NEW_LOGICAL_RUNTIME = "new_logical_runtime"
    IMMUTABLE = "immutable"


class RuntimeProviderLifecycleOperation(enum.StrEnum):
    """Lifecycle operation vocabulary for Provider capability contracts."""

    START = "start"
    STOP = "stop"
    RESTART = "restart"
    RESET = "reset"
    OBSERVE = "observe"
    TERMINAL_DELETE = "terminal_delete"


class RuntimeProviderPersistenceKind(enum.StrEnum):
    """Workspace persistence semantics declared by a Provider."""

    PERSISTENT = "persistent"
    EPHEMERAL = "ephemeral"


class RuntimeProviderPersistenceContract(BaseModel):
    """Provider-declared Agent Workspace persistence behavior."""

    model_config = ConfigDict(extra="forbid")

    kind: RuntimeProviderPersistenceKind
    reset_destroys_workspace: bool
    terminal_delete_destroys_workspace: bool


class RuntimeProviderConfigFieldBase(BaseModel):
    """Shared safe metadata for one contract-declared configuration field."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    scope: RuntimeProviderPolicyScope
    required: bool = False
    secret: bool = False
    application_impact: RuntimeProviderApplicationImpact


class RuntimeProviderStringConfigField(RuntimeProviderConfigFieldBase):
    """Bounded string field descriptor."""

    type: Literal["string"]
    default: str | None = None
    min_length: int | None = Field(default=None, ge=0, le=4_096)
    max_length: int | None = Field(default=None, ge=0, le=4_096)

    @model_validator(mode="after")
    def validate_bounds(self) -> "RuntimeProviderStringConfigField":
        """Reject invalid string descriptor boundaries and secret defaults."""
        if self.min_length is not None and self.max_length is not None:
            if self.min_length > self.max_length:
                raise ValueError("String field min_length exceeds max_length.")
        if self.secret and self.default is not None:
            raise ValueError("Secret field must not declare a default value.")
        if self.default is not None and self.max_length is not None:
            if len(self.default) > self.max_length:
                raise ValueError("String field default exceeds max_length.")
        return self


class RuntimeProviderIntegerConfigField(RuntimeProviderConfigFieldBase):
    """Bounded integer field descriptor."""

    type: Literal["integer"]
    default: int | None = None
    minimum: int | None = None
    maximum: int | None = None

    @model_validator(mode="after")
    def validate_bounds(self) -> "RuntimeProviderIntegerConfigField":
        """Reject invalid integer descriptor boundaries and secret defaults."""
        if self.minimum is not None and self.maximum is not None:
            if self.minimum > self.maximum:
                raise ValueError("Integer field minimum exceeds maximum.")
        if self.secret and self.default is not None:
            raise ValueError("Secret field must not declare a default value.")
        if self.default is not None:
            if self.minimum is not None and self.default < self.minimum:
                raise ValueError("Integer field default is below minimum.")
            if self.maximum is not None and self.default > self.maximum:
                raise ValueError("Integer field default exceeds maximum.")
        return self


class RuntimeProviderBooleanConfigField(RuntimeProviderConfigFieldBase):
    """Boolean field descriptor."""

    type: Literal["boolean"]
    default: bool | None = None

    @model_validator(mode="after")
    def validate_secret_default(self) -> "RuntimeProviderBooleanConfigField":
        """Reject secret boolean defaults."""
        if self.secret and self.default is not None:
            raise ValueError("Secret field must not declare a default value.")
        return self


class RuntimeProviderEnumConfigField(RuntimeProviderConfigFieldBase):
    """Closed string enum field descriptor."""

    type: Literal["enum"]
    values: Annotated[list[str], Field(min_length=1, max_length=100)]
    default: str | None = None

    @model_validator(mode="after")
    def validate_values(self) -> "RuntimeProviderEnumConfigField":
        """Reject duplicate enum values and invalid secret defaults."""
        if any(not value or len(value) > 120 for value in self.values):
            raise ValueError("Enum field values must be non-empty and bounded.")
        if len(set(self.values)) != len(self.values):
            raise ValueError("Enum field values must be unique.")
        if self.secret and self.default is not None:
            raise ValueError("Secret field must not declare a default value.")
        if self.default is not None and self.default not in self.values:
            raise ValueError("Enum field default is not one of the declared values.")
        return self


RuntimeProviderConfigField = Annotated[
    RuntimeProviderStringConfigField
    | RuntimeProviderIntegerConfigField
    | RuntimeProviderBooleanConfigField
    | RuntimeProviderEnumConfigField,
    Field(discriminator="type"),
]


class RuntimeProviderCapabilityContract(BaseModel):
    """Complete immutable capability proposal from one authenticated Provider."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Annotated[int, Field(ge=1)]
    implementation_key: Annotated[str, Field(min_length=1, max_length=120)]
    implementation_version: Annotated[str, Field(min_length=1, max_length=120)]
    protocol_version: Annotated[str, Field(min_length=1, max_length=120)]
    core_lifecycle_operations: set[RuntimeProviderLifecycleOperation]
    optional_capabilities: set[Annotated[str, Field(min_length=1, max_length=120)]] = (
        set()
    )
    persistence: RuntimeProviderPersistenceContract
    configuration_fields: list[RuntimeProviderConfigField] = Field(
        default_factory=list,
        max_length=100,
    )

    @model_validator(mode="after")
    def validate_contract(self) -> "RuntimeProviderCapabilityContract":
        """Require complete core lifecycle support and unique field names."""
        required_operations = set(RuntimeProviderLifecycleOperation)
        if not required_operations.issubset(self.core_lifecycle_operations):
            missing = sorted(
                operation.value
                for operation in required_operations - self.core_lifecycle_operations
            )
            raise ValueError(
                "Provider contract omits required lifecycle operations: "
                f"{', '.join(missing)}"
            )
        names = [field.name for field in self.configuration_fields]
        if len(set(names)) != len(names):
            raise ValueError(
                "Provider contract configuration field names must be unique."
            )
        return self


@dataclass(frozen=True)
class CanonicalRuntimeProviderContract:
    """Canonical JSON payload and digest for one validated contract proposal."""

    contract: RuntimeProviderCapabilityContract
    canonical_json: dict[str, object]
    digest: str


def canonicalize_runtime_provider_contract(
    contract: RuntimeProviderCapabilityContract,
) -> CanonicalRuntimeProviderContract:
    """Produce stable semantic JSON and a digest for one validated contract."""
    canonical_json = contract.model_dump(mode="json")
    canonical_json["core_lifecycle_operations"] = sorted(
        canonical_json["core_lifecycle_operations"]
    )
    canonical_json["optional_capabilities"] = sorted(
        canonical_json["optional_capabilities"]
    )
    encoded = json.dumps(
        canonical_json,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return CanonicalRuntimeProviderContract(
        contract=contract,
        canonical_json=canonical_json,
        digest=hashlib.sha256(encoded).hexdigest(),
    )
