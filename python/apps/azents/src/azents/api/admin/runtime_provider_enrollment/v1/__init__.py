"""Runtime Provider enrollment v1 Admin API."""

import datetime
from textwrap import dedent
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, HTTPException, status

from azents.core.auth.deps import SystemAdmin, get_system_admin
from azents.services.runtime_provider_control.data import (
    RuntimeProviderEnrollmentGrantIssued,
    RuntimeProviderEnrollmentUnavailable,
)
from azents.services.runtime_provider_control.deps import (
    get_runtime_provider_enrollment_service,
)
from azents.utils.fastapi.route import RouteMounter

from .data import (
    RuntimeProviderCredentialRevokeResponse,
    RuntimeProviderEnrollmentGrantIssueRequest,
    RuntimeProviderEnrollmentGrantIssueResponse,
)

router = APIRouter()


class RuntimeProviderEnrollmentGrantIssuer(Protocol):
    """Issue and revoke credential authority for known Providers."""

    async def issue_grant(
        self,
        *,
        provider_id: str,
        expires_at: datetime.datetime,
        issued_by_user_id: str | None,
        issued_by_source_id: str | None,
    ) -> RuntimeProviderEnrollmentGrantIssued:
        """Issue one enrollment grant."""
        ...

    async def revoke_credential(
        self,
        *,
        credential_id: str,
        revoked_by_user_id: str | None,
    ) -> bool:
        """Revoke one Provider credential."""
        ...


@router.post(
    "/runtime-providers/{provider_id}/enrollment-grants",
    status_code=status.HTTP_201_CREATED,
)
async def issue_enrollment_grant(
    system_admin: Annotated[SystemAdmin, Depends(get_system_admin)],
    service: Annotated[
        RuntimeProviderEnrollmentGrantIssuer,
        Depends(get_runtime_provider_enrollment_service),
    ],
    request_body: RuntimeProviderEnrollmentGrantIssueRequest,
    *,
    provider_id: str,
) -> RuntimeProviderEnrollmentGrantIssueResponse:
    """Issue one-time Provider enrollment authority for a Deployment Operator."""
    try:
        issued = await service.issue_grant(
            provider_id=provider_id,
            expires_at=request_body.expires_at,
            issued_by_user_id=system_admin.user_id,
            issued_by_source_id=None,
        )
    except RuntimeProviderEnrollmentUnavailable as error:
        if error.code == "grant_expiry_invalid":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Enrollment grant expiry must be in the future.",
            ) from None
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Runtime Provider was not found or is unavailable.",
        ) from None
    return RuntimeProviderEnrollmentGrantIssueResponse(
        grant_id=issued.grant_id,
        provider_id=issued.provider_id,
        secret=issued.secret,
        expires_at=issued.expires_at,
    )


@router.delete("/runtime-provider-credentials/{credential_id}")
async def revoke_credential(
    system_admin: Annotated[SystemAdmin, Depends(get_system_admin)],
    service: Annotated[
        RuntimeProviderEnrollmentGrantIssuer,
        Depends(get_runtime_provider_enrollment_service),
    ],
    *,
    credential_id: str,
) -> RuntimeProviderCredentialRevokeResponse:
    """Revoke one Provider credential without deleting its audit history."""
    revoked = await service.revoke_credential(
        credential_id=credential_id,
        revoked_by_user_id=system_admin.user_id,
    )
    if not revoked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Runtime Provider credential was not found or is already revoked.",
        )
    return RuntimeProviderCredentialRevokeResponse(revoked=True)


def mount(mounter: RouteMounter) -> None:
    """Mount Runtime Provider enrollment v1 Admin routes."""
    mounter(
        router,
        prefix="/runtime-provider-enrollment/v1",
        tag="Runtime Provider Enrollment v1",
        description=dedent(
            """
            Runtime Provider Enrollment API (Admin)

            System Admin control-plane operations for Provider enrollment authority.
            """
        ),
    )
