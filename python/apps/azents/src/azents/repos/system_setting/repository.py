"""System Settings repositories."""

import datetime
import hashlib

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.system_setting import (
    SystemDataMigrationOutcome,
    SystemSettingSection,
    SystemSettingValidationStatus,
)
from azents.rdb.models.system_setting import (
    RDBSystemDataMigration,
    RDBSystemSetting,
    RDBSystemSettingAuditEvent,
    RDBSystemSettingCandidate,
    RDBSystemSettingHealth,
)

from .data import (
    StoredSystemDataMigration,
    StoredSystemSetting,
    StoredSystemSettingAuditEvent,
    StoredSystemSettingCandidate,
    StoredSystemSettingHealth,
    SystemSettingAuditEventCreate,
    SystemSettingAuditEventList,
    SystemSettingCandidateCreate,
    SystemSettingCurrentWrite,
    SystemSettingHealthWrite,
)


def _advisory_lock_id(namespace: str, name: str) -> int:
    """Derive a stable signed PostgreSQL advisory lock ID."""
    digest = hashlib.sha256(f"{namespace}:{name}".encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


class SystemSettingRepository:
    """Persist current, candidate, health, and audit Section state."""

    async def acquire_section_lock(
        self,
        session: AsyncSession,
        *,
        section: SystemSettingSection,
    ) -> None:
        """Serialize mutations for one Section."""
        await session.execute(
            sa.select(
                sa.func.pg_advisory_xact_lock(
                    _advisory_lock_id("system-setting-section", section.value)
                )
            )
        )

    async def get_current(
        self,
        session: AsyncSession,
        *,
        section: SystemSettingSection,
    ) -> StoredSystemSetting | None:
        """Fetch current Admin-managed Section state."""
        rdb = await session.get(RDBSystemSetting, section)
        return self._build_current(rdb) if rdb is not None else None

    async def write_current(
        self,
        session: AsyncSession,
        *,
        write: SystemSettingCurrentWrite,
    ) -> StoredSystemSetting:
        """Insert or replace current Section state."""
        statement = (
            insert(RDBSystemSetting)
            .values(
                section=write.section,
                schema_version=write.schema_version,
                version=write.version,
                config=write.config,
                encrypted_secrets=write.encrypted_secrets,
                secret_metadata=write.secret_metadata,
                validation_status=write.validation_status,
                validated_generation=write.validated_generation,
                validation_metadata=write.validation_metadata,
                validated_at=write.validated_at,
                updated_by_user_id=write.updated_by_user_id,
            )
            .on_conflict_do_update(
                index_elements=[RDBSystemSetting.section],
                set_={
                    "schema_version": write.schema_version,
                    "version": write.version,
                    "config": write.config,
                    "encrypted_secrets": write.encrypted_secrets,
                    "secret_metadata": write.secret_metadata,
                    "validation_status": write.validation_status,
                    "validated_generation": write.validated_generation,
                    "validation_metadata": write.validation_metadata,
                    "validated_at": write.validated_at,
                    "updated_by_user_id": write.updated_by_user_id,
                    "updated_at": sa.func.now(),
                },
            )
            .returning(RDBSystemSetting)
        )
        result = await session.execute(statement)
        return self._build_current(result.scalar_one())

    async def get_candidate(
        self,
        session: AsyncSession,
        *,
        section: SystemSettingSection,
    ) -> StoredSystemSettingCandidate | None:
        """Fetch the single candidate for a Section."""
        result = await session.execute(
            sa.select(RDBSystemSettingCandidate).where(
                RDBSystemSettingCandidate.section == section
            )
        )
        rdb = result.scalar_one_or_none()
        return self._build_candidate(rdb) if rdb is not None else None

    async def replace_candidate(
        self,
        session: AsyncSession,
        *,
        create: SystemSettingCandidateCreate,
    ) -> StoredSystemSettingCandidate:
        """Delete any previous candidate and store the replacement."""
        await session.execute(
            sa.delete(RDBSystemSettingCandidate).where(
                RDBSystemSettingCandidate.section == create.section
            )
        )
        rdb = RDBSystemSettingCandidate(
            id=create.id,
            section=create.section,
            schema_version=create.schema_version,
            base_version=create.base_version,
            config=create.config,
            validation_status=create.validation_status,
            created_at=create.created_at,
            updated_at=create.updated_at,
            expires_at=create.expires_at,
            encrypted_secrets=create.encrypted_secrets,
            secret_metadata=create.secret_metadata,
            validated_generation=None,
            validation_code=None,
            validation_message=None,
            action_hint=None,
            validation_metadata=None,
            impact=None,
            created_by_user_id=create.created_by_user_id,
        )
        session.add(rdb)
        await session.flush()
        return self._build_candidate(rdb)

    async def update_candidate_validation(
        self,
        session: AsyncSession,
        *,
        candidate_id: str,
        status: SystemSettingValidationStatus,
        validated_generation: str | None,
        validation_code: str | None,
        validation_message: str | None,
        action_hint: str | None,
        validation_metadata: dict[str, object] | None,
        impact: dict[str, object] | None,
        updated_at: datetime.datetime,
    ) -> StoredSystemSettingCandidate | None:
        """Update validation fields only when the candidate still exists."""
        result = await session.execute(
            sa.update(RDBSystemSettingCandidate)
            .where(RDBSystemSettingCandidate.id == candidate_id)
            .values(
                validation_status=status,
                validated_generation=validated_generation,
                validation_code=validation_code,
                validation_message=validation_message,
                action_hint=action_hint,
                validation_metadata=validation_metadata,
                impact=impact,
                updated_at=updated_at,
            )
            .returning(RDBSystemSettingCandidate)
        )
        rdb = result.scalar_one_or_none()
        return self._build_candidate(rdb) if rdb is not None else None

    async def delete_candidate(
        self,
        session: AsyncSession,
        *,
        section: SystemSettingSection,
        candidate_id: str | None = None,
    ) -> bool:
        """Delete the current candidate and its ciphertext."""
        filters = [RDBSystemSettingCandidate.section == section]
        if candidate_id is not None:
            filters.append(RDBSystemSettingCandidate.id == candidate_id)
        result = await session.execute(
            sa.delete(RDBSystemSettingCandidate)
            .where(*filters)
            .returning(RDBSystemSettingCandidate.id)
        )
        return result.scalar_one_or_none() is not None

    async def get_health(
        self,
        session: AsyncSession,
        *,
        section: SystemSettingSection,
    ) -> StoredSystemSettingHealth | None:
        """Fetch the latest explicit health result."""
        rdb = await session.get(RDBSystemSettingHealth, section)
        return self._build_health(rdb) if rdb is not None else None

    async def write_health(
        self,
        session: AsyncSession,
        *,
        write: SystemSettingHealthWrite,
    ) -> StoredSystemSettingHealth:
        """Insert or replace the latest health result."""
        statement = (
            insert(RDBSystemSettingHealth)
            .values(
                section=write.section,
                effective_generation=write.effective_generation,
                status=write.status,
                code=write.code,
                message=write.message,
                action_hint=write.action_hint,
                result_metadata=write.metadata,
                checked_by_user_id=write.checked_by_user_id,
                checked_at=write.checked_at,
            )
            .on_conflict_do_update(
                index_elements=[RDBSystemSettingHealth.section],
                set_={
                    "effective_generation": write.effective_generation,
                    "status": write.status,
                    "code": write.code,
                    "message": write.message,
                    "action_hint": write.action_hint,
                    RDBSystemSettingHealth.result_metadata: write.metadata,
                    "checked_by_user_id": write.checked_by_user_id,
                    "checked_at": write.checked_at,
                },
            )
            .returning(RDBSystemSettingHealth)
        )
        result = await session.execute(statement)
        return self._build_health(result.scalar_one())

    async def append_audit_event(
        self,
        session: AsyncSession,
        *,
        create: SystemSettingAuditEventCreate,
    ) -> StoredSystemSettingAuditEvent:
        """Append one metadata-only audit event."""
        rdb = RDBSystemSettingAuditEvent(
            id=uuid7().hex,
            section=create.section,
            event_type=create.event_type,
            source=create.source,
            changed_fields=create.changed_fields,
            secret_actions=create.secret_actions,
            impact_confirmed=create.impact_confirmed,
            created_at=create.created_at,
            previous_version=create.previous_version,
            new_version=create.new_version,
            actor_user_id=create.actor_user_id,
            validation_status=create.validation_status,
            candidate_id=create.candidate_id,
            confirmation_action=create.confirmation_action,
            event_metadata=create.metadata,
        )
        session.add(rdb)
        await session.flush()
        return self._build_audit(rdb)

    async def list_audit_events(
        self,
        session: AsyncSession,
        *,
        section: SystemSettingSection | None,
        offset: int,
        limit: int,
    ) -> SystemSettingAuditEventList:
        """List metadata-only audit events newest first."""
        filters = []
        if section is not None:
            filters.append(RDBSystemSettingAuditEvent.section == section)
        total_result = await session.execute(
            sa.select(sa.func.count())
            .select_from(RDBSystemSettingAuditEvent)
            .where(*filters)
        )
        result = await session.execute(
            sa.select(RDBSystemSettingAuditEvent)
            .where(*filters)
            .order_by(RDBSystemSettingAuditEvent.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return SystemSettingAuditEventList(
            items=[self._build_audit(rdb) for rdb in result.scalars().all()],
            total=total_result.scalar_one(),
        )

    @staticmethod
    def _build_current(rdb: RDBSystemSetting) -> StoredSystemSetting:
        return StoredSystemSetting(
            section=rdb.section,
            schema_version=rdb.schema_version,
            version=rdb.version,
            config=rdb.config,
            encrypted_secrets=rdb.encrypted_secrets,
            secret_metadata=rdb.secret_metadata,
            validation_status=rdb.validation_status,
            validated_generation=rdb.validated_generation,
            validation_metadata=rdb.validation_metadata,
            validated_at=rdb.validated_at,
            updated_by_user_id=rdb.updated_by_user_id,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )

    @staticmethod
    def _build_candidate(
        rdb: RDBSystemSettingCandidate,
    ) -> StoredSystemSettingCandidate:
        return StoredSystemSettingCandidate(
            id=rdb.id,
            section=rdb.section,
            schema_version=rdb.schema_version,
            base_version=rdb.base_version,
            config=rdb.config,
            encrypted_secrets=rdb.encrypted_secrets,
            secret_metadata=rdb.secret_metadata,
            validation_status=rdb.validation_status,
            validated_generation=rdb.validated_generation,
            validation_code=rdb.validation_code,
            validation_message=rdb.validation_message,
            action_hint=rdb.action_hint,
            validation_metadata=rdb.validation_metadata,
            impact=rdb.impact,
            created_by_user_id=rdb.created_by_user_id,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
            expires_at=rdb.expires_at,
        )

    @staticmethod
    def _build_health(rdb: RDBSystemSettingHealth) -> StoredSystemSettingHealth:
        return StoredSystemSettingHealth(
            section=rdb.section,
            effective_generation=rdb.effective_generation,
            status=rdb.status,
            code=rdb.code,
            message=rdb.message,
            action_hint=rdb.action_hint,
            metadata=rdb.result_metadata,
            checked_by_user_id=rdb.checked_by_user_id,
            checked_at=rdb.checked_at,
        )

    @staticmethod
    def _build_audit(rdb: RDBSystemSettingAuditEvent) -> StoredSystemSettingAuditEvent:
        return StoredSystemSettingAuditEvent(
            id=rdb.id,
            section=rdb.section,
            event_type=rdb.event_type,
            source=rdb.source,
            previous_version=rdb.previous_version,
            new_version=rdb.new_version,
            actor_user_id=rdb.actor_user_id,
            changed_fields=rdb.changed_fields,
            secret_actions=rdb.secret_actions,
            validation_status=rdb.validation_status,
            candidate_id=rdb.candidate_id,
            impact_confirmed=rdb.impact_confirmed,
            confirmation_action=rdb.confirmation_action,
            metadata=rdb.event_metadata,
            created_at=rdb.created_at,
        )


class SystemDataMigrationRepository:
    """Persist application data-migration completion markers."""

    async def acquire_lock(self, session: AsyncSession, *, name: str) -> None:
        """Serialize one application migration across processes."""
        await session.execute(
            sa.select(
                sa.func.pg_advisory_xact_lock(
                    _advisory_lock_id("system-data-migration", name)
                )
            )
        )

    async def get(
        self,
        session: AsyncSession,
        *,
        name: str,
    ) -> StoredSystemDataMigration | None:
        """Fetch a migration marker."""
        rdb = await session.get(RDBSystemDataMigration, name)
        if rdb is None:
            return None
        return StoredSystemDataMigration(
            name=rdb.name,
            outcome=rdb.outcome,
            metadata=rdb.migration_metadata,
            completed_at=rdb.completed_at,
        )

    async def create(
        self,
        session: AsyncSession,
        *,
        name: str,
        outcome: SystemDataMigrationOutcome,
        metadata: dict[str, object],
        completed_at: datetime.datetime,
    ) -> StoredSystemDataMigration:
        """Create a completed migration marker in the caller's transaction."""
        rdb = RDBSystemDataMigration(
            name=name,
            outcome=outcome,
            migration_metadata=metadata,
            completed_at=completed_at,
        )
        session.add(rdb)
        await session.flush()
        return StoredSystemDataMigration(
            name=rdb.name,
            outcome=rdb.outcome,
            metadata=rdb.migration_metadata,
            completed_at=rdb.completed_at,
        )
