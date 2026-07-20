"""Provider-neutral System Settings lifecycle service."""

import dataclasses
import datetime
import json
import os
from collections.abc import Awaitable, Callable, Mapping
from typing import Annotated, Any

from azcommon.datetime import tznow
from azcommon.uuid import uuid7
from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import CredentialEncryptionConfig
from azents.core.crypto import CredentialCipher
from azents.core.deps import (
    get_credential_cipher,
    get_credential_encryption_config,
)
from azents.core.github_system_setting import get_platform_github_app_definition
from azents.core.system_setting import (
    ResolvedSystemSetting,
    SystemSettingActivationMode,
    SystemSettingAuditEventType,
    SystemSettingAuditSource,
    SystemSettingCandidateExpired,
    SystemSettingCandidateNotFound,
    SystemSettingCandidateNotValidated,
    SystemSettingCandidateReplaced,
    SystemSettingDefinition,
    SystemSettingEffectiveGenerationChanged,
    SystemSettingEnvironment,
    SystemSettingEnvironmentFieldReadOnly,
    SystemSettingFieldSource,
    SystemSettingFieldTarget,
    SystemSettingGenerationHasher,
    SystemSettingImpactChanged,
    SystemSettingRegistry,
    SystemSettingSecretActionType,
    SystemSettingSection,
    SystemSettingValidationStatus,
    SystemSettingVersionConflict,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.system_setting.data import (
    StoredSystemDataMigration,
    StoredSystemSetting,
    StoredSystemSettingCandidate,
    SystemSettingAuditEventCreate,
    SystemSettingCandidateCreate,
    SystemSettingCurrentWrite,
    SystemSettingHealthWrite,
)
from azents.repos.system_setting.repository import (
    SystemDataMigrationRepository,
    SystemSettingRepository,
)

from .data import (
    CurrentSystemSettingHealth,
    SystemDataMigrationResult,
    SystemSettingActivated,
    SystemSettingCandidatePending,
    SystemSettingCandidateValidationResult,
    SystemSettingCandidateValidationSnapshot,
    SystemSettingHealthResult,
    SystemSettingMutation,
    SystemSettingMutationResult,
    SystemSettingState,
)

SystemDataMigrationOperation = Callable[
    [AsyncSession], Awaitable[SystemDataMigrationResult]
]
SystemSettingCandidateValidator = Callable[
    [SystemSettingCandidateValidationSnapshot],
    Awaitable[SystemSettingCandidateValidationResult],
]
SystemSettingImpactResolver = Callable[
    [AsyncSession, ResolvedSystemSetting, ResolvedSystemSetting],
    Awaitable[dict[str, Any] | None],
]
SystemSettingConfirmationHandler = Callable[
    [AsyncSession, str, ResolvedSystemSetting, dict[str, Any] | None],
    Awaitable[None],
]


def get_system_setting_registry() -> SystemSettingRegistry:
    """Return the compiled System Settings Section registry."""
    return SystemSettingRegistry(
        definitions=(get_platform_github_app_definition(),),
    )


def get_system_setting_environment() -> SystemSettingEnvironment:
    """Return the process environment overlay view."""
    return SystemSettingEnvironment(values=os.environ)


def get_system_setting_generation_hasher(
    config: Annotated[
        CredentialEncryptionConfig,
        Depends(get_credential_encryption_config),
    ],
) -> SystemSettingGenerationHasher:
    """Return the effective-generation hasher rooted in deployment material."""
    return SystemSettingGenerationHasher(config.key)


@dataclasses.dataclass(frozen=True)
class SystemSettingsService:
    """Resolve and mutate provider-neutral System Settings Sections."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    repository: Annotated[SystemSettingRepository, Depends(SystemSettingRepository)]
    registry: Annotated[SystemSettingRegistry, Depends(get_system_setting_registry)]
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)]
    environment: Annotated[
        SystemSettingEnvironment,
        Depends(get_system_setting_environment),
    ]
    generation_hasher: Annotated[
        SystemSettingGenerationHasher,
        Depends(get_system_setting_generation_hasher),
    ]

    async def resolve(
        self,
        section: SystemSettingSection,
    ) -> ResolvedSystemSetting:
        """Resolve one current effective Section for an operation."""
        definition = self.registry.get(section)
        async with self.session_manager() as session:
            current = await self.repository.get_current(session, section=section)
        return self._resolve_current(definition=definition, current=current)

    async def mutate(
        self,
        mutation: SystemSettingMutation,
    ) -> SystemSettingMutationResult:
        """Apply a direct mutation or replace the Section candidate."""
        definition = self.registry.get(mutation.section)
        now = tznow()
        async with self.session_manager() as session:
            await self.repository.acquire_section_lock(
                session,
                section=mutation.section,
            )
            current = await self.repository.get_current(
                session,
                section=mutation.section,
            )
            current_version = current.version if current is not None else 0
            if mutation.expected_version != current_version:
                raise SystemSettingVersionConflict(
                    section=mutation.section,
                    expected_version=mutation.expected_version,
                    current_version=current_version,
                )
            await self._delete_expired_candidate(
                session=session,
                definition=definition,
                now=now,
            )
            base_config, base_secrets = self._load_base_payload(
                definition=definition,
                current=current,
            )
            self._reject_environment_owned_mutations(
                definition=definition,
                config_fields=mutation.config_patch,
                secret_fields=mutation.secret_actions,
            )
            config_data = base_config.model_dump(mode="python")
            secret_data = base_secrets.model_dump(mode="python")
            self._validate_patch_fields(
                definition=definition,
                config_patch=mutation.config_patch,
                secret_actions=mutation.secret_actions,
            )
            config_data.update(mutation.config_patch)
            for field_name, action in mutation.secret_actions.items():
                match action.action:
                    case SystemSettingSecretActionType.REPLACE:
                        if action.value is None:
                            raise ValueError(
                                f"Secret replacement requires a value: {field_name}"
                            )
                        secret_data[field_name] = action.value
                    case SystemSettingSecretActionType.CLEAR:
                        if action.value is not None:
                            raise ValueError(
                                f"Secret clear cannot include a value: {field_name}"
                            )
                        secret_data[field_name] = None
            typed_config = definition.config_model.model_validate(config_data)
            typed_secrets = definition.secret_model.model_validate(secret_data)
            resolved = self._resolve_payload(
                definition=definition,
                admin_version=current_version,
                config=typed_config,
                secrets=typed_secrets,
            )
            secret_metadata = self._update_secret_metadata(
                current=current,
                secrets=typed_secrets,
                changed_fields=mutation.secret_actions,
                changed_at=now,
            )
            encrypted_secrets = self._encrypt_secrets(typed_secrets)
            secret_actions = {
                field_name: action.action.value
                for field_name, action in mutation.secret_actions.items()
            }
            changed_fields = sorted(mutation.config_patch)

            if definition.activation_mode == SystemSettingActivationMode.DIRECT:
                new_version = current_version + 1
                stored = await self.repository.write_current(
                    session,
                    write=SystemSettingCurrentWrite(
                        section=mutation.section,
                        schema_version=definition.schema_version,
                        version=new_version,
                        config=typed_config.model_dump(mode="json"),
                        encrypted_secrets=encrypted_secrets,
                        secret_metadata=secret_metadata,
                        validation_status=None,
                        validated_generation=None,
                        validation_metadata=None,
                        validated_at=None,
                        updated_by_user_id=mutation.actor_user_id,
                    ),
                )
                await self.repository.delete_candidate(
                    session,
                    section=mutation.section,
                )
                await self.repository.append_audit_event(
                    session,
                    create=SystemSettingAuditEventCreate(
                        section=mutation.section,
                        event_type=SystemSettingAuditEventType.ACTIVATED,
                        source=SystemSettingAuditSource.ADMIN_API,
                        previous_version=current_version,
                        new_version=new_version,
                        actor_user_id=mutation.actor_user_id,
                        changed_fields=changed_fields,
                        secret_actions=secret_actions,
                        validation_status=None,
                        candidate_id=None,
                        impact_confirmed=False,
                        confirmation_action=None,
                        metadata=None,
                        created_at=now,
                    ),
                )
                return SystemSettingActivated(
                    current=stored,
                    resolved=dataclasses.replace(
                        resolved,
                        admin_version=new_version,
                    ),
                )

            candidate_id = uuid7().hex
            candidate = await self.repository.replace_candidate(
                session,
                create=SystemSettingCandidateCreate(
                    id=candidate_id,
                    section=mutation.section,
                    schema_version=definition.schema_version,
                    base_version=current_version,
                    config=typed_config.model_dump(mode="json"),
                    encrypted_secrets=encrypted_secrets,
                    secret_metadata=secret_metadata,
                    validation_status=SystemSettingValidationStatus.PENDING,
                    created_by_user_id=mutation.actor_user_id,
                    created_at=now,
                    updated_at=now,
                    expires_at=now + definition.candidate_ttl,
                ),
            )
            await self.repository.append_audit_event(
                session,
                create=SystemSettingAuditEventCreate(
                    section=mutation.section,
                    event_type=SystemSettingAuditEventType.CANDIDATE_REPLACED,
                    source=SystemSettingAuditSource.ADMIN_API,
                    previous_version=current_version,
                    new_version=None,
                    actor_user_id=mutation.actor_user_id,
                    changed_fields=changed_fields,
                    secret_actions=secret_actions,
                    validation_status=SystemSettingValidationStatus.PENDING,
                    candidate_id=candidate_id,
                    impact_confirmed=False,
                    confirmation_action=None,
                    metadata=None,
                    created_at=now,
                ),
            )
            return SystemSettingCandidatePending(
                candidate=candidate,
                resolved=resolved,
            )

    async def get_candidate(
        self,
        section: SystemSettingSection,
    ) -> StoredSystemSettingCandidate | None:
        """Return a non-expired candidate, deleting expired ciphertext."""
        definition = self.registry.get(section)
        now = tznow()
        async with self.session_manager() as session:
            await self.repository.acquire_section_lock(session, section=section)
            await self._delete_expired_candidate(
                session=session,
                definition=definition,
                now=now,
            )
            return await self.repository.get_candidate(session, section=section)

    async def get_state(
        self,
        section: SystemSettingSection,
    ) -> SystemSettingState:
        """Return current internal state for a redacted domain projection."""
        definition = self.registry.get(section)
        now = tznow()
        async with self.session_manager() as session:
            await self.repository.acquire_section_lock(session, section=section)
            await self._delete_expired_candidate(
                session=session,
                definition=definition,
                now=now,
            )
            current = await self.repository.get_current(session, section=section)
            candidate = await self.repository.get_candidate(session, section=section)
            health = await self.repository.get_health(session, section=section)
            resolved = self._resolve_current(definition=definition, current=current)
            if (
                health is not None
                and health.effective_generation != resolved.effective_generation
            ):
                health = None
        return SystemSettingState(
            current=current,
            candidate=candidate,
            resolved=resolved,
            health=health,
        )

    async def prepare_candidate_validation(
        self,
        section: SystemSettingSection,
        *,
        candidate_id: str | None,
    ) -> SystemSettingCandidateValidationSnapshot:
        """Return a stable current/candidate snapshot for external validation."""
        definition = self.registry.get(section)
        now = tznow()
        expired_candidate_id: str | None = None
        snapshot: SystemSettingCandidateValidationSnapshot | None = None
        async with self.session_manager() as session:
            await self.repository.acquire_section_lock(session, section=section)
            candidate = await self.repository.get_candidate(session, section=section)
            if candidate is None:
                if candidate_id is not None:
                    raise SystemSettingCandidateReplaced(
                        section=section,
                        candidate_id=candidate_id,
                    )
                raise SystemSettingCandidateNotFound(section=section)
            if candidate_id is not None and candidate.id != candidate_id:
                raise SystemSettingCandidateReplaced(
                    section=section,
                    candidate_id=candidate_id,
                )
            if candidate.expires_at <= now:
                await self.repository.delete_candidate(
                    session,
                    section=section,
                    candidate_id=candidate.id,
                )
                expired_candidate_id = candidate.id
            else:
                current = await self.repository.get_current(session, section=section)
                current_version = current.version if current is not None else 0
                if candidate.base_version != current_version:
                    raise SystemSettingVersionConflict(
                        section=section,
                        expected_version=candidate.base_version,
                        current_version=current_version,
                    )
                snapshot = SystemSettingCandidateValidationSnapshot(
                    candidate=candidate,
                    current_resolved=self._resolve_current(
                        definition=definition,
                        current=current,
                    ),
                    candidate_resolved=self._resolve_candidate(
                        definition=definition,
                        candidate=candidate,
                    ),
                )
        if expired_candidate_id is not None:
            raise SystemSettingCandidateExpired(
                section=section,
                candidate_id=expired_candidate_id,
            )
        if snapshot is None:
            raise RuntimeError("Candidate validation snapshot was not produced.")
        return snapshot

    async def validate_candidate(
        self,
        *,
        section: SystemSettingSection,
        candidate_id: str | None,
        validator: SystemSettingCandidateValidator,
    ) -> SystemSettingMutationResult:
        """Validate a candidate externally and activate when confirmation is absent."""
        snapshot = await self.prepare_candidate_validation(
            section,
            candidate_id=candidate_id,
        )
        result = await validator(snapshot)
        return await self._record_candidate_validation(
            snapshot=snapshot,
            result=result,
        )

    async def confirm_candidate(
        self,
        *,
        section: SystemSettingSection,
        candidate_id: str,
        expected_version: int,
        confirmation_action: str,
        actor_user_id: str | None,
        impact_resolver: SystemSettingImpactResolver,
        confirmation_handler: SystemSettingConfirmationHandler,
    ) -> SystemSettingActivated:
        """Activate a valid candidate after rechecking generation and impact."""
        definition = self.registry.get(section)
        now = tznow()
        expired_candidate_id: str | None = None
        activated: SystemSettingActivated | None = None
        async with self.session_manager() as session:
            await self.repository.acquire_section_lock(session, section=section)
            candidate = await self.repository.get_candidate(session, section=section)
            if candidate is None or candidate.id != candidate_id:
                raise SystemSettingCandidateNotFound(section=section)
            if candidate.expires_at <= now:
                await self.repository.delete_candidate(
                    session,
                    section=section,
                    candidate_id=candidate.id,
                )
                expired_candidate_id = candidate.id
            else:
                current = await self.repository.get_current(session, section=section)
                current_version = current.version if current is not None else 0
                if expected_version != current_version:
                    raise SystemSettingVersionConflict(
                        section=section,
                        expected_version=expected_version,
                        current_version=current_version,
                    )
                if candidate.base_version != current_version:
                    raise SystemSettingVersionConflict(
                        section=section,
                        expected_version=candidate.base_version,
                        current_version=current_version,
                    )
                if (
                    candidate.validation_status != SystemSettingValidationStatus.VALID
                    or candidate.validated_generation is None
                ):
                    raise SystemSettingCandidateNotValidated(
                        section=section,
                        candidate_id=candidate.id,
                    )
                current_resolved = self._resolve_current(
                    definition=definition,
                    current=current,
                )
                candidate_resolved = self._resolve_candidate(
                    definition=definition,
                    candidate=candidate,
                )
                if (
                    candidate_resolved.effective_generation
                    != candidate.validated_generation
                ):
                    raise SystemSettingEffectiveGenerationChanged(
                        section=section,
                        expected_generation=candidate.validated_generation,
                        current_generation=(candidate_resolved.effective_generation),
                    )
                current_impact = await impact_resolver(
                    session,
                    current_resolved,
                    candidate_resolved,
                )
                if current_impact != candidate.impact:
                    raise SystemSettingImpactChanged(
                        section=section,
                        candidate_id=candidate.id,
                        current_impact=current_impact,
                    )
                await confirmation_handler(
                    session,
                    confirmation_action,
                    candidate_resolved,
                    current_impact,
                )
                activated = await self._activate_candidate(
                    session=session,
                    candidate=candidate,
                    resolved=candidate_resolved,
                    actor_user_id=actor_user_id,
                    impact_confirmed=True,
                    confirmation_action=confirmation_action,
                    now=now,
                )
        if expired_candidate_id is not None:
            raise SystemSettingCandidateExpired(
                section=section,
                candidate_id=expired_candidate_id,
            )
        if activated is None:
            raise RuntimeError("Candidate confirmation did not activate a setting.")
        return activated

    async def cancel_candidate(
        self,
        *,
        section: SystemSettingSection,
        candidate_id: str,
        actor_user_id: str | None,
    ) -> None:
        """Cancel one candidate and delete its encrypted secret payload."""
        now = tznow()
        expired = False
        async with self.session_manager() as session:
            await self.repository.acquire_section_lock(session, section=section)
            candidate = await self.repository.get_candidate(session, section=section)
            if candidate is None or candidate.id != candidate_id:
                raise SystemSettingCandidateNotFound(section=section)
            if candidate.expires_at <= now:
                await self.repository.delete_candidate(
                    session,
                    section=section,
                    candidate_id=candidate_id,
                )
                expired = True
            else:
                await self.repository.delete_candidate(
                    session,
                    section=section,
                    candidate_id=candidate_id,
                )
                await self.repository.append_audit_event(
                    session,
                    create=SystemSettingAuditEventCreate(
                        section=section,
                        event_type=SystemSettingAuditEventType.CANDIDATE_CANCELLED,
                        source=SystemSettingAuditSource.ADMIN_API,
                        previous_version=candidate.base_version,
                        new_version=None,
                        actor_user_id=actor_user_id,
                        changed_fields=[],
                        secret_actions={},
                        validation_status=candidate.validation_status,
                        candidate_id=candidate_id,
                        impact_confirmed=False,
                        confirmation_action=None,
                        metadata=None,
                        created_at=now,
                    ),
                )
        if expired:
            raise SystemSettingCandidateExpired(
                section=section,
                candidate_id=candidate_id,
            )

    async def get_current_health(
        self,
        section: SystemSettingSection,
    ) -> CurrentSystemSettingHealth:
        """Return only a health result matching the current effective generation."""
        resolved = await self.resolve(section)
        async with self.session_manager() as session:
            health = await self.repository.get_health(session, section=section)
        if (
            health is not None
            and health.effective_generation != resolved.effective_generation
        ):
            health = None
        return CurrentSystemSettingHealth(resolved=resolved, health=health)

    async def record_health(
        self,
        *,
        section: SystemSettingSection,
        expected_generation: str,
        result: SystemSettingHealthResult,
        actor_user_id: str | None,
    ) -> CurrentSystemSettingHealth:
        """Persist health only if the effective generation remains unchanged."""
        now = tznow()
        definition = self.registry.get(section)
        async with self.session_manager() as session:
            await self.repository.acquire_section_lock(session, section=section)
            current = await self.repository.get_current(session, section=section)
            resolved = self._resolve_current(definition=definition, current=current)
            if resolved.effective_generation != expected_generation:
                raise SystemSettingEffectiveGenerationChanged(
                    section=section,
                    expected_generation=expected_generation,
                    current_generation=resolved.effective_generation,
                )
            health = await self.repository.write_health(
                session,
                write=SystemSettingHealthWrite(
                    section=section,
                    effective_generation=expected_generation,
                    status=result.status,
                    code=result.code,
                    message=result.message,
                    action_hint=result.action_hint,
                    metadata=result.metadata,
                    checked_by_user_id=actor_user_id,
                    checked_at=now,
                ),
            )
            await self.repository.append_audit_event(
                session,
                create=SystemSettingAuditEventCreate(
                    section=section,
                    event_type=SystemSettingAuditEventType.HEALTH_CHECKED,
                    source=SystemSettingAuditSource.ADMIN_API,
                    previous_version=resolved.admin_version,
                    new_version=None,
                    actor_user_id=actor_user_id,
                    changed_fields=[],
                    secret_actions={},
                    validation_status=None,
                    candidate_id=None,
                    impact_confirmed=False,
                    confirmation_action=None,
                    metadata={"status": result.status.value},
                    created_at=now,
                ),
            )
        return CurrentSystemSettingHealth(resolved=resolved, health=health)

    async def _record_candidate_validation(
        self,
        *,
        snapshot: SystemSettingCandidateValidationSnapshot,
        result: SystemSettingCandidateValidationResult,
    ) -> SystemSettingMutationResult:
        if result.status == SystemSettingValidationStatus.PENDING:
            raise ValueError("External validation cannot return pending status.")
        if (
            result.confirmation_required
            and result.status != SystemSettingValidationStatus.VALID
        ):
            raise ValueError("Only a valid candidate can require confirmation.")
        section = snapshot.candidate.section
        definition = self.registry.get(section)
        now = tznow()
        expired_candidate_id: str | None = None
        output: SystemSettingMutationResult | None = None
        async with self.session_manager() as session:
            await self.repository.acquire_section_lock(session, section=section)
            candidate = await self.repository.get_candidate(session, section=section)
            if candidate is None:
                raise SystemSettingCandidateReplaced(
                    section=section,
                    candidate_id=snapshot.candidate.id,
                )
            if candidate.id != snapshot.candidate.id:
                raise SystemSettingCandidateReplaced(
                    section=section,
                    candidate_id=snapshot.candidate.id,
                )
            if candidate.expires_at <= now:
                await self.repository.delete_candidate(
                    session,
                    section=section,
                    candidate_id=candidate.id,
                )
                expired_candidate_id = candidate.id
            else:
                current = await self.repository.get_current(session, section=section)
                current_version = current.version if current is not None else 0
                if candidate.base_version != current_version:
                    raise SystemSettingVersionConflict(
                        section=section,
                        expected_version=candidate.base_version,
                        current_version=current_version,
                    )
                resolved = self._resolve_candidate(
                    definition=definition,
                    candidate=candidate,
                )
                if (
                    resolved.effective_generation
                    != snapshot.candidate_resolved.effective_generation
                ):
                    raise SystemSettingEffectiveGenerationChanged(
                        section=section,
                        expected_generation=(
                            snapshot.candidate_resolved.effective_generation
                        ),
                        current_generation=resolved.effective_generation,
                    )
                updated = await self.repository.update_candidate_validation(
                    session,
                    candidate_id=candidate.id,
                    status=result.status,
                    validated_generation=(
                        resolved.effective_generation
                        if result.status == SystemSettingValidationStatus.VALID
                        else None
                    ),
                    validation_code=result.code,
                    validation_message=result.message,
                    action_hint=result.action_hint,
                    validation_metadata=result.metadata,
                    impact=result.impact,
                    updated_at=now,
                )
                if updated is None:
                    raise SystemSettingCandidateNotFound(section=section)
                await self.repository.append_audit_event(
                    session,
                    create=SystemSettingAuditEventCreate(
                        section=section,
                        event_type=SystemSettingAuditEventType.CANDIDATE_VALIDATED,
                        source=SystemSettingAuditSource.ADMIN_API,
                        previous_version=current_version,
                        new_version=None,
                        actor_user_id=candidate.created_by_user_id,
                        changed_fields=[],
                        secret_actions={},
                        validation_status=result.status,
                        candidate_id=candidate.id,
                        impact_confirmed=False,
                        confirmation_action=None,
                        metadata=(
                            {"code": result.code} if result.code is not None else None
                        ),
                        created_at=now,
                    ),
                )
                if (
                    result.status == SystemSettingValidationStatus.VALID
                    and not result.confirmation_required
                ):
                    output = await self._activate_candidate(
                        session=session,
                        candidate=updated,
                        resolved=resolved,
                        actor_user_id=candidate.created_by_user_id,
                        impact_confirmed=False,
                        confirmation_action=None,
                        now=now,
                    )
                else:
                    output = SystemSettingCandidatePending(
                        candidate=updated,
                        resolved=resolved,
                    )
        if expired_candidate_id is not None:
            raise SystemSettingCandidateExpired(
                section=section,
                candidate_id=expired_candidate_id,
            )
        if output is None:
            raise RuntimeError("Candidate validation result was not persisted.")
        return output

    async def _activate_candidate(
        self,
        *,
        session: AsyncSession,
        candidate: StoredSystemSettingCandidate,
        resolved: ResolvedSystemSetting,
        actor_user_id: str | None,
        impact_confirmed: bool,
        confirmation_action: str | None,
        now: datetime.datetime,
    ) -> SystemSettingActivated:
        new_version = candidate.base_version + 1
        current = await self.repository.write_current(
            session,
            write=SystemSettingCurrentWrite(
                section=candidate.section,
                schema_version=candidate.schema_version,
                version=new_version,
                config=candidate.config,
                encrypted_secrets=candidate.encrypted_secrets,
                secret_metadata=candidate.secret_metadata,
                validation_status=SystemSettingValidationStatus.VALID,
                validated_generation=resolved.effective_generation,
                validation_metadata=candidate.validation_metadata,
                validated_at=now,
                updated_by_user_id=actor_user_id,
            ),
        )
        await self.repository.delete_candidate(
            session,
            section=candidate.section,
            candidate_id=candidate.id,
        )
        await self.repository.append_audit_event(
            session,
            create=SystemSettingAuditEventCreate(
                section=candidate.section,
                event_type=SystemSettingAuditEventType.ACTIVATED,
                source=SystemSettingAuditSource.ADMIN_API,
                previous_version=candidate.base_version,
                new_version=new_version,
                actor_user_id=actor_user_id,
                changed_fields=[],
                secret_actions={},
                validation_status=SystemSettingValidationStatus.VALID,
                candidate_id=candidate.id,
                impact_confirmed=impact_confirmed,
                confirmation_action=confirmation_action,
                metadata=None,
                created_at=now,
            ),
        )
        return SystemSettingActivated(
            current=current,
            resolved=dataclasses.replace(resolved, admin_version=new_version),
        )

    def _resolve_candidate(
        self,
        *,
        definition: SystemSettingDefinition,
        candidate: StoredSystemSettingCandidate,
    ) -> ResolvedSystemSetting:
        config, secrets = self._load_base_payload(
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
        return self._resolve_payload(
            definition=definition,
            admin_version=candidate.base_version,
            config=config,
            secrets=secrets,
        )

    def _resolve_current(
        self,
        *,
        definition: SystemSettingDefinition,
        current: StoredSystemSetting | None,
    ) -> ResolvedSystemSetting:
        config, secrets = self._load_base_payload(
            definition=definition,
            current=current,
        )
        return self._resolve_payload(
            definition=definition,
            admin_version=current.version if current is not None else 0,
            config=config,
            secrets=secrets,
        )

    def _load_base_payload(
        self,
        *,
        definition: SystemSettingDefinition,
        current: StoredSystemSetting | None,
    ) -> tuple[BaseModel, BaseModel]:
        if current is None:
            config_data: dict[str, Any] = {}
            secret_data: dict[str, Any] = {}
            schema_version = definition.schema_version
        else:
            config_data = current.config
            secret_data = self._decrypt_secrets(current.encrypted_secrets)
            schema_version = current.schema_version
        config_data, secret_data = definition.migrate_payload(
            schema_version=schema_version,
            config=config_data,
            secrets=secret_data,
        )
        return (
            definition.config_model.model_validate(config_data),
            definition.secret_model.model_validate(secret_data),
        )

    def _resolve_payload(
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

    def _reject_environment_owned_mutations(
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
    def _validate_patch_fields(
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

    def _decrypt_secrets(self, ciphertext: str | None) -> dict[str, Any]:
        if ciphertext is None:
            return {}
        payload = json.loads(self.cipher.decrypt(ciphertext))
        if not isinstance(payload, dict):
            raise ValueError("Stored System Settings secret payload must be an object.")
        return payload

    def _encrypt_secrets(self, secrets: BaseModel) -> str | None:
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
    def _update_secret_metadata(
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

    async def _delete_expired_candidate(
        self,
        *,
        session: AsyncSession,
        definition: SystemSettingDefinition,
        now: datetime.datetime,
    ) -> None:
        candidate = await self.repository.get_candidate(
            session,
            section=definition.section,
        )
        if candidate is None or candidate.expires_at > now:
            return
        await self.repository.delete_candidate(
            session,
            section=definition.section,
            candidate_id=candidate.id,
        )


@dataclasses.dataclass(frozen=True)
class SystemDataMigrationRunner:
    """Serialize application data migrations and persist their outcome."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    repository: Annotated[
        SystemDataMigrationRepository,
        Depends(SystemDataMigrationRepository),
    ]

    async def run(
        self,
        *,
        name: str,
        operation: SystemDataMigrationOperation,
    ) -> StoredSystemDataMigration:
        """Run one migration once with data and marker in the same transaction."""
        async with self.session_manager() as session:
            await self.repository.acquire_lock(session, name=name)
            existing = await self.repository.get(session, name=name)
            if existing is not None:
                return existing
            result = await operation(session)
            return await self.repository.create(
                session,
                name=name,
                outcome=result.outcome,
                metadata=result.metadata,
                completed_at=tznow(),
            )
