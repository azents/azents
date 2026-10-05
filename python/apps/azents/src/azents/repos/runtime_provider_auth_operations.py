"""Atomic credential/binding/provider authentication ownership."""

import datetime
import hmac
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from pydantic import BaseModel, ConfigDict, ValidationError

from azents.core.enums import (
    RuntimeProviderAuthMethod,
    RuntimeProviderBindingOwner,
    RuntimeProviderBindingState,
    RuntimeProviderKind,
    RuntimeProviderLifecycleState,
    RuntimeProviderScope,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.runtime_provider.repository import RuntimeProviderRepository
from azents.repos.runtime_provider_binding.repository import (
    RuntimeProviderAuthBindingRepository,
)
from azents.repos.runtime_provider_control.repository import (
    RuntimeProviderControlRepository,
)

_TERMINAL = frozenset(
    {
        RuntimeProviderLifecycleState.DECOMMISSIONED,
        RuntimeProviderLifecycleState.FORCE_RETIRED,
    }
)
_KUBERNETES_AUDIENCE = "azents-runtime-control"


class _KubernetesServiceAccountBindingConfig(BaseModel):
    """Decode consumed binding fields while retaining unknown-field compatibility."""

    model_config = ConfigDict(strict=True, extra="ignore", frozen=True)

    audience: str
    namespace: str
    service_account_name: str


@dataclass(frozen=True)
class RuntimeProviderAuthenticationRecord:
    """Authenticated logical and resource identities for one durable Provider."""

    binding_id: str
    credential_id: str | None
    provider_id: str
    provider_resource_id: str
    provider_kind: RuntimeProviderKind
    provider_scope: RuntimeProviderScope
    provider_workspace_id: str | None
    auth_method: RuntimeProviderAuthMethod
    auth_subject: str
    evidence_expires_at: datetime.datetime | None

    def __post_init__(self) -> None:
        """Enforce method-specific evidence persistence invariants."""
        if (
            self.auth_method is RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN
            and self.credential_id is None
        ):
            raise ValueError("issued-token authentication requires credential_id")
        if self.auth_method is RuntimeProviderAuthMethod.KUBERNETES_SERVICE_ACCOUNT:
            if self.credential_id is not None:
                raise ValueError(
                    "Kubernetes ServiceAccount authentication cannot use credential_id"
                )
            if self.evidence_expires_at is None:
                raise ValueError(
                    "Kubernetes ServiceAccount authentication requires evidence expiry"
                )


@dataclass
class RuntimeProviderAuthenticationRejected(Exception):
    """Existing bounded credential failure after rollback."""

    code: str

    def __post_init__(self) -> None:
        Exception.__init__(self, self.code)


@dataclass
class RuntimeProviderAuthenticationOperationRepository:
    """Complete authentication reads and conditional writes in one RW scope."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    repository: Annotated[
        RuntimeProviderControlRepository, Depends(RuntimeProviderControlRepository)
    ]
    provider_repository: Annotated[
        RuntimeProviderRepository, Depends(RuntimeProviderRepository)
    ]
    binding_repository: Annotated[
        RuntimeProviderAuthBindingRepository,
        Depends(RuntimeProviderAuthBindingRepository),
    ]

    async def verify_issued_token(
        self, *, verifier: str, now: datetime.datetime
    ) -> RuntimeProviderAuthenticationRecord:
        """Commit both credential usage and binding authentication or roll back both."""
        async with self.session_manager() as session:
            credential = await self.repository.get_active_credential_by_verifier(
                session,
                verifier=verifier,
                now=now,
            )
            if credential is None or not hmac.compare_digest(
                verifier, credential.verifier
            ):
                raise RuntimeProviderAuthenticationRejected("credential_unavailable")
            binding = await self.binding_repository.get_by_id(
                session,
                binding_id=credential.binding_id,
            )
            if (
                binding is None
                or binding.state is not RuntimeProviderBindingState.ACTIVE
                or binding.auth_method
                is not RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN
            ):
                raise RuntimeProviderAuthenticationRejected("binding_unavailable")
            if binding.provider_id != credential.provider_id:
                raise RuntimeProviderAuthenticationRejected("binding_unavailable")
            provider = await self.provider_repository.get_by_id(
                session,
                provider_id=binding.provider_id,
            )
            if provider is None or provider.lifecycle_state in _TERMINAL:
                raise RuntimeProviderAuthenticationRejected("provider_unavailable")
            if not await self.repository.mark_credential_used(
                session,
                credential_id=credential.id,
                used_at=now,
            ):
                raise RuntimeProviderAuthenticationRejected("credential_unavailable")
            evidence_expires_at = credential.expires_at
            if not await self.binding_repository.mark_authenticated(
                session,
                binding_id=binding.id,
                authenticated_at=now,
            ):
                raise RuntimeProviderAuthenticationRejected("binding_unavailable")
        return RuntimeProviderAuthenticationRecord(
            binding_id=binding.id,
            credential_id=credential.id,
            provider_id=provider.provider_id,
            provider_resource_id=provider.id,
            provider_kind=provider.kind,
            provider_scope=provider.scope,
            provider_workspace_id=provider.workspace_id,
            auth_method=RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN,
            auth_subject=binding.subject,
            evidence_expires_at=evidence_expires_at,
        )

    async def verify_workload_binding(
        self,
        *,
        subject: str,
        namespace: str,
        service_account_name: str,
        evidence_expires_at: datetime.datetime,
        now: datetime.datetime,
    ) -> RuntimeProviderAuthenticationRecord:
        """Check current durable authority only after external TokenReview completes."""
        async with self.session_manager() as session:
            binding = await self.binding_repository.get_active_by_subject(
                session,
                auth_method=RuntimeProviderAuthMethod.KUBERNETES_SERVICE_ACCOUNT,
                subject=subject,
            )
            if (
                binding is None
                or binding.owner is not RuntimeProviderBindingOwner.BOOTSTRAP
            ):
                raise RuntimeProviderAuthenticationRejected("binding_unavailable")
            try:
                config = _KubernetesServiceAccountBindingConfig.model_validate(
                    binding.config
                )
            except ValidationError:
                raise RuntimeProviderAuthenticationRejected(
                    "binding_unavailable"
                ) from None
            if (
                config.audience != _KUBERNETES_AUDIENCE
                or config.namespace != namespace
                or config.service_account_name != service_account_name
            ):
                raise RuntimeProviderAuthenticationRejected("binding_unavailable")
            provider = await self.provider_repository.get_by_id(
                session,
                provider_id=binding.provider_id,
            )
            if provider is None or provider.lifecycle_state in _TERMINAL:
                raise RuntimeProviderAuthenticationRejected("provider_unavailable")
            if not await self.binding_repository.mark_authenticated(
                session,
                binding_id=binding.id,
                authenticated_at=now,
            ):
                raise RuntimeProviderAuthenticationRejected("binding_unavailable")
        return RuntimeProviderAuthenticationRecord(
            binding_id=binding.id,
            credential_id=None,
            provider_id=provider.provider_id,
            provider_resource_id=provider.id,
            provider_kind=provider.kind,
            provider_scope=provider.scope,
            provider_workspace_id=provider.workspace_id,
            auth_method=RuntimeProviderAuthMethod.KUBERNETES_SERVICE_ACCOUNT,
            auth_subject=subject,
            evidence_expires_at=evidence_expires_at,
        )
