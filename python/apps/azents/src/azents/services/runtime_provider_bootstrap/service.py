"""Trusted Runtime Provider bootstrap reconciliation service."""

import dataclasses
import datetime
from typing import Annotated

from azcommon.datetime import tznow
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeProviderAuditEventType,
    RuntimeProviderBootstrapDeclarationState,
    RuntimeProviderLifecycleState,
    RuntimeProviderRegistrationMethod,
    RuntimeProviderScope,
)
from azents.core.platform_runtime_system_setting import (
    PlatformRuntimeConfig,
    get_platform_runtime_definition,
)
from azents.core.system_setting import (
    SystemSettingAuditEventType,
    SystemSettingAuditSource,
    SystemSettingSection,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.runtime_provider.data import (
    RuntimeProvider,
    RuntimeProviderAuditEventCreate,
    RuntimeProviderBootstrapDeclaration,
    RuntimeProviderBootstrapDeclarationCreate,
    RuntimeProviderBootstrapSource,
    RuntimeProviderBootstrapSourceCreate,
    RuntimeProviderCreate,
)
from azents.repos.runtime_provider.repository import RuntimeProviderRepository
from azents.repos.system_setting.data import (
    SystemSettingAuditEventCreate,
    SystemSettingCurrentWrite,
)
from azents.repos.system_setting.repository import SystemSettingRepository

from .data import (
    RuntimeProviderBootstrapDeclarationInput,
    RuntimeProviderBootstrapReconcileResult,
    RuntimeProviderBootstrapSnapshot,
    RuntimeProviderBootstrapSourceError,
)

_TERMINAL_LIFECYCLE_STATES = frozenset(
    {
        RuntimeProviderLifecycleState.DECOMMISSIONED,
        RuntimeProviderLifecycleState.FORCE_RETIRED,
    }
)


@dataclasses.dataclass(frozen=True)
class _DeclarationReconcileOutcome:
    """Internal reconciliation outcome for one declaration."""

    created_provider_id: str | None
    reconciled_provider_id: str | None
    conflicted_declaration_key: str | None


@dataclasses.dataclass(frozen=True)
class RuntimeProviderBootstrapService:
    """Reconcile successful authoritative bootstrap source snapshots."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    repository: Annotated[RuntimeProviderRepository, Depends(RuntimeProviderRepository)]
    system_setting_repository: Annotated[
        SystemSettingRepository, Depends(SystemSettingRepository)
    ]

    async def reconcile(
        self,
        snapshot: RuntimeProviderBootstrapSnapshot,
    ) -> RuntimeProviderBootstrapReconcileResult:
        """Apply one complete authoritative source snapshot transactionally."""
        now = tznow()
        created_provider_ids: list[str] = []
        reconciled_provider_ids: list[str] = []
        conflicted_declaration_keys: list[str] = []
        withdrawn_provider_ids: list[str] = []

        async with self.session_manager() as session:
            await self.repository.acquire_bootstrap_source_lock(
                session,
                source_key=snapshot.source_key,
            )
            source = await self.repository.get_or_create_bootstrap_source(
                session,
                create=RuntimeProviderBootstrapSourceCreate(
                    source_key=snapshot.source_key,
                    adapter_kind=snapshot.adapter_kind,
                ),
            )
            present_declaration_keys: set[str] = set()
            for declaration in snapshot.declarations:
                present_declaration_keys.add(declaration.declaration_key)
                outcome = await self._reconcile_declaration(
                    session=session,
                    source=source,
                    snapshot=snapshot,
                    declaration=declaration,
                    now=now,
                )
                if outcome.created_provider_id is not None:
                    created_provider_ids.append(outcome.created_provider_id)
                if outcome.reconciled_provider_id is not None:
                    reconciled_provider_ids.append(outcome.reconciled_provider_id)
                if outcome.conflicted_declaration_key is not None:
                    conflicted_declaration_keys.append(
                        outcome.conflicted_declaration_key
                    )

            withdrawn = await self.repository.mark_missing_declarations_absent(
                session,
                source_id=source.id,
                present_declaration_keys=present_declaration_keys,
                source_revision=snapshot.source_revision,
                source_digest=snapshot.source_digest,
                occurred_at=now,
            )
            for declaration in withdrawn:
                if declaration.provider_id is None:
                    continue
                withdrawn_provider_ids.append(declaration.provider_id)
                await self.repository.append_audit_event(
                    session,
                    create=RuntimeProviderAuditEventCreate(
                        provider_id=declaration.provider_id,
                        event_type=RuntimeProviderAuditEventType.BOOTSTRAP_WITHDRAWN,
                        actor_user_id=None,
                        metadata={
                            "source_key": snapshot.source_key,
                            "declaration_key": declaration.declaration_key,
                            "source_revision": snapshot.source_revision,
                        },
                        created_at=now,
                    ),
                )

            await self.repository.record_source_reconciled(
                session,
                source_id=source.id,
                source_revision=snapshot.source_revision,
                source_digest=snapshot.source_digest,
                reconciled_at=now,
            )

        return RuntimeProviderBootstrapReconcileResult(
            source_id=source.id,
            created_provider_ids=tuple(created_provider_ids),
            reconciled_provider_ids=tuple(reconciled_provider_ids),
            withdrawn_provider_ids=tuple(withdrawn_provider_ids),
            conflicted_declaration_keys=tuple(conflicted_declaration_keys),
        )

    async def record_source_error(
        self,
        source_error: RuntimeProviderBootstrapSourceError,
    ) -> None:
        """Record a failed adapter read without withdrawing declarations."""
        now = tznow()
        async with self.session_manager() as session:
            await self.repository.acquire_bootstrap_source_lock(
                session,
                source_key=source_error.source_key,
            )
            source = await self.repository.get_or_create_bootstrap_source(
                session,
                create=RuntimeProviderBootstrapSourceCreate(
                    source_key=source_error.source_key,
                    adapter_kind=source_error.adapter_kind,
                ),
            )
            await self.repository.record_source_error(
                session,
                source_id=source.id,
                error_code=source_error.error_code,
                error_message=source_error.error_message,
                occurred_at=now,
            )

    async def _reconcile_declaration(
        self,
        *,
        session: AsyncSession,
        source: RuntimeProviderBootstrapSource,
        snapshot: RuntimeProviderBootstrapSnapshot,
        declaration: RuntimeProviderBootstrapDeclarationInput,
        now: datetime.datetime,
    ) -> _DeclarationReconcileOutcome:
        """Reconcile one immutable source-local declaration identity."""
        await self.repository.acquire_provider_identity_lock(
            session,
            provider_logical_id=declaration.provider_logical_id,
        )
        existing = await self.repository.get_bootstrap_declaration(
            session,
            source_id=source.id,
            declaration_key=declaration.declaration_key,
            for_update=True,
        )
        if existing is not None and (
            existing.provider_logical_id != declaration.provider_logical_id
            or existing.kind != declaration.kind
        ):
            await self._record_conflict(
                session=session,
                source=source,
                snapshot=snapshot,
                declaration=declaration,
                existing=existing,
                provider_id=existing.provider_id,
                code="immutable_declaration_identity_changed",
                message="Bootstrap declaration identity cannot change.",
                now=now,
            )
            return _DeclarationReconcileOutcome(
                created_provider_id=None,
                reconciled_provider_id=None,
                conflicted_declaration_key=declaration.declaration_key,
            )

        provider = await self.repository.get_by_provider_id(
            session,
            provider_logical_id=declaration.provider_logical_id,
            for_update=True,
        )
        if existing is not None and existing.provider_id is not None:
            return await self._reconcile_linked_declaration(
                session=session,
                source=source,
                snapshot=snapshot,
                declaration=declaration,
                existing=existing,
                provider=provider,
                now=now,
            )

        if provider is not None:
            linked_declaration = (
                await self.repository.get_bootstrap_declaration_by_provider_id(
                    session,
                    provider_id=provider.id,
                    for_update=True,
                )
            )
            conflict_code = self._existing_provider_conflict_code(
                provider=provider,
                linked_declaration=linked_declaration,
                source_id=source.id,
                declaration_key=declaration.declaration_key,
            )
            await self._record_conflict(
                session=session,
                source=source,
                snapshot=snapshot,
                declaration=declaration,
                existing=existing,
                provider_id=provider.id,
                code=conflict_code,
                message="Bootstrap sources cannot adopt an existing Provider.",
                now=now,
            )
            return _DeclarationReconcileOutcome(
                created_provider_id=None,
                reconciled_provider_id=None,
                conflicted_declaration_key=declaration.declaration_key,
            )

        created = await self.repository.create(
            session,
            RuntimeProviderCreate(
                provider_id=declaration.provider_logical_id,
                scope=RuntimeProviderScope.SYSTEM,
                workspace_id=None,
                kind=declaration.kind,
                display_name=declaration.display_name,
                registration_method=RuntimeProviderRegistrationMethod.BOOTSTRAP,
                enabled=declaration.enabled,
                lifecycle_state=RuntimeProviderLifecycleState.ACTIVE,
                availability_mode=declaration.availability_mode,
                capabilities=declaration.capabilities,
                config_schema=declaration.config_schema,
                metadata=declaration.metadata,
            ),
        )
        if existing is None:
            await self.repository.create_bootstrap_declaration(
                session,
                create=RuntimeProviderBootstrapDeclarationCreate(
                    source_id=source.id,
                    declaration_key=declaration.declaration_key,
                    provider_logical_id=declaration.provider_logical_id,
                    kind=declaration.kind,
                    provider_id=created.id,
                    source_revision=snapshot.source_revision,
                    source_digest=snapshot.source_digest,
                    state=RuntimeProviderBootstrapDeclarationState.PRESENT,
                    creation_seeds=declaration.creation_seeds,
                    conflict_code=None,
                    conflict_message=None,
                    last_seen_at=now,
                    withdrawn_at=None,
                ),
            )
        else:
            await self.repository.update_bootstrap_declaration(
                session,
                declaration_id=existing.id,
                provider_id=created.id,
                source_revision=snapshot.source_revision,
                source_digest=snapshot.source_digest,
                state=RuntimeProviderBootstrapDeclarationState.PRESENT,
                creation_seeds=(
                    existing.creation_seeds
                    if existing.creation_seeds is not None
                    else declaration.creation_seeds
                ),
                conflict_code=None,
                conflict_message=None,
                last_seen_at=now,
                withdrawn_at=None,
                updated_at=now,
            )
        await self._seed_platform_default_when_unset(
            session=session,
            source=source,
            declaration=declaration,
            creation_seeds=(
                existing.creation_seeds
                if existing is not None and existing.creation_seeds is not None
                else declaration.creation_seeds
            ),
            now=now,
        )
        await self.repository.append_audit_event(
            session,
            create=RuntimeProviderAuditEventCreate(
                provider_id=created.id,
                event_type=RuntimeProviderAuditEventType.REGISTERED,
                actor_user_id=None,
                metadata={
                    "registration_method": (
                        RuntimeProviderRegistrationMethod.BOOTSTRAP.value
                    ),
                    "source_key": source.source_key,
                    "declaration_key": declaration.declaration_key,
                },
                created_at=now,
            ),
        )
        await self._append_reconciled_audit_event(
            session=session,
            provider_id=created.id,
            source=source,
            declaration_key=declaration.declaration_key,
            source_revision=snapshot.source_revision,
            now=now,
        )
        return _DeclarationReconcileOutcome(
            created_provider_id=created.id,
            reconciled_provider_id=created.id,
            conflicted_declaration_key=None,
        )

    async def _seed_platform_default_when_unset(
        self,
        *,
        session: AsyncSession,
        source: RuntimeProviderBootstrapSource,
        declaration: RuntimeProviderBootstrapDeclarationInput,
        creation_seeds: dict[str, object] | None,
        now: datetime.datetime,
    ) -> None:
        """Apply the creation-only Platform default seed when policy is unset."""
        if not creation_seeds or not creation_seeds.get(
            "set_as_platform_default_when_unset",
            False,
        ):
            return
        section = SystemSettingSection.PLATFORM_RUNTIME
        await self.system_setting_repository.acquire_section_lock(
            session,
            section=section,
        )
        current = await self.system_setting_repository.get_current(
            session,
            section=section,
        )
        candidate = await self.system_setting_repository.get_candidate(
            session,
            section=section,
        )
        if candidate is not None:
            return
        if current is not None:
            current_config = PlatformRuntimeConfig.model_validate(current.config)
            if current_config.default_provider_id is not None:
                return
        definition = get_platform_runtime_definition()
        previous_version = current.version if current is not None else 0
        next_version = previous_version + 1
        config = PlatformRuntimeConfig(
            default_provider_id=declaration.provider_logical_id
        )
        await self.system_setting_repository.write_current(
            session,
            write=SystemSettingCurrentWrite(
                section=section,
                schema_version=definition.schema_version,
                version=next_version,
                config=config.model_dump(mode="json"),
                encrypted_secrets=(
                    current.encrypted_secrets if current is not None else None
                ),
                secret_metadata=(
                    current.secret_metadata if current is not None else {}
                ),
                validation_status=None,
                validated_generation=None,
                validation_metadata=None,
                validated_at=None,
                updated_by_user_id=None,
            ),
        )
        await self.system_setting_repository.append_audit_event(
            session,
            create=SystemSettingAuditEventCreate(
                section=section,
                event_type=SystemSettingAuditEventType.ACTIVATED,
                source=SystemSettingAuditSource.SYSTEM,
                previous_version=previous_version,
                new_version=next_version,
                actor_user_id=None,
                changed_fields=["default_provider_id"],
                secret_actions={},
                validation_status=None,
                candidate_id=None,
                impact_confirmed=False,
                confirmation_action=None,
                metadata={
                    "bootstrap_source_key": source.source_key,
                    "bootstrap_declaration_key": declaration.declaration_key,
                },
                created_at=now,
            ),
        )

    async def _reconcile_linked_declaration(
        self,
        *,
        session: AsyncSession,
        source: RuntimeProviderBootstrapSource,
        snapshot: RuntimeProviderBootstrapSnapshot,
        declaration: RuntimeProviderBootstrapDeclarationInput,
        existing: RuntimeProviderBootstrapDeclaration,
        provider: RuntimeProvider | None,
        now: datetime.datetime,
    ) -> _DeclarationReconcileOutcome:
        """Reconcile a declaration already linked to a Provider aggregate."""
        if provider is None or provider.id != existing.provider_id:
            await self._record_conflict(
                session=session,
                source=source,
                snapshot=snapshot,
                declaration=declaration,
                existing=existing,
                provider_id=existing.provider_id,
                code="linked_provider_identity_missing",
                message="The linked Provider no longer matches its declaration.",
                now=now,
            )
            return _DeclarationReconcileOutcome(
                created_provider_id=None,
                reconciled_provider_id=None,
                conflicted_declaration_key=declaration.declaration_key,
            )
        if provider.lifecycle_state in _TERMINAL_LIFECYCLE_STATES:
            await self._record_conflict(
                session=session,
                source=source,
                snapshot=snapshot,
                declaration=declaration,
                existing=existing,
                provider_id=provider.id,
                code="provider_terminal",
                message="A terminal Provider identity cannot be restored by bootstrap.",
                now=now,
            )
            return _DeclarationReconcileOutcome(
                created_provider_id=None,
                reconciled_provider_id=None,
                conflicted_declaration_key=declaration.declaration_key,
            )
        await self.repository.update_bootstrap_declaration(
            session,
            declaration_id=existing.id,
            provider_id=provider.id,
            source_revision=snapshot.source_revision,
            source_digest=snapshot.source_digest,
            state=RuntimeProviderBootstrapDeclarationState.PRESENT,
            creation_seeds=existing.creation_seeds,
            conflict_code=None,
            conflict_message=None,
            last_seen_at=now,
            withdrawn_at=None,
            updated_at=now,
        )
        await self._append_reconciled_audit_event(
            session=session,
            provider_id=provider.id,
            source=source,
            declaration_key=declaration.declaration_key,
            source_revision=snapshot.source_revision,
            now=now,
        )
        return _DeclarationReconcileOutcome(
            created_provider_id=None,
            reconciled_provider_id=provider.id,
            conflicted_declaration_key=None,
        )

    async def _record_conflict(
        self,
        *,
        session: AsyncSession,
        source: RuntimeProviderBootstrapSource,
        snapshot: RuntimeProviderBootstrapSnapshot,
        declaration: RuntimeProviderBootstrapDeclarationInput,
        existing: RuntimeProviderBootstrapDeclaration | None,
        provider_id: str | None,
        code: str,
        message: str,
        now: datetime.datetime,
    ) -> None:
        """Persist a source declaration conflict without implicit Provider adoption."""
        if existing is None:
            await self.repository.create_bootstrap_declaration(
                session,
                create=RuntimeProviderBootstrapDeclarationCreate(
                    source_id=source.id,
                    declaration_key=declaration.declaration_key,
                    provider_logical_id=declaration.provider_logical_id,
                    kind=declaration.kind,
                    provider_id=None,
                    source_revision=snapshot.source_revision,
                    source_digest=snapshot.source_digest,
                    state=RuntimeProviderBootstrapDeclarationState.CONFLICT,
                    creation_seeds=declaration.creation_seeds,
                    conflict_code=code,
                    conflict_message=message,
                    last_seen_at=now,
                    withdrawn_at=None,
                ),
            )
        else:
            await self.repository.update_bootstrap_declaration(
                session,
                declaration_id=existing.id,
                provider_id=existing.provider_id,
                source_revision=snapshot.source_revision,
                source_digest=snapshot.source_digest,
                state=RuntimeProviderBootstrapDeclarationState.CONFLICT,
                creation_seeds=existing.creation_seeds,
                conflict_code=code,
                conflict_message=message,
                last_seen_at=now,
                withdrawn_at=None,
                updated_at=now,
            )
        if provider_id is None:
            return
        await self.repository.append_audit_event(
            session,
            create=RuntimeProviderAuditEventCreate(
                provider_id=provider_id,
                event_type=RuntimeProviderAuditEventType.BOOTSTRAP_CONFLICT,
                actor_user_id=None,
                metadata={
                    "source_key": source.source_key,
                    "declaration_key": declaration.declaration_key,
                    "code": code,
                },
                created_at=now,
            ),
        )

    @staticmethod
    def _existing_provider_conflict_code(
        *,
        provider: RuntimeProvider,
        linked_declaration: RuntimeProviderBootstrapDeclaration | None,
        source_id: str,
        declaration_key: str,
    ) -> str:
        """Classify an attempted source claim of an existing Provider identity."""
        if provider.registration_method != RuntimeProviderRegistrationMethod.BOOTSTRAP:
            return "provider_owned_by_admin"
        if linked_declaration is None:
            return "bootstrap_provider_declaration_missing"
        if (
            linked_declaration.source_id != source_id
            or linked_declaration.declaration_key != declaration_key
        ):
            return "provider_owned_by_different_source"
        return "provider_already_linked"

    async def _append_reconciled_audit_event(
        self,
        *,
        session: AsyncSession,
        provider_id: str,
        source: RuntimeProviderBootstrapSource,
        declaration_key: str,
        source_revision: str,
        now: datetime.datetime,
    ) -> None:
        """Append a metadata-only successful reconciliation audit event."""
        await self.repository.append_audit_event(
            session,
            create=RuntimeProviderAuditEventCreate(
                provider_id=provider_id,
                event_type=RuntimeProviderAuditEventType.BOOTSTRAP_RECONCILED,
                actor_user_id=None,
                metadata={
                    "source_key": source.source_key,
                    "declaration_key": declaration_key,
                    "source_revision": source_revision,
                },
                created_at=now,
            ),
        )
