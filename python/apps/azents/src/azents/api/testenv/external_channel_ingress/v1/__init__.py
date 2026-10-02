"""Credential-free active External Channel ingress controls."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from azents.services.external_channel.ingress_observability import (
    ExternalChannelIngressObservabilityService,
    ExternalChannelIngressObservation,
)
from azents.services.external_channel.ingress_release import (
    ExternalChannelIngressReleaseService,
)
from azents.services.external_channel.ingress_test_control import (
    ExternalChannelIngressTestControl,
    get_external_channel_ingress_test_control,
)
from azents.utils.fastapi.route import RouteMounter

router = APIRouter()


class IngressOwnerRequest(BaseModel):
    """Exact ingress owner identity for a bounded release action."""

    model_config = ConfigDict(extra="forbid")

    owner_id: str


class IngressSessionRequest(BaseModel):
    """Exact Session identity for a bounded wake-control action."""

    model_config = ConfigDict(extra="forbid")

    session_id: str


class IngressReleaseResponse(BaseModel):
    """Accepted Runtime release submission."""

    accepted: bool


@router.get("/active")
async def inspect_active_ingress(
    service: Annotated[
        ExternalChannelIngressObservabilityService,
        Depends(ExternalChannelIngressObservabilityService),
    ],
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> ExternalChannelIngressObservation:
    """Inspect sanitized active queue state and process metrics."""
    return await service.observe(limit=limit)


@router.post("/release")
async def release_active_ingress(
    body: IngressOwnerRequest,
    service: Annotated[
        ExternalChannelIngressReleaseService,
        Depends(ExternalChannelIngressReleaseService),
    ],
) -> IngressReleaseResponse:
    """Submit one exact active owner drain through the real Job Runtime."""
    if not await service.release(owner_id=body.owner_id):
        raise HTTPException(status_code=404, detail="Active ingress owner not found.")
    return IngressReleaseResponse(accepted=True)


@router.post("/fail-next-wake")
async def fail_next_wake(
    body: IngressSessionRequest,
    control: Annotated[
        ExternalChannelIngressTestControl,
        Depends(get_external_channel_ingress_test_control),
    ],
) -> IngressReleaseResponse:
    """Inject one exact post-commit wake failure."""
    control.fail_next_wake(session_id=body.session_id)
    return IngressReleaseResponse(accepted=True)


def mount(mounter: RouteMounter) -> None:
    """Mount credential-free ingress devtools."""
    mounter(
        router,
        prefix="/external-channel-ingress/v1",
        tag="External Channel ingress v1",
        description="Sanitized active ingress inspection and deterministic controls",
    )
