"""Credential-free active External Channel ingress controls."""

import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from azents.job_runtime.deps import get_job_runtime
from azents.job_runtime.types import JobRuntime
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.ingress_queue import (
    ExternalChannelIngressQueueRepository,
)
from azents.services.external_channel.ingress_observability import (
    ExternalChannelIngressObservabilityService,
    ExternalChannelIngressObservation,
)
from azents.services.external_channel.ingress_queue import (
    build_external_channel_ingress_job_request,
)
from azents.services.external_channel.ingress_test_control import (
    ExternalChannelIngressTestControl,
    get_external_channel_ingress_test_control,
)
from azents.utils.fastapi.route import RouteMounter

router = APIRouter()


class IngressSessionRequest(BaseModel):
    """Exact Session identity for a bounded testenv action."""

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
    body: IngressSessionRequest,
    runtime: Annotated[JobRuntime, Depends(get_job_runtime)],
    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ],
    repository: Annotated[
        ExternalChannelIngressQueueRepository,
        Depends(ExternalChannelIngressQueueRepository),
    ],
) -> IngressReleaseResponse:
    """Submit one exact active Session drain through the real Job Runtime."""
    async with session_manager() as session:
        drain = await repository.get_active_session(
            session,
            session_id=body.session_id,
        )
        await session.commit()
    if drain is None:
        raise HTTPException(status_code=404, detail="Active ingress Session not found.")
    await runtime.submit(
        build_external_channel_ingress_job_request(
            session_id=body.session_id,
            drain_created_at=drain.created_at,
            now=datetime.datetime.now(datetime.UTC),
        )
    )
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
