"""Runtime Provider enrollment v1 Public API."""

import datetime
from textwrap import dedent
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, HTTPException, Request, status

from azents.services.runtime_provider_control.data import (
    RuntimeProviderCredentialIssued,
    RuntimeProviderEnrollmentUnavailable,
)
from azents.services.runtime_provider_control.deps import (
    get_runtime_provider_enrollment_rate_limiter,
    get_runtime_provider_enrollment_service,
)
from azents.services.runtime_provider_control.rate_limit import (
    RuntimeProviderEnrollmentRateLimited,
    RuntimeProviderEnrollmentRateLimiter,
)
from azents.utils.fastapi.route import RouteMounter

from .data import (
    RuntimeProviderCredentialExchangeRequest,
    RuntimeProviderCredentialExchangeResponse,
)

router = APIRouter()


class RuntimeProviderCredentialExchanger(Protocol):
    """Exchange one enrollment grant for one Provider credential."""

    async def exchange_grant(
        self,
        *,
        grant_id: str,
        secret: str,
        credential_expires_at: datetime.datetime | None,
        source_address: str | None,
    ) -> RuntimeProviderCredentialIssued:
        """Return one issued Provider credential."""
        ...


@router.post("/credentials/exchange")
async def exchange_credential(
    service: Annotated[
        RuntimeProviderCredentialExchanger,
        Depends(get_runtime_provider_enrollment_service),
    ],
    rate_limiter: Annotated[
        RuntimeProviderEnrollmentRateLimiter,
        Depends(get_runtime_provider_enrollment_rate_limiter),
    ],
    request: Request,
    request_body: RuntimeProviderCredentialExchangeRequest,
) -> RuntimeProviderCredentialExchangeResponse:
    """Exchange one enrollment grant for one Provider credential."""
    source_address = request.client.host if request.client is not None else "unknown"
    try:
        await rate_limiter.acquire(
            grant_id=request_body.grant_id,
            source_address=source_address,
        )
    except RuntimeProviderEnrollmentRateLimited as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Provider enrollment exchange rate limit exceeded.",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from None
    try:
        issued = await service.exchange_grant(
            grant_id=request_body.grant_id,
            secret=request_body.secret,
            credential_expires_at=None,
            source_address=source_address,
        )
    except RuntimeProviderEnrollmentUnavailable:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Provider enrollment grant is invalid or unavailable.",
        ) from None
    return RuntimeProviderCredentialExchangeResponse(
        credential_id=issued.credential_id,
        provider_id=issued.provider_id,
        credential=issued.secret,
        expires_at=issued.expires_at,
    )


def mount(mounter: RouteMounter) -> None:
    """Mount Runtime Provider enrollment v1 routes."""
    mounter(
        router,
        prefix="/runtime-provider-enrollment/v1",
        tag="Runtime Provider Enrollment v1",
        description=dedent(
            """
            Runtime Provider Enrollment API (Public)

            Operator-facing one-time enrollment grant exchange for known Providers.
            """
        ),
    )
