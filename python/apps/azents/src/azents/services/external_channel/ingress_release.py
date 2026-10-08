"""Session-free release submission for guarded active ingress controls."""

import datetime
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from azents.job_runtime.deps import get_job_runtime
from azents.job_runtime.types import JobRuntime
from azents.repos.external_channel.ingress_control_read import (
    ExternalChannelIngressControlReadRepository,
)
from azents.services.external_channel.ingress_queue import (
    build_external_channel_ingress_job_request,
)


@dataclass(frozen=True)
class ExternalChannelIngressReleaseService:
    """Sequence a completed presence read and the existing Job Runtime request."""

    repository: Annotated[
        ExternalChannelIngressControlReadRepository,
        Depends(ExternalChannelIngressControlReadRepository),
    ]
    runtime: Annotated[JobRuntime, Depends(get_job_runtime)]

    async def release(self, *, owner_id: str) -> bool:
        """Return not-found or submit acceptance without awaiting drain."""
        owner = await self.repository.get_release_owner(owner_id=owner_id)
        if owner is None:
            return False
        await self.runtime.submit(
            build_external_channel_ingress_job_request(
                owner_id=owner_id,
                drain_created_at=owner.created_at,
                now=datetime.datetime.now(datetime.UTC),
            )
        )
        return True
