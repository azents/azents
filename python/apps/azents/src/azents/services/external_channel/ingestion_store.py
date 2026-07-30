"""Database-backed synchronous External Channel ingestion store."""

import dataclasses
import datetime
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.enums import (
    AgentLifecycleStatus,
    AgentSessionStartReason,
    ExternalChannelAccessRequestStatus,
    ExternalChannelAppMode,
    ExternalChannelBindingActivationStatus,
    ExternalChannelBindingStatus,
    ExternalChannelConversationAdmissionOrigin,
    ExternalChannelConversationAdmissionStatus,
    ExternalChannelConversationScopeKind,
    ExternalChannelDeliveryOperation,
    ExternalChannelDeliveryOriginType,
    ExternalChannelDeliveryStatus,
    ExternalChannelHydrationStatus,
    ExternalChannelIngressProfile,
    ExternalChannelInvocationWakeDispatchStatus,
    ExternalChannelMessageLifecycle,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
    MailboxItemKind,
    MailboxSchedulingMode,
)
from azents.core.external_channel_progress import checking_progress
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSessionCreate
from azents.repos.external_channel.data import (
    ExternalChannelAccessRequestCreate,
    ExternalChannelAgentRoute,
    ExternalChannelBinding,
    ExternalChannelBindingCreate,
    ExternalChannelConnection,
    ExternalChannelConversationAdmission,
    ExternalChannelConversationAdmissionCreate,
    ExternalChannelConversationPosition,
    ExternalChannelConversationPositionCreate,
    ExternalChannelDeliveryAttemptCreate,
    ExternalChannelInvocationBatchCreate,
    ExternalChannelInvocationBatchItemCreate,
    ExternalChannelMessage,
    ExternalChannelMessageCreate,
    ExternalChannelMessageRevisionCreate,
    ExternalChannelPrincipalCreate,
    ExternalChannelResource,
    ExternalChannelResourceCreate,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.conversation import ExternalChannelHistoryRange
from azents.services.external_channel.discord_selector_scope import (
    build_discord_selector_custom_id,
)
from azents.services.external_channel.ingestion import (
    ExternalChannelCanonicalHistoryMessage,
    ExternalChannelIngestionAcceptance,
    ExternalChannelIngestionOperation,
    ExternalChannelIngestionOutcome,
    ExternalChannelIngestionOutcomeKind,
    ExternalChannelIngestionPreparation,
    ExternalChannelIngestionReason,
    ExternalChannelIngestionRequest,
    ExternalChannelIngressAuthorityKind,
)
from azents.services.mailbox import (
    MailboxEnqueue,
    MailboxService,
    build_external_channel_mailbox_payload,
)
from azents.services.root_agent_session_creation import (
    RootAgentSessionCreationService,
)
from azents.services.root_agent_session_creation.data import (
    AgentDefaultRootWorkspaceIntent,
)

_ACCESS_REQUEST_AGE = datetime.timedelta(days=7)


@dataclasses.dataclass(frozen=True)
class _ResolvedRouting:
    """Locked routing state for one final acceptance transaction."""

    resource: ExternalChannelResource
    route: ExternalChannelAgentRoute
    binding: ExternalChannelBinding | None
    admission: ExternalChannelConversationAdmission | None


@dataclasses.dataclass(frozen=True)
class _PendingSelection:
    """Locked route-selection state for one unbound conversation."""

    resource: ExternalChannelResource
    admission: ExternalChannelConversationAdmission


@dataclasses.dataclass(frozen=True)
class _PersistedMessage:
    """Canonical message and immutable accepted revision identity."""

    message: ExternalChannelMessage
    revision_id: str


@dataclasses.dataclass(frozen=True)
class _ExistingBatch:
    """Existing accepted batch and its routing Session."""

    batch_id: str
    session_id: str


@dataclasses.dataclass
class ExternalChannelDatabaseIngestionStore:
    """Persist synchronous ingestion through short caller-owned transactions."""

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    repository: Annotated[
        ExternalChannelRepository,
        Depends(ExternalChannelRepository),
    ]
    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    agent_session_repository: Annotated[
        AgentSessionRepository,
        Depends(AgentSessionRepository),
    ]
    root_agent_session_creation_service: Annotated[
        RootAgentSessionCreationService,
        Depends(RootAgentSessionCreationService),
    ]
    mailbox_service: Annotated[MailboxService, Depends(MailboxService)]
    config: Annotated[Config, Depends(get_config)]

    async def prepare(
        self,
        *,
        request: ExternalChannelIngestionRequest,
    ) -> ExternalChannelIngestionPreparation:
        """Commit only metadata required before provider-history retrieval."""
        now = _utc_now()
        async with self.session_manager() as session:
            connection = await self._lock_authority(session, request=request, now=now)
            if connection is None:
                return _immediate(
                    ExternalChannelIngestionOutcomeKind.TERMINAL_REJECTION,
                    ExternalChannelIngestionReason.INGRESS_AUTHORITY_STALE,
                )
            position = await self._prepare_position(session, request=request)
            if position is None:
                return _immediate(
                    ExternalChannelIngestionOutcomeKind.TERMINAL_REJECTION,
                    ExternalChannelIngestionReason.INVALID_REPLAY_BOUNDARY,
                )
            resource = await self.repository.get_resource_by_provider_key(
                session,
                connection_id=request.locator.connection_id,
                provider_resource_key=request.locator.provider_resource_key,
            )
            metadata_source_created = resource is None
            if request.replay_boundary is not None and (
                resource is None
                or not await self._replay_source_matches(
                    session,
                    request=request,
                    resource=resource,
                )
            ):
                await session.commit()
                return _immediate(
                    ExternalChannelIngestionOutcomeKind.TERMINAL_REJECTION,
                    ExternalChannelIngestionReason.INVALID_REPLAY_BOUNDARY,
                )
            if resource is None:
                if not request.locator.invocation:
                    await session.commit()
                    return _immediate(
                        ExternalChannelIngestionOutcomeKind.IGNORED,
                        ExternalChannelIngestionReason.NOT_AN_INVOCATION,
                    )
                resource = await self._create_metadata_source(
                    session,
                    request=request,
                    position=position,
                    now=now,
                )
            binding = await self.repository.get_active_binding_by_resource(
                session,
                resource_id=resource.id,
            )
            existing = await self._existing_batch(
                session,
                resource=resource,
                binding=binding,
                request=request,
            )
            if existing is not None:
                await session.commit()
                return ExternalChannelIngestionPreparation(
                    position_id=None,
                    exclusive_start_position=None,
                    immediate_outcome=ExternalChannelIngestionOutcome(
                        kind=ExternalChannelIngestionOutcomeKind.DUPLICATE,
                        reason=ExternalChannelIngestionReason.DUPLICATE,
                        batch_id=existing.batch_id,
                        control_delivery_attempt_id=None,
                        connection_id=None,
                    ),
                    wake_batch_id=existing.batch_id,
                    wake_session_id=existing.session_id,
                )
            if (
                position.read_through_position is not None
                and request.locator.trigger_position <= position.read_through_position
                and request.operation
                is ExternalChannelIngestionOperation.CURRENT_TRIGGER
            ):
                await session.commit()
                return _immediate(
                    ExternalChannelIngestionOutcomeKind.IGNORED,
                    ExternalChannelIngestionReason.DUPLICATE,
                )
            admission = (
                None
                if binding is not None
                else await self.repository.get_open_conversation_admission(
                    session,
                    resource_id=resource.id,
                )
            )
            if (
                admission is not None
                and admission.status
                is ExternalChannelConversationAdmissionStatus.PENDING_SELECTION
                and request.selected_route_id is None
                and not metadata_source_created
            ):
                await session.commit()
                return _immediate(
                    ExternalChannelIngestionOutcomeKind.AWAITING_SELECTION,
                    ExternalChannelIngestionReason.SELECTION_REQUIRED,
                )
            start = position.read_through_position
            boundary = request.replay_boundary
            if (
                boundary is not None
                and start is not None
                and start >= boundary.trigger_position
            ):
                start = boundary.range_start_position
            await session.commit()
            return ExternalChannelIngestionPreparation(
                position_id=position.id,
                exclusive_start_position=start,
                immediate_outcome=None,
                wake_batch_id=None,
                wake_session_id=None,
            )

    async def accept(
        self,
        *,
        request: ExternalChannelIngestionRequest,
        preparation: ExternalChannelIngestionPreparation,
        history: ExternalChannelHistoryRange[ExternalChannelCanonicalHistoryMessage],
    ) -> ExternalChannelIngestionAcceptance:
        """Apply canonical history, input, wake intent, and position atomically."""
        now = _utc_now()
        async with self.session_manager() as session:
            connection = await self._lock_authority(session, request=request, now=now)
            if connection is None:
                return _rejected(ExternalChannelIngestionReason.INGRESS_AUTHORITY_STALE)
            if preparation.position_id is None:
                raise ValueError("External Channel ingestion position is unavailable.")
            position = await self.repository.lock_conversation_position(
                session,
                position_id=preparation.position_id,
            )
            if position is None or position.connection_id != connection.id:
                return _rejected(
                    ExternalChannelIngestionReason.CONVERSATION_UNAVAILABLE
                )
            replay_after_position = (
                request.replay_boundary is not None
                and position.read_through_position is not None
                and position.read_through_position
                >= request.replay_boundary.trigger_position
            )
            if (
                not replay_after_position
                and position.read_through_position
                != preparation.exclusive_start_position
            ):
                await session.rollback()
                return _position_mismatch()
            trigger = history.trigger
            if (
                trigger.provider_message_key
                != request.locator.trigger_provider_message_key
                or trigger.provider_position != request.locator.trigger_position
            ):
                return _rejected(ExternalChannelIngestionReason.INVALID_REPLAY_BOUNDARY)
            pending_selection = await self._lock_pending_selection(
                session,
                request=request,
                position=position,
            )
            if pending_selection is not None:
                if (
                    trigger.author_type is not ExternalChannelPrincipalAuthorType.HUMAN
                    or trigger.provider_user_id is None
                ):
                    return await self._commit_ignored_position(
                        session,
                        request=request,
                        position=position,
                        replay_after_position=replay_after_position,
                        reason=ExternalChannelIngestionReason.AUTHOR_NOT_ELIGIBLE,
                    )
                await self._persist_history_message(
                    session,
                    request=request,
                    resource=pending_selection.resource,
                    message=trigger,
                )
                control_delivery_attempt_id = (
                    await self._create_selector_control_intent(
                        session,
                        request=request,
                        admission=pending_selection.admission,
                    )
                )
                await session.commit()
                return ExternalChannelIngestionAcceptance(
                    status="awaiting_selection",
                    reason=ExternalChannelIngestionReason.SELECTION_REQUIRED,
                    batch_id=None,
                    session_id=None,
                    control_delivery_attempt_id=control_delivery_attempt_id,
                    connection_id=(
                        connection.id
                        if control_delivery_attempt_id is not None
                        else None
                    ),
                )
            routing = await self._lock_routing(
                session,
                request=request,
            )
            if routing is None:
                return _rejected(
                    ExternalChannelIngestionReason.CONVERSATION_UNAVAILABLE
                )
            if (
                trigger.author_type is not ExternalChannelPrincipalAuthorType.HUMAN
                or trigger.provider_user_id is None
            ):
                return await self._commit_ignored_position(
                    session,
                    request=request,
                    position=position,
                    replay_after_position=replay_after_position,
                    reason=ExternalChannelIngestionReason.AUTHOR_NOT_ELIGIBLE,
                )
            if routing.binding is None and not request.locator.invocation:
                return await self._commit_ignored_position(
                    session,
                    request=request,
                    position=position,
                    replay_after_position=replay_after_position,
                    reason=ExternalChannelIngestionReason.NOT_AN_INVOCATION,
                )
            persisted_source = await self._persist_history_message(
                session,
                request=request,
                resource=routing.resource,
                message=trigger,
            )
            source_message = persisted_source.message
            trigger_principal_id = source_message.principal_id
            if trigger_principal_id is None:
                raise RuntimeError("External Channel trigger principal disappeared.")
            agent_id = routing.route.require_active_agent_id()
            if (
                await self.repository.get_active_block(
                    session,
                    agent_id=agent_id,
                    principal_id=trigger_principal_id,
                )
                is not None
            ):
                return await self._commit_ignored_position(
                    session,
                    request=request,
                    position=position,
                    replay_after_position=replay_after_position,
                    reason=ExternalChannelIngestionReason.AUTHOR_NOT_ELIGIBLE,
                )
            grant = await self.repository.get_active_access_grant(
                session,
                agent_id=agent_id,
                principal_id=trigger_principal_id,
                agent_session_id=(
                    None
                    if routing.binding is None
                    else routing.binding.agent_session_id
                ),
            )
            if grant is None and not routing.route.open_access_enabled:
                access_request = await self.repository.create_access_request_idempotent(
                    session,
                    ExternalChannelAccessRequestCreate(
                        route_id=routing.route.id,
                        resource_id=routing.resource.id,
                        source_message_id=source_message.id,
                        principal_id=trigger_principal_id,
                        agent_session_id=(
                            None
                            if routing.binding is None
                            else routing.binding.agent_session_id
                        ),
                        status=ExternalChannelAccessRequestStatus.PENDING,
                        decision_policy_snapshot={"policy_version": 2},
                        decided_by_user_id=None,
                        decision_summary=None,
                        expires_at=now + _ACCESS_REQUEST_AGE,
                        decided_at=None,
                        connection_id=connection.id,
                        conversation_position_id=position.id,
                        range_start_position=history.range_start_position,
                        trigger_position=history.trigger_position,
                    ),
                )
                control_delivery_attempt_id = await self._create_access_control_intent(
                    session,
                    request_id=access_request.id,
                    request=request,
                    routing=routing,
                    principal_provider_user_id=trigger.provider_user_id,
                    participant_label=(
                        trigger.sender_display_name or trigger.provider_user_id
                    ),
                    now=now,
                )
                if routing.admission is not None:
                    await self.repository.transition_conversation_admission(
                        session,
                        admission_id=routing.admission.id,
                        status=(
                            ExternalChannelConversationAdmissionStatus.AWAITING_ACCESS
                        ),
                        selected_route_id=routing.route.id,
                    )
                await session.commit()
                return ExternalChannelIngestionAcceptance(
                    status="awaiting_access",
                    reason=ExternalChannelIngestionReason.ACCESS_REQUIRED,
                    batch_id=None,
                    session_id=None,
                    control_delivery_attempt_id=control_delivery_attempt_id,
                    connection_id=(
                        connection.id
                        if control_delivery_attempt_id is not None
                        else None
                    ),
                )
            binding = routing.binding or await self._create_binding(
                session,
                routing=routing,
                source_message=source_message,
                now=now,
            )
            persisted = [
                await self._persist_history_message(
                    session,
                    request=request,
                    resource=routing.resource,
                    message=message,
                )
                for message in history.messages
            ]
            trigger_message = next(
                item.message
                for item in persisted
                if item.message.provider_message_key
                == request.locator.trigger_provider_message_key
            )
            existing = await self.repository.get_invocation_batch(
                session,
                binding_id=binding.id,
                trigger_message_id=trigger_message.id,
            )
            if existing is None:
                batch = await self.repository.create_invocation_batch_idempotent(
                    session,
                    ExternalChannelInvocationBatchCreate(
                        binding_id=binding.id,
                        trigger_message_id=trigger_message.id,
                        first_provider_position=persisted[0].message.provider_position,
                        last_provider_position=persisted[-1].message.provider_position,
                        conversation_position_id=position.id,
                        range_start_position=history.range_start_position,
                        trigger_position=history.trigger_position,
                        context_omitted=history.context_omitted,
                        wake_dispatch_status=(
                            ExternalChannelInvocationWakeDispatchStatus.PENDING
                        ),
                        wake_dispatch_claimed_at=None,
                        truncation_message_count=0,
                        truncation_size=0,
                        mailbox_item_id=None,
                        connection_id=connection.id,
                    ),
                )
                for sequence, item in enumerate(persisted):
                    await self.repository.create_invocation_batch_item_idempotent(
                        session,
                        ExternalChannelInvocationBatchItemCreate(
                            batch_id=batch.id,
                            message_revision_id=item.revision_id,
                            sequence=sequence,
                            provider_position=item.message.provider_position,
                        ),
                    )
            else:
                batch = existing
            await self.repository.ensure_active_work(
                session,
                binding_id=binding.id,
                desired_progress_payload=checking_progress().model_dump(mode="json"),
            )
            resource_history_position = history.trigger_position
            if replay_after_position:
                assert position.read_through_position is not None
                resource_history_position = position.read_through_position
            await self.repository.mark_resource_history_ready(
                session,
                resource_id=routing.resource.id,
                through_provider_position=resource_history_position,
                completed_at=now,
            )
            locked_batch = await self.repository.lock_invocation_batch(
                session,
                batch_id=batch.id,
            )
            if locked_batch is None:
                raise RuntimeError("External Channel invocation batch disappeared.")
            if locked_batch.mailbox_item_id is None:
                projection = await self.repository.list_invocation_projection_items(
                    session,
                    batch_id=batch.id,
                )
                enqueue = await self.mailbox_service.enqueue(
                    session,
                    MailboxEnqueue(
                        session_id=binding.agent_session_id,
                        kind=MailboxItemKind.EXTERNAL_CHANNEL_INVOCATION,
                        scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
                        requested_model_target_label=None,
                        requested_reasoning_effort=None,
                        sender_user_id=None,
                        content="",
                        idempotency_key=f"external-channel-invocation:{batch.id}",
                        metadata={},
                        attachments=[],
                        file_parts=[],
                        action=None,
                        payload=build_external_channel_mailbox_payload(projection),
                    ),
                )
                await self.repository.link_invocation_batch_mailbox_item(
                    session,
                    batch_id=batch.id,
                    mailbox_item_id=enqueue.mailbox_item.id,
                )
            await self.agent_session_repository.mark_running_for_input_wakeup(
                session,
                binding.agent_session_id,
            )
            activated = await self.repository.mark_binding_activated(
                session,
                binding_id=binding.id,
                now=now,
                projected_through_position=history.trigger_position,
            )
            if activated is None:
                raise RuntimeError("External Channel binding activation failed.")
            if not replay_after_position:
                advanced = (
                    await self.repository.advance_conversation_position_if_current(
                        session,
                        position_id=position.id,
                        expected_read_through_position=(
                            preparation.exclusive_start_position
                        ),
                        read_through_position=history.trigger_position,
                    )
                )
                if not advanced:
                    await session.rollback()
                    return _position_mismatch()
            await self._initialize_thread_position(
                session,
                request=request,
                parent_position=position,
                trigger_position=history.trigger_position,
            )
            if routing.admission is not None:
                await self.repository.transition_conversation_admission(
                    session,
                    admission_id=routing.admission.id,
                    status=ExternalChannelConversationAdmissionStatus.BOUND,
                    selected_route_id=routing.route.id,
                )
            await session.commit()
            return ExternalChannelIngestionAcceptance(
                status="duplicate" if existing is not None else "accepted",
                reason=(
                    ExternalChannelIngestionReason.DUPLICATE
                    if existing is not None
                    else ExternalChannelIngestionReason.ACCEPTED
                ),
                batch_id=batch.id,
                session_id=binding.agent_session_id,
                control_delivery_attempt_id=None,
                connection_id=None,
            )

    async def _prepare_position(
        self,
        session: AsyncSession,
        *,
        request: ExternalChannelIngestionRequest,
    ) -> ExternalChannelConversationPosition | None:
        boundary = request.replay_boundary
        if boundary is not None:
            if (
                boundary.connection_id != request.locator.connection_id
                or boundary.trigger_position != request.locator.trigger_position
            ):
                return None
            position = await self.repository.get_conversation_position(
                session,
                position_id=boundary.conversation_position_id,
            )
        else:
            position = await self.repository.create_conversation_position_idempotent(
                session,
                ExternalChannelConversationPositionCreate(
                    connection_id=request.scope.connection_id,
                    scope_kind=request.scope.kind,
                    provider_channel_id=request.scope.provider_channel_id,
                    provider_thread_key=request.scope.provider_thread_key,
                    read_through_position=None,
                ),
            )
        if position is None:
            return None
        if (
            position.connection_id != request.scope.connection_id
            or position.scope_kind is not request.scope.kind
            or position.provider_channel_id != request.scope.provider_channel_id
            or position.provider_thread_key != request.scope.provider_thread_key
        ):
            return None
        return position

    async def _replay_source_matches(
        self,
        session: AsyncSession,
        *,
        request: ExternalChannelIngestionRequest,
        resource: ExternalChannelResource,
    ) -> bool:
        """Revalidate one replay boundary against its canonical metadata owners."""
        boundary = request.replay_boundary
        if boundary is None:
            return True
        if (
            boundary.resource_id != resource.id
            or resource.connection_id != boundary.connection_id
        ):
            return False
        source = await self.repository.get_message(
            session,
            message_id=boundary.source_message_id,
        )
        return (
            source is not None
            and source.resource_id == resource.id
            and source.provider_message_key
            == request.locator.trigger_provider_message_key
            and source.provider_position == boundary.trigger_position
        )

    async def _create_metadata_source(
        self,
        session: AsyncSession,
        *,
        request: ExternalChannelIngestionRequest,
        position: ExternalChannelConversationPosition,
        now: datetime.datetime,
    ) -> ExternalChannelResource:
        resource = await self.repository.create_resource_idempotent(
            session,
            ExternalChannelResourceCreate(
                connection_id=request.locator.connection_id,
                resource_type=ExternalChannelResourceType.THREAD,
                provider_resource_key=request.locator.provider_resource_key,
                labels=_resource_labels(request),
                status=ExternalChannelResourceStatus.ACTIVE,
                hydration_status=ExternalChannelHydrationStatus.PENDING,
                hydration_cursor=None,
                hydration_high_watermark_position=None,
                reconciliation_boundary_received_at=None,
                reconciliation_boundary_event_id=None,
                hydration_error_kind=None,
                hydration_error_summary=None,
                hydration_started_at=None,
                hydration_completed_at=None,
                latest_activity_at=None,
                unavailable_at=None,
                deleted_at=None,
            ),
        )
        principal_id = None
        if request.locator.provider_user_id is not None:
            principal = await self.repository.create_principal_idempotent(
                session,
                ExternalChannelPrincipalCreate(
                    provider=request.locator.provider,
                    provider_tenant_id=request.locator.provider_tenant_id,
                    provider_user_id=request.locator.provider_user_id,
                    author_type=ExternalChannelPrincipalAuthorType.HUMAN,
                    display_name=None,
                    avatar_url=None,
                    profile=None,
                ),
            )
            principal_id = principal.id
        source = await self.repository.create_message_idempotent(
            session,
            ExternalChannelMessageCreate(
                resource_id=resource.id,
                provider_message_key=request.locator.trigger_provider_message_key,
                provider_position=request.locator.trigger_position,
                principal_id=principal_id,
                author_type=ExternalChannelPrincipalAuthorType.HUMAN,
                current_revision_id=None,
                original_url=None,
                lifecycle=ExternalChannelMessageLifecycle.CURRENT,
                pending_size=0,
                provider_created_at=None,
                provider_updated_at=None,
            ),
        )
        connection = await self.repository.get_connection(
            session,
            connection_id=request.locator.connection_id,
        )
        if connection is None:
            raise RuntimeError("External Channel connection disappeared.")
        route = None
        if request.selected_route_id is not None:
            route = await self.repository.get_routable_route_by_id(
                session,
                route_id=request.selected_route_id,
            )
        elif connection.app_mode is ExternalChannelAppMode.SINGLE:
            route = await self.repository.lock_routable_single_route(
                session,
                connection_id=connection.id,
            )
        else:
            route = await self.repository.lock_routable_channel_default(
                session,
                connection_id=connection.id,
                provider_channel_id=request.locator.provider_channel_id,
            )
        await self.repository.create_conversation_admission_idempotent(
            session,
            ExternalChannelConversationAdmissionCreate(
                connection_id=connection.id,
                resource_id=resource.id,
                source_message_id=source.id,
                initiating_principal_id=principal_id,
                origin=(
                    ExternalChannelConversationAdmissionOrigin.MENTION_SELECTOR
                    if route is None
                    else ExternalChannelConversationAdmissionOrigin.SINGLE_ROUTE
                    if connection.app_mode is ExternalChannelAppMode.SINGLE
                    else ExternalChannelConversationAdmissionOrigin.CHANNEL_DEFAULT
                ),
                status=(
                    ExternalChannelConversationAdmissionStatus.PENDING_SELECTION
                    if route is None
                    else ExternalChannelConversationAdmissionStatus.SELECTED
                ),
                selected_route_id=None if route is None else route.id,
                interaction_id=None,
                conversation_position_id=position.id,
                range_start_position=position.read_through_position,
                trigger_position=request.locator.trigger_position,
                expires_at=now + _ACCESS_REQUEST_AGE,
            ),
        )
        return resource

    async def _lock_routing(
        self,
        session: AsyncSession,
        *,
        request: ExternalChannelIngestionRequest,
    ) -> _ResolvedRouting | None:
        resource = await self.repository.get_resource_by_provider_key(
            session,
            connection_id=request.locator.connection_id,
            provider_resource_key=request.locator.provider_resource_key,
        )
        if resource is None:
            return None
        resource = await self.repository.lock_resource(
            session,
            resource_id=resource.id,
        )
        if (
            resource is None
            or resource.status is not ExternalChannelResourceStatus.ACTIVE
            or not await self._replay_source_matches(
                session,
                request=request,
                resource=resource,
            )
        ):
            return None
        binding = await self.repository.lock_active_binding_by_resource(
            session,
            resource_id=resource.id,
        )
        admission = (
            None
            if binding is not None
            else await self.repository.lock_open_conversation_admission(
                session,
                resource_id=resource.id,
            )
        )
        route_id = (
            binding.route_id
            if binding is not None
            else request.selected_route_id
            or (None if admission is None else admission.selected_route_id)
        )
        if (
            binding is not None
            and request.selected_route_id is not None
            and binding.route_id != request.selected_route_id
        ):
            return None
        if (
            admission is not None
            and request.selected_route_id is not None
            and admission.selected_route_id != request.selected_route_id
        ):
            return None
        if route_id is None:
            return None
        route = await self.repository.get_routable_route_by_id(
            session,
            route_id=route_id,
        )
        if route is None or route.connection_id != request.locator.connection_id:
            return None
        return _ResolvedRouting(
            resource=resource,
            route=route,
            binding=binding,
            admission=admission,
        )

    async def _lock_pending_selection(
        self,
        session: AsyncSession,
        *,
        request: ExternalChannelIngestionRequest,
        position: ExternalChannelConversationPosition,
    ) -> _PendingSelection | None:
        """Lock one still-unbound selector admission after provider history I/O."""
        if request.selected_route_id is not None:
            return None
        resource = await self.repository.get_resource_by_provider_key(
            session,
            connection_id=request.locator.connection_id,
            provider_resource_key=request.locator.provider_resource_key,
        )
        if resource is None:
            return None
        resource = await self.repository.lock_resource(
            session,
            resource_id=resource.id,
        )
        if (
            resource is None
            or resource.status is not ExternalChannelResourceStatus.ACTIVE
            or not await self._replay_source_matches(
                session,
                request=request,
                resource=resource,
            )
        ):
            return None
        if (
            await self.repository.lock_active_binding_by_resource(
                session,
                resource_id=resource.id,
            )
            is not None
        ):
            return None
        admission = await self.repository.lock_open_conversation_admission(
            session,
            resource_id=resource.id,
        )
        if (
            admission is None
            or admission.status
            is not ExternalChannelConversationAdmissionStatus.PENDING_SELECTION
            or admission.selected_route_id is not None
            or admission.conversation_position_id != position.id
            or admission.trigger_position != request.locator.trigger_position
        ):
            return None
        return _PendingSelection(resource=resource, admission=admission)

    async def _create_binding(
        self,
        session: AsyncSession,
        *,
        routing: _ResolvedRouting,
        source_message: ExternalChannelMessage,
        now: datetime.datetime,
    ) -> ExternalChannelBinding:
        agent_id = routing.route.require_active_agent_id()
        agent = await self.agent_repository.get_by_id(session, agent_id)
        if agent is None or agent.lifecycle_status is not AgentLifecycleStatus.ACTIVE:
            raise ValueError("External Channel Agent is unavailable.")
        root = await self.root_agent_session_creation_service.create_root_session(
            session,
            create=AgentSessionCreate(
                workspace_id=agent.workspace_id,
                agent_id=agent.id,
                title=None,
                start_reason=AgentSessionStartReason.EXTERNAL_CHANNEL,
            ),
            workspace_intent=AgentDefaultRootWorkspaceIntent(),
        )
        return await self.repository.create_binding_idempotent(
            session,
            ExternalChannelBindingCreate(
                resource_id=routing.resource.id,
                route_id=routing.route.id,
                agent_session_id=root.agent_session.id,
                status=ExternalChannelBindingStatus.ACTIVE,
                activation_status=ExternalChannelBindingActivationStatus.ACTIVE,
                activation_trigger_message_id=source_message.id,
                activated_at=now,
                activation_wake_claimed_at=None,
                projected_through_position=source_message.provider_position,
                truncated_message_count=0,
                truncated_size=0,
                disconnected_at=None,
                disconnect_reason=None,
            ),
            expected_admission_id=(
                None if routing.admission is None else routing.admission.id
            ),
            expected_access_request_id=None,
        )

    async def _create_access_control_intent(
        self,
        session: AsyncSession,
        *,
        request_id: str,
        request: ExternalChannelIngestionRequest,
        routing: _ResolvedRouting,
        principal_provider_user_id: str,
        participant_label: str,
        now: datetime.datetime,
    ) -> str | None:
        """Create one durable approval control without provider I/O."""
        approval_url = _approval_url(self.config.web_url, request_id)
        if request.locator.provider is ExternalChannelProvider.SLACK:
            thread_ts = request.locator.delivery_thread_key
            if thread_ts is None:
                raise RuntimeError(
                    "External Channel Slack access target is unavailable."
                )
            payload: dict[str, object] = {
                "provider": "slack",
                "tenant_id": request.locator.provider_tenant_id,
                "channel_id": request.locator.provider_channel_id,
                "thread_ts": thread_ts,
                "access_request_id": request_id,
                "participant_provider_user_id": principal_provider_user_id,
                "participant_label": participant_label,
            }
            if approval_url is not None:
                payload["approval_url"] = approval_url
        elif request.locator.provider is ExternalChannelProvider.DISCORD:
            delivery_channel_id = request.locator.delivery_thread_key
            if delivery_channel_id is None:
                raise RuntimeError(
                    "External Channel Discord access target is unavailable."
                )
            payload = {
                "provider": "discord",
                "guild_id": request.locator.provider_tenant_id,
                "channel_id": delivery_channel_id,
                "access_request_id": request_id,
                "participant_provider_user_id": principal_provider_user_id,
                "text": (
                    _render_discord_access_request_control(approval_url)
                    if approval_url is not None
                    else None
                ),
                "embeds": (
                    _discord_access_request_embeds()
                    if approval_url is not None
                    else None
                ),
                "components": (
                    _discord_link_button(label="Review access", url=approval_url)
                    if approval_url is not None
                    else None
                ),
            }
        else:
            raise RuntimeError("External Channel provider is not supported.")
        attempt = await self.repository.create_delivery_attempt_idempotent(
            session,
            ExternalChannelDeliveryAttemptCreate(
                origin_type=ExternalChannelDeliveryOriginType.ACCESS_REQUEST,
                origin_id=request_id,
                channel_action_id=None,
                binding_id=(None if routing.binding is None else routing.binding.id),
                operation=ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
                request_payload=payload,
                status=(
                    ExternalChannelDeliveryStatus.PENDING
                    if approval_url is not None
                    else ExternalChannelDeliveryStatus.NOT_ATTEMPTED
                ),
                provider_message_key=None,
                error_kind=(
                    None if approval_url is not None else "web_url_unavailable"
                ),
                error_summary=(
                    None
                    if approval_url is not None
                    else "Azents Web URL is not configured."
                ),
                attempted_at=None,
                completed_at=None if approval_url is not None else now,
            ),
        )
        if attempt.status is ExternalChannelDeliveryStatus.PENDING:
            return attempt.id
        return None

    async def _create_selector_control_intent(
        self,
        session: AsyncSession,
        *,
        request: ExternalChannelIngestionRequest,
        admission: ExternalChannelConversationAdmission,
    ) -> str | None:
        """Create or reuse one durable provider-native Agent selector control."""
        delivery_channel_id = request.locator.delivery_thread_key
        if delivery_channel_id is None:
            raise RuntimeError(
                "External Channel selector delivery target is unavailable."
            )
        if request.locator.provider is ExternalChannelProvider.SLACK:
            payload: dict[str, object] = {
                "provider": "slack",
                "control_kind": "agent_selector",
                "tenant_id": request.locator.provider_tenant_id,
                "channel_id": request.locator.provider_channel_id,
                "thread_ts": delivery_channel_id,
                "conversation_admission_id": admission.id,
            }
        elif request.locator.provider is ExternalChannelProvider.DISCORD:
            payload = {
                "provider": "discord",
                "control_kind": "agent_selector",
                "guild_id": request.locator.provider_tenant_id,
                "channel_id": delivery_channel_id,
                "conversation_admission_id": admission.id,
                "text": "Select an Agent to continue this conversation.",
                "embeds": [
                    {
                        "title": "Select an Agent",
                        "description": (
                            "Choose the Agent that should continue this conversation."
                        ),
                        "color": 0x5865F2,
                    }
                ],
                "components": [
                    {
                        "type": 1,
                        "components": [
                            {
                                "type": 2,
                                "style": 1,
                                "label": "Select Agent",
                                "custom_id": build_discord_selector_custom_id(
                                    secret=self.config.auth.jwt.secret_key,
                                    admission_id=admission.id,
                                    action="open",
                                ),
                            }
                        ],
                    }
                ],
            }
        else:
            raise RuntimeError("External Channel provider is not supported.")
        attempt = await self.repository.create_delivery_attempt_idempotent(
            session,
            ExternalChannelDeliveryAttemptCreate(
                origin_type=ExternalChannelDeliveryOriginType.MANAGER_OPERATION,
                origin_id=admission.id,
                channel_action_id=None,
                binding_id=None,
                operation=ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
                request_payload=payload,
                status=ExternalChannelDeliveryStatus.PENDING,
                provider_message_key=None,
                error_kind=None,
                error_summary=None,
                attempted_at=None,
                completed_at=None,
            ),
        )
        if attempt.status is ExternalChannelDeliveryStatus.PENDING:
            return attempt.id
        return None

    async def _persist_principal(
        self,
        session: AsyncSession,
        *,
        request: ExternalChannelIngestionRequest,
        message: ExternalChannelCanonicalHistoryMessage,
    ) -> str:
        if message.provider_user_id is None:
            raise ValueError(
                "External Channel human principal identity is unavailable."
            )
        principal = await self.repository.create_principal_idempotent(
            session,
            ExternalChannelPrincipalCreate(
                provider=request.locator.provider,
                provider_tenant_id=request.locator.provider_tenant_id,
                provider_user_id=message.provider_user_id,
                author_type=message.author_type,
                display_name=message.sender_display_name,
                avatar_url=None,
                profile=None,
            ),
        )
        return principal.id

    async def _persist_history_message(
        self,
        session: AsyncSession,
        *,
        request: ExternalChannelIngestionRequest,
        resource: ExternalChannelResource,
        message: ExternalChannelCanonicalHistoryMessage,
    ) -> _PersistedMessage:
        principal_id = None
        if message.provider_user_id is not None:
            principal_id = await self._persist_principal(
                session,
                request=request,
                message=message,
            )
        canonical = await self.repository.create_message_idempotent(
            session,
            ExternalChannelMessageCreate(
                resource_id=resource.id,
                provider_message_key=message.provider_message_key,
                provider_position=message.provider_position,
                principal_id=principal_id,
                author_type=message.author_type,
                current_revision_id=None,
                original_url=message.original_url,
                lifecycle=message.lifecycle,
                pending_size=message.normalized_size,
                provider_created_at=message.provider_created_at,
                provider_updated_at=message.provider_updated_at,
            ),
        )
        revision = await self.repository.create_message_revision_idempotent(
            session,
            ExternalChannelMessageRevisionCreate(
                message_id=canonical.id,
                revision_key=message.revision_key,
                revision_kind=message.revision_kind,
                normalized_body=message.normalized_body,
                attachment_metadata=message.attachment_metadata,
                reference_mappings=message.reference_mappings,
                source_event_id=None,
                provider_occurred_at=(
                    message.provider_updated_at or message.provider_created_at
                ),
            ),
        )
        canonical = await self.repository.apply_message_revision(
            session,
            message_id=canonical.id,
            revision_id=revision.id,
            principal_id=principal_id,
            author_type=message.author_type,
            lifecycle=message.lifecycle,
            pending_size=message.normalized_size,
            provider_created_at=message.provider_created_at,
            provider_updated_at=message.provider_updated_at,
            original_url=message.original_url,
        )
        if canonical is None:
            raise RuntimeError("External Channel canonical message disappeared.")
        return _PersistedMessage(message=canonical, revision_id=revision.id)

    async def _initialize_thread_position(
        self,
        session: AsyncSession,
        *,
        request: ExternalChannelIngestionRequest,
        parent_position: ExternalChannelConversationPosition,
        trigger_position: str,
    ) -> None:
        if (
            parent_position.scope_kind
            is not ExternalChannelConversationScopeKind.PARENT_CHANNEL
            or request.locator.delivery_thread_key is None
        ):
            return
        await self.repository.create_conversation_position_idempotent(
            session,
            ExternalChannelConversationPositionCreate(
                connection_id=request.locator.connection_id,
                scope_kind=ExternalChannelConversationScopeKind.THREAD,
                provider_channel_id=(
                    request.locator.provider_channel_id
                    if request.locator.provider is ExternalChannelProvider.SLACK
                    else request.locator.delivery_thread_key
                ),
                provider_thread_key=request.locator.delivery_thread_key,
                read_through_position=(
                    trigger_position
                    if request.locator.provider is ExternalChannelProvider.SLACK
                    else None
                ),
            ),
        )

    async def _commit_ignored_position(
        self,
        session: AsyncSession,
        *,
        request: ExternalChannelIngestionRequest,
        position: ExternalChannelConversationPosition,
        replay_after_position: bool,
        reason: ExternalChannelIngestionReason,
    ) -> ExternalChannelIngestionAcceptance:
        if not replay_after_position:
            await self.repository.advance_conversation_position_if_current(
                session,
                position_id=position.id,
                expected_read_through_position=position.read_through_position,
                read_through_position=request.locator.trigger_position,
            )
        await session.commit()
        return ExternalChannelIngestionAcceptance(
            status="ignored",
            reason=reason,
            batch_id=None,
            session_id=None,
            control_delivery_attempt_id=None,
            connection_id=None,
        )

    async def _existing_batch(
        self,
        session: AsyncSession,
        *,
        resource: ExternalChannelResource,
        binding: ExternalChannelBinding | None,
        request: ExternalChannelIngestionRequest,
    ) -> _ExistingBatch | None:
        if binding is None:
            return None
        message = await self.repository.get_message_by_provider_key(
            session,
            resource_id=resource.id,
            provider_message_key=request.locator.trigger_provider_message_key,
        )
        if message is None:
            return None
        batch = await self.repository.get_invocation_batch(
            session,
            binding_id=binding.id,
            trigger_message_id=message.id,
        )
        if batch is None:
            return None
        return _ExistingBatch(
            batch_id=batch.id,
            session_id=binding.agent_session_id,
        )

    async def _lock_authority(
        self,
        session: AsyncSession,
        *,
        request: ExternalChannelIngestionRequest,
        now: datetime.datetime,
    ) -> ExternalChannelConnection | None:
        connection = await self.repository.lock_connection_for_routing(
            session,
            connection_id=request.locator.connection_id,
        )
        if (
            connection is None
            or connection.provider is not request.locator.provider
            or connection.provider_tenant_id != request.locator.provider_tenant_id
            or connection.ingress_profile is not request.authority.ingress_profile
            or connection.configuration_generation
            != request.authority.configuration_generation
        ):
            return None
        if (
            request.authority.kind is ExternalChannelIngressAuthorityKind.CONFIGURATION
            and request.authority.ingress_profile
            is not ExternalChannelIngressProfile.SLACK_HTTP
        ):
            return None
        if (
            request.authority.kind is ExternalChannelIngressAuthorityKind.LEASE
            and request.authority.ingress_profile
            not in {
                ExternalChannelIngressProfile.SLACK_SOCKET,
                ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP,
            }
        ):
            return None
        if request.authority.kind is ExternalChannelIngressAuthorityKind.LEASE and (
            request.authority.ingress_profile
            is ExternalChannelIngressProfile.SLACK_SOCKET
        ):
            if (
                request.authority.lease_owner is None
                or request.authority.lease_generation is not None
                or connection.socket_lease_owner != request.authority.lease_owner
                or connection.socket_lease_until is None
                or connection.socket_lease_until < now
            ):
                return None
        if request.authority.kind is ExternalChannelIngressAuthorityKind.LEASE and (
            request.authority.ingress_profile
            is ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP
        ):
            if (
                request.authority.lease_owner is None
                or request.authority.lease_generation is None
            ):
                return None
            owned = await self.repository.get_owned_discord_gateway_configuration(
                session,
                connection_id=connection.id,
                lease_owner=request.authority.lease_owner,
                lease_generation=request.authority.lease_generation,
                now=now,
            )
            if owned is None:
                return None
        return connection


def _resource_labels(request: ExternalChannelIngestionRequest) -> dict[str, object]:
    if request.locator.provider is ExternalChannelProvider.SLACK:
        return {
            "provider": "slack",
            "tenant_id": request.locator.provider_tenant_id,
            "channel_id": request.locator.provider_channel_id,
            "thread_ts": (
                request.locator.delivery_thread_key
                or request.locator.trigger_provider_message_key
            ),
        }
    delivery = request.locator.delivery_thread_key
    return {
        "provider": "discord",
        "guild_id": request.locator.provider_tenant_id,
        "source_channel_id": request.locator.provider_channel_id,
        "parent_channel_id": (
            request.locator.provider_parent_channel_id
            or request.locator.provider_channel_id
        ),
        "root_message_id": (
            request.locator.provider_thread_key
            or request.locator.trigger_provider_message_id
        ),
        **(
            {"thread_channel_id": delivery, "delivery_channel_id": delivery}
            if delivery
            else {}
        ),
    }


def _immediate(
    kind: ExternalChannelIngestionOutcomeKind,
    reason: ExternalChannelIngestionReason,
) -> ExternalChannelIngestionPreparation:
    return ExternalChannelIngestionPreparation(
        position_id=None,
        exclusive_start_position=None,
        immediate_outcome=ExternalChannelIngestionOutcome(
            kind=kind,
            reason=reason,
            batch_id=None,
            control_delivery_attempt_id=None,
            connection_id=None,
        ),
        wake_batch_id=None,
        wake_session_id=None,
    )


def _position_mismatch() -> ExternalChannelIngestionAcceptance:
    return ExternalChannelIngestionAcceptance(
        status="position_mismatch",
        reason=ExternalChannelIngestionReason.POSITION_CHANGED,
        batch_id=None,
        session_id=None,
        control_delivery_attempt_id=None,
        connection_id=None,
    )


def _rejected(
    reason: ExternalChannelIngestionReason,
) -> ExternalChannelIngestionAcceptance:
    return ExternalChannelIngestionAcceptance(
        status="terminal_rejection",
        reason=reason,
        batch_id=None,
        session_id=None,
        control_delivery_attempt_id=None,
        connection_id=None,
    )


def _approval_url(web_url: str, access_request_id: str) -> str | None:
    normalized = web_url.rstrip("/")
    if not normalized:
        return None
    return f"{normalized}/external-channel/access/{access_request_id}"


def _render_discord_access_request_control(approval_url: str) -> str:
    """Render the Discord approval prompt without exposing a bare URL."""
    return (
        "Approval is required before this participant can invoke the Agent. "
        f"[Review access]({approval_url})"
    )


def _discord_access_request_embeds() -> list[dict[str, object]]:
    """Render one provider-native approval boundary without participant disclosure."""
    return [
        {
            "title": "Access approval required",
            "description": (
                "A Workspace member must approve this participant before the Agent "
                "can continue the conversation."
            ),
            "color": 0xFEE75C,
        }
    ]


def _discord_link_button(*, label: str, url: str) -> list[dict[str, object]]:
    """Return one bounded Discord link button row for an approved web action."""
    return [
        {
            "type": 1,
            "components": [
                {
                    "type": 2,
                    "style": 5,
                    "label": label,
                    "url": url,
                }
            ],
        }
    ]


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)
