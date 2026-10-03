"""Durable Session-bound External Channel ingress admission and draining."""

import dataclasses
import datetime
import logging
import time
from typing import Annotated, assert_never

from azcommon.uuid import uuid7
from fastapi import Depends
from pydantic import BaseModel

from azents.core.enums import (
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
)
from azents.core.external_channel_conversation_data import (
    ExternalChannelHistoryError,
    ExternalChannelHistoryRange,
    ExternalChannelOperationDeadline,
)
from azents.core.external_channel_ingestion import (
    _DEFAULT_RETRY_DELAYS,
    _MAX_ITEM_AGE,
    _MAX_PROVIDER_ATTEMPTS,
    ExternalChannelCanonicalHistoryMessage,
    ExternalChannelIngressFailureCategory,
    ExternalChannelWakeDispatchUnavailable,
    _locator,
    _PreparedFailure,
    _PreparedItem,
    _PreparedSuccess,
    _PreparedSuppressed,
    _provider_failure,
)
from azents.core.external_channel_provider_effect import ProviderEffectPlan
from azents.job_runtime.types import (
    JobExecutionContext,
    JobPayload,
    JobRequest,
)
from azents.repos.external_channel.ingress_drain import (
    ExternalChannelIngressDrainRepository,
)
from azents.repos.external_channel.ingress_queue_data import (
    ExternalChannelIngressBatch,
    ExternalChannelIngressItem,
    ExternalChannelIngressOwner,
)
from azents.services.external_channel.ingestion_history import (
    ExternalChannelProviderHistoryReader,
)
from azents.services.external_channel.ingress_metrics import (
    ExternalChannelIngressMetrics,
    get_external_channel_ingress_metrics,
)
from azents.services.external_channel.ingress_provisioning import (
    ExternalChannelIngressProvisioningError,
    ExternalChannelIngressProvisioningService,
)
from azents.services.external_channel.mailbox_wake import (
    ExternalChannelMailboxWakeDispatcher,
)
from azents.services.external_channel.provider_control import (
    ExternalChannelProviderControlService,
    get_external_channel_provider_control_service,
)

logger = logging.getLogger(__name__)

EXTERNAL_CHANNEL_INGRESS_JOB_HANDLER_KEY = "external_channel.ingress"
_LEASE_DURATION = datetime.timedelta(minutes=10)
_JOB_DURATION = datetime.timedelta(minutes=10)
_PROVIDER_OPERATION_DURATION = datetime.timedelta(minutes=2)
_MAX_COORDINATION_RETRIES = 4


class ExternalChannelIngressJobPayload(BaseModel):
    """JSON-safe conversation owner submitted to the common Job Runtime."""

    owner_id: str


@dataclasses.dataclass
class ExternalChannelIngressProviderPolicyRegistry:
    """Closed Slack/Discord exact-and-history policy registry."""

    history_reader: Annotated[
        ExternalChannelProviderHistoryReader,
        Depends(ExternalChannelProviderHistoryReader),
    ]

    async def resolve(
        self,
        *,
        item: ExternalChannelIngressItem,
        exclusive_start_position: str | None,
        deadline: ExternalChannelOperationDeadline,
    ) -> ExternalChannelHistoryRange[ExternalChannelCanonicalHistoryMessage]:
        """Resolve one provider range through the adopted typed SDK adapter."""
        match item.provider:
            case ExternalChannelProvider.SLACK | ExternalChannelProvider.DISCORD:
                return await self.history_reader.read_range(
                    locator=_locator(item),
                    exclusive_start_position=exclusive_start_position,
                    deadline=deadline,
                )
            case _:
                assert_never(item.provider)


@dataclasses.dataclass
class ExternalChannelIngressDrainService:
    """Drain one Session queue with bounded provider work and atomic finalization."""

    operations: Annotated[
        ExternalChannelIngressDrainRepository,
        Depends(ExternalChannelIngressDrainRepository),
    ]
    provider_policies: Annotated[
        ExternalChannelIngressProviderPolicyRegistry,
        Depends(ExternalChannelIngressProviderPolicyRegistry),
    ]
    provisioning_service: Annotated[
        ExternalChannelIngressProvisioningService,
        Depends(ExternalChannelIngressProvisioningService),
    ]
    wake_dispatcher: Annotated[
        ExternalChannelMailboxWakeDispatcher,
        Depends(ExternalChannelMailboxWakeDispatcher),
    ]
    provider_control: Annotated[
        ExternalChannelProviderControlService,
        Depends(get_external_channel_provider_control_service),
    ]
    metrics: Annotated[
        ExternalChannelIngressMetrics,
        Depends(get_external_channel_ingress_metrics),
    ]

    async def drain(
        self,
        *,
        owner_id: str,
        deadline: datetime.datetime,
    ) -> None:
        """Acquire one conversation-owner lease and process due batches until idle."""
        lease_owner = uuid7().hex
        now = datetime.datetime.now(datetime.UTC)
        claim = await self.operations.claim_lease(
            owner_id=owner_id,
            lease_owner=lease_owner,
            now=now,
            lease_expires_at=min(deadline, now + _LEASE_DURATION),
        )
        if claim is None:
            return
        if not claim.owner.ready and not await self._prepare_owner(
            owner=claim.owner,
            lease_owner=lease_owner,
            lease_generation=claim.owner.lease_generation,
        ):
            return
        coordination_retries = 0
        while True:
            now = datetime.datetime.now(datetime.UTC)
            batch = await self.operations.claim_due_batch(
                owner_id=owner_id,
                lease_owner=lease_owner,
                lease_generation=claim.owner.lease_generation,
                now=now,
            )
            if batch is None:
                await self.operations.release_lease(
                    owner_id=owner_id,
                    lease_owner=lease_owner,
                    lease_generation=claim.owner.lease_generation,
                )
                return
            self.metrics.record_claim(len(batch.items))
            started_at = time.perf_counter()
            try:
                prepared = await self._prepare_batch(batch, deadline=deadline)
                stale = await self._finalize_batch(batch, prepared=prepared)
            finally:
                self.metrics.record_processing_duration(
                    time.perf_counter() - started_at
                )
            if stale:
                coordination_retries += 1
                if coordination_retries >= _MAX_COORDINATION_RETRIES:
                    await self.operations.release_lease(
                        owner_id=owner_id,
                        lease_owner=lease_owner,
                        lease_generation=claim.owner.lease_generation,
                    )
                    return
                continue
            coordination_retries = 0

    async def _prepare_owner(
        self,
        *,
        owner: ExternalChannelIngressOwner,
        lease_owner: str,
        lease_generation: int,
    ) -> bool:
        """Prepare one provider conversation and record its resulting Session."""
        try:
            preparation = await self.provisioning_service.prepare(owner=owner)
            completion = await self.operations.complete_owner(
                owner=owner,
                lease_owner=lease_owner,
                lease_generation=lease_generation,
                preparation=preparation,
            )
            if completion is None:
                return False
            await self._attempt_control_plans(completion.control_plans)
            return True
        except ExternalChannelIngressProvisioningError as error:
            return await self._record_preparation_failure(
                owner=owner,
                lease_owner=lease_owner,
                lease_generation=lease_generation,
                error=error,
            )

    async def _attempt_control_plans(
        self,
        plans: tuple[ProviderEffectPlan, ...],
    ) -> None:
        """Attempt committed Binding controls once without gating queue readiness."""
        for plan in plans:
            try:
                await self.provider_control.attempt(plan)
            except Exception:
                logger.exception(
                    "External Channel ingress provider control attempt failed"
                )

    async def _record_preparation_failure(
        self,
        *,
        owner: ExternalChannelIngressOwner,
        lease_owner: str,
        lease_generation: int,
        error: ExternalChannelIngressProvisioningError,
    ) -> bool:
        """Apply one bounded owner-level retry or terminal deletion."""
        now = datetime.datetime.now(datetime.UTC)
        exhausted = (
            not error.retryable
            or owner.preparation_attempt_count + 1 >= _MAX_PROVIDER_ATTEMPTS
            or now - owner.created_at >= _MAX_ITEM_AGE
        )
        delay_index = min(
            owner.preparation_attempt_count, len(_DEFAULT_RETRY_DELAYS) - 1
        )
        updated = await self.operations.record_preparation_failure(
            owner=owner,
            lease_owner=lease_owner,
            lease_generation=lease_generation,
            exhausted=exhausted,
            next_attempt_at=None
            if exhausted
            else now + datetime.timedelta(seconds=_DEFAULT_RETRY_DELAYS[delay_index]),
        )
        if updated and exhausted:
            logger.warning(
                "External Channel ingress owner exceeded its active lifecycle",
                extra={
                    "external_channel_ingress_owner_id": owner.id,
                    "external_channel_failure_category": error.category,
                    "external_channel_attempt_count": owner.preparation_attempt_count
                    + 1,
                    "external_channel_age_seconds": max(
                        0, int((now - owner.created_at).total_seconds())
                    ),
                },
            )
        return False

    async def _prepare_batch(
        self,
        batch: ExternalChannelIngressBatch,
        *,
        deadline: datetime.datetime,
    ) -> list[_PreparedItem]:
        """Resolve claimed items sequentially with a same-batch tentative cursor."""
        durable_cursors: dict[str, str | None] = {}
        tentative_cursors: dict[str, str | None] = {}
        prepared: list[_PreparedItem] = []
        for item in batch.items:
            if item.conversation_position_id not in durable_cursors:
                position = await self.operations.get_position(
                    position_id=item.conversation_position_id
                )
                if position is None:
                    prepared.append(
                        _PreparedFailure(
                            item=item,
                            durable_cursor=None,
                            category=(
                                ExternalChannelIngressFailureCategory.OWNERSHIP_STALE
                            ),
                            retryable=False,
                            retry_after_seconds=None,
                        )
                    )
                    continue
                durable_cursors[item.conversation_position_id] = (
                    position.read_through_position
                )
                tentative_cursors[item.conversation_position_id] = (
                    position.read_through_position
                )
            durable_cursor = durable_cursors[item.conversation_position_id]
            tentative_cursor = tentative_cursors[item.conversation_position_id]
            if (
                tentative_cursor is not None
                and item.trigger_position <= tentative_cursor
            ):
                prepared.append(
                    _PreparedSuppressed(item=item, durable_cursor=durable_cursor)
                )
                continue
            now = datetime.datetime.now(datetime.UTC)
            operation_deadline = ExternalChannelOperationDeadline(
                expires_at=min(deadline, now + _PROVIDER_OPERATION_DURATION)
            )
            try:
                history = await self.provider_policies.resolve(
                    item=item,
                    exclusive_start_position=tentative_cursor,
                    deadline=operation_deadline,
                )
            except ExternalChannelHistoryError as error:
                prepared.append(
                    _provider_failure(
                        item=item,
                        durable_cursor=durable_cursor,
                        error=error,
                    )
                )
                continue
            trigger = history.trigger
            if (
                trigger.provider_message_key != item.trigger_provider_message_key
                or trigger.provider_position != item.trigger_position
                or trigger.author_type is not ExternalChannelPrincipalAuthorType.HUMAN
                or trigger.provider_user_id != item.provider_user_id
            ):
                prepared.append(
                    _PreparedFailure(
                        item=item,
                        durable_cursor=durable_cursor,
                        category=ExternalChannelIngressFailureCategory.TRIGGER_MISSING,
                        retryable=False,
                        retry_after_seconds=None,
                    )
                )
                continue
            prepared.append(
                _PreparedSuccess(
                    item=item,
                    durable_cursor=durable_cursor,
                    history=history,
                )
            )
            tentative_cursors[item.conversation_position_id] = history.trigger_position
        return prepared

    async def _finalize_batch(
        self, batch: ExternalChannelIngressBatch, *, prepared: list[_PreparedItem]
    ) -> bool:
        """Attempt external effects only after completed atomic queue finalization."""
        now = datetime.datetime.now(datetime.UTC)
        result = await self.operations.finalize_batch(batch, prepared=prepared, now=now)
        if not result.committed:
            return result.stale
        for failure in result.bounded_failures:
            message = (
                "External Channel ingress trigger was missing; item ignored"
                if failure.category
                is ExternalChannelIngressFailureCategory.TRIGGER_MISSING
                else "External Channel ingress item exceeded its active lifecycle"
            )
            logger.warning(
                message,
                extra={
                    "external_channel_ingress_id": failure.item.id,
                    "external_channel_provider": failure.item.provider.value,
                    "external_channel_failure_category": failure.category.value,
                    "external_channel_attempt_count": failure.item.attempt_count,
                    "external_channel_age_seconds": max(
                        0,
                        int((now - failure.item.created_at).total_seconds()),
                    ),
                },
            )
        if result.progress_plan is not None:
            await self._attempt_control_plans((result.progress_plan,))
        self.metrics.record_finalization(
            retries=result.retries,
            bounded_failures=len(result.bounded_failures),
            cursor_suppressions=result.cursor_suppressions,
            mailbox_rows=result.mailbox_rows,
        )
        if result.wake is not None:
            try:
                await self.wake_dispatcher.dispatch(
                    mailbox_item_id=result.wake.mailbox_item_id,
                    session_id=result.wake.session_id,
                    now=now,
                    deadline=ExternalChannelOperationDeadline(
                        expires_at=now + datetime.timedelta(seconds=10)
                    ),
                )
            except ExternalChannelWakeDispatchUnavailable:
                self.metrics.record_wake_attempt(failed=True)
                logger.warning(
                    "External Channel post-batch Session wake is pending",
                    exc_info=True,
                    extra={"external_channel_session_id": result.wake.session_id},
                )
            else:
                self.metrics.record_wake_attempt(failed=False)
        return False


async def execute_external_channel_ingress_job(
    context: JobExecutionContext,
) -> JobPayload:
    """Resolve and drain one conversation owner through task-local dependencies."""
    payload = ExternalChannelIngressJobPayload.model_validate(context.request.payload)
    service = await context.container.solve(ExternalChannelIngressDrainService)
    await service.drain(
        owner_id=payload.owner_id,
        deadline=context.request.deadline,
    )
    return {"owner_id": payload.owner_id}


def build_external_channel_ingress_job_request(
    *,
    owner_id: str,
    drain_created_at: datetime.datetime,
    now: datetime.datetime,
) -> JobRequest:
    """Build one coalesced active-drain-lifecycle request."""
    payload = ExternalChannelIngressJobPayload(owner_id=owner_id)
    lifecycle = drain_created_at.astimezone(datetime.UTC).isoformat(
        timespec="microseconds"
    )
    return JobRequest(
        handler_key=EXTERNAL_CHANNEL_INGRESS_JOB_HANDLER_KEY,
        execution_key=f"external-channel-ingress:{owner_id}:{lifecycle}",
        deadline=now + _JOB_DURATION,
        payload=payload.model_dump(mode="json"),
    )
