"""Completed database-only System Settings lifecycle operations."""

import dataclasses
import datetime
from typing import Annotated

from azcommon.datetime import tznow
from azcommon.uuid import uuid7
from fastapi import Depends
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.system_setting import (
    ResolvedSystemSetting,
    SystemSettingActivationMode,
    SystemSettingAuditEventType,
    SystemSettingAuditSource,
    SystemSettingCandidateNotFound,
    SystemSettingCandidateNotValidated,
    SystemSettingCandidateReplaced,
    SystemSettingDefinition,
    SystemSettingEffectiveGenerationChanged,
    SystemSettingImpactChanged,
    SystemSettingSecretActionType,
    SystemSettingSection,
    SystemSettingValidationStatus,
    SystemSettingVersionConflict,
)
from azents.core.system_setting_data import (
    CurrentSystemSettingHealth,
    StoredSystemSettingCandidate,
    SystemSettingActivated,
    SystemSettingAuditEventCreate,
    SystemSettingAuditEventList,
    SystemSettingCandidateCreate,
    SystemSettingCandidatePending,
    SystemSettingCandidateValidationResult,
    SystemSettingCandidateValidationSnapshot,
    SystemSettingCurrentWrite,
    SystemSettingExpiryCommitted,
    SystemSettingHealthResult,
    SystemSettingHealthWrite,
    SystemSettingMutation,
    SystemSettingMutationResult,
    SystemSettingState,
)
from azents.core.system_setting_payload import SystemSettingPayloadResolver
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.github_platform_system_setting.data import (
    PlatformGitHubAppConfirmationImpact,
)
from azents.repos.github_platform_system_setting.operations import (
    PlatformGitHubAppImpactRepository,
)
from azents.repos.system_setting.repository import SystemSettingRepository


@dataclasses.dataclass(frozen=True)
class SystemSettingsRepository:
    """Own Section lifetimes and atomic query composition."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    repository: Annotated[SystemSettingRepository, Depends(SystemSettingRepository)]
    payloads: Annotated[
        SystemSettingPayloadResolver, Depends(SystemSettingPayloadResolver)
    ]
    github_impact: Annotated[
        PlatformGitHubAppImpactRepository, Depends(PlatformGitHubAppImpactRepository)
    ]

    async def resolve(
        self,
        section: SystemSettingSection,
    ) -> ResolvedSystemSetting:
        """Resolve one current effective Section for an operation."""
        definition = self.payloads.registry.get(section)
        async with self.session_manager() as session:
            current = await self.repository.get_current(session, section=section)
        return self.payloads.resolve_current(definition=definition, current=current)

    async def mutate(
        self,
        mutation: SystemSettingMutation,
    ) -> SystemSettingMutationResult:
        """Apply a direct mutation or replace the Section candidate."""
        definition = self.payloads.registry.get(mutation.section)
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
            base_config, base_secrets = self.payloads.load_base_payload(
                definition=definition,
                current=current,
            )
            self.payloads.reject_environment_owned_mutations(
                definition=definition,
                config_fields=mutation.config_patch,
                secret_fields=mutation.secret_actions,
            )
            config_data = base_config.model_dump(mode="python")
            secret_data = base_secrets.model_dump(mode="python")
            self.payloads.validate_patch_fields(
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
            resolved = self.payloads.resolve_payload(
                definition=definition,
                admin_version=current_version,
                config=typed_config,
                secrets=typed_secrets,
            )
            secret_metadata = self.payloads.update_secret_metadata(
                current=current,
                secrets=typed_secrets,
                changed_fields=mutation.secret_actions,
                changed_at=now,
            )
            encrypted_secrets = self.payloads.encrypt_secrets(typed_secrets)
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
        definition = self.payloads.registry.get(section)
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
        definition = self.payloads.registry.get(section)
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
            resolved = self.payloads.resolve_current(
                definition=definition, current=current
            )
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
    ) -> SystemSettingCandidateValidationSnapshot | SystemSettingExpiryCommitted:
        """Return a stable current/candidate snapshot for external validation."""
        definition = self.payloads.registry.get(section)
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
                    current_resolved=self.payloads.resolve_current(
                        definition=definition,
                        current=current,
                    ),
                    candidate_resolved=self.payloads.resolve_candidate(
                        definition=definition,
                        candidate=candidate,
                    ),
                )
        if expired_candidate_id is not None:
            return SystemSettingExpiryCommitted(
                section=section,
                candidate_id=expired_candidate_id,
            )
        if snapshot is None:
            raise RuntimeError("Candidate validation snapshot was not produced.")
        return snapshot

    async def confirm_candidate(
        self,
        *,
        section: SystemSettingSection,
        candidate_id: str,
        expected_version: int,
        confirmation_action: str,
        actor_user_id: str | None,
    ) -> SystemSettingActivated | SystemSettingExpiryCommitted:
        """Activate a valid candidate after rechecking generation and impact."""
        definition = self.payloads.registry.get(section)
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
                snapshot = await self._prepare_confirmation_in_session(
                    session,
                    definition=definition,
                    candidate=candidate,
                    expected_version=expected_version,
                )
                current_resolved = snapshot.current_resolved
                candidate_resolved = snapshot.candidate_resolved
                current_impact = await self.github_impact.resolve_impact_in_session(
                    session, current_resolved, candidate_resolved
                )
                try:
                    candidate_impact = (
                        PlatformGitHubAppConfirmationImpact.model_validate(
                            candidate.impact
                        )
                    )
                except ValidationError as error:
                    raise SystemSettingImpactChanged(
                        section=section,
                        candidate_id=candidate.id,
                        current_impact=current_impact.model_dump(mode="json"),
                    ) from error
                if current_impact != candidate_impact:
                    raise SystemSettingImpactChanged(
                        section=section,
                        candidate_id=candidate.id,
                        current_impact=current_impact.model_dump(mode="json"),
                    )
                if confirmation_action not in current_impact.confirmation_actions:
                    raise ValueError(
                        "Unsupported Platform GitHub App confirmation action."
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
            return SystemSettingExpiryCommitted(
                section=section,
                candidate_id=expired_candidate_id,
            )
        if activated is None:
            raise RuntimeError("Candidate confirmation did not activate a setting.")
        return activated

    async def _prepare_confirmation_in_session(
        self,
        session: AsyncSession,
        *,
        definition: SystemSettingDefinition,
        candidate: StoredSystemSettingCandidate,
        expected_version: int,
    ) -> SystemSettingCandidateValidationSnapshot:
        """Check generic confirmation authority within the locked transaction."""
        section = candidate.section
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
        current_resolved = self.payloads.resolve_current(
            definition=definition,
            current=current,
        )
        candidate_resolved = self.payloads.resolve_candidate(
            definition=definition,
            candidate=candidate,
        )
        if candidate_resolved.effective_generation != candidate.validated_generation:
            raise SystemSettingEffectiveGenerationChanged(
                section=section,
                expected_generation=candidate.validated_generation,
                current_generation=candidate_resolved.effective_generation,
            )
        return SystemSettingCandidateValidationSnapshot(
            candidate=candidate,
            current_resolved=current_resolved,
            candidate_resolved=candidate_resolved,
        )

    async def cancel_candidate(
        self,
        *,
        section: SystemSettingSection,
        candidate_id: str,
        actor_user_id: str | None,
    ) -> SystemSettingExpiryCommitted | None:
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
            return SystemSettingExpiryCommitted(
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
        definition = self.payloads.registry.get(section)
        async with self.session_manager() as session:
            await self.repository.acquire_section_lock(session, section=section)
            current = await self.repository.get_current(session, section=section)
            resolved = self.payloads.resolve_current(
                definition=definition, current=current
            )
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

    async def record_candidate_validation(
        self,
        *,
        snapshot: SystemSettingCandidateValidationSnapshot,
        result: SystemSettingCandidateValidationResult,
    ) -> SystemSettingMutationResult | SystemSettingExpiryCommitted:
        if result.status == SystemSettingValidationStatus.PENDING:
            raise ValueError("External validation cannot return pending status.")
        if (
            result.confirmation_required
            and result.status != SystemSettingValidationStatus.VALID
        ):
            raise ValueError("Only a valid candidate can require confirmation.")
        section = snapshot.candidate.section
        definition = self.payloads.registry.get(section)
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
                resolved = self.payloads.resolve_candidate(
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
            return SystemSettingExpiryCommitted(
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

    async def list_audit_events(
        self, *, section: SystemSettingSection | None, offset: int, limit: int
    ) -> SystemSettingAuditEventList:
        """Complete the metadata-only audit read before returning."""
        async with self.session_manager() as session:
            return await self.repository.list_audit_events(
                session, section=section, offset=offset, limit=limit
            )
