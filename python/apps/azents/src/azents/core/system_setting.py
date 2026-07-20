"""Provider-neutral System Settings contracts."""

import base64
import datetime
import enum
import hashlib
import hmac
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel


class SystemSettingSection(enum.StrEnum):
    """Compiled instance System Settings sections."""

    PLATFORM_GITHUB_APP = "platform_github_app"


class SystemSettingActivationMode(enum.StrEnum):
    """Mutation lifecycle selected by a Section definition."""

    DIRECT = "direct"
    VALIDATED = "validated"
    CONFIRMED = "confirmed"


class SystemSettingValidationStatus(enum.StrEnum):
    """Persisted candidate or activation validation state."""

    PENDING = "pending"
    VALID = "valid"
    INVALID = "invalid"
    UNAVAILABLE = "unavailable"


class SystemSettingHealthStatus(enum.StrEnum):
    """Persisted explicit health-check result."""

    HEALTHY = "healthy"
    INVALID = "invalid"
    UNAVAILABLE = "unavailable"


class SystemSettingAuditEventType(enum.StrEnum):
    """Metadata-only System Settings audit event type."""

    CANDIDATE_REPLACED = "candidate_replaced"
    CANDIDATE_VALIDATED = "candidate_validated"
    CANDIDATE_CANCELLED = "candidate_cancelled"
    ACTIVATED = "activated"
    HEALTH_CHECKED = "health_checked"


class SystemSettingAuditSource(enum.StrEnum):
    """Authority that produced a System Settings audit event."""

    ADMIN_API = "admin_api"
    APPLICATION_MIGRATION = "application_migration"
    SYSTEM = "system"


class SystemDataMigrationOutcome(enum.StrEnum):
    """Persisted application data-migration outcome."""

    APPLIED = "applied"
    SKIPPED = "skipped"


class SystemSettingFieldTarget(enum.StrEnum):
    """Typed payload targeted by an environment binding."""

    CONFIG = "config"
    SECRET = "secret"


class SystemSettingFieldSource(enum.StrEnum):
    """Effective field source."""

    ADMIN = "admin"
    ENVIRONMENT = "environment"
    UNSET = "unset"


class SystemSettingSecretActionType(enum.StrEnum):
    """Explicit secret mutation action."""

    REPLACE = "replace"
    CLEAR = "clear"


@dataclass(frozen=True)
class SystemSettingSecretAction:
    """Internal explicit secret mutation."""

    action: SystemSettingSecretActionType
    value: str | None


@dataclass(frozen=True)
class SystemSettingEnvironmentBinding:
    """Environment overlay binding for one typed field."""

    field_name: str
    environment_variable: str
    target: SystemSettingFieldTarget


SystemSettingPayloadMigrator = Callable[
    [dict[str, Any], dict[str, Any]], tuple[dict[str, Any], dict[str, Any]]
]
SystemSettingLocalValidator = Callable[[BaseModel, BaseModel], None]


@dataclass(frozen=True)
class SystemSettingDefinition:
    """Compiled typed Section definition."""

    section: SystemSettingSection
    schema_version: int
    config_model: type[BaseModel]
    secret_model: type[BaseModel]
    activation_mode: SystemSettingActivationMode
    environment_bindings: tuple[SystemSettingEnvironmentBinding, ...]
    candidate_ttl: datetime.timedelta
    local_validator: SystemSettingLocalValidator
    payload_migrations: Mapping[int, SystemSettingPayloadMigrator] = field(
        default_factory=dict
    )

    def migrate_payload(
        self,
        *,
        schema_version: int,
        config: dict[str, Any],
        secrets: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Migrate persisted payloads in memory to the compiled schema version."""
        if schema_version > self.schema_version:
            raise SystemSettingNewerSchemaVersion(
                section=self.section,
                stored_version=schema_version,
                compiled_version=self.schema_version,
            )
        current_version = schema_version
        migrated_config = config
        migrated_secrets = secrets
        while current_version < self.schema_version:
            migrator = self.payload_migrations.get(current_version)
            if migrator is None:
                raise SystemSettingMissingSchemaMigration(
                    section=self.section,
                    stored_version=schema_version,
                    compiled_version=self.schema_version,
                    missing_from_version=current_version,
                )
            migrated_config, migrated_secrets = migrator(
                migrated_config,
                migrated_secrets,
            )
            current_version += 1
        return migrated_config, migrated_secrets


@dataclass(frozen=True)
class SystemSettingRegistry:
    """Immutable registry of compiled Section definitions."""

    definitions: tuple[SystemSettingDefinition, ...]
    _by_section: Mapping[SystemSettingSection, SystemSettingDefinition] = field(
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        by_section: dict[SystemSettingSection, SystemSettingDefinition] = {}
        for definition in self.definitions:
            if definition.section in by_section:
                raise ValueError(
                    f"Duplicate System Settings Section: {definition.section.value}"
                )
            if definition.schema_version < 1:
                raise ValueError("System Settings schema versions must start at 1.")
            config_fields = set(definition.config_model.model_fields)
            secret_fields = set(definition.secret_model.model_fields)
            overlapping_fields = config_fields & secret_fields
            if overlapping_fields:
                raise ValueError(
                    "System Settings config and secret field names must be distinct: "
                    f"{sorted(overlapping_fields)}"
                )
            bound_fields: set[tuple[SystemSettingFieldTarget, str]] = set()
            environment_variables: set[str] = set()
            for binding in definition.environment_bindings:
                target_fields = (
                    config_fields
                    if binding.target == SystemSettingFieldTarget.CONFIG
                    else secret_fields
                )
                if binding.field_name not in target_fields:
                    raise ValueError(
                        "System Settings environment binding targets an unknown field: "
                        f"{definition.section.value}.{binding.field_name}"
                    )
                key = (binding.target, binding.field_name)
                if key in bound_fields:
                    raise ValueError(
                        "Duplicate System Settings environment field binding: "
                        f"{definition.section.value}.{binding.field_name}"
                    )
                if binding.environment_variable in environment_variables:
                    raise ValueError(
                        "Duplicate System Settings environment variable binding: "
                        f"{binding.environment_variable}"
                    )
                bound_fields.add(key)
                environment_variables.add(binding.environment_variable)
            by_section[definition.section] = definition
        object.__setattr__(self, "_by_section", MappingProxyType(by_section))

    def get(self, section: SystemSettingSection) -> SystemSettingDefinition:
        """Return one registered definition."""
        try:
            return self._by_section[section]
        except KeyError as error:
            raise SystemSettingSectionNotRegistered(section=section) from error


@dataclass(frozen=True)
class SystemSettingEnvironment:
    """Injected process environment view that preserves key presence."""

    values: Mapping[str, str]

    def contains(self, name: str) -> bool:
        """Return whether an environment variable is present, including empty."""
        return name in self.values

    def get_present(self, name: str) -> str:
        """Return a present environment value."""
        try:
            return self.values[name]
        except KeyError as error:
            raise RuntimeError(
                f"Environment variable is not present: {name}"
            ) from error


@dataclass(frozen=True)
class ResolvedSystemSetting:
    """Internal typed effective Section snapshot for one operation."""

    section: SystemSettingSection
    schema_version: int
    admin_version: int
    config: BaseModel
    secrets: BaseModel
    field_sources: Mapping[str, SystemSettingFieldSource]
    effective_generation: str


class SystemSettingGenerationHasher:
    """Produce opaque generations from complete effective typed payloads."""

    _DOMAIN_LABEL = b"azents/system-settings-effective-generation/v1"

    def __init__(self, credential_encryption_key: str) -> None:
        """Initialize a domain-separated HMAC key.

        :param credential_encryption_key: Deployment-controlled Fernet root key
        """
        root = base64.urlsafe_b64decode(credential_encryption_key.encode())
        self.key = hmac.new(root, self._DOMAIN_LABEL, hashlib.sha256).digest()

    def generate(
        self,
        *,
        section: SystemSettingSection,
        schema_version: int,
        config: BaseModel,
        secrets: BaseModel,
    ) -> str:
        """Return the stable generation for one complete effective payload."""
        canonical = json.dumps(
            {
                "section": section.value,
                "schema_version": schema_version,
                "config": config.model_dump(mode="json"),
                "secrets": secrets.model_dump(mode="json"),
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
        return hmac.new(self.key, canonical, hashlib.sha256).hexdigest()


@dataclass
class SystemSettingSectionNotRegistered(Exception):
    """Requested Section is not compiled into this process."""

    section: SystemSettingSection


@dataclass
class SystemSettingNewerSchemaVersion(Exception):
    """Persisted Section schema is newer than the compiled definition."""

    section: SystemSettingSection
    stored_version: int
    compiled_version: int


@dataclass
class SystemSettingMissingSchemaMigration(Exception):
    """No registered migration can read an older persisted payload."""

    section: SystemSettingSection
    stored_version: int
    compiled_version: int
    missing_from_version: int


@dataclass
class SystemSettingVersionConflict(Exception):
    """Mutation expected a stale Admin base version."""

    section: SystemSettingSection
    expected_version: int
    current_version: int


@dataclass
class SystemSettingEnvironmentFieldReadOnly(Exception):
    """Mutation attempted to write an environment-owned field."""

    section: SystemSettingSection
    field_name: str
    environment_variable: str


@dataclass
class SystemSettingEffectiveGenerationChanged(Exception):
    """Effective Section changed while an external operation was in flight."""

    section: SystemSettingSection
    expected_generation: str
    current_generation: str


@dataclass
class SystemSettingCandidateNotFound(Exception):
    """Requested candidate does not exist."""

    section: SystemSettingSection


@dataclass
class SystemSettingCandidateExpired(Exception):
    """Requested candidate has expired."""

    section: SystemSettingSection
    candidate_id: str


@dataclass(frozen=True)
class SystemSettingCandidateNotValidated(Exception):
    """Candidate is not valid for confirmation."""

    section: SystemSettingSection
    candidate_id: str


@dataclass(frozen=True)
class SystemSettingImpactChanged(Exception):
    """Candidate impact changed after external validation."""

    section: SystemSettingSection
    candidate_id: str
    current_impact: dict[str, Any] | None
