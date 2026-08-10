"""Producer-local recovery wake loop for active External Channel ingress state."""

import asyncio
import dataclasses
import datetime
import logging
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.job_runtime.deps import get_job_runtime
from azents.job_runtime.local import JobRuntimeClosedError
from azents.job_runtime.types import JobRuntime
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.ingress_queue import (
    ExternalChannelIngressQueueRepository,
)
from azents.services.external_channel.ingress_queue import (
    build_external_channel_ingress_job_request,
)

logger = logging.getLogger(__name__)

_RECOVERY_INTERVAL_SECONDS = 30
_RECOVERY_SCAN_LIMIT = 100


@dataclasses.dataclass
class ExternalChannelIngressRecoveryService:
    """Resubmit due active Session domain state without claiming generic jobs."""

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    queue_repository: Annotated[
        ExternalChannelIngressQueueRepository,
        Depends(ExternalChannelIngressQueueRepository),
    ]
    job_runtime: Annotated[JobRuntime, Depends(get_job_runtime)]

    async def run(self, shutdown_event: asyncio.Event) -> None:
        """Scan at startup and periodically until producer shutdown."""
        while not shutdown_event.is_set():
            await self.run_once(now=datetime.datetime.now(datetime.UTC))
            try:
                await asyncio.wait_for(
                    shutdown_event.wait(),
                    timeout=_RECOVERY_INTERVAL_SECONDS,
                )
            except TimeoutError:
                continue

    async def run_once(self, *, now: datetime.datetime) -> list[str]:
        """Submit one bounded set of due or reclaimable Session identities."""
        async with self.session_manager() as session:
            drains = await self.queue_repository.list_recoverable_sessions(
                session,
                now=now,
                limit=_RECOVERY_SCAN_LIMIT,
            )
            await session.commit()
        submitted: list[str] = []
        for drain in drains:
            try:
                await self.job_runtime.submit(
                    build_external_channel_ingress_job_request(
                        session_id=drain.session_id,
                        drain_created_at=drain.created_at,
                        now=now,
                    )
                )
            except JobRuntimeClosedError:
                logger.warning(
                    "External Channel ingress recovery Runtime is unavailable",
                    extra={"external_channel_session_id": drain.session_id},
                )
                break
            submitted.append(drain.session_id)
        return submitted
