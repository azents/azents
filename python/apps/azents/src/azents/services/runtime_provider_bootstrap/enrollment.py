"""Bootstrap-owned Runtime Provider credential enrollment."""

import dataclasses
import datetime
from typing import Annotated

from azcommon.datetime import tznow
from fastapi import Depends

from azents.core.runtime_provider_bootstrap import RuntimeProviderBootstrapSnapshot
from azents.repos.runtime_provider.bootstrap_enrollment_read import (
    RuntimeProviderBootstrapEnrollmentReadRepository,
)
from azents.services.runtime_provider_control.data import (
    RuntimeProviderCredentialUnavailable,
)
from azents.services.runtime_provider_control.deps import (
    get_runtime_provider_enrollment_service,
)
from azents.services.runtime_provider_control.service import (
    RuntimeProviderEnrollmentService,
)

from .service import RuntimeProviderBootstrapService


@dataclasses.dataclass(frozen=True)
class RuntimeProviderBootstrapCredential:
    """Credential material ensured by its owning bootstrap source."""

    secret: str
    changed: bool


@dataclasses.dataclass(frozen=True)
class RuntimeProviderBootstrapEnrollmentService:
    """Reconcile a declaration and ensure its Provider credential."""

    repository: Annotated[
        RuntimeProviderBootstrapEnrollmentReadRepository,
        Depends(RuntimeProviderBootstrapEnrollmentReadRepository),
    ]
    bootstrap_service: Annotated[RuntimeProviderBootstrapService, Depends()]
    enrollment_service: Annotated[
        RuntimeProviderEnrollmentService,
        Depends(get_runtime_provider_enrollment_service),
    ]

    async def ensure_credential(
        self,
        *,
        snapshot: RuntimeProviderBootstrapSnapshot,
        provider_logical_id: str,
        existing_secret: str | None,
    ) -> RuntimeProviderBootstrapCredential:
        """Return an active credential for one declaration-owned Provider."""
        matching_declarations = tuple(
            declaration
            for declaration in snapshot.declarations
            if declaration.provider_logical_id == provider_logical_id
        )
        if len(matching_declarations) != 1:
            raise ValueError(
                "Bootstrap credential target must match exactly one declaration."
            )
        reconcile_result = await self.bootstrap_service.reconcile(snapshot)
        target = await self.repository.resolve(
            provider_logical_id=provider_logical_id,
            source_id=reconcile_result.source_id,
        )
        provider_id = target.provider_id
        source_id = target.source_id

        if existing_secret is not None:
            try:
                authentication = await self.enrollment_service.authenticate_credential(
                    secret=existing_secret
                )
            except RuntimeProviderCredentialUnavailable:
                pass
            else:
                if authentication.provider_resource_id == provider_id:
                    return RuntimeProviderBootstrapCredential(
                        secret=existing_secret,
                        changed=False,
                    )

        grant = await self.enrollment_service.issue_grant(
            provider_id=provider_id,
            expires_at=tznow() + datetime.timedelta(minutes=5),
            issued_by_user_id=None,
            issued_by_source_id=source_id,
        )
        credential = await self.enrollment_service.exchange_grant(
            grant_id=grant.grant_id,
            secret=grant.secret,
            credential_expires_at=None,
            source_address=None,
        )
        return RuntimeProviderBootstrapCredential(
            secret=credential.secret,
            changed=True,
        )
