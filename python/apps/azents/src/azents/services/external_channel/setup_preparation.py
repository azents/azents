"""Recoverable Discord first-mention preparation using existing setup claims."""

import asyncio
import dataclasses
import datetime
import logging
from typing import Annotated
from uuid import uuid4

from fastapi import Depends

from azents.core.external_channel_conversation_data import (
    ExternalChannelOperationDeadline,
)
from azents.core.external_channel_ingestion import (
    ExternalChannelIngestionOutcome,
    ExternalChannelIngestionOutcomeKind,
    ExternalChannelIngestionReason,
    ExternalChannelIngestionRequest,
    ExternalChannelSetupPreparationBoundary,
)
from azents.job_runtime.deps import get_job_runtime
from azents.job_runtime.local import JobRuntimeClosedError
from azents.job_runtime.types import (
    JobRuntime,
)
from azents.repos.external_channel.setup_preparation import (
    ExternalChannelSetupPreparationRepository,
)
from azents.services.external_channel.ingestion import (
    ExternalChannelConversationIngestionService,
)
from azents.services.external_channel.ingestion_deps import (
    get_external_channel_conversation_ingestion_service,
)
from azents.services.external_channel.provider_control import (
    ExternalChannelProviderControlService,
    get_external_channel_provider_control_service,
)
from azents.services.external_channel.setup_preparation_job import (
    build_setup_preparation_job,
)
from azents.utils.logging import sanitized_exception_info

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class ExternalChannelSetupPreparationService:
    """Submit/recover preparation and execute each source behind a DB lease."""

    operations: Annotated[
        ExternalChannelSetupPreparationRepository,
        Depends(ExternalChannelSetupPreparationRepository),
    ]
    job_runtime: Annotated[JobRuntime, Depends(get_job_runtime)]
    ingestion_service: Annotated[
        ExternalChannelConversationIngestionService,
        Depends(get_external_channel_conversation_ingestion_service),
    ]
    provider_control: Annotated[
        ExternalChannelProviderControlService,
        Depends(get_external_channel_provider_control_service),
    ]

    async def admit(
        self, request: ExternalChannelIngestionRequest
    ) -> ExternalChannelIngestionOutcome | None:
        """Acknowledge committed setup receipt without waiting for provider reads."""
        now = datetime.datetime.now(datetime.UTC)
        claim_id = await self.operations.admit(request=request, now=now)
        if claim_id is None:
            return None
        await self.submit(claim_id, now=now)
        return ExternalChannelIngestionOutcome(
            kind=ExternalChannelIngestionOutcomeKind.AWAITING_SELECTION,
            reason=ExternalChannelIngestionReason.SETUP_REQUIRED,
            mailbox_item_id=None,
            control_plans=(),
            connection_id=None,
        )

    async def submit(self, claim_id: str, *, now: datetime.datetime) -> None:
        """Lost local submission is recovered from the committed setup claim."""
        try:
            await self.job_runtime.submit(
                build_setup_preparation_job(claim_id, now=now)
            )
        except asyncio.CancelledError:
            raise
        except JobRuntimeClosedError:
            logger.warning(
                "Setup preparation Runtime submission is unavailable",
                extra={"external_channel_setup_claim_id": claim_id},
            )

    async def recover(self, *, now: datetime.datetime, limit: int) -> None:
        """Submit due/expired preparation without borrowing a Gateway lease."""
        for claim_id in await self.operations.recoverable_ids(now=now, limit=limit):
            await self.submit(claim_id, now=now)

    async def process(
        self, claim_id: str, *, deadline: ExternalChannelOperationDeadline
    ) -> None:
        """Prepare one exact source, then fence any external control dispatch."""
        attempt = await self.operations.claim(
            claim_id=claim_id,
            owner=uuid4().hex,
            now=datetime.datetime.now(datetime.UTC),
            deadline=deadline,
        )
        if attempt.failure_code is not None:
            logger.warning(
                "Setup preparation terminated",
                extra={
                    "external_channel_setup_claim_id": claim_id,
                    "failure_code": attempt.failure_code,
                },
            )
        request = attempt.request
        if request is None:
            return
        boundary = request.replay_boundary
        assert isinstance(boundary, ExternalChannelSetupPreparationBoundary)
        dispatch_started = False
        try:
            outcome = await self.ingestion_service.ingest(request)
            if outcome.kind is ExternalChannelIngestionOutcomeKind.RETRYABLE_FAILURE:
                await self.operations.transition(
                    boundary=boundary,
                    dispatch=False,
                    retry=True,
                    now=datetime.datetime.now(datetime.UTC),
                )
                return
            if outcome.control_plans:
                if not await self.operations.transition(
                    boundary=boundary,
                    dispatch=True,
                    retry=False,
                    now=datetime.datetime.now(datetime.UTC),
                ):
                    return
                dispatch_started = True
                for plan in outcome.control_plans:
                    delivered = await self.provider_control.attempt(plan)
                    if delivered is not None and delivered.status == "unknown":
                        logger.warning(
                            "Setup control dispatch is uncertain",
                            extra={"external_channel_setup_claim_id": claim_id},
                        )
                        break
                    if delivered is not None and delivered.status == "failed":
                        await self.operations.transition(
                            boundary=boundary,
                            dispatch=False,
                            retry=True,
                            now=datetime.datetime.now(datetime.UTC),
                        )
                        return
            await self.operations.transition(
                boundary=boundary,
                dispatch=False,
                retry=False,
                now=datetime.datetime.now(datetime.UTC),
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.error(
                "Setup preparation execution failed",
                exc_info=sanitized_exception_info(
                    error, message="Setup failure details redacted."
                ),
                extra={"external_channel_setup_claim_id": claim_id},
            )
            await self.operations.transition(
                boundary=boundary,
                dispatch=False,
                retry=not dispatch_started,
                now=datetime.datetime.now(datetime.UTC),
            )
