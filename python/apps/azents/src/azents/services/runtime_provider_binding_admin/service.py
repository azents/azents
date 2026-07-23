"""Admin lifecycle operations for Runtime Provider authentication bindings."""

import dataclasses
import datetime
from typing import Annotated, Any

from azcommon.datetime import tznow
from fastapi import Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeProviderAuthMethod,
    RuntimeProviderBindingAuditEventType,
    RuntimeProviderBindingOwner,
    RuntimeProviderBindingState,
    RuntimeProviderLifecycleState,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.runtime_provider.repository import RuntimeProviderRepository
from azents.repos.runtime_provider_binding.data import (
    RuntimeProviderAuthBinding,
    RuntimeProviderAuthBindingAuditEvent,
    RuntimeProviderAuthBindingAuditEventCreate,
    RuntimeProviderAuthBindingCreate,
    RuntimeProviderAuthBindingRevoke,
)
from azents.repos.runtime_provider_binding.repository import (
    RuntimeProviderAuthBindingRepository,
)
from azents.repos.runtime_provider_control.data import (
    RuntimeProviderEnrollmentGrantCreate,
)
from azents.repos.runtime_provider_control.repository import (
    RuntimeProviderControlRepository,
)
from azents.services.runtime_provider_control.deps import (
    get_runtime_provider_enrollment_service,
)
from azents.services.runtime_provider_control.service import (
    RuntimeProviderEnrollmentService,
)

_TERMINAL_PROVIDER_STATES = frozenset(
    {
        RuntimeProviderLifecycleState.DECOMMISSIONED,
        RuntimeProviderLifecycleState.FORCE_RETIRED,
    }
)
_KUBERNETES_CONFIG_KEYS = (
    "namespace",
    "service_account_name",
    "audience",
)


@dataclasses.dataclass(frozen=True)
class RuntimeProviderBindingAdminProjection:
    """Secret-safe binding projection with current connection health."""

    binding: RuntimeProviderAuthBinding
    provider_id: str
    connected: bool


@dataclasses.dataclass(frozen=True)
class RuntimeProviderBindingRotation:
    """One-time enrollment grant returned after binding rotation."""

    binding: RuntimeProviderBindingAdminProjection
    grant_id: str
    secret: str
    expires_at: datetime.datetime


@dataclasses.dataclass
class RuntimeProviderBindingAdminUnavailable(Exception):
    """Binding Admin operation cannot be completed safely."""

    code: str
    current_binding: RuntimeProviderBindingAdminProjection | None = None

    def __post_init__(self) -> None:
        Exception.__init__(self, self.code)


@dataclasses.dataclass
class RuntimeProviderBindingAdminService:
    """Manage Provider authentication bindings without exposing stored secrets."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    provider_repository: Annotated[
        RuntimeProviderRepository, Depends(RuntimeProviderRepository)
    ]
    binding_repository: Annotated[
        RuntimeProviderAuthBindingRepository,
        Depends(RuntimeProviderAuthBindingRepository),
    ]
    control_repository: Annotated[
        RuntimeProviderControlRepository,
        Depends(RuntimeProviderControlRepository),
    ]
    enrollment_service: Annotated[
        RuntimeProviderEnrollmentService,
        Depends(get_runtime_provider_enrollment_service),
    ]

    async def list_bindings(
        self, provider_id: str
    ) -> tuple[RuntimeProviderBindingAdminProjection, ...]:
        """List bindings for one stable logical Provider ID."""
        async with self.session_manager() as session:
            provider = await self.provider_repository.get_by_provider_id(
                session, provider_logical_id=provider_id, for_update=False
            )
            if provider is None:
                raise RuntimeProviderBindingAdminUnavailable("provider_not_found")
            bindings = await self.binding_repository.list_for_provider(
                session, provider_id=provider.id
            )
            return tuple(
                [await self._projection(session, binding) for binding in bindings]
            )

    async def get_binding(
        self, binding_id: str
    ) -> RuntimeProviderBindingAdminProjection:
        """Get one safe binding projection."""
        async with self.session_manager() as session:
            binding = await self.binding_repository.get_by_id(
                session, binding_id=binding_id, for_update=False
            )
            if binding is None:
                raise RuntimeProviderBindingAdminUnavailable("binding_not_found")
            return await self._projection(session, binding)

    async def create_binding(
        self,
        provider_id: str,
        *,
        auth_method: RuntimeProviderAuthMethod,
        subject: str,
        config: dict[str, Any] | None,
        actor_user_id: str,
    ) -> RuntimeProviderBindingAdminProjection:
        """Create one Admin-owned issued-token binding."""
        if auth_method is not RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN:
            raise RuntimeProviderBindingAdminUnavailable("unsupported_binding_method")
        normalized_subject = subject.strip()
        if not normalized_subject or len(normalized_subject) > 255:
            raise RuntimeProviderBindingAdminUnavailable("binding_subject_invalid")
        if config is not None:
            raise RuntimeProviderBindingAdminUnavailable("binding_config_invalid")
        async with self.session_manager() as session:
            provider = await self.provider_repository.get_by_provider_id(
                session, provider_logical_id=provider_id, for_update=True
            )
            if provider is None:
                raise RuntimeProviderBindingAdminUnavailable("provider_not_found")
            if provider.lifecycle_state in _TERMINAL_PROVIDER_STATES:
                raise RuntimeProviderBindingAdminUnavailable("provider_unavailable")
            try:
                binding = await self.binding_repository.create(
                    session,
                    create=RuntimeProviderAuthBindingCreate(
                        provider_id=provider.id,
                        auth_method=auth_method,
                        subject=normalized_subject,
                        owner=RuntimeProviderBindingOwner.ADMIN,
                        bootstrap_declaration_id=None,
                        config=config,
                    ),
                )
            except IntegrityError:
                raise RuntimeProviderBindingAdminUnavailable(
                    "binding_conflict"
                ) from None
            await self.binding_repository.append_audit_event(
                session,
                create=RuntimeProviderAuthBindingAuditEventCreate(
                    binding_id=binding.id,
                    event_type=RuntimeProviderBindingAuditEventType.CREATED,
                    actor_user_id=actor_user_id,
                    previous_admin_version=None,
                    new_admin_version=binding.admin_version,
                    metadata=None,
                    created_at=tznow(),
                ),
            )
            return await self._projection(session, binding)

    async def rotate_binding(
        self,
        binding_id: str,
        *,
        expected_admin_version: int,
        expires_at: datetime.datetime,
        actor_user_id: str,
    ) -> RuntimeProviderBindingRotation:
        """Advance binding version and issue one binding-scoped enrollment grant."""
        now = tznow()
        if (
            expires_at.tzinfo is None
            or expires_at.utcoffset() is None
            or expires_at <= now
        ):
            raise RuntimeProviderBindingAdminUnavailable("grant_expiry_invalid")
        async with self.session_manager() as session:
            current = await self._mutable_binding(session, binding_id)
            if current.admin_version != expected_admin_version:
                raise RuntimeProviderBindingAdminUnavailable(
                    "stale_binding_version",
                    await self._projection(session, current),
                )
            rotated = await self.binding_repository.rotate(
                session,
                binding_id=binding_id,
                expected_admin_version=expected_admin_version,
            )
            if rotated is None:
                raise RuntimeProviderBindingAdminUnavailable("stale_binding_version")
            secret = self.enrollment_service.verifier.issue_secret()
            grant = await self.control_repository.create_enrollment_grant(
                session,
                create=RuntimeProviderEnrollmentGrantCreate(
                    provider_id=rotated.provider_id,
                    binding_id=rotated.id,
                    verifier=self.enrollment_service.verifier.verifier_for(secret),
                    expires_at=expires_at,
                    issued_by_user_id=actor_user_id,
                    issued_by_source_id=None,
                ),
            )
            await self.binding_repository.append_audit_event(
                session,
                create=RuntimeProviderAuthBindingAuditEventCreate(
                    binding_id=rotated.id,
                    event_type=RuntimeProviderBindingAuditEventType.ROTATED,
                    actor_user_id=actor_user_id,
                    previous_admin_version=expected_admin_version,
                    new_admin_version=rotated.admin_version,
                    metadata={"grant_id": grant.id},
                    created_at=now,
                ),
            )
            return RuntimeProviderBindingRotation(
                binding=await self._projection(session, rotated),
                grant_id=grant.id,
                secret=secret,
                expires_at=grant.expires_at,
            )

    async def revoke_binding(
        self,
        binding_id: str,
        *,
        expected_admin_version: int,
        reason: str | None,
        actor_user_id: str,
    ) -> RuntimeProviderBindingAdminProjection:
        """Revoke an Admin binding and all retained authority."""
        now = tznow()
        async with self.session_manager() as session:
            current = await self._mutable_binding(session, binding_id)
            revoked = await self.binding_repository.revoke(
                session,
                revoke=RuntimeProviderAuthBindingRevoke(
                    binding_id=binding_id,
                    expected_admin_version=expected_admin_version,
                    revoked_at=now,
                    revoked_by_user_id=actor_user_id,
                    reason=reason,
                ),
            )
            if revoked is None:
                raise RuntimeProviderBindingAdminUnavailable(
                    "stale_binding_version",
                    await self._projection(session, current),
                )
            await self.control_repository.revoke_binding_authority(
                session,
                binding_id=binding_id,
                revoked_at=now,
                revoked_by_user_id=actor_user_id,
            )
            await self.binding_repository.append_audit_event(
                session,
                create=RuntimeProviderAuthBindingAuditEventCreate(
                    binding_id=binding_id,
                    event_type=RuntimeProviderBindingAuditEventType.REVOKED,
                    actor_user_id=actor_user_id,
                    previous_admin_version=expected_admin_version,
                    new_admin_version=revoked.admin_version,
                    metadata={"reason": reason},
                    created_at=now,
                ),
            )
            return await self._projection(session, revoked)

    async def list_audit_events(
        self, binding_id: str, *, offset: int, limit: int
    ) -> tuple[RuntimeProviderAuthBindingAuditEvent, ...]:
        """List metadata-only binding audit history."""
        async with self.session_manager() as session:
            binding = await self.binding_repository.get_by_id(
                session, binding_id=binding_id, for_update=False
            )
            if binding is None:
                raise RuntimeProviderBindingAdminUnavailable("binding_not_found")
            return await self.binding_repository.list_audit_events(
                session, binding_id=binding_id, offset=offset, limit=limit
            )

    async def _mutable_binding(
        self, session: AsyncSession, binding_id: str
    ) -> RuntimeProviderAuthBinding:
        binding = await self.binding_repository.get_by_id(
            session, binding_id=binding_id, for_update=True
        )
        if binding is None:
            raise RuntimeProviderBindingAdminUnavailable("binding_not_found")
        if binding.owner is not RuntimeProviderBindingOwner.ADMIN:
            raise RuntimeProviderBindingAdminUnavailable("binding_read_only")
        if binding.auth_method is not RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN:
            raise RuntimeProviderBindingAdminUnavailable("unsupported_binding_method")
        if binding.state is not RuntimeProviderBindingState.ACTIVE:
            raise RuntimeProviderBindingAdminUnavailable("binding_not_active")
        return binding

    async def _projection(
        self,
        session: AsyncSession,
        binding: RuntimeProviderAuthBinding,
    ) -> RuntimeProviderBindingAdminProjection:
        connected = await self.control_repository.has_connected_connection_for_binding(
            session, binding_id=binding.id, now=tznow()
        )
        return RuntimeProviderBindingAdminProjection(
            binding=dataclasses.replace(
                binding,
                config=self._safe_config(binding),
            ),
            provider_id=await self._provider_logical_id(session, binding.provider_id),
            connected=connected,
        )

    @staticmethod
    def _safe_config(
        binding: RuntimeProviderAuthBinding,
    ) -> dict[str, Any] | None:
        """Return only method-defined non-secret configuration fields."""
        if (
            binding.auth_method
            is not RuntimeProviderAuthMethod.KUBERNETES_SERVICE_ACCOUNT
            or binding.config is None
        ):
            return None
        safe_config = {
            key: value
            for key in _KUBERNETES_CONFIG_KEYS
            if isinstance((value := binding.config.get(key)), str)
        }
        return safe_config or None

    async def _provider_logical_id(
        self,
        session: AsyncSession,
        provider_id: str,
    ) -> str:
        provider = await self.provider_repository.get_by_id(
            session,
            provider_id=provider_id,
            for_update=False,
        )
        if provider is None:
            raise RuntimeProviderBindingAdminUnavailable("provider_not_found")
        return provider.provider_id
