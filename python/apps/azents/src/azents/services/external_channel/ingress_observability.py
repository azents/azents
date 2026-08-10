"""Bounded observability for active External Channel ingress."""

import dataclasses
import datetime
from typing import Annotated

from fastapi import Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from azents.job_runtime.deps import get_job_runtime
from azents.job_runtime.types import JobRuntime
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.ingress_queue import (
    ExternalChannelIngressQueueRepository,
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

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    queue_repository: Annotated[
        ExternalChannelIngressQueueRepository,
        Depends(ExternalChannelIngressQueueRepository),
    ]
    metrics: Annotated[
        ExternalChannelIngressMetrics,
        Depends(get_external_channel_ingress_metrics),
    ]
    runtime: Annotated[JobRuntime, Depends(get_job_runtime)]

    async def observe(self, *, limit: int = 200) -> ExternalChannelIngressObservation:
        """Return bounded queue and process observations."""
        now = datetime.datetime.now(datetime.UTC)
        async with self.session_manager() as session:
            queue = await self.queue_repository.inspect_active(
                session,
                now=now,
                limit=limit,
            )
            await session.commit()
        return ExternalChannelIngressObservation(
            queue=queue,
            metrics=self.metrics.snapshot(
                self.runtime,
                active_backlog_size=queue.counts.total,
                oldest_queue_age_seconds=queue.oldest_queue_age_seconds,
            ),
        )
