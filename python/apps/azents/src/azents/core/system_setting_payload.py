"""Pure System Settings payload migration and effective projection."""

import dataclasses
import datetime
import json
from collections.abc import Mapping
from typing import Annotated, Any, NamedTuple

from fastapi import Depends
from pydantic import BaseModel

from azents.core.crypto import CredentialCipher
from azents.core.deps import get_credential_cipher
from azents.core.system_setting import (
    ResolvedSystemSetting,
    SystemSettingDefinition,
    SystemSettingEnvironment,
    SystemSettingEnvironmentFieldReadOnly,
    SystemSettingFieldSource,
    SystemSettingFieldTarget,
    SystemSettingGenerationHasher,
    SystemSettingRegistry,
)
from azents.core.system_setting_data import (
    StoredSystemSetting,
    StoredSystemSettingCandidate,
)
from azents.core.system_setting_deps import (
    get_system_setting_environment,
    get_system_setting_generation_hasher,
)
from azents.core.system_setting_registry import get_system_setting_registry


class _SystemSettingBasePayload(NamedTuple):
    """Validated base configuration and secret models."""

    config: BaseModel
    secrets: BaseModel


@dataclasses.dataclass(frozen=True)
class SystemSettingPayloadResolver:
    """Project detached payloads without database or provider I/O."""

    registry: Annotated[SystemSettingRegistry, Depends(get_system_setting_registry)]
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)]
    environment: Annotated[
        SystemSettingEnvironment, Depends(get_system_setting_environment)
    ]
    generation_hasher: Annotated[
        SystemSettingGenerationHasher, Depends(get_system_setting_generation_hasher)
    ]

    def resolve_candidate(
        self,
        *,
        definition: SystemSettingDefinition,
        candidate: StoredSystemSettingCandidate,
    ) -> ResolvedSystemSetting:
        config, secrets = self.load_base_payload(
            definition=definition,
            current=StoredSystemSetting(
                section=candidate.section,
                schema_version=candidate.schema_version,
                version=candidate.base_version,
                config=candidate.config,
                encrypted_secrets=candidate.encrypted_secrets,
                secret_metadata=candidate.secret_metadata,
                validation_status=candidate.validation_status,
                validated_generation=candidate.validated_generation,
                validation_metadata=candidate.validation_metadata,
                validated_at=None,
                updated_by_user_id=candidate.created_by_user_id,
                created_at=candidate.created_at,
                updated_at=candidate.updated_at,
            ),
        )
        return self.resolve_payload(
            definition=definition,
            admin_version=candidate.base_version,
            config=config,
            secrets=secrets,
        )

    def resolve_current(
        self,
        *,
        definition: SystemSettingDefinition,
        current: StoredSystemSetting | None,
    ) -> ResolvedSystemSetting:
        config, secrets = self.load_base_payload(
            definition=definition,
            current=current,
        )
        return self.resolve_payload(
            definition=definition,
            admin_version=current.version if current is not None else 0,
            config=config,
            secrets=secrets,
        )

    def load_base_payload(
        self,
        *,
        definition: SystemSettingDefinition,
        current: StoredSystemSetting | None,
    ) -> _SystemSettingBasePayload:
        if current is None:
            config_data: dict[str, Any] = {}
            secret_data: dict[str, Any] = {}
            schema_version = definition.schema_version
        else:
            config_data = current.config
            secret_data = self.decrypt_secrets(current.encrypted_secrets)
            schema_version = current.schema_version
        config_data, secret_data = definition.migrate_payload(
            schema_version=schema_version,
            config=config_data,
            secrets=secret_data,
        )
        return _SystemSettingBasePayload(
            config=definition.config_model.model_validate(config_data),
            secrets=definition.secret_model.model_validate(secret_data),
        )

    def resolve_payload(
        self,
        *,
        definition: SystemSettingDefinition,
        admin_version: int,
        config: BaseModel,
        secrets: BaseModel,
    ) -> ResolvedSystemSetting:
        config_data = config.model_dump(mode="python")
        secret_data = secrets.model_dump(mode="python")
        sources: dict[str, SystemSettingFieldSource] = {}
        for field_name, value in config_data.items():
            sources[field_name] = (
                SystemSettingFieldSource.ADMIN
                if value is not None
                else SystemSettingFieldSource.UNSET
            )
        for field_name, value in secret_data.items():
            sources[field_name] = (
                SystemSettingFieldSource.ADMIN
                if value is not None
                else SystemSettingFieldSource.UNSET
            )
        for binding in definition.environment_bindings:
            if not self.environment.contains(binding.environment_variable):
                continue
            value = self.environment.get_present(binding.environment_variable)
            if binding.target == SystemSettingFieldTarget.CONFIG:
                config_data[binding.field_name] = value
            else:
                secret_data[binding.field_name] = value
            sources[binding.field_name] = SystemSettingFieldSource.ENVIRONMENT
        effective_config = definition.config_model.model_validate(config_data)
        effective_secrets = definition.secret_model.model_validate(secret_data)
        definition.local_validator(effective_config, effective_secrets)
        return ResolvedSystemSetting(
            section=definition.section,
            schema_version=definition.schema_version,
            admin_version=admin_version,
            config=effective_config,
            secrets=effective_secrets,
            field_sources=sources,
            effective_generation=self.generation_hasher.generate(
                section=definition.section,
                schema_version=definition.schema_version,
                config=effective_config,
                secrets=effective_secrets,
            ),
        )

    def reject_environment_owned_mutations(
        self,
        *,
        definition: SystemSettingDefinition,
        config_fields: dict[str, Any],
        secret_fields: Mapping[str, object],
    ) -> None:
        for binding in definition.environment_bindings:
            if not self.environment.contains(binding.environment_variable):
                continue
            fields = (
                config_fields
                if binding.target == SystemSettingFieldTarget.CONFIG
                else secret_fields
            )
            if binding.field_name in fields:
                raise SystemSettingEnvironmentFieldReadOnly(
                    section=definition.section,
                    field_name=binding.field_name,
                    environment_variable=binding.environment_variable,
                )

    @staticmethod
    def validate_patch_fields(
        *,
        definition: SystemSettingDefinition,
        config_patch: dict[str, Any],
        secret_actions: Mapping[str, object],
    ) -> None:
        unknown_config = set(config_patch) - set(definition.config_model.model_fields)
        unknown_secrets = set(secret_actions) - set(
            definition.secret_model.model_fields
        )
        if unknown_config:
            raise ValueError(
                f"Unknown System Settings config fields: {sorted(unknown_config)}"
            )
        if unknown_secrets:
            raise ValueError(
                f"Unknown System Settings secret fields: {sorted(unknown_secrets)}"
            )

    def decrypt_secrets(self, ciphertext: str | None) -> dict[str, Any]:
        if ciphertext is None:
            return {}
        payload = json.loads(self.cipher.decrypt(ciphertext))
        if not isinstance(payload, dict):
            raise ValueError("Stored System Settings secret payload must be an object.")
        return payload

    def encrypt_secrets(self, secrets: BaseModel) -> str | None:
        payload = secrets.model_dump(mode="json")
        if all(value is None for value in payload.values()):
            return None
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return self.cipher.encrypt(encoded)

    @staticmethod
    def update_secret_metadata(
        *,
        current: StoredSystemSetting | None,
        secrets: BaseModel,
        changed_fields: Mapping[str, object],
        changed_at: datetime.datetime,
    ) -> dict[str, Any]:
        metadata = dict(current.secret_metadata) if current is not None else {}
        secret_data = secrets.model_dump(mode="python")
        for field_name in changed_fields:
            metadata[field_name] = {
                "configured": secret_data[field_name] is not None,
                "last_changed_at": changed_at.isoformat(),
            }
        for field_name, value in secret_data.items():
            metadata.setdefault(
                field_name,
                {
                    "configured": value is not None,
                    "last_changed_at": None,
                },
            )
        return metadata
