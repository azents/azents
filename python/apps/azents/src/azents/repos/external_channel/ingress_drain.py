"""Completed atomic External Channel ingress lease and finalization operations."""

import dataclasses
import datetime
from typing import Annotated, Literal, assert_never

from azcommon.uuid import uuid7
from fastapi import Depends

from azents.core.enums import (
    AgentSessionStatus,
    ExternalChannelIngressAuthorityKind,
    ExternalChannelIngressProfile,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    MailboxItemKind,
    MailboxSchedulingMode,
)
from azents.core.external_channel_conversation_preparation import (
    ExternalChannelConversationPreparation,
    ExternalChannelConversationProvisioningError,
)
from azents.core.external_channel_ingestion import (
    ExternalChannelIngressFailureCategory,
    _message_idempotency_key,
    _PreparedFailure,
    _PreparedItem,
    _PreparedSuccess,
    _PreparedSuppressed,
    _projection_item,
    _retry_transition,
    _slack_presence_thread_ts,
)
from azents.core.external_channel_mailbox_payload import (
    build_external_channel_mailbox_payload,
)
from azents.core.external_channel_progress import checking_progress
from azents.core.external_channel_provider_effect import ProviderEffectPlan
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.external_channel.data import (
    ExternalChannelBinding,
    ExternalChannelConnection,
    ExternalChannelConversationPosition,
    ExternalChannelResource,
)
from azents.repos.external_channel.ingress_provisioning import (
    ExternalChannelIngressProvisioningRepository,
)
from azents.repos.external_channel.ingress_queue import (
    ExternalChannelIngressQueueRepository,
)
from azents.repos.external_channel.ingress_queue_data import (
    ExternalChannelIngressBatch,
    ExternalChannelIngressItem,
    ExternalChannelIngressLeaseClaim,
    ExternalChannelIngressOwner,
)
from azents.repos.external_channel.mailbox_ingestion import (
    ExternalChannelConfiguredBindingResult,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.external_channel.work import ExternalChannelWorkRepository
from azents.repos.mailbox.admission import MailboxAdmissionRepository
from azents.repos.mailbox.admission_data import MailboxEnqueue


@dataclasses.dataclass(frozen=True)
class IngressWakeIntent:
    """One committed mailbox identity awaiting recoverable Session wake."""

    mailbox_item_id: str
    session_id: str


@dataclasses.dataclass(frozen=True)
class IngressBatchFinalization:
    """Detached committed queue outcome and post-transaction side-effect intents."""

    stale: bool
    committed: bool
    wake: IngressWakeIntent | None
    progress_plan: ProviderEffectPlan | None
    retries: int
    bounded_failures: list[_PreparedFailure]
    cursor_suppressions: int
    mailbox_rows: int

    @classmethod
    def uncommitted(cls, *, stale: bool) -> "IngressBatchFinalization":
        return cls(
            stale=stale,
            committed=False,
            wake=None,
            progress_plan=None,
            retries=0,
            bounded_failures=[],
            cursor_suppressions=0,
            mailbox_rows=0,
        )


@dataclasses.dataclass
class ExternalChannelIngressDrainRepository:
    """Own short lease scopes and each complete queue/mailbox/position transaction."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    repository: Annotated[
        ExternalChannelRepository, Depends(ExternalChannelRepository.create)
    ]
    queue_repository: Annotated[
        ExternalChannelIngressQueueRepository,
        Depends(ExternalChannelIngressQueueRepository),
    ]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    work_repository: Annotated[
        ExternalChannelWorkRepository, Depends(ExternalChannelWorkRepository.create)
    ]
    mailbox_admission_repository: Annotated[
        MailboxAdmissionRepository, Depends(MailboxAdmissionRepository)
    ]
    provisioning_repository: Annotated[
        ExternalChannelIngressProvisioningRepository,
        Depends(ExternalChannelIngressProvisioningRepository),
    ]

    async def claim_lease(
        self,
        *,
        owner_id: str,
        lease_owner: str,
        now: datetime.datetime,
        lease_expires_at: datetime.datetime,
    ) -> ExternalChannelIngressLeaseClaim | None:
        async with self.session_manager() as session:
            claim = await self.queue_repository.claim_lease(
                session,
                owner_id=owner_id,
                lease_owner=lease_owner,
                now=now,
                lease_expires_at=lease_expires_at,
            )
            await session.write_session.commit()
            return claim

    async def claim_due_batch(
        self,
        *,
        owner_id: str,
        lease_owner: str,
        lease_generation: int,
        now: datetime.datetime,
    ) -> ExternalChannelIngressBatch | None:
        async with self.session_manager() as session:
            batch = await self.queue_repository.claim_due_batch(
                session,
                owner_id=owner_id,
                lease_owner=lease_owner,
                lease_generation=lease_generation,
                now=now,
            )
            await session.write_session.commit()
            return batch

    async def get_position(
        self, *, position_id: str
    ) -> ExternalChannelConversationPosition | None:
        async with self.session_manager() as session:
            position = await self.repository.get_conversation_position(
                session, position_id=position_id
            )
            await session.write_session.commit()
            return position

    async def record_preparation_failure(
        self,
        *,
        owner: ExternalChannelIngressOwner,
        lease_owner: str,
        lease_generation: int,
        exhausted: bool,
        next_attempt_at: datetime.datetime | None,
    ) -> bool:
        async with self.session_manager() as session:
            locked = await self.queue_repository.lock_leased_owner(
                session,
                owner_id=owner.id,
                lease_owner=lease_owner,
                lease_generation=lease_generation,
                now=datetime.datetime.now(datetime.UTC),
            )
            if locked is None:
                await session.write_session.rollback()
                return False
            if exhausted:
                await self.queue_repository.delete_owner(session, owner=locked)
            else:
                assert next_attempt_at is not None
                await self.queue_repository.schedule_preparation_retry(
                    session,
                    owner=locked,
                    next_attempt_at=next_attempt_at,
                )
            await session.write_session.commit()
            return True

    async def complete_owner(
        self,
        *,
        owner: ExternalChannelIngressOwner,
        lease_owner: str,
        lease_generation: int,
        preparation: ExternalChannelConversationPreparation,
    ) -> ExternalChannelConfiguredBindingResult | None:
        """Revalidate and mark owner ready with the complete binding/session group."""
        async with self.session_manager() as session:
            now = datetime.datetime.now(datetime.UTC)
            connection = await self.repository.lock_connection_for_routing(
                session,
                connection_id=owner.connection_id,
            )
            if connection is None:
                await session.write_session.rollback()
                raise ExternalChannelConversationProvisioningError(
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
                await session.write_session.rollback()
                return None
            first_item = await self.queue_repository.lock_first_authoritative_item(
                session,
                owner_id=locked.id,
            )
            if first_item is None:
                await session.write_session.rollback()
                return None
            completion = await self.provisioning_repository.complete_in_session(
                session,
                owner=ExternalChannelIngressOwner.model_validate(locked),
                preparation=preparation,
                initial_provider=first_item.provider,
                initial_invocation=first_item.invocation,
            )
            await self.queue_repository.mark_owner_ready(
                session,
                owner=locked,
                binding_id=completion.binding.id,
                session_id=completion.binding.agent_session_id,
                initial_title_eligible=completion.session_created,
            )
            await session.write_session.commit()
        return completion

    async def finalize_batch(
        self,
        batch: ExternalChannelIngressBatch,
        *,
        prepared: list[_PreparedItem],
        now: datetime.datetime,
    ) -> IngressBatchFinalization:
        """Atomically apply one prepared successful subset and queue transitions."""
        wake: IngressWakeIntent | None = None
        progress_plan: ProviderEffectPlan | None = None
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
                await session.write_session.rollback()
                return IngressBatchFinalization.uncommitted(stale=False)
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
                    await session.write_session.commit()
                    return IngressBatchFinalization.uncommitted(stale=True)
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
                await session.write_session.commit()
                return IngressBatchFinalization.uncommitted(stale=True)

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
            trigger_mailbox_keys: set[str] = set()
            visible_tracker_mailbox_keys: set[str] = set()
            slack_presence_by_mailbox_key: dict[str, tuple[str, str]] = {}
            target_resource: ExternalChannelResource | None = None
            target_binding: ExternalChannelBinding | None = None
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
                        target_resource = resource
                        target_binding = binding
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
                            mailbox_idempotency_key = _message_idempotency_key(
                                invocation_id=invocation_id,
                                provider_message_key=message.provider_message_key,
                            )
                            trigger_message = (
                                message.provider_message_key
                                == item.trigger_provider_message_key
                            )
                            if trigger_message:
                                trigger_mailbox_keys.add(mailbox_idempotency_key)
                            if (
                                item.provider is ExternalChannelProvider.SLACK
                                and item.invocation
                                and trigger_message
                            ):
                                visible_tracker_mailbox_keys.add(
                                    mailbox_idempotency_key
                                )
                            if (
                                item.provider is ExternalChannelProvider.SLACK
                                and trigger_message
                                and item.provider_user_id is not None
                            ):
                                slack_presence_by_mailbox_key[
                                    mailbox_idempotency_key
                                ] = (
                                    _slack_presence_thread_ts(
                                        item=item,
                                        resource=resource,
                                    ),
                                    item.provider_user_id,
                                )
                            enqueues.append(
                                MailboxEnqueue(
                                    session_id=batch.session_id,
                                    kind=MailboxItemKind.EXTERNAL_CHANNEL_MESSAGE,
                                    scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
                                    requested_model_target_label=None,
                                    requested_reasoning_effort=None,
                                    requested_enabled_execution_options=[],
                                    sender_user_id=None,
                                    order_group=order_group,
                                    order_sequence=order_sequence,
                                    content="",
                                    idempotency_key=mailbox_idempotency_key,
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
                        if (
                            failure.category
                            is ExternalChannelIngressFailureCategory.TRIGGER_MISSING
                        ):
                            bounded_failures.append(failure)
                            delete_items.append(locked_item)
                            continue
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
                else await self.mailbox_admission_repository.enqueue_many_in_session(
                    session, enqueues
                )
            )
            trigger_result = next(
                (
                    result
                    for enqueue, result in zip(enqueues, mailbox_results, strict=True)
                    if enqueue.idempotency_key in trigger_mailbox_keys
                ),
                None,
            )
            created_trigger = (
                trigger_result
                if trigger_result is not None and trigger_result.created
                else None
            )
            slack_presence = next(
                (
                    slack_presence_by_mailbox_key[enqueue.idempotency_key]
                    for enqueue, result in zip(
                        enqueues,
                        mailbox_results,
                        strict=True,
                    )
                    if result.created
                    and enqueue.idempotency_key in slack_presence_by_mailbox_key
                ),
                None,
            )
            tracker_visibility: Literal["hidden", "visible"] = (
                "visible"
                if any(
                    result.created
                    and enqueue.idempotency_key in visible_tracker_mailbox_keys
                    for enqueue, result in zip(enqueues, mailbox_results, strict=True)
                )
                else "hidden"
            )
            if created_trigger is not None:
                if target_resource is None or target_binding is None:
                    raise RuntimeError(
                        "External Channel final control ownership disappeared."
                    )
                target_session = await self.agent_session_repository.get_by_id(
                    session,
                    batch.session_id,
                )
                if target_session is None:
                    raise RuntimeError(
                        "External Channel final Session ownership disappeared."
                    )
                work = await self.work_repository.ensure_active_work(
                    session,
                    agent_id=target_session.agent_id,
                    session_id=batch.session_id,
                    binding_id=batch.binding_id,
                    desired_progress=checking_progress(),
                    tracker_visibility=tracker_visibility,
                    slack_presence_thread_ts=(
                        None if slack_presence is None else slack_presence[0]
                    ),
                    slack_presence_initiator_user_id=(
                        None if slack_presence is None else slack_presence[1]
                    ),
                )
                resumed_work = await self.work_repository.resume_from_human_input(
                    session,
                    agent_id=target_session.agent_id,
                    session_id=batch.session_id,
                    binding_id=batch.binding_id,
                )
                if resumed_work is None:
                    raise RuntimeError(
                        "External Channel Work disappeared after mailbox admission."
                    )
                progress_plan = await self.work_repository.prepare_initial_progress(
                    session,
                    agent_id=target_session.agent_id,
                    session_id=batch.session_id,
                    binding_id=batch.binding_id,
                    work_cycle_id=work.work_cycle_id,
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
                    await session.write_session.rollback()
                    await self._reset_claim(batch)
                    return IngressBatchFinalization.uncommitted(stale=True)
            if created_trigger is not None:
                admitted_session = (
                    await self.agent_session_repository.admit_input_wakeup(
                        session,
                        batch.session_id,
                    )
                )
                if admitted_session is None:
                    await session.write_session.rollback()
                    await self._reset_claim(batch)
                    return IngressBatchFinalization.uncommitted(stale=True)
                wake = IngressWakeIntent(
                    mailbox_item_id=created_trigger.mailbox_item.id,
                    session_id=batch.session_id,
                )
            elif trigger_result is not None:
                wake = IngressWakeIntent(
                    mailbox_item_id=trigger_result.mailbox_item.id,
                    session_id=batch.session_id,
                )
            await self.queue_repository.finish_batch(
                session,
                owner=drain,
                deleted_items=delete_items,
            )
            await session.write_session.commit()
        return IngressBatchFinalization(
            stale=False,
            committed=True,
            wake=wake,
            progress_plan=progress_plan,
            retries=len(retry_outcomes),
            bounded_failures=bounded_failures,
            cursor_suppressions=cursor_suppressions,
            mailbox_rows=len(mailbox_results),
        )

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
            await session.write_session.commit()

    async def release_lease(
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
            await session.write_session.commit()

    async def _ownership_current(
        self,
        session: WriteSession,
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
        target_session = await self.agent_session_repository.get_by_id(
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


async def _authority_current(
    *,
    repository: ExternalChannelRepository,
    session: ReadSession,
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
