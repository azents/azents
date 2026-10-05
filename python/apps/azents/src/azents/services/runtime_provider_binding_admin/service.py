"""Admin orchestration for completed Runtime Provider binding operations."""

import dataclasses
import datetime
from typing import Annotated, Any

from azcommon.datetime import tznow
from fastapi import Depends

from azents.core.enums import RuntimeProviderAuthMethod
from azents.repos.runtime_provider_binding.admin_operations import (
    BindingAdminOperationUnavailable,
    BindingAdminSnapshot,
    RuntimeProviderBindingAdminOperationsRepository,
)
from azents.repos.runtime_provider_binding.data import (
    RuntimeProviderAuthBinding,
    RuntimeProviderAuthBindingAuditEvent,
)
from azents.services.runtime_provider_control.deps import (
    get_runtime_provider_enrollment_service,
)
from azents.services.runtime_provider_control.service import (
    RuntimeProviderEnrollmentService,
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


def _projection(
    snapshot: BindingAdminSnapshot,
) -> RuntimeProviderBindingAdminProjection:
    """Present one completed, secret-safe binding snapshot."""
    return RuntimeProviderBindingAdminProjection(
        binding=snapshot.binding,
        provider_id=snapshot.provider_id,
        connected=snapshot.connected,
    )


def _unavailable(
    error: BindingAdminOperationUnavailable,
) -> RuntimeProviderBindingAdminUnavailable:
    """Keep the public failure contract independent of repository error types."""
    return RuntimeProviderBindingAdminUnavailable(
        code=error.code,
        current_binding=(
            _projection(error.current_binding)
            if error.current_binding is not None
            else None
        ),
    )


@dataclasses.dataclass
class RuntimeProviderBindingAdminService:
    """Manage Provider binding presentation and one-time secret preparation."""

    repository: Annotated[
        RuntimeProviderBindingAdminOperationsRepository,
        Depends(RuntimeProviderBindingAdminOperationsRepository),
    ]
    enrollment_service: Annotated[
        RuntimeProviderEnrollmentService,
        Depends(get_runtime_provider_enrollment_service),
    ]

    async def list_bindings(
        self, provider_id: str
    ) -> tuple[RuntimeProviderBindingAdminProjection, ...]:
        """List bindings for one stable logical Provider ID."""
        try:
            snapshots = await self.repository.list_bindings(provider_id)
        except BindingAdminOperationUnavailable as error:
            raise _unavailable(error) from error
        return tuple(_projection(snapshot) for snapshot in snapshots)

    async def get_binding(
        self, binding_id: str
    ) -> RuntimeProviderBindingAdminProjection:
        """Get one safe binding projection."""
        try:
            snapshot = await self.repository.get_binding(binding_id)
        except BindingAdminOperationUnavailable as error:
            raise _unavailable(error) from error
        return _projection(snapshot)

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
        try:
            snapshot = await self.repository.create_binding(
                provider_id,
                auth_method=auth_method,
                subject=subject,
                config=config,
                actor_user_id=actor_user_id,
            )
        except BindingAdminOperationUnavailable as error:
            raise _unavailable(error) from error
        return _projection(snapshot)

    async def rotate_binding(
        self,
        binding_id: str,
        *,
        expected_admin_version: int,
        expires_at: datetime.datetime,
        actor_user_id: str,
    ) -> RuntimeProviderBindingRotation:
        """Prepare a secret, then atomically rotate binding, grant and audit."""
        now = tznow()
        if (
            expires_at.tzinfo is None
            or expires_at.utcoffset() is None
            or expires_at <= now
        ):
            raise RuntimeProviderBindingAdminUnavailable("grant_expiry_invalid")
        secret = self.enrollment_service.verifier.issue_secret()
        grant_verifier = self.enrollment_service.verifier.verifier_for(secret)
        try:
            snapshot = await self.repository.rotate_binding(
                binding_id,
                expected_admin_version=expected_admin_version,
                expires_at=expires_at,
                actor_user_id=actor_user_id,
                grant_verifier=grant_verifier,
                now=now,
            )
        except BindingAdminOperationUnavailable as error:
            raise _unavailable(error) from error
        return RuntimeProviderBindingRotation(
            binding=_projection(snapshot.binding),
            grant_id=snapshot.grant_id,
            secret=secret,
            expires_at=snapshot.expires_at,
        )

    async def revoke_binding(
        self,
        binding_id: str,
        *,
        expected_admin_version: int,
        reason: str | None,
        actor_user_id: str,
    ) -> RuntimeProviderBindingAdminProjection:
        """Revoke a binding and retained authority in one completed operation."""
        try:
            snapshot = await self.repository.revoke_binding(
                binding_id,
                expected_admin_version=expected_admin_version,
                reason=reason,
                actor_user_id=actor_user_id,
            )
        except BindingAdminOperationUnavailable as error:
            raise _unavailable(error) from error
        return _projection(snapshot)

    async def list_audit_events(
        self, binding_id: str, *, offset: int, limit: int
    ) -> tuple[RuntimeProviderAuthBindingAuditEvent, ...]:
        """List metadata-only binding audit history."""
        try:
            return await self.repository.list_audit_events(
                binding_id, offset=offset, limit=limit
            )
        except BindingAdminOperationUnavailable as error:
            raise _unavailable(error) from error
