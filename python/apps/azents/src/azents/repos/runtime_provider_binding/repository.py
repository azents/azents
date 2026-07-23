"""Repository for durable Runtime Provider authentication bindings."""

import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeProviderAuthMethod,
    RuntimeProviderBindingState,
    RuntimeProviderConnectionStatus,
)
from azents.rdb.models.runtime_provider_binding import (
    RDBRuntimeProviderAuthBinding,
    RDBRuntimeProviderAuthBindingAuditEvent,
)
from azents.rdb.models.runtime_provider_control import RDBRuntimeProviderConnection

from .data import (
    RuntimeProviderAuthBinding,
    RuntimeProviderAuthBindingAuditEvent,
    RuntimeProviderAuthBindingAuditEventCreate,
    RuntimeProviderAuthBindingCreate,
    RuntimeProviderAuthBindingRevoke,
)


class RuntimeProviderAuthBindingRepository:
    """Persist and resolve Provider authentication bindings."""

    async def create(
        self,
        session: AsyncSession,
        *,
        create: RuntimeProviderAuthBindingCreate,
    ) -> RuntimeProviderAuthBinding:
        """Create one binding."""
        binding = RDBRuntimeProviderAuthBinding(
            provider_id=create.provider_id,
            auth_method=create.auth_method,
            subject=create.subject,
            state=RuntimeProviderBindingState.ACTIVE,
            owner=create.owner,
            bootstrap_declaration_id=create.bootstrap_declaration_id,
            config=create.config,
        )
        session.add(binding)
        await session.flush()
        return self._build(binding)

    async def get_by_id(
        self,
        session: AsyncSession,
        *,
        binding_id: str,
        for_update: bool,
    ) -> RuntimeProviderAuthBinding | None:
        """Get one binding by durable identifier."""
        query = sa.select(RDBRuntimeProviderAuthBinding).where(
            RDBRuntimeProviderAuthBinding.id == binding_id
        )
        if for_update:
            query = query.with_for_update()
        result = await session.execute(query)
        binding = result.scalar_one_or_none()
        return self._build(binding) if binding is not None else None

    async def get_active_by_subject(
        self,
        session: AsyncSession,
        *,
        auth_method: RuntimeProviderAuthMethod,
        subject: str,
    ) -> RuntimeProviderAuthBinding | None:
        """Resolve one active binding by method and normalized subject."""
        result = await session.execute(
            sa.select(RDBRuntimeProviderAuthBinding).where(
                RDBRuntimeProviderAuthBinding.auth_method == auth_method,
                RDBRuntimeProviderAuthBinding.subject == subject,
                RDBRuntimeProviderAuthBinding.state
                == RuntimeProviderBindingState.ACTIVE,
            )
        )
        binding = result.scalar_one_or_none()
        return self._build(binding) if binding is not None else None

    async def get_by_bootstrap_declaration_id(
        self,
        session: AsyncSession,
        *,
        bootstrap_declaration_id: str,
        for_update: bool,
    ) -> RuntimeProviderAuthBinding | None:
        """Get the binding owned by one bootstrap declaration."""
        query = (
            sa.select(RDBRuntimeProviderAuthBinding)
            .where(
                RDBRuntimeProviderAuthBinding.bootstrap_declaration_id
                == bootstrap_declaration_id
            )
            .order_by(
                sa.case(
                    (
                        RDBRuntimeProviderAuthBinding.state
                        == RuntimeProviderBindingState.ACTIVE,
                        0,
                    ),
                    else_=1,
                ),
                RDBRuntimeProviderAuthBinding.created_at.desc(),
                RDBRuntimeProviderAuthBinding.id.desc(),
            )
            .limit(1)
        )
        if for_update:
            query = query.with_for_update()
        result = await session.execute(query)
        binding = result.scalar_one_or_none()
        return self._build(binding) if binding is not None else None

    async def list_for_provider(
        self,
        session: AsyncSession,
        *,
        provider_id: str,
    ) -> tuple[RuntimeProviderAuthBinding, ...]:
        """List all authentication bindings for one Provider."""
        result = await session.execute(
            sa.select(RDBRuntimeProviderAuthBinding)
            .where(RDBRuntimeProviderAuthBinding.provider_id == provider_id)
            .order_by(
                RDBRuntimeProviderAuthBinding.created_at,
                RDBRuntimeProviderAuthBinding.id,
            )
        )
        return tuple(self._build(binding) for binding in result.scalars())

    async def mark_authenticated(
        self,
        session: AsyncSession,
        *,
        binding_id: str,
        authenticated_at: datetime.datetime,
    ) -> bool:
        """Record successful authentication while requiring an active binding."""
        result = await session.execute(
            sa.update(RDBRuntimeProviderAuthBinding)
            .where(
                RDBRuntimeProviderAuthBinding.id == binding_id,
                RDBRuntimeProviderAuthBinding.state
                == RuntimeProviderBindingState.ACTIVE,
            )
            .values(last_authenticated_at=authenticated_at)
            .returning(RDBRuntimeProviderAuthBinding.id)
        )
        return result.scalar_one_or_none() is not None

    async def mark_connected(
        self,
        session: AsyncSession,
        *,
        binding_id: str,
        connected_at: datetime.datetime,
    ) -> bool:
        """Record a connection health timestamp for an active binding."""
        result = await session.execute(
            sa.update(RDBRuntimeProviderAuthBinding)
            .where(
                RDBRuntimeProviderAuthBinding.id == binding_id,
                RDBRuntimeProviderAuthBinding.state
                == RuntimeProviderBindingState.ACTIVE,
            )
            .values(last_connected_at=connected_at)
            .returning(RDBRuntimeProviderAuthBinding.id)
        )
        return result.scalar_one_or_none() is not None

    async def revoke(
        self,
        session: AsyncSession,
        *,
        revoke: RuntimeProviderAuthBindingRevoke,
    ) -> RuntimeProviderAuthBinding | None:
        """Revoke one active binding using optimistic concurrency."""
        result = await session.execute(
            sa.update(RDBRuntimeProviderAuthBinding)
            .where(
                RDBRuntimeProviderAuthBinding.id == revoke.binding_id,
                RDBRuntimeProviderAuthBinding.state
                == RuntimeProviderBindingState.ACTIVE,
                RDBRuntimeProviderAuthBinding.admin_version
                == revoke.expected_admin_version,
            )
            .values(
                state=RuntimeProviderBindingState.REVOKED,
                revoked_at=revoke.revoked_at,
                revoked_by_user_id=revoke.revoked_by_user_id,
                revocation_reason=revoke.reason,
                admin_version=RDBRuntimeProviderAuthBinding.admin_version + 1,
            )
            .returning(RDBRuntimeProviderAuthBinding)
        )
        binding = result.scalar_one_or_none()
        if binding is not None:
            await session.execute(
                sa.update(RDBRuntimeProviderConnection)
                .where(
                    RDBRuntimeProviderConnection.binding_id == binding.id,
                    RDBRuntimeProviderConnection.status
                    == RuntimeProviderConnectionStatus.CONNECTED,
                )
                .values(
                    status=RuntimeProviderConnectionStatus.DISCONNECTED,
                    disconnected_at=revoke.revoked_at,
                )
            )
        return self._build(binding) if binding is not None else None

    async def append_audit_event(
        self,
        session: AsyncSession,
        *,
        create: RuntimeProviderAuthBindingAuditEventCreate,
    ) -> RuntimeProviderAuthBindingAuditEvent:
        """Append one metadata-only binding audit event."""
        event = RDBRuntimeProviderAuthBindingAuditEvent(
            binding_id=create.binding_id,
            event_type=create.event_type,
            actor_user_id=create.actor_user_id,
            previous_admin_version=create.previous_admin_version,
            new_admin_version=create.new_admin_version,
            metadata_=create.metadata,
        )
        event.created_at = create.created_at
        session.add(event)
        await session.flush()
        return self._build_audit_event(event)

    async def list_audit_events(
        self,
        session: AsyncSession,
        *,
        binding_id: str,
        offset: int,
        limit: int,
    ) -> tuple[RuntimeProviderAuthBindingAuditEvent, ...]:
        """List binding audit events in newest-first order."""
        result = await session.execute(
            sa.select(RDBRuntimeProviderAuthBindingAuditEvent)
            .where(RDBRuntimeProviderAuthBindingAuditEvent.binding_id == binding_id)
            .order_by(
                RDBRuntimeProviderAuthBindingAuditEvent.created_at.desc(),
                RDBRuntimeProviderAuthBindingAuditEvent.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
        return tuple(self._build_audit_event(event) for event in result.scalars())

    @staticmethod
    def _build(
        binding: RDBRuntimeProviderAuthBinding,
    ) -> RuntimeProviderAuthBinding:
        """Build a safe binding projection."""
        return RuntimeProviderAuthBinding(
            id=binding.id,
            provider_id=binding.provider_id,
            auth_method=binding.auth_method,
            subject=binding.subject,
            state=binding.state,
            owner=binding.owner,
            bootstrap_declaration_id=binding.bootstrap_declaration_id,
            config=binding.config,
            admin_version=binding.admin_version,
            last_authenticated_at=binding.last_authenticated_at,
            last_connected_at=binding.last_connected_at,
            revoked_at=binding.revoked_at,
            revoked_by_user_id=binding.revoked_by_user_id,
            revocation_reason=binding.revocation_reason,
            created_at=binding.created_at,
            updated_at=binding.updated_at,
        )

    @staticmethod
    def _build_audit_event(
        event: RDBRuntimeProviderAuthBindingAuditEvent,
    ) -> RuntimeProviderAuthBindingAuditEvent:
        """Build a safe audit projection."""
        return RuntimeProviderAuthBindingAuditEvent(
            id=event.id,
            binding_id=event.binding_id,
            event_type=event.event_type,
            actor_user_id=event.actor_user_id,
            previous_admin_version=event.previous_admin_version,
            new_admin_version=event.new_admin_version,
            metadata=event.metadata_,
            created_at=event.created_at,
        )
