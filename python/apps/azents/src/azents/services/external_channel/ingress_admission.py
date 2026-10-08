"""External dispatch after completed atomic conversation-trigger admission."""

import dataclasses
import datetime
import logging
from typing import Annotated

from fastapi import Depends

from azents.core.external_channel_ingestion import (
    ExternalChannelIngestionOutcome,
    ExternalChannelIngestionRequest,
)
from azents.job_runtime.deps import get_job_runtime
from azents.job_runtime.local import JobRuntimeClosedError
from azents.job_runtime.types import JobRuntime
from azents.repos.external_channel.ingress_admission_operations import (
    ExternalChannelIngressAdmissionOperations,
)
from azents.services.external_channel.ingress_queue import (
    build_external_channel_ingress_job_request,
)

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class ExternalChannelIngressAdmissionService:
    operations: Annotated[
        ExternalChannelIngressAdmissionOperations,
        Depends(ExternalChannelIngressAdmissionOperations),
    ]
    job_runtime: Annotated[JobRuntime, Depends(get_job_runtime)]

    async def admit_current_trigger(
        self, *, provider_event_id: str, request: ExternalChannelIngestionRequest
    ) -> ExternalChannelIngestionOutcome | None:
        now = datetime.datetime.now(datetime.UTC)
        result = await self.operations.admit_current_trigger(
            provider_event_id=provider_event_id, request=request, now=now
        )
        admission = result.admission
        if admission is not None:
            if admission.replaced_stale_owner:
                logger.warning(
                    "External Channel ingress stale provisioning owner was replaced",
                    extra={
                        "external_channel_ingress_owner_id": admission.owner.id,
                        "external_channel_connection_id": admission.owner.connection_id,
                    },
                )
            await self._submit(
                admission.owner.id, drain_created_at=admission.owner.created_at, now=now
            )
        return result.outcome

    async def _submit(
        self,
        owner_id: str,
        *,
        drain_created_at: datetime.datetime,
        now: datetime.datetime,
    ) -> None:
        """Best-effort submit one coalesced owner execution key."""
        try:
            await self.job_runtime.submit(
                build_external_channel_ingress_job_request(
                    owner_id=owner_id,
                    drain_created_at=drain_created_at,
                    now=now,
                )
            )
        except JobRuntimeClosedError:
            logger.warning(
                "External Channel ingress Runtime submission is unavailable",
                exc_info=True,
                extra={"external_channel_ingress_owner_id": owner_id},
            )
