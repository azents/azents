"""Durable Session-bound External Channel ingress admission and draining."""

import dataclasses
import datetime
import enum
import hashlib
import logging
import time
from typing import Annotated, Literal, assert_never

from azcommon.uuid import uuid7
from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentSessionStatus,
    ExternalChannelIngressAuthorityKind,
    ExternalChannelIngressProfile,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    MailboxItemKind,
    MailboxSchedulingMode,
)
from azents.job_runtime.types import (
    JobExecutionContext,
    JobPayload,
    JobRequest,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.external_channel.data import (
    ExternalChannelBinding,
    ExternalChannelConnection,
    ExternalChannelMailboxProjectionItem,
    ExternalChannelResource,
)
from azents.repos.external_channel.ingress_queue import (
    ExternalChannelIngressQueueRepository,
)
from azents.repos.external_channel.ingress_queue_data import (
    ExternalChannelIngressBatch,
    ExternalChannelIngressItem,
    ExternalChannelIngressOwner,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.conversation import (
    ExternalChannelHistoryCredentialsInvalid,
    ExternalChannelHistoryDeadlineExceeded,
    ExternalChannelHistoryError,
    ExternalChannelHistoryMalformed,
    ExternalChannelHistoryPermissionDenied,
    ExternalChannelHistoryPositionInvalid,
    ExternalChannelHistoryRange,
    ExternalChannelHistoryRangeIncomplete,
    ExternalChannelHistoryRateLimited,
    ExternalChannelHistoryResourceUnavailable,
    ExternalChannelHistoryTemporaryFailure,
    ExternalChannelHistoryTriggerMissing,
    ExternalChannelOperationDeadline,
)
from azents.services.external_channel.ingestion import (
    ExternalChannelCanonicalHistoryMessage,
    ExternalChannelIngestionOutcome,
    ExternalChannelIngestionOutcomeKind,
    ExternalChannelIngestionReason,
    ExternalChannelTriggerLocator,
    ExternalChannelWakeDispatchUnavailable,
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
from azents.services.external_channel.provider_effect import ProviderEffectPlan
from azents.services.mailbox import (
    MailboxEnqueue,
    MailboxService,
    build_external_channel_mailbox_payload,
)

logger = logging.getLogger(__name__)

EXTERNAL_CHANNEL_INGRESS_JOB_HANDLER_KEY = "external_channel.ingress"
_LEASE_DURATION = datetime.timedelta(minutes=10)
_JOB_DURATION = datetime.timedelta(minutes=10)
_PROVIDER_OPERATION_DURATION = datetime.timedelta(minutes=2)
_MAX_COORDINATION_RETRIES = 4
_MAX_PROVIDER_ATTEMPTS = 5
_MAX_ITEM_AGE = datetime.timedelta(minutes=5)
_DEFAULT_RETRY_DELAYS = (2, 10, 30, 60)


class ExternalChannelIngressFailureCategory(enum.StrEnum):
    """Closed content-free provider failure categories."""

    CREDENTIALS_INVALID = "credentials_invalid"
    PERMISSION_DENIED = "permission_denied"
    RESOURCE_UNAVAILABLE = "resource_unavailable"
    RATE_LIMITED = "rate_limited"
    TEMPORARY_FAILURE = "temporary_failure"
    MALFORMED_RESPONSE = "malformed_response"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    TRIGGER_MISSING = "trigger_missing"
    RANGE_INCOMPLETE = "range_incomplete"
    POSITION_INVALID = "position_invalid"
    OWNERSHIP_STALE = "ownership_stale"


@dataclasses.dataclass(frozen=True)
class _PreparedSuccess:
    """Provider content prepared against one durable cursor snapshot."""

    item: ExternalChannelIngressItem
    durable_cursor: str | None
    history: ExternalChannelHistoryRange[ExternalChannelCanonicalHistoryMessage]


@dataclasses.dataclass(frozen=True)
class _PreparedSuppressed:
    """One queued trigger already covered by the tentative cursor."""

    item: ExternalChannelIngressItem
    durable_cursor: str | None


@dataclasses.dataclass(frozen=True)
class _PreparedFailure:
    """One safe provider failure awaiting transactional retry or deletion."""

    item: ExternalChannelIngressItem
    durable_cursor: str | None
    category: ExternalChannelIngressFailureCategory
    retryable: bool
    retry_after_seconds: int | None


type _PreparedItem = _PreparedSuccess | _PreparedSuppressed | _PreparedFailure


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

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    repository: Annotated[
        ExternalChannelRepository,
        Depends(ExternalChannelRepository.create),
    ]
    queue_repository: Annotated[
        ExternalChannelIngressQueueRepository,
        Depends(ExternalChannelIngressQueueRepository),
    ]
    agent_session_repository: Annotated[
        AgentSessionRepository,
        Depends(AgentSessionRepository),
    ]
    provider_policies: Annotated[
        ExternalChannelIngressProviderPolicyRegistry,
        Depends(ExternalChannelIngressProviderPolicyRegistry),
    ]
    provisioning_service: Annotated[
        ExternalChannelIngressProvisioningService,
        Depends(ExternalChannelIngressProvisioningService),
    ]
    mailbox_service: Annotated[MailboxService, Depends(MailboxService)]
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
        async with self.session_manager() as session:
            claim = await self.queue_repository.claim_lease(
                session,
                owner_id=owner_id,
                lease_owner=lease_owner,
                now=now,
                lease_expires_at=min(deadline, now + _LEASE_DURATION),
            )
            await session.commit()
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
            async with self.session_manager() as session:
                batch = await self.queue_repository.claim_due_batch(
                    session,
                    owner_id=owner_id,
                    lease_owner=lease_owner,
                    lease_generation=claim.owner.lease_generation,
                    now=now,
                )
                await session.commit()
            if batch is None:
                async with self.session_manager() as session:
                    await self.queue_repository.release_lease(
                        session,
                        owner_id=owner_id,
                        lease_owner=lease_owner,
                        lease_generation=claim.owner.lease_generation,
                    )
                    await session.commit()
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
                    await self._release_lease(
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
            async with self.session_manager() as session:
                now = datetime.datetime.now(datetime.UTC)
                connection = await self.repository.lock_connection_for_routing(
                    session,
                    connection_id=owner.connection_id,
                )
                if connection is None:
                    await session.rollback()
                    raise ExternalChannelIngressProvisioningError(
                        category="ownership_stale",
                        retryable=False,
                    )
                locked = await self.queue_repository.lock_leased_owner(
                    session,
                    owner_id=owner.id,
                    lease_owner=lease_owner,
                    lease_generation=lease_generation,
                    now=now,
                )
                if locked is None:
                    await session.rollback()
                    return False
                completion = await self.provisioning_service.complete(
                    session,
                    owner=ExternalChannelIngressOwner.model_validate(locked),
                    preparation=preparation,
                )
                await self.queue_repository.mark_owner_ready(
                    session,
                    owner=locked,
                    binding_id=completion.binding.id,
                    session_id=completion.binding.agent_session_id,
                    initial_title_eligible=completion.session_created,
                )
                await session.commit()
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
        async with self.session_manager() as session:
            locked = await self.queue_repository.lock_leased_owner(
                session,
                owner_id=owner.id,
                lease_owner=lease_owner,
                lease_generation=lease_generation,
                now=datetime.datetime.now(datetime.UTC),
            )
            if locked is None:
                await session.rollback()
                return False
            if exhausted:
                logger.warning(
                    "External Channel ingress owner exceeded its active lifecycle",
                    extra={
                        "external_channel_ingress_owner_id": owner.id,
                        "external_channel_failure_category": error.category,
                        "external_channel_attempt_count": (
                            owner.preparation_attempt_count + 1
                        ),
                        "external_channel_age_seconds": max(
                            0,
                            int((now - owner.created_at).total_seconds()),
                        ),
                    },
                )
                await self.queue_repository.delete_owner(session, owner=locked)
            else:
                delay_index = min(
                    owner.preparation_attempt_count,
                    len(_DEFAULT_RETRY_DELAYS) - 1,
                )
                await self.queue_repository.schedule_preparation_retry(
                    session,
                    owner=locked,
                    next_attempt_at=now
                    + datetime.timedelta(seconds=_DEFAULT_RETRY_DELAYS[delay_index]),
                )
            await session.commit()
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
                async with self.session_manager() as session:
                    position = await self.repository.get_conversation_position(
                        session,
                        position_id=item.conversation_position_id,
                    )
                    await session.commit()
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
        self,
        batch: ExternalChannelIngressBatch,
        *,
        prepared: list[_PreparedItem],
    ) -> bool:
        """Atomically apply one prepared successful subset and queue transitions."""
        now = datetime.datetime.now(datetime.UTC)
        wake: tuple[str, str] | None = None
        async with self.session_manager() as session:
            connections = {
                connection_id: await self.repository.lock_connection_for_routing(
                    session,
                    connection_id=connection_id,
                )
                for connection_id in sorted(
                    {item.connection_id for item in batch.items}
                )
            }
            locked = await self.queue_repository.lock_claimed_batch(
                session,
                claim=batch,
                now=now,
            )
            if locked is None:
                await session.rollback()
                return False
            drain, items = locked
            positions = {}
            for position_id in sorted(
                {item.conversation_position_id for item in batch.items}
            ):
                position = await self.repository.lock_conversation_position(
                    session,
                    position_id=position_id,
                )
                if position is None:
                    await self.queue_repository.reset_batch_for_coordination(
                        session,
                        owner=drain,
                        items=items,
                    )
                    await session.commit()
                    return True
                positions[position_id] = position
            initial_cursors = {
                outcome.item.conversation_position_id: outcome.durable_cursor
                for outcome in prepared
            }
            if any(
                positions[position_id].read_through_position != initial_cursor
                for position_id, initial_cursor in initial_cursors.items()
            ):
                await self.queue_repository.reset_batch_for_coordination(
                    session,
                    owner=drain,
                    items=items,
                )
                await session.commit()
                return True

            invalid_positions: set[str] = set()
            locked_by_id = {item.id: item for item in items}
            for item in batch.items:
                if not await self._ownership_current(
                    session,
                    item=item,
                    batch=batch,
                    connection=connections[item.connection_id],
                    now=now,
                ):
                    invalid_positions.add(item.conversation_position_id)

            correlations = {}
            for position_id in positions:
                correlations[
                    position_id
                ] = await self.queue_repository.list_active_correlations(
                    session,
                    connection_id=next(
                        item.connection_id
                        for item in batch.items
                        if item.conversation_position_id == position_id
                    ),
                    conversation_position_id=position_id,
                )

            order_group = uuid7().hex
            order_sequence = 0
            enqueues: list[MailboxEnqueue] = []
            successful_positions = {
                outcome.item.conversation_position_id: outcome.history.trigger_position
                for outcome in prepared
                if isinstance(outcome, _PreparedSuccess)
                and outcome.item.conversation_position_id not in invalid_positions
            }
            retry_outcomes: list[_PreparedFailure] = []
            delete_items = []
            bounded_failures: list[_PreparedFailure] = []
            cursor_suppressions = 0
            for outcome in prepared:
                item = outcome.item
                locked_item = locked_by_id[item.id]
                effective_outcome = outcome
                if item.conversation_position_id in invalid_positions:
                    effective_outcome = _PreparedFailure(
                        item=item,
                        durable_cursor=outcome.durable_cursor,
                        category=ExternalChannelIngressFailureCategory.OWNERSHIP_STALE,
                        retryable=False,
                        retry_after_seconds=None,
                    )
                match effective_outcome:
                    case _PreparedSuccess() as success:
                        resource = await self.repository.lock_resource(
                            session,
                            resource_id=batch.target_resource_id,
                        )
                        binding = await self.repository.lock_binding(
                            session,
                            binding_id=batch.binding_id,
                        )
                        if resource is None or binding is None:
                            raise RuntimeError(
                                "External Channel final ownership disappeared."
                            )
                        for message_index, message in enumerate(
                            success.history.messages
                        ):
                            correlation = correlations[
                                item.conversation_position_id
                            ].get(message.provider_message_key)
                            prompt_role: Literal["context", "invocation"] = (
                                "invocation" if correlation is not None else "context"
                            )
                            invocation_id = (
                                item.invocation_id
                                if correlation is None
                                else correlation.invocation_id
                            )
                            projection = _projection_item(
                                item=item,
                                resource=resource,
                                binding=binding,
                                message=message,
                                invocation_id=invocation_id,
                                principal_id=(
                                    None
                                    if correlation is None
                                    else correlation.principal_id
                                ),
                                prompt_role=prompt_role,
                                context_omitted=(
                                    message_index == 0
                                    and success.history.context_omitted
                                ),
                                sequence=order_sequence,
                            )
                            enqueues.append(
                                MailboxEnqueue(
                                    session_id=batch.session_id,
                                    kind=MailboxItemKind.EXTERNAL_CHANNEL_MESSAGE,
                                    scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
                                    requested_model_target_label=None,
                                    requested_reasoning_effort=None,
                                    sender_user_id=None,
                                    order_group=order_group,
                                    order_sequence=order_sequence,
                                    content="",
                                    idempotency_key=_message_idempotency_key(
                                        invocation_id=invocation_id,
                                        provider_message_key=(
                                            message.provider_message_key
                                        ),
                                    ),
                                    metadata={},
                                    attachments=[],
                                    file_parts=[],
                                    action=None,
                                    payload=build_external_channel_mailbox_payload(
                                        projection,
                                        context_omitted=(
                                            message_index == 0
                                            and success.history.context_omitted
                                        ),
                                        initial_title_eligible=(
                                            item.initial_title_eligible
                                            and message.provider_message_key
                                            == item.trigger_provider_message_key
                                            and prompt_role == "invocation"
                                        ),
                                    ),
                                )
                            )
                            order_sequence += 1
                        delete_items.append(locked_item)
                    case _PreparedSuppressed():
                        cursor_suppressions += 1
                        delete_items.append(locked_item)
                    case _PreparedFailure() as failure:
                        covered_position = successful_positions.get(
                            item.conversation_position_id
                        )
                        if (
                            covered_position is not None
                            and item.trigger_position <= covered_position
                        ):
                            cursor_suppressions += 1
                            delete_items.append(locked_item)
                            continue
                        transition = _retry_transition(failure, now=now)
                        if transition is None:
                            bounded_failures.append(failure)
                            delete_items.append(locked_item)
                        else:
                            retry_outcomes.append(failure)
                            await self.queue_repository.move_to_retry_tail(
                                session,
                                item=locked_item,
                                next_attempt_at=transition,
                            )
                    case _:
                        assert_never(outcome)

            mailbox_results = (
                []
                if not enqueues
                else await self.mailbox_service.enqueue_many(session, enqueues)
            )
            for position_id, final_position in successful_positions.items():
                advanced = (
                    await self.repository.advance_conversation_position_if_current(
                        session,
                        position_id=position_id,
                        expected_read_through_position=initial_cursors[position_id],
                        read_through_position=final_position,
                    )
                )
                if not advanced:
                    await session.rollback()
                    await self._reset_claim(batch)
                    return True
            if mailbox_results:
                await self.agent_session_repository.mark_running_for_input_wakeup(
                    session,
                    batch.session_id,
                )
                wake = (mailbox_results[0].mailbox_item.id, batch.session_id)
            for failure in bounded_failures:
                logger.warning(
                    "External Channel ingress item exceeded its active lifecycle",
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
            await self.queue_repository.finish_batch(
                session,
                owner=drain,
                deleted_items=delete_items,
            )
            await session.commit()
        self.metrics.record_finalization(
            retries=len(retry_outcomes),
            bounded_failures=len(bounded_failures),
            cursor_suppressions=cursor_suppressions,
            mailbox_rows=len(mailbox_results),
        )
        if wake is not None:
            try:
                await self.wake_dispatcher.dispatch(
                    mailbox_item_id=wake[0],
                    session_id=wake[1],
                    now=now,
                    deadline=ExternalChannelOperationDeadline(
                        expires_at=now + datetime.timedelta(seconds=10)
                    ),
                )
            except ExternalChannelWakeDispatchUnavailable:
                self.metrics.record_wake_attempt(failed=True)
                logger.warning(
                    "External Channel post-batch Session wake is pending",
                    extra={"external_channel_session_id": wake[1]},
                )
            else:
                self.metrics.record_wake_attempt(failed=False)
        return False

    async def _reset_claim(self, batch: ExternalChannelIngressBatch) -> None:
        """Return one still-owned batch to pending after a late cursor conflict."""
        async with self.session_manager() as session:
            locked = await self.queue_repository.lock_claimed_batch(
                session,
                claim=batch,
                now=datetime.datetime.now(datetime.UTC),
            )
            if locked is not None:
                owner, items = locked
                await self.queue_repository.reset_batch_for_coordination(
                    session,
                    owner=owner,
                    items=items,
                )
            await session.commit()

    async def _release_lease(
        self,
        *,
        owner_id: str,
        lease_owner: str,
        lease_generation: int,
    ) -> None:
        """Release one current lease after bounded coordination exhaustion."""
        async with self.session_manager() as session:
            await self.queue_repository.release_lease(
                session,
                owner_id=owner_id,
                lease_owner=lease_owner,
                lease_generation=lease_generation,
            )
            await session.commit()

    async def _ownership_current(
        self,
        session: AsyncSession,
        *,
        item: ExternalChannelIngressItem,
        batch: ExternalChannelIngressBatch,
        connection: ExternalChannelConnection | None,
        now: datetime.datetime,
    ) -> bool:
        """Revalidate technical authority without rerouting retained triggers."""
        if (
            connection is None
            or connection.provider is not item.provider
            or connection.provider_tenant_id != item.provider_tenant_id
            or connection.ingress_profile is not item.ingress_profile
            or connection.configuration_generation != item.configuration_generation
            or not await _authority_current(
                repository=self.repository,
                session=session,
                connection=connection,
                authority_kind=item.authority_kind,
                ingress_profile=item.ingress_profile,
                lease_owner=item.authority_lease_owner,
                lease_generation=item.authority_lease_generation,
                now=now,
            )
        ):
            return False
        source_resource = await self.repository.lock_resource(
            session,
            resource_id=item.source_resource_id,
        )
        target_resource = await self.repository.lock_resource(
            session,
            resource_id=batch.target_resource_id,
        )
        binding = await self.repository.lock_binding(
            session,
            binding_id=batch.binding_id,
        )
        target_session = await self.agent_session_repository.lock_by_id(
            session,
            batch.session_id,
        )
        return (
            source_resource is not None
            and source_resource.connection_id == item.connection_id
            and source_resource.status is ExternalChannelResourceStatus.ACTIVE
            and target_resource is not None
            and target_resource.connection_id == item.connection_id
            and target_resource.status is ExternalChannelResourceStatus.ACTIVE
            and binding is not None
            and binding.resource_id == batch.target_resource_id
            and binding.agent_session_id == batch.session_id
            and binding.disconnected_at is None
            and target_session is not None
            and target_session.status is AgentSessionStatus.ACTIVE
            and target_session.stop_requested_at is None
        )


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


async def _authority_current(
    *,
    repository: ExternalChannelRepository,
    session: AsyncSession,
    connection: ExternalChannelConnection,
    authority_kind: ExternalChannelIngressAuthorityKind,
    ingress_profile: ExternalChannelIngressProfile,
    lease_owner: str | None,
    lease_generation: int | None,
    now: datetime.datetime,
) -> bool:
    """Validate one retained transport authority fence."""
    if authority_kind is ExternalChannelIngressAuthorityKind.CONFIGURATION:
        return ingress_profile is ExternalChannelIngressProfile.SLACK_HTTP
    if authority_kind is ExternalChannelIngressAuthorityKind.DURABLE_REPLAY:
        return True
    if lease_owner is None:
        return False
    if ingress_profile is ExternalChannelIngressProfile.SLACK_SOCKET:
        return (
            lease_generation is None
            and connection.socket_lease_owner == lease_owner
            and connection.socket_lease_until is not None
            and connection.socket_lease_until >= now
        )
    if (
        ingress_profile is ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP
        and lease_generation is not None
    ):
        return (
            await repository.get_owned_discord_gateway_configuration(
                session,
                connection_id=connection.id,
                lease_owner=lease_owner,
                lease_generation=lease_generation,
                now=now,
            )
            is not None
        )
    return False


def _provider_failure(
    *,
    item: ExternalChannelIngressItem,
    durable_cursor: str | None,
    error: ExternalChannelHistoryError,
) -> _PreparedFailure:
    """Classify a provider exception without retaining its raw message."""
    retry_after_seconds = None
    match error:
        case ExternalChannelHistoryRateLimited():
            category = ExternalChannelIngressFailureCategory.RATE_LIMITED
            retryable = True
            retry_after_seconds = error.retry_after_seconds
        case ExternalChannelHistoryTemporaryFailure():
            category = ExternalChannelIngressFailureCategory.TEMPORARY_FAILURE
            retryable = True
        case ExternalChannelHistoryDeadlineExceeded():
            category = ExternalChannelIngressFailureCategory.DEADLINE_EXCEEDED
            retryable = True
        case ExternalChannelHistoryCredentialsInvalid():
            category = ExternalChannelIngressFailureCategory.CREDENTIALS_INVALID
            retryable = False
        case ExternalChannelHistoryPermissionDenied():
            category = ExternalChannelIngressFailureCategory.PERMISSION_DENIED
            retryable = False
        case ExternalChannelHistoryResourceUnavailable():
            category = ExternalChannelIngressFailureCategory.RESOURCE_UNAVAILABLE
            retryable = False
        case ExternalChannelHistoryMalformed():
            category = ExternalChannelIngressFailureCategory.MALFORMED_RESPONSE
            retryable = False
        case ExternalChannelHistoryTriggerMissing():
            category = ExternalChannelIngressFailureCategory.TRIGGER_MISSING
            retryable = False
        case ExternalChannelHistoryRangeIncomplete():
            category = ExternalChannelIngressFailureCategory.RANGE_INCOMPLETE
            retryable = False
        case ExternalChannelHistoryPositionInvalid():
            category = ExternalChannelIngressFailureCategory.POSITION_INVALID
            retryable = False
        case _:
            raise error
    return _PreparedFailure(
        item=item,
        durable_cursor=durable_cursor,
        category=category,
        retryable=retryable,
        retry_after_seconds=retry_after_seconds,
    )


def _retry_transition(
    failure: _PreparedFailure,
    *,
    now: datetime.datetime,
) -> datetime.datetime | None:
    """Return a bounded retry time or classify the item for deletion."""
    item = failure.item
    if not failure.retryable or item.attempt_count >= _MAX_PROVIDER_ATTEMPTS:
        return None
    age = now - item.created_at
    remaining = _MAX_ITEM_AGE - age
    if remaining <= datetime.timedelta(0):
        return None
    if failure.retry_after_seconds is not None:
        delay = datetime.timedelta(seconds=failure.retry_after_seconds)
    else:
        base = _DEFAULT_RETRY_DELAYS[item.attempt_count - 1]
        digest = hashlib.sha256(f"{item.id}:{item.attempt_count}".encode()).digest()
        jitter = 0.9 + (digest[0] / 2550)
        delay = datetime.timedelta(seconds=base * jitter)
    if delay > remaining:
        return None
    return now + delay


def _locator(item: ExternalChannelIngressItem) -> ExternalChannelTriggerLocator:
    """Rebuild one credential-free provider locator from active queue state."""
    return ExternalChannelTriggerLocator(
        connection_id=item.connection_id,
        provider=item.provider,
        provider_event_type=item.provider_event_type,
        provider_tenant_id=item.provider_tenant_id,
        provider_channel_id=item.provider_channel_id,
        provider_parent_channel_id=item.provider_parent_channel_id,
        provider_thread_key=item.provider_thread_key,
        delivery_thread_key=item.delivery_thread_key,
        provider_resource_key=item.provider_resource_key,
        trigger_provider_message_key=item.trigger_provider_message_key,
        trigger_provider_message_id=item.trigger_provider_message_id,
        trigger_position=item.trigger_position,
        provider_user_id=item.provider_user_id,
        invocation=item.invocation,
    )


def _projection_item(
    *,
    item: ExternalChannelIngressItem,
    resource: ExternalChannelResource,
    binding: ExternalChannelBinding,
    message: ExternalChannelCanonicalHistoryMessage,
    invocation_id: str,
    principal_id: str | None,
    prompt_role: Literal["context", "invocation"],
    context_omitted: bool,
    sequence: int,
) -> ExternalChannelMailboxProjectionItem:
    """Build one canonical single-message mailbox projection."""
    return ExternalChannelMailboxProjectionItem(
        invocation_id=invocation_id,
        binding_id=binding.id,
        trigger_provider_message_key=item.trigger_provider_message_key,
        prompt_role=prompt_role,
        context_omitted=context_omitted,
        sequence=sequence,
        revision_kind=message.revision_kind,
        body=message.normalized_body,
        attachment_metadata=message.attachment_metadata,
        reference_mappings=message.reference_mappings,
        resource_id=resource.id,
        provider_resource_key=resource.provider_resource_key,
        resource_type=resource.resource_type,
        resource_labels=resource.labels,
        provider=item.provider,
        provider_tenant_id=item.provider_tenant_id,
        provider_message_key=message.provider_message_key,
        provider_position=message.provider_position,
        principal_id=principal_id,
        provider_user_id=message.provider_user_id,
        sender_display_name=message.sender_display_name,
        author_type=message.author_type,
        provider_created_at=message.provider_created_at,
        provider_updated_at=message.provider_updated_at,
        original_url=message.original_url,
    )


def _invocation_id(
    *,
    connection_id: str,
    position_id: str,
    provider_message_key: str,
    trigger_position: str,
) -> str:
    """Return one stable ingress invocation identity."""
    digest = hashlib.sha256(
        "\0".join(
            (
                connection_id,
                position_id,
                provider_message_key,
                trigger_position,
            )
        ).encode()
    ).hexdigest()
    return f"external-channel:{digest}"


def _message_idempotency_key(
    *,
    invocation_id: str,
    provider_message_key: str,
) -> str:
    """Return one stable provider-message mailbox identity."""
    digest = hashlib.md5(  # noqa: S324 - non-cryptographic durable identity only
        f"{len(invocation_id)}:{invocation_id}{provider_message_key}".encode(),
        usedforsecurity=False,
    ).hexdigest()
    return f"external-channel-message:{digest}"


def _outcome(
    kind: ExternalChannelIngestionOutcomeKind,
    reason: ExternalChannelIngestionReason,
) -> ExternalChannelIngestionOutcome:
    """Build one content-free callback outcome."""
    return ExternalChannelIngestionOutcome(
        kind=kind,
        reason=reason,
        mailbox_item_id=None,
        control_plans=(),
        connection_id=None,
    )
