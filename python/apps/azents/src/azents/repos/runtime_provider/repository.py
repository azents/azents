"""Runtime Provider aggregate persistence."""

import datetime
import hashlib

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeProviderAvailabilityMode,
    RuntimeProviderBootstrapDeclarationState,
    RuntimeProviderLifecycleState,
)
from azents.rdb.models.runtime_provider import RDBRuntimeProvider
from azents.rdb.models.runtime_provider_bootstrap import (
    RDBRuntimeProviderAuditEvent,
    RDBRuntimeProviderBootstrapDeclaration,
    RDBRuntimeProviderBootstrapSource,
    RDBRuntimeProviderWorkspaceAvailability,
)

from .data import (
    RuntimeProvider,
    RuntimeProviderAuditEventCreate,
    RuntimeProviderBootstrapDeclaration,
    RuntimeProviderBootstrapDeclarationCreate,
    RuntimeProviderBootstrapSource,
    RuntimeProviderBootstrapSourceCreate,
    RuntimeProviderCreate,
)


def _advisory_lock_id(namespace: str, name: str) -> int:
    """Derive a stable signed PostgreSQL advisory lock ID."""
    digest = hashlib.sha256(f"{namespace}:{name}".encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


class RuntimeProviderRepository:
    """Persist Runtime Provider aggregates and trusted bootstrap declarations."""

    async def acquire_bootstrap_source_lock(
        self,
        session: AsyncSession,
        *,
        source_key: str,
    ) -> None:
        """Serialize reconciliation for one trusted bootstrap source."""
        await session.execute(
            sa.select(
                sa.func.pg_advisory_xact_lock(
                    _advisory_lock_id("runtime-provider-bootstrap-source", source_key)
                )
            )
        )

    async def acquire_provider_identity_lock(
        self,
        session: AsyncSession,
        *,
        provider_logical_id: str,
    ) -> None:
        """Serialize aggregate identity claims across Admins and sources."""
        await session.execute(
            sa.select(
                sa.func.pg_advisory_xact_lock(
                    _advisory_lock_id(
                        "runtime-provider-logical-id",
                        provider_logical_id,
                    )
                )
            )
        )

    async def create(
        self,
        session: AsyncSession,
        create: RuntimeProviderCreate,
    ) -> RuntimeProvider:
        """Create a Runtime Provider aggregate."""
        rdb = RDBRuntimeProvider(
            provider_id=create.provider_id,
            scope=create.scope,
            workspace_id=create.workspace_id,
            kind=create.kind,
            display_name=create.display_name,
            enabled=create.enabled,
            capabilities=create.capabilities,
            config_schema=create.config_schema,
            metadata_=create.metadata,
        )
        rdb.registration_method = create.registration_method
        rdb.lifecycle_state = create.lifecycle_state
        rdb.availability_mode = create.availability_mode
        rdb.admin_version = 0
        session.add(rdb)
        await session.flush()
        return self._build_provider(rdb)

    async def get_by_provider_id(
        self,
        session: AsyncSession,
        *,
        provider_logical_id: str,
        for_update: bool,
    ) -> RuntimeProvider | None:
        """Fetch one aggregate by stable logical ID."""
        statement = sa.select(RDBRuntimeProvider).where(
            RDBRuntimeProvider.provider_id == provider_logical_id
        )
        if for_update:
            statement = statement.with_for_update()
        result = await session.execute(statement)
        rdb = result.scalar_one_or_none()
        return self._build_provider(rdb) if rdb is not None else None

    async def get_by_id(
        self,
        session: AsyncSession,
        *,
        provider_id: str,
        for_update: bool,
    ) -> RuntimeProvider | None:
        """Fetch one aggregate by internal ID."""
        statement = sa.select(RDBRuntimeProvider).where(
            RDBRuntimeProvider.id == provider_id
        )
        if for_update:
            statement = statement.with_for_update()
        result = await session.execute(statement)
        rdb = result.scalar_one_or_none()
        return self._build_provider(rdb) if rdb is not None else None

    async def list_available(
        self,
        session: AsyncSession,
        *,
        workspace_id: str | None,
        include_disabled: bool,
    ) -> list[RuntimeProvider]:
        """Fetch legacy-scope available Provider list."""
        statement = sa.select(RDBRuntimeProvider)
        if workspace_id is not None:
            statement = statement.where(
                sa.or_(
                    RDBRuntimeProvider.workspace_id == workspace_id,
                    RDBRuntimeProvider.workspace_id.is_(None),
                )
            )
        if not include_disabled:
            statement = statement.where(RDBRuntimeProvider.enabled.is_(True))
        statement = statement.order_by(RDBRuntimeProvider.provider_id)
        result = await session.execute(statement)
        return [self._build_provider(rdb) for rdb in result.scalars()]

    async def update_administrative_policy(
        self,
        session: AsyncSession,
        *,
        provider_id: str,
        enabled: bool,
        lifecycle_state: RuntimeProviderLifecycleState,
        availability_mode: RuntimeProviderAvailabilityMode,
    ) -> RuntimeProvider | None:
        """Replace mutable Provider policy and advance its Admin version."""
        result = await session.execute(
            sa.select(RDBRuntimeProvider)
            .where(RDBRuntimeProvider.id == provider_id)
            .with_for_update()
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        rdb.enabled = enabled
        rdb.lifecycle_state = lifecycle_state
        rdb.availability_mode = availability_mode
        rdb.admin_version += 1
        await session.flush()
        return self._build_provider(rdb)

    async def replace_workspace_availability(
        self,
        session: AsyncSession,
        *,
        provider_id: str,
        workspace_ids: set[str],
    ) -> None:
        """Replace explicit selected-Workspace availability membership."""
        await session.execute(
            sa.delete(RDBRuntimeProviderWorkspaceAvailability).where(
                RDBRuntimeProviderWorkspaceAvailability.provider_id == provider_id
            )
        )
        session.add_all(
            [
                RDBRuntimeProviderWorkspaceAvailability(
                    provider_id=provider_id,
                    workspace_id=workspace_id,
                )
                for workspace_id in sorted(workspace_ids)
            ]
        )
        await session.flush()

    async def get_or_create_bootstrap_source(
        self,
        session: AsyncSession,
        *,
        create: RuntimeProviderBootstrapSourceCreate,
    ) -> RuntimeProviderBootstrapSource:
        """Fetch or establish one source after its source lock is held."""
        result = await session.execute(
            sa.select(RDBRuntimeProviderBootstrapSource)
            .where(RDBRuntimeProviderBootstrapSource.source_key == create.source_key)
            .with_for_update()
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            rdb = RDBRuntimeProviderBootstrapSource(
                source_key=create.source_key,
                adapter_kind=create.adapter_kind,
            )
            session.add(rdb)
            await session.flush()
        elif rdb.adapter_kind != create.adapter_kind:
            raise ValueError("Bootstrap source adapter kind is immutable.")
        return self._build_source(rdb)

    async def record_source_reconciled(
        self,
        session: AsyncSession,
        *,
        source_id: str,
        source_revision: str,
        source_digest: str,
        reconciled_at: datetime.datetime,
    ) -> None:
        """Record successful authoritative source reconciliation."""
        await session.execute(
            sa.update(RDBRuntimeProviderBootstrapSource)
            .where(RDBRuntimeProviderBootstrapSource.id == source_id)
            .values(
                last_revision=source_revision,
                last_digest=source_digest,
                last_reconciled_at=reconciled_at,
                error_code=None,
                error_message=None,
                updated_at=reconciled_at,
            )
        )
        await session.flush()

    async def record_source_error(
        self,
        session: AsyncSession,
        *,
        source_id: str,
        error_code: str,
        error_message: str,
        occurred_at: datetime.datetime,
    ) -> None:
        """Record an adapter failure without changing declaration presence."""
        await session.execute(
            sa.update(RDBRuntimeProviderBootstrapSource)
            .where(RDBRuntimeProviderBootstrapSource.id == source_id)
            .values(
                error_code=error_code,
                error_message=error_message,
                updated_at=occurred_at,
            )
        )
        await session.flush()

    async def get_bootstrap_declaration(
        self,
        session: AsyncSession,
        *,
        source_id: str,
        declaration_key: str,
        for_update: bool,
    ) -> RuntimeProviderBootstrapDeclaration | None:
        """Fetch one declaration by immutable source-local identity."""
        statement = sa.select(RDBRuntimeProviderBootstrapDeclaration).where(
            RDBRuntimeProviderBootstrapDeclaration.source_id == source_id,
            RDBRuntimeProviderBootstrapDeclaration.declaration_key == declaration_key,
        )
        if for_update:
            statement = statement.with_for_update()
        result = await session.execute(statement)
        rdb = result.scalar_one_or_none()
        return self._build_declaration(rdb) if rdb is not None else None

    async def get_bootstrap_declaration_by_provider_id(
        self,
        session: AsyncSession,
        *,
        provider_id: str,
        for_update: bool,
    ) -> RuntimeProviderBootstrapDeclaration | None:
        """Fetch a successfully linked bootstrap declaration for one aggregate."""
        statement = sa.select(RDBRuntimeProviderBootstrapDeclaration).where(
            RDBRuntimeProviderBootstrapDeclaration.provider_id == provider_id
        )
        if for_update:
            statement = statement.with_for_update()
        result = await session.execute(statement)
        rdb = result.scalar_one_or_none()
        return self._build_declaration(rdb) if rdb is not None else None

    async def create_bootstrap_declaration(
        self,
        session: AsyncSession,
        *,
        create: RuntimeProviderBootstrapDeclarationCreate,
    ) -> RuntimeProviderBootstrapDeclaration:
        """Store a source declaration with or without an aggregate link."""
        rdb = RDBRuntimeProviderBootstrapDeclaration(
            source_id=create.source_id,
            provider_logical_id=create.provider_logical_id,
            kind=create.kind,
            provider_id=create.provider_id,
            declaration_key=create.declaration_key,
            source_revision=create.source_revision,
            source_digest=create.source_digest,
            state=create.state,
            creation_seeds=create.creation_seeds,
            conflict_code=create.conflict_code,
            conflict_message=create.conflict_message,
            last_seen_at=create.last_seen_at,
            withdrawn_at=create.withdrawn_at,
        )
        session.add(rdb)
        await session.flush()
        return self._build_declaration(rdb)

    async def update_bootstrap_declaration(
        self,
        session: AsyncSession,
        *,
        declaration_id: str,
        provider_id: str | None,
        source_revision: str,
        source_digest: str,
        state: RuntimeProviderBootstrapDeclarationState,
        creation_seeds: dict[str, object] | None,
        conflict_code: str | None,
        conflict_message: str | None,
        last_seen_at: datetime.datetime | None,
        withdrawn_at: datetime.datetime | None,
        updated_at: datetime.datetime,
    ) -> RuntimeProviderBootstrapDeclaration:
        """Replace mutable reconciliation projection for one declaration."""
        result = await session.execute(
            sa.update(RDBRuntimeProviderBootstrapDeclaration)
            .where(RDBRuntimeProviderBootstrapDeclaration.id == declaration_id)
            .values(
                provider_id=provider_id,
                source_revision=source_revision,
                source_digest=source_digest,
                state=state,
                creation_seeds=creation_seeds,
                conflict_code=conflict_code,
                conflict_message=conflict_message,
                last_seen_at=last_seen_at,
                withdrawn_at=withdrawn_at,
                updated_at=updated_at,
            )
            .returning(RDBRuntimeProviderBootstrapDeclaration)
        )
        rdb = result.scalar_one()
        return self._build_declaration(rdb)

    async def mark_missing_declarations_absent(
        self,
        session: AsyncSession,
        *,
        source_id: str,
        present_declaration_keys: set[str],
        source_revision: str,
        source_digest: str,
        occurred_at: datetime.datetime,
    ) -> list[RuntimeProviderBootstrapDeclaration]:
        """Mark omitted declarations absent from an authoritative source snapshot."""
        filters: list[sa.ColumnElement[bool]] = [
            RDBRuntimeProviderBootstrapDeclaration.source_id == source_id,
            RDBRuntimeProviderBootstrapDeclaration.state
            != RuntimeProviderBootstrapDeclarationState.ABSENT,
        ]
        if present_declaration_keys:
            filters.append(
                RDBRuntimeProviderBootstrapDeclaration.declaration_key.not_in(
                    present_declaration_keys
                )
            )
        result = await session.execute(
            sa.select(RDBRuntimeProviderBootstrapDeclaration)
            .where(*filters)
            .with_for_update()
        )
        declarations = result.scalars().all()
        for declaration in declarations:
            declaration.source_revision = source_revision
            declaration.source_digest = source_digest
            declaration.state = RuntimeProviderBootstrapDeclarationState.ABSENT
            declaration.conflict_code = None
            declaration.conflict_message = None
            declaration.withdrawn_at = occurred_at
            declaration.updated_at = occurred_at
        await session.flush()
        return [self._build_declaration(declaration) for declaration in declarations]

    async def append_audit_event(
        self,
        session: AsyncSession,
        *,
        create: RuntimeProviderAuditEventCreate,
    ) -> None:
        """Append a metadata-only Provider aggregate audit event."""
        rdb = RDBRuntimeProviderAuditEvent(
            provider_id=create.provider_id,
            event_type=create.event_type,
            actor_user_id=create.actor_user_id,
            metadata_=create.metadata,
        )
        rdb.created_at = create.created_at
        session.add(rdb)
        await session.flush()

    @staticmethod
    def _build_provider(rdb: RDBRuntimeProvider) -> RuntimeProvider:
        return RuntimeProvider(
            id=rdb.id,
            provider_id=rdb.provider_id,
            scope=rdb.scope,
            workspace_id=rdb.workspace_id,
            kind=rdb.kind,
            display_name=rdb.display_name,
            registration_method=rdb.registration_method,
            enabled=rdb.enabled,
            lifecycle_state=rdb.lifecycle_state,
            availability_mode=rdb.availability_mode,
            admin_version=rdb.admin_version,
            capabilities=rdb.capabilities,
            config_schema=rdb.config_schema,
            metadata=rdb.metadata_,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )

    @staticmethod
    def _build_source(
        rdb: RDBRuntimeProviderBootstrapSource,
    ) -> RuntimeProviderBootstrapSource:
        return RuntimeProviderBootstrapSource(
            id=rdb.id,
            source_key=rdb.source_key,
            adapter_kind=rdb.adapter_kind,
            last_revision=rdb.last_revision,
            last_digest=rdb.last_digest,
            last_reconciled_at=rdb.last_reconciled_at,
            error_code=rdb.error_code,
            error_message=rdb.error_message,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )

    @staticmethod
    def _build_declaration(
        rdb: RDBRuntimeProviderBootstrapDeclaration,
    ) -> RuntimeProviderBootstrapDeclaration:
        return RuntimeProviderBootstrapDeclaration(
            id=rdb.id,
            source_id=rdb.source_id,
            declaration_key=rdb.declaration_key,
            provider_logical_id=rdb.provider_logical_id,
            kind=rdb.kind,
            provider_id=rdb.provider_id,
            source_revision=rdb.source_revision,
            source_digest=rdb.source_digest,
            state=rdb.state,
            creation_seeds=rdb.creation_seeds,
            conflict_code=rdb.conflict_code,
            conflict_message=rdb.conflict_message,
            last_seen_at=rdb.last_seen_at,
            withdrawn_at=rdb.withdrawn_at,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )
