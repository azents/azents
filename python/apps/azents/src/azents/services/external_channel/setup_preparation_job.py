"""Registration-safe setup preparation Job Runtime contract."""

import datetime

from pydantic import BaseModel

from azents.core.external_channel_conversation_data import (
    ExternalChannelOperationDeadline,
)
from azents.job_runtime.types import JobExecutionContext, JobPayload, JobRequest

SETUP_PREPARATION_JOB_HANDLER_KEY = "external_channel.setup_preparation"
_ATTEMPT_BUDGET = datetime.timedelta(minutes=2)


class SetupPreparationJobPayload(BaseModel):
    """The durable claim identity is sufficient for process-local execution."""

    claim_id: str


def build_setup_preparation_job(claim_id: str, *, now: datetime.datetime) -> JobRequest:
    """Coalesce wakes while PostgreSQL retains execution authority."""
    return JobRequest(
        handler_key=SETUP_PREPARATION_JOB_HANDLER_KEY,
        execution_key=f"external-channel-setup:{claim_id}",
        deadline=now + _ATTEMPT_BUDGET,
        payload=SetupPreparationJobPayload(claim_id=claim_id).model_dump(mode="json"),
    )


async def execute_setup_preparation_job(context: JobExecutionContext) -> JobPayload:
    """Resolve fresh task-local dependencies after Runtime registry construction."""
    from azents.services.external_channel.setup_preparation import (  # noqa: PLC0415
        ExternalChannelSetupPreparationService,
    )

    payload = SetupPreparationJobPayload.model_validate(context.request.payload)
    service = await context.container.solve(ExternalChannelSetupPreparationService)
    await service.process(
        payload.claim_id,
        deadline=ExternalChannelOperationDeadline(context.request.deadline),
    )
    return {"claim_id": payload.claim_id}
