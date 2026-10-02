"""Bounded observability for active External Channel ingress."""

import dataclasses
import datetime
from typing import Annotated

from fastapi import Depends
from pydantic import BaseModel, ConfigDict

from azents.job_runtime.deps import get_job_runtime
from azents.job_runtime.types import JobRuntime
from azents.repos.external_channel.ingress_control_read import (
    ExternalChannelIngressControlReadRepository,
)
from azents.repos.external_channel.ingress_queue_data import (
    ExternalChannelIngressDiagnosticSnapshot,
)
from azents.services.external_channel.ingress_metrics import (
    ExternalChannelIngressMetrics,
    ExternalChannelIngressMetricSnapshot,
    get_external_channel_ingress_metrics,
)


class ExternalChannelIngressObservation(BaseModel):
    """Combined durable queue and process metric observation."""

    model_config = ConfigDict(frozen=True)

    queue: ExternalChannelIngressDiagnosticSnapshot
    metrics: ExternalChannelIngressMetricSnapshot


@dataclasses.dataclass
class ExternalChannelIngressObservabilityService:
    """Read active queue state and current process metrics."""

    repository: Annotated[
        ExternalChannelIngressControlReadRepository,
        Depends(ExternalChannelIngressControlReadRepository),
    ]
    metrics: Annotated[
        ExternalChannelIngressMetrics,
        Depends(get_external_channel_ingress_metrics),
    ]
    runtime: Annotated[JobRuntime, Depends(get_job_runtime)]

    async def observe(self, *, limit: int = 200) -> ExternalChannelIngressObservation:
        """Return bounded queue and process observations."""
        now = datetime.datetime.now(datetime.UTC)
        queue = await self.repository.inspect_active(now=now, limit=limit)
        return ExternalChannelIngressObservation(
            queue=queue,
            metrics=self.metrics.snapshot(
                self.runtime,
                active_backlog_size=queue.counts.total,
                oldest_queue_age_seconds=queue.oldest_queue_age_seconds,
            ),
        )
