"""System Settings repositories."""

import datetime
import hashlib

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import insert

from azents.core.system_setting import (
    SystemDataMigrationOutcome,
    SystemSettingSection,
    SystemSettingValidationStatus,
    SystemSettingVersionConflict,
)
from azents.core.system_setting_data import (
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
from azents.rdb.models.system_setting import (
    RDBSystemDataMigration,
    RDBSystemSetting,
    RDBSystemSettingAuditEvent,
    RDBSystemSettingCandidate,
    RDBSystemSettingHealth,
)
from azents.rdb.session_capabilities import ReadSession, WriteSession


def _advisory_lock_id(namespace: str, name: str) -> int:
    """Derive a stable signed PostgreSQL advisory lock ID."""
    digest = hashlib.sha256(f"{namespace}:{name}".encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


class SystemSettingRepository:
    """Persist current, candidate, health, and audit Section state."""

    async def acquire_section_lock(
        self,
        session: WriteSession,
        *,
        section: SystemSettingSection,
    ) -> None:
        """Serialize mutations for one Section."""
        await session.write_session.execute(
            sa.select(
                sa.func.pg_advisory_xact_lock(
                    _advisory_lock_id("system-setting-section", section.value)
                )
            )
        )

    async def get_current(
        self,
        session: ReadSession,
        *,
        section: SystemSettingSection,
    ) -> StoredSystemSetting | None:
        """Fetch current Admin-managed Section state."""
        rdb = await session.read_session.get(RDBSystemSetting, section)
        return self._build_current(rdb) if rdb is not None else None

    async def write_current(
        self,
        session: WriteSession,
        *,
        write: SystemSettingCurrentWrite,
    ) -> StoredSystemSetting:
        """Conditionally publish current Section state at its existing version."""
        if write.section in {
            SystemSettingSection.SLACK_IDENTITY_OAUTH,
            SystemSettingSection.DISCORD_IDENTITY_OAUTH,
        }:
            # These writers must exclude exact OAuth claim/link finalization
            # through commit, including environment-backed absent current rows.
            await self.acquire_section_lock(session, section=write.section)
        stored = await self._write_current_if_unchanged(session, write=write)
        if stored is None:
            current = await self.get_current(session, section=write.section)
            raise SystemSettingVersionConflict(
                section=write.section,
                expected_version=write.version - 1,
                current_version=current.version if current is not None else 0,
            )
        return stored

    async def acquire_platform_runtime_initialization_claim(
        self, session: WriteSession
    ) -> None:
        """Order optional default initialization against new candidate intent."""
        await session.write_session.execute(
            sa.select(
                sa.func.pg_advisory_xact_lock(
                    _advisory_lock_id(
                        "platform-runtime-initialization",
                        SystemSettingSection.PLATFORM_RUNTIME.value,
                    )
                )
            )
        )

    async def initialize_current_if_unchanged(
        self,
        session: WriteSession,
        *,
        write: SystemSettingCurrentWrite,
    ) -> StoredSystemSetting | None:
        """Publish an optional Platform default only without pending intent."""
        if write.section is not SystemSettingSection.PLATFORM_RUNTIME:
            raise ValueError("Optional initialization requires Platform Runtime.")
        await self.acquire_platform_runtime_initialization_claim(session)
        candidate = await self.get_candidate(session, section=write.section)
        if candidate is not None:
            return None
        return await self._write_current_if_unchanged(session, write=write)

    async def _write_current_if_unchanged(
        self,
        session: WriteSession,
        *,
        write: SystemSettingCurrentWrite,
    ) -> StoredSystemSetting | None:
        """Return the published state or an exact expected-version CAS loss."""
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
                where=RDBSystemSetting.version == write.version - 1,
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
        result = await session.write_session.execute(statement)
        row = result.scalar_one_or_none()
        return self._build_current(row) if row is not None else None

    async def get_candidate(
        self,
        session: ReadSession,
        *,
        section: SystemSettingSection,
    ) -> StoredSystemSettingCandidate | None:
        """Fetch the single candidate for a Section."""
        result = await session.read_session.execute(
            sa.select(RDBSystemSettingCandidate).where(
                RDBSystemSettingCandidate.section == section
            )
        )
        rdb = result.scalar_one_or_none()
        return self._build_candidate(rdb) if rdb is not None else None

    async def replace_candidate(
        self,
        session: WriteSession,
        *,
        create: SystemSettingCandidateCreate,
    ) -> StoredSystemSettingCandidate:
        """Replace the candidate atomically at its unique Section boundary."""
        if create.section is SystemSettingSection.PLATFORM_RUNTIME:
            await self.acquire_platform_runtime_initialization_claim(session)
            current = await self.get_current(session, section=create.section)
            current_version = current.version if current is not None else 0
            if current_version != create.base_version:
                raise SystemSettingVersionConflict(
                    section=create.section,
                    expected_version=create.base_version,
                    current_version=current_version,
                )
        statement = insert(RDBSystemSettingCandidate).values(
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
        statement = statement.on_conflict_do_update(
            index_elements=[RDBSystemSettingCandidate.section],
            set_={
                "id": statement.excluded.id,
                "schema_version": statement.excluded.schema_version,
                "base_version": statement.excluded.base_version,
                "config": statement.excluded.config,
                "validation_status": statement.excluded.validation_status,
                "created_at": statement.excluded.created_at,
                "updated_at": statement.excluded.updated_at,
                "expires_at": statement.excluded.expires_at,
                "encrypted_secrets": statement.excluded.encrypted_secrets,
                "secret_metadata": statement.excluded.secret_metadata,
                "validated_generation": statement.excluded.validated_generation,
                "validation_code": statement.excluded.validation_code,
                "validation_message": statement.excluded.validation_message,
                "action_hint": statement.excluded.action_hint,
                "validation_metadata": statement.excluded.validation_metadata,
                "impact": statement.excluded.impact,
                "created_by_user_id": statement.excluded.created_by_user_id,
            },
        ).returning(RDBSystemSettingCandidate)
        row = (await session.write_session.execute(statement)).scalar_one()
        return self._build_candidate(row)

    async def update_candidate_validation(
        self,
        session: WriteSession,
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
        result = await session.write_session.execute(
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
        session: WriteSession,
        *,
        section: SystemSettingSection,
        candidate_id: str | None = None,
    ) -> bool:
        """Delete the current candidate and its ciphertext."""
        filters = [RDBSystemSettingCandidate.section == section]
        if candidate_id is not None:
            filters.append(RDBSystemSettingCandidate.id == candidate_id)
        result = await session.write_session.execute(
            sa.delete(RDBSystemSettingCandidate)
            .where(*filters)
            .returning(RDBSystemSettingCandidate.id)
        )
        return result.scalar_one_or_none() is not None

    async def get_health(
        self,
        session: ReadSession,
        *,
        section: SystemSettingSection,
    ) -> StoredSystemSettingHealth | None:
        """Fetch the latest explicit health result."""
        rdb = await session.read_session.get(RDBSystemSettingHealth, section)
        return self._build_health(rdb) if rdb is not None else None

    async def write_health(
        self,
        session: WriteSession,
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
        result = await session.write_session.execute(statement)
        return self._build_health(result.scalar_one())

    async def append_audit_event(
        self,
        session: WriteSession,
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
        session.write_session.add(rdb)
        await session.write_session.flush()
        return self._build_audit(rdb)

    async def list_audit_events(
        self,
        session: ReadSession,
        *,
        section: SystemSettingSection | None,
        offset: int,
        limit: int,
    ) -> SystemSettingAuditEventList:
        """List metadata-only audit events newest first."""
        filters = []
        if section is not None:
            filters.append(RDBSystemSettingAuditEvent.section == section)
        total_result = await session.read_session.execute(
            sa.select(sa.func.count())
            .select_from(RDBSystemSettingAuditEvent)
            .where(*filters)
        )
        result = await session.read_session.execute(
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

    async def acquire_lock(self, session: WriteSession, *, name: str) -> None:
        """Serialize one application migration across processes."""
        await session.write_session.execute(
            sa.select(
                sa.func.pg_advisory_xact_lock(
                    _advisory_lock_id("system-data-migration", name)
                )
            )
        )

    async def get(
        self,
        session: ReadSession,
        *,
        name: str,
    ) -> StoredSystemDataMigration | None:
        """Fetch a migration marker."""
        rdb = await session.read_session.get(RDBSystemDataMigration, name)
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
        session: WriteSession,
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
        session.write_session.add(rdb)
        await session.write_session.flush()
        return StoredSystemDataMigration(
            name=rdb.name,
            outcome=rdb.outcome,
            metadata=rdb.migration_metadata,
            completed_at=rdb.completed_at,
        )
