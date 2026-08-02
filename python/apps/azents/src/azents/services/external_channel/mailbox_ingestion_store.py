"""Canonical-mailbox synchronous External Channel ingestion store."""

import dataclasses
import datetime
import hashlib
import logging
from typing import Annotated
from urllib.parse import quote, urlparse, urlunparse

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.enums import (
    AgentLifecycleStatus,
    AgentSessionStartReason,
    ExternalChannelAccessRequestStatus,
    ExternalChannelAppMode,
    ExternalChannelConversationLocation,
    ExternalChannelConversationScopeKind,
    ExternalChannelDeliveryOperation,
    ExternalChannelDeliveryOriginType,
    ExternalChannelDeliveryStatus,
    ExternalChannelIngressProfile,
    ExternalChannelInteractionStatus,
    ExternalChannelInteractionType,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
    ExternalChannelResponseMode,
    ExternalChannelSetupClaimStatus,
    MailboxItemKind,
    MailboxSchedulingMode,
)
from azents.core.external_channel_progress import checking_progress
from azents.core.external_channel_session_presence import (
    binding_settings_on_demand_payload,
    session_presence_payload,
    setup_required_payload,
)
from azents.core.slack_external_channel_progress import (
    render_slack_progress,
)
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
    ExternalChannelConversationPosition,
    ExternalChannelConversationPositionCreate,
    ExternalChannelDeliveryAttemptCreate,
    ExternalChannelInteraction,
    ExternalChannelInteractionCreate,
    ExternalChannelMailboxProjectionItem,
    ExternalChannelParticipationSetting,
    ExternalChannelPrincipalCreate,
    ExternalChannelResource,
    ExternalChannelResourceCreate,
    ExternalChannelSetupClaim,
    ExternalChannelSetupClaimCreate,
    ExternalChannelWork,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.external_channel.work import ExternalChannelWorkRepository
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
    ExternalChannelSetupReplayBoundary,
)
from azents.services.external_channel.participation_state import (
    ExternalChannelSetupSourceProjection,
    build_setup_continuation_request,
    projection_with_setup_source,
    setup_source_from_projection,
)
from azents.services.external_channel.selector_state import (
    ExternalChannelSelectorState,
    projection_with_selector_state,
    selector_provider_interaction_key,
    selector_state_from_interaction,
)
from azents.services.mailbox import (
    MailboxEnqueue,
    MailboxService,
    build_external_channel_mailbox_payload,
)
from azents.services.root_agent_session_creation import RootAgentSessionCreationService
from azents.services.root_agent_session_creation.data import (
    AgentDefaultRootWorkspaceIntent,
)

_ACCESS_REQUEST_AGE = datetime.timedelta(days=7)
logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class _Conversation:
    """Current durable conversation routing state."""

    source_resource: ExternalChannelResource
    resource: ExternalChannelResource
    route: ExternalChannelAgentRoute | None
    setting: ExternalChannelParticipationSetting | None
    binding: ExternalChannelBinding | None
    principal_id: str
    selector: ExternalChannelInteraction | None
    setup_claim: ExternalChannelSetupClaim | None
    setup_required: bool


@dataclasses.dataclass(frozen=True)
class _BindingCreation:
    """New binding plus whether its root Session was created in this transaction."""

    binding: ExternalChannelBinding
    session_created: bool


@dataclasses.dataclass
class ExternalChannelMailboxIngestionStore:
    """Accept provider history directly into one canonical mailbox item."""

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    repository: Annotated[
        ExternalChannelRepository,
        Depends(ExternalChannelRepository),
    ]
    work_repository: Annotated[
        ExternalChannelWorkRepository,
        Depends(ExternalChannelWorkRepository),
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
        """Prepare one content-free routing snapshot before provider history."""
        now = _utc_now()
        async with self.session_manager() as session:
            connection = await self._lock_authority(session, request=request, now=now)
            if connection is None:
                return _immediate(
                    ExternalChannelIngestionOutcomeKind.TERMINAL_REJECTION,
                    ExternalChannelIngestionReason.INGRESS_AUTHORITY_STALE,
                )
            priority_request = await self._selected_setup_priority_request(
                session,
                request=request,
            )
            if priority_request is not None:
                await session.commit()
                return ExternalChannelIngestionPreparation(
                    position_id=None,
                    exclusive_start_position=None,
                    immediate_outcome=None,
                    wake_mailbox_item_id=None,
                    wake_session_id=None,
                    priority_request=priority_request,
                )
            position = await self._prepare_position(session, request=request)
            if position is None:
                return _immediate(
                    ExternalChannelIngestionOutcomeKind.TERMINAL_REJECTION,
                    ExternalChannelIngestionReason.INVALID_REPLAY_BOUNDARY,
                )
            source_resource = await self._get_source_resource(
                session,
                request=request,
            )
            if (
                source_resource is not None
                and source_resource.status is not ExternalChannelResourceStatus.ACTIVE
            ):
                await session.commit()
                return _immediate(
                    ExternalChannelIngestionOutcomeKind.TERMINAL_REJECTION,
                    ExternalChannelIngestionReason.CONVERSATION_UNAVAILABLE,
                )
            if source_resource is not None and not self._replay_source_matches(
                request=request,
                resource=source_resource,
            ):
                await session.commit()
                return _immediate(
                    ExternalChannelIngestionOutcomeKind.TERMINAL_REJECTION,
                    ExternalChannelIngestionReason.INVALID_REPLAY_BOUNDARY,
                )
            binding = await self._prepare_effective_binding(
                session,
                request=request,
                connection=connection,
                source_resource=source_resource,
            )
            ignored_reason = _response_mode_ignored_reason(
                request=request,
                binding=binding,
            )
            if ignored_reason is not None:
                await session.commit()
                return _immediate(
                    ExternalChannelIngestionOutcomeKind.IGNORED,
                    ignored_reason,
                )
            if source_resource is None:
                if request.replay_boundary is not None:
                    await session.commit()
                    return _immediate(
                        ExternalChannelIngestionOutcomeKind.TERMINAL_REJECTION,
                        ExternalChannelIngestionReason.INVALID_REPLAY_BOUNDARY,
                    )
                source_resource = await self._create_source_resource(
                    session,
                    request=request,
                    now=now,
                )
            if not self._replay_source_matches(
                request=request,
                resource=source_resource,
            ):
                await session.commit()
                return _immediate(
                    ExternalChannelIngestionOutcomeKind.TERMINAL_REJECTION,
                    ExternalChannelIngestionReason.INVALID_REPLAY_BOUNDARY,
                )
            if (
                request.operation is ExternalChannelIngestionOperation.CURRENT_TRIGGER
                and position.read_through_position is not None
                and request.locator.trigger_position <= position.read_through_position
            ):
                wake_item_id = None
                wake_session_id = None
                if binding is not None:
                    existing = await self.mailbox_service.get_by_idempotency_key(
                        session,
                        session_id=binding.agent_session_id,
                        kind=MailboxItemKind.EXTERNAL_CHANNEL_INVOCATION,
                        idempotency_key=_mailbox_idempotency_key(
                            request=request,
                            position_id=position.id,
                        ),
                    )
                    if existing is not None:
                        wake_item_id = existing.id
                        wake_session_id = binding.agent_session_id
                await session.commit()
                return ExternalChannelIngestionPreparation(
                    position_id=None,
                    exclusive_start_position=None,
                    immediate_outcome=ExternalChannelIngestionOutcome(
                        kind=ExternalChannelIngestionOutcomeKind.DUPLICATE,
                        reason=ExternalChannelIngestionReason.DUPLICATE,
                        mailbox_item_id=wake_item_id,
                        control_delivery_attempt_id=None,
                        connection_id=None,
                    ),
                    wake_mailbox_item_id=wake_item_id,
                    wake_session_id=wake_session_id,
                    priority_request=None,
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
                wake_mailbox_item_id=None,
                wake_session_id=None,
                priority_request=None,
            )

    async def accept(
        self,
        *,
        request: ExternalChannelIngestionRequest,
        preparation: ExternalChannelIngestionPreparation,
        history: ExternalChannelHistoryRange[ExternalChannelCanonicalHistoryMessage],
    ) -> ExternalChannelIngestionAcceptance:
        """Atomically enqueue provider history and advance its durable position."""
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
                or trigger.author_type is not ExternalChannelPrincipalAuthorType.HUMAN
                or trigger.provider_user_id is None
                or (
                    request.locator.provider_user_id is not None
                    and trigger.provider_user_id != request.locator.provider_user_id
                )
            ):
                return _rejected(ExternalChannelIngestionReason.INVALID_REPLAY_BOUNDARY)
            source_resource = await self.repository.get_resource_by_provider_key(
                session,
                connection_id=connection.id,
                resource_type=ExternalChannelResourceType.THREAD,
                provider_resource_key=request.locator.provider_resource_key,
            )
            if (
                source_resource is None
                or source_resource.status is not ExternalChannelResourceStatus.ACTIVE
                or not self._replay_source_matches(
                    request=request,
                    resource=source_resource,
                )
            ):
                return _rejected(
                    ExternalChannelIngestionReason.CONVERSATION_UNAVAILABLE
                )
            conversation = await self._resolve_conversation(
                session,
                request=request,
                connection=connection,
                source_resource=source_resource,
                position=position,
                now=now,
            )
            ignored_reason = _response_mode_ignored_reason(
                request=request,
                binding=conversation.binding,
            )
            if ignored_reason is not None:
                return await self._commit_ignored(session, ignored_reason)
            if conversation.setup_required:
                return await self._accept_setup_required(
                    session,
                    request=request,
                    connection=connection,
                    position=position,
                    history=history,
                    conversation=conversation,
                    now=now,
                )
            if conversation.route is None:
                selector = conversation.selector or await self._ensure_selector(
                    session,
                    request=request,
                    connection=connection,
                    resource=conversation.resource,
                    position=position,
                    principal_id=conversation.principal_id,
                    setup_claim_id=None,
                    now=now,
                )
                delivery_id = await self._create_selector_control_intent(
                    session,
                    request=request,
                    selector_id=selector.id,
                )
                await session.commit()
                return ExternalChannelIngestionAcceptance(
                    status="awaiting_selection",
                    reason=ExternalChannelIngestionReason.SELECTION_REQUIRED,
                    mailbox_item_id=None,
                    session_id=None,
                    control_delivery_attempt_id=delivery_id,
                    connection_id=connection.id if delivery_id is not None else None,
                )
            agent_id = conversation.route.require_active_agent_id()
            if (
                await self.repository.get_active_block(
                    session,
                    agent_id=agent_id,
                    principal_id=conversation.principal_id,
                )
                is not None
            ):
                return await self._commit_ignored(
                    session,
                    ExternalChannelIngestionReason.AUTHOR_NOT_ELIGIBLE,
                )
            grant = await self.repository.get_active_access_grant(
                session,
                agent_id=agent_id,
                principal_id=conversation.principal_id,
                agent_session_id=(
                    None
                    if conversation.binding is None
                    else conversation.binding.agent_session_id
                ),
            )
            if grant is None and not _route_has_automatic_access(conversation.route):
                access_request = await self.repository.create_access_request_idempotent(
                    session,
                    ExternalChannelAccessRequestCreate(
                        route_id=conversation.route.id,
                        resource_id=conversation.resource.id,
                        trigger_provider_message_key=(
                            request.locator.trigger_provider_message_key
                        ),
                        principal_id=conversation.principal_id,
                        agent_session_id=(
                            None
                            if conversation.binding is None
                            else conversation.binding.agent_session_id
                        ),
                        setup_claim_id=None,
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
                delivery_id = await self._create_access_control_intent(
                    session,
                    request_id=access_request.id,
                    request=request,
                    binding=conversation.binding,
                    principal_provider_user_id=trigger.provider_user_id,
                    participant_label=trigger.sender_display_name
                    or trigger.provider_user_id,
                    now=now,
                )
                await session.commit()
                return ExternalChannelIngestionAcceptance(
                    status="awaiting_access",
                    reason=ExternalChannelIngestionReason.ACCESS_REQUIRED,
                    mailbox_item_id=None,
                    session_id=None,
                    control_delivery_attempt_id=delivery_id,
                    connection_id=connection.id if delivery_id is not None else None,
                )
            session_created = False
            binding = conversation.binding
            existing_binding = binding is not None
            if binding is None:
                creation = await self._create_binding(
                    session,
                    route=conversation.route,
                    resource=conversation.resource,
                    response_mode=(
                        None
                        if conversation.setting is None
                        else conversation.setting.response_mode
                    ),
                )
                binding = creation.binding
                session_created = creation.session_created
            work = await self.repository.ensure_active_work(
                session,
                binding_id=binding.id,
                desired_progress_payload=checking_progress().model_dump(mode="json"),
            )
            session_presence_id = await self._create_session_presence_intent(
                session,
                resource=conversation.resource,
                binding=binding,
            )
            settings_control_id = (
                await self._create_binding_settings_on_demand_intent(
                    session,
                    resource=conversation.resource,
                    binding=binding,
                )
                if existing_binding and request.locator.invocation
                else None
            )
            progress_id = await self._create_initial_progress_intent(
                session,
                request=request,
                resource=conversation.resource,
                binding=binding,
                work=work,
            )
            idempotency_key = _mailbox_idempotency_key(
                request=request,
                position_id=position.id,
            )
            projection = _invocation_projection(
                request=request,
                history=history,
                resource=conversation.resource,
                binding=binding,
                trigger_principal_id=conversation.principal_id,
                invocation_id=idempotency_key,
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
                    idempotency_key=idempotency_key,
                    metadata={},
                    attachments=[],
                    file_parts=[],
                    action=None,
                    payload=build_external_channel_mailbox_payload(projection),
                ),
            )
            await self.agent_session_repository.mark_running_for_input_wakeup(
                session,
                binding.agent_session_id,
            )
            if not replay_after_position:
                advance = self.repository.advance_conversation_position_if_current
                advanced = await advance(
                    session,
                    position_id=position.id,
                    expected_read_through_position=preparation.exclusive_start_position,
                    read_through_position=history.trigger_position,
                )
                if not advanced:
                    await session.rollback()
                    return _position_mismatch()
            if (
                conversation.resource.resource_type
                is ExternalChannelResourceType.THREAD
            ):
                await self._initialize_thread_position(
                    session,
                    request=request,
                    resource=conversation.resource,
                    parent_position=position,
                    trigger_position=history.trigger_position,
                )
            await self._complete_setup_replay(
                session,
                request=request,
                conversation=conversation,
                now=now,
            )
            await session.commit()
            if session_created:
                logger.info(
                    "Created External Channel AgentSession",
                    extra={
                        "external_channel_provider": request.locator.provider.value,
                        "provider_event_type": request.locator.provider_event_type,
                    },
                )
            control_id = settings_control_id or session_presence_id or progress_id
            return ExternalChannelIngestionAcceptance(
                status="accepted" if enqueue.created else "duplicate",
                reason=(
                    ExternalChannelIngestionReason.ACCEPTED
                    if enqueue.created
                    else ExternalChannelIngestionReason.DUPLICATE
                ),
                mailbox_item_id=enqueue.mailbox_item.id,
                session_id=binding.agent_session_id,
                control_delivery_attempt_id=control_id,
                connection_id=connection.id if control_id is not None else None,
            )

    async def _get_source_resource(
        self,
        session: AsyncSession,
        *,
        request: ExternalChannelIngestionRequest,
    ) -> ExternalChannelResource | None:
        """Fetch the route-neutral provider-history source Resource."""
        return await self.repository.get_resource_by_provider_key(
            session,
            connection_id=request.locator.connection_id,
            resource_type=ExternalChannelResourceType.THREAD,
            provider_resource_key=request.locator.provider_resource_key,
        )

    async def _create_source_resource(
        self,
        session: AsyncSession,
        *,
        request: ExternalChannelIngestionRequest,
        now: datetime.datetime,
    ) -> ExternalChannelResource:
        """Create the route-neutral provider-history source Resource."""
        return await self.repository.create_resource_idempotent(
            session,
            ExternalChannelResourceCreate(
                connection_id=request.locator.connection_id,
                resource_type=ExternalChannelResourceType.THREAD,
                provider_resource_key=request.locator.provider_resource_key,
                labels=_resource_labels(request),
                status=ExternalChannelResourceStatus.ACTIVE,
                latest_activity_at=now,
                unavailable_at=None,
                deleted_at=None,
            ),
        )

    async def _prepare_effective_binding(
        self,
        session: AsyncSession,
        *,
        request: ExternalChannelIngestionRequest,
        connection: ExternalChannelConnection,
        source_resource: ExternalChannelResource | None,
    ) -> ExternalChannelBinding | None:
        """Resolve only the concrete Binding needed by the response predicate."""
        if source_resource is not None:
            source_binding = await self.repository.lock_connected_binding_by_resource(
                session,
                resource_id=source_resource.id,
            )
            if source_binding is not None:
                return source_binding
        boundary = request.replay_boundary
        if isinstance(boundary, ExternalChannelSetupReplayBoundary):
            target = await self.repository.lock_resource(
                session,
                resource_id=boundary.target_resource_id,
            )
            if (
                target is None
                or target.connection_id != connection.id
                or target.status is not ExternalChannelResourceStatus.ACTIVE
            ):
                return None
            return await self.repository.lock_connected_binding_by_resource(
                session,
                resource_id=target.id,
            )
        if (
            request.scope.kind
            is not ExternalChannelConversationScopeKind.PARENT_CHANNEL
        ):
            return None
        route = await self._resolve_route(
            session,
            request=request,
            connection=connection,
        )
        if route is None:
            return None
        setting = await self.repository.lock_active_participation_setting(
            session,
            connection_id=connection.id,
            provider_parent_channel_id=_provider_parent_channel_id(request),
        )
        if (
            setting is None
            or setting.route_id != route.id
            or setting.location is not ExternalChannelConversationLocation.CHANNEL
        ):
            return None
        parent_resource = await self.repository.get_resource_by_provider_key(
            session,
            connection_id=connection.id,
            resource_type=ExternalChannelResourceType.PARENT_CHANNEL,
            provider_resource_key=setting.provider_parent_channel_id,
        )
        if (
            parent_resource is None
            or parent_resource.status is not ExternalChannelResourceStatus.ACTIVE
        ):
            return None
        return await self.repository.lock_connected_binding_by_resource(
            session,
            resource_id=parent_resource.id,
        )

    async def _selected_setup_priority_request(
        self,
        session: AsyncSession,
        *,
        request: ExternalChannelIngestionRequest,
    ) -> ExternalChannelIngestionRequest | None:
        """Return the selected continuation that must precede newer parent traffic."""
        if (
            request.operation is not ExternalChannelIngestionOperation.CURRENT_TRIGGER
            or request.scope.kind
            is not ExternalChannelConversationScopeKind.PARENT_CHANNEL
        ):
            return None
        claim = await self.repository.lock_nonterminal_setup_claim(
            session,
            connection_id=request.locator.connection_id,
            provider_parent_channel_id=_provider_parent_channel_id(request),
        )
        if (
            claim is None
            or claim.status is not ExternalChannelSetupClaimStatus.SELECTED
        ):
            return None
        if (
            claim.selected_setting_id is None
            or claim.selected_resource_id is None
            or claim.selected_source_revision is None
        ):
            raise ValueError("Selected External Channel setup claim is incomplete.")
        configuration = await self.repository.get_connection_configuration(
            session,
            connection_id=claim.connection_id,
        )
        setting = await self.repository.get_active_participation_setting(
            session,
            connection_id=claim.connection_id,
            provider_parent_channel_id=claim.provider_parent_channel_id,
        )
        source_resource = await self.repository.get_resource(
            session,
            resource_id=claim.source_resource_id,
        )
        target_resource = await self.repository.get_resource(
            session,
            resource_id=claim.selected_resource_id,
        )
        principal = await self.repository.get_principal(
            session,
            principal_id=claim.principal_id,
        )
        if (
            configuration is None
            or setting is None
            or setting.id != claim.selected_setting_id
            or source_resource is None
            or source_resource.status is not ExternalChannelResourceStatus.ACTIVE
            or target_resource is None
            or target_resource.status is not ExternalChannelResourceStatus.ACTIVE
            or principal is None
        ):
            raise ValueError("Selected External Channel setup owners are unavailable.")
        return build_setup_continuation_request(
            configuration=configuration,
            claim=claim,
            setting=setting,
            source_resource=source_resource,
            principal=principal,
            source=setup_source_from_projection(claim.source_projection),
            deadline=request.deadline,
        )

    async def _resolve_conversation(
        self,
        session: AsyncSession,
        *,
        request: ExternalChannelIngestionRequest,
        connection: ExternalChannelConnection,
        source_resource: ExternalChannelResource,
        position: ExternalChannelConversationPosition,
        now: datetime.datetime,
    ) -> _Conversation:
        principal_id = await self._ensure_principal(
            session,
            request=request,
        )
        boundary = request.replay_boundary
        if isinstance(boundary, ExternalChannelSetupReplayBoundary):
            route = await self._resolve_route(
                session,
                request=request,
                connection=connection,
            )
            setting = await self.repository.lock_active_participation_setting(
                session,
                connection_id=connection.id,
                provider_parent_channel_id=_provider_parent_channel_id(request),
            )
            claim = await self.repository.lock_setup_claim(
                session,
                claim_id=boundary.claim_id,
            )
            target_resource = await self.repository.lock_resource(
                session,
                resource_id=boundary.target_resource_id,
            )
            if (
                route is None
                or setting is None
                or setting.id != boundary.setting_id
                or setting.route_id != route.id
                or setting.settings_generation != boundary.settings_generation
                or setting.location is not boundary.location
                or claim is None
                or claim.status is not ExternalChannelSetupClaimStatus.SELECTED
                or claim.claim_generation != boundary.expected_claim_generation
                or claim.selected_source_revision != boundary.selected_source_revision
                or claim.selected_resource_id != boundary.target_resource_id
                or claim.source_resource_id != source_resource.id
                or target_resource is None
                or target_resource.connection_id != connection.id
                or target_resource.status is not ExternalChannelResourceStatus.ACTIVE
            ):
                raise ValueError(
                    "External Channel selected setup replay is no longer current."
                )
            binding = await self.repository.lock_connected_binding_by_resource(
                session,
                resource_id=target_resource.id,
            )
            return _Conversation(
                source_resource=source_resource,
                resource=target_resource,
                route=route,
                setting=setting,
                binding=binding,
                principal_id=principal_id,
                selector=None,
                setup_claim=claim,
                setup_required=False,
            )
        source_binding = await self.repository.lock_connected_binding_by_resource(
            session,
            resource_id=source_resource.id,
        )
        if source_binding is not None:
            route = await self.repository.get_routable_route_by_id(
                session,
                route_id=source_binding.route_id,
            )
            return _Conversation(
                source_resource=source_resource,
                resource=source_resource,
                route=route,
                setting=None,
                binding=source_binding,
                principal_id=principal_id,
                selector=None,
                setup_claim=None,
                setup_required=False,
            )
        route = await self._resolve_route(
            session,
            request=request,
            connection=connection,
        )
        setting = await self.repository.lock_active_participation_setting(
            session,
            connection_id=connection.id,
            provider_parent_channel_id=_provider_parent_channel_id(request),
        )
        if setting is not None:
            if route is None or setting.route_id != route.id:
                raise ValueError(
                    "External Channel participation route is no longer current."
                )
            target_resource = source_resource
            if (
                request.scope.kind
                is ExternalChannelConversationScopeKind.PARENT_CHANNEL
                and setting.location is ExternalChannelConversationLocation.CHANNEL
            ):
                target_resource = await self.repository.get_resource_by_provider_key(
                    session,
                    connection_id=connection.id,
                    resource_type=ExternalChannelResourceType.PARENT_CHANNEL,
                    provider_resource_key=setting.provider_parent_channel_id,
                ) or await self.repository.create_resource_idempotent(
                    session,
                    ExternalChannelResourceCreate(
                        connection_id=connection.id,
                        resource_type=ExternalChannelResourceType.PARENT_CHANNEL,
                        provider_resource_key=setting.provider_parent_channel_id,
                        labels=_parent_resource_labels(request),
                        status=ExternalChannelResourceStatus.ACTIVE,
                        latest_activity_at=now,
                        unavailable_at=None,
                        deleted_at=None,
                    ),
                )
            binding = await self.repository.lock_connected_binding_by_resource(
                session,
                resource_id=target_resource.id,
            )
            return _Conversation(
                source_resource=source_resource,
                resource=target_resource,
                route=route,
                setting=setting,
                binding=binding,
                principal_id=principal_id,
                selector=None,
                setup_claim=None,
                setup_required=False,
            )
        setup_required = (
            request.operation is ExternalChannelIngestionOperation.CURRENT_TRIGGER
            and request.scope.kind
            is ExternalChannelConversationScopeKind.PARENT_CHANNEL
            and request.locator.invocation
        )
        selector = None
        if route is None and not setup_required:
            selector = await self._ensure_selector(
                session,
                request=request,
                connection=connection,
                resource=source_resource,
                position=position,
                principal_id=principal_id,
                setup_claim_id=None,
                now=now,
            )
        return _Conversation(
            source_resource=source_resource,
            resource=source_resource,
            route=route,
            setting=None,
            binding=None,
            principal_id=principal_id,
            selector=selector,
            setup_claim=None,
            setup_required=setup_required,
        )

    async def _accept_setup_required(
        self,
        session: AsyncSession,
        *,
        request: ExternalChannelIngestionRequest,
        connection: ExternalChannelConnection,
        position: ExternalChannelConversationPosition,
        history: ExternalChannelHistoryRange[ExternalChannelCanonicalHistoryMessage],
        conversation: _Conversation,
        now: datetime.datetime,
    ) -> ExternalChannelIngestionAcceptance:
        """Commit only setup state for one eligible unconfigured invocation."""
        route = conversation.route
        if route is not None:
            agent_id = route.require_active_agent_id()
            if (
                await self.repository.get_active_block(
                    session,
                    agent_id=agent_id,
                    principal_id=conversation.principal_id,
                )
                is not None
            ):
                return await self._commit_ignored(
                    session,
                    ExternalChannelIngestionReason.AUTHOR_NOT_ELIGIBLE,
                )
        claim = await self._ensure_setup_claim(
            session,
            request=request,
            position=position,
            source_resource=conversation.source_resource,
            principal_id=conversation.principal_id,
            route=route,
            history=history,
            now=now,
        )
        if claim is None:
            await session.rollback()
            return _position_mismatch()
        if route is None:
            selector = await self._ensure_selector(
                session,
                request=request,
                connection=connection,
                resource=conversation.source_resource,
                position=position,
                principal_id=conversation.principal_id,
                setup_claim_id=claim.id,
                now=now,
            )
            delivery_id = await self._create_selector_control_intent(
                session,
                request=request,
                selector_id=selector.id,
            )
            await session.commit()
            return ExternalChannelIngestionAcceptance(
                status="awaiting_selection",
                reason=ExternalChannelIngestionReason.SELECTION_REQUIRED,
                mailbox_item_id=None,
                session_id=None,
                control_delivery_attempt_id=delivery_id,
                connection_id=connection.id if delivery_id is not None else None,
            )
        grant = await self.repository.get_active_access_grant(
            session,
            agent_id=route.require_active_agent_id(),
            principal_id=conversation.principal_id,
            agent_session_id=None,
        )
        if grant is None and not _route_has_automatic_access(route):
            access_request = await self.repository.create_access_request_idempotent(
                session,
                ExternalChannelAccessRequestCreate(
                    route_id=route.id,
                    resource_id=conversation.source_resource.id,
                    trigger_provider_message_key=(
                        request.locator.trigger_provider_message_key
                    ),
                    principal_id=conversation.principal_id,
                    agent_session_id=None,
                    setup_claim_id=claim.id,
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
            trigger = history.trigger
            assert trigger.provider_user_id is not None
            delivery_id = await self._create_access_control_intent(
                session,
                request_id=access_request.id,
                request=request,
                binding=None,
                principal_provider_user_id=trigger.provider_user_id,
                participant_label=(
                    trigger.sender_display_name or trigger.provider_user_id
                ),
                now=now,
            )
            await session.commit()
            return ExternalChannelIngestionAcceptance(
                status="awaiting_access",
                reason=ExternalChannelIngestionReason.ACCESS_REQUIRED,
                mailbox_item_id=None,
                session_id=None,
                control_delivery_attempt_id=delivery_id,
                connection_id=connection.id if delivery_id is not None else None,
            )
        delivery_id = await self._create_setup_control_intent(
            session,
            resource=conversation.source_resource,
            claim=claim,
        )
        await session.commit()
        return ExternalChannelIngestionAcceptance(
            status="awaiting_selection",
            reason=ExternalChannelIngestionReason.SETUP_REQUIRED,
            mailbox_item_id=None,
            session_id=None,
            control_delivery_attempt_id=delivery_id,
            connection_id=connection.id if delivery_id is not None else None,
        )

    async def _ensure_setup_claim(
        self,
        session: AsyncSession,
        *,
        request: ExternalChannelIngestionRequest,
        position: ExternalChannelConversationPosition,
        source_resource: ExternalChannelResource,
        principal_id: str,
        route: ExternalChannelAgentRoute | None,
        history: ExternalChannelHistoryRange[ExternalChannelCanonicalHistoryMessage],
        now: datetime.datetime,
    ) -> ExternalChannelSetupClaim | None:
        """Create or replace the one latest eligible pending setup source."""
        provider_parent_channel_id = _provider_parent_channel_id(request)
        source_projection = projection_with_setup_source(
            ExternalChannelSetupSourceProjection(
                schema_version=1,
                provider=request.locator.provider,
                provider_event_type=request.locator.provider_event_type,
                provider_tenant_id=request.locator.provider_tenant_id,
                provider_channel_id=request.locator.provider_channel_id,
                provider_parent_channel_id=provider_parent_channel_id,
                scope_kind=request.scope.kind,
                provider_thread_key=request.locator.provider_thread_key,
                delivery_thread_key=request.locator.delivery_thread_key,
                provider_resource_key=request.locator.provider_resource_key,
                trigger_provider_message_key=(
                    request.locator.trigger_provider_message_key
                ),
                trigger_provider_message_id=(
                    request.locator.trigger_provider_message_id
                ),
                trigger_position=history.trigger_position,
                range_start_position=history.range_start_position,
            )
        )
        claim = await self.repository.lock_nonterminal_setup_claim(
            session,
            connection_id=request.locator.connection_id,
            provider_parent_channel_id=provider_parent_channel_id,
        )
        if (
            claim is not None
            and claim.status is ExternalChannelSetupClaimStatus.SELECTED
        ):
            return None
        if claim is None:
            return await self.repository.create_setup_claim(
                session,
                ExternalChannelSetupClaimCreate(
                    connection_id=request.locator.connection_id,
                    provider_parent_channel_id=provider_parent_channel_id,
                    route_id=None if route is None else route.id,
                    conversation_position_id=position.id,
                    source_resource_id=source_resource.id,
                    principal_id=principal_id,
                    source_projection=source_projection,
                    source_revision=1,
                    claim_generation=1,
                    status=(
                        ExternalChannelSetupClaimStatus.PENDING_AGENT
                        if route is None
                        else ExternalChannelSetupClaimStatus.PENDING_LOCATION
                    ),
                    selected_setting_id=None,
                    selected_resource_id=None,
                    selected_source_revision=None,
                    expires_at=now + _ACCESS_REQUEST_AGE,
                    selected_at=None,
                    completed_at=None,
                ),
            )
        if (
            claim.status is ExternalChannelSetupClaimStatus.PENDING_AGENT
            and route is not None
        ):
            claim = await self.repository.assign_setup_claim_route(
                session,
                claim_id=claim.id,
                expected_claim_generation=claim.claim_generation,
                route_id=route.id,
            )
            if claim is None:
                return None
        if (route is None) != (claim.route_id is None) or (
            route is not None and claim.route_id != route.id
        ):
            raise ValueError("External Channel setup route changed during admission.")
        existing_source = setup_source_from_projection(claim.source_projection)
        if (
            existing_source.trigger_provider_message_key
            == request.locator.trigger_provider_message_key
        ):
            return claim
        if (
            claim.conversation_position_id == position.id
            and claim.source_resource_id == source_resource.id
            and claim.principal_id == principal_id
            and claim.source_projection == source_projection
        ):
            return claim
        return await self.repository.replace_setup_claim_source(
            session,
            claim_id=claim.id,
            expected_claim_generation=claim.claim_generation,
            expected_source_revision=claim.source_revision,
            conversation_position_id=position.id,
            source_resource_id=source_resource.id,
            principal_id=principal_id,
            source_projection=source_projection,
            expires_at=now + _ACCESS_REQUEST_AGE,
        )

    async def _complete_setup_replay(
        self,
        session: AsyncSession,
        *,
        request: ExternalChannelIngestionRequest,
        conversation: _Conversation,
        now: datetime.datetime,
    ) -> None:
        """Complete one selected claim in the canonical acceptance transaction."""
        boundary = request.replay_boundary
        if not isinstance(boundary, ExternalChannelSetupReplayBoundary):
            return
        claim = conversation.setup_claim
        if claim is None:
            raise ValueError("External Channel setup replay claim is unavailable.")
        completed = await self.repository.complete_setup_claim(
            session,
            claim_id=claim.id,
            expected_claim_generation=boundary.expected_claim_generation,
            expected_selected_source_revision=boundary.selected_source_revision,
            completed_at=now,
        )
        if completed is None:
            raise ValueError("External Channel setup replay completion was fenced.")

    async def _resolve_route(
        self,
        session: AsyncSession,
        *,
        request: ExternalChannelIngestionRequest,
        connection: ExternalChannelConnection,
    ) -> ExternalChannelAgentRoute | None:
        if request.selected_route_id is not None:
            route = await self.repository.get_routable_route_by_id(
                session,
                route_id=request.selected_route_id,
            )
            if route is None or route.connection_id != connection.id:
                return None
            return route
        if connection.app_mode is ExternalChannelAppMode.SINGLE:
            return await self.repository.lock_routable_single_route(
                session,
                connection_id=connection.id,
            )
        return await self.repository.lock_routable_channel_default(
            session,
            connection_id=connection.id,
            provider_channel_id=_provider_parent_channel_id(request),
        )

    async def _ensure_principal(
        self,
        session: AsyncSession,
        *,
        request: ExternalChannelIngestionRequest,
    ) -> str:
        boundary = request.replay_boundary
        if boundary is not None:
            principal = await self.repository.get_principal(
                session,
                principal_id=boundary.principal_id,
            )
            if (
                principal is None
                or principal.provider is not request.locator.provider
                or principal.provider_tenant_id != request.locator.provider_tenant_id
                or principal.author_type is not ExternalChannelPrincipalAuthorType.HUMAN
                or (
                    request.locator.provider_user_id is not None
                    and principal.provider_user_id != request.locator.provider_user_id
                )
            ):
                raise ValueError(
                    "External Channel replay principal identity is unavailable."
                )
            return principal.id
        provider_user_id = request.locator.provider_user_id
        if provider_user_id is None:
            raise ValueError(
                "External Channel human principal identity is unavailable."
            )
        principal = await self.repository.create_principal_idempotent(
            session,
            ExternalChannelPrincipalCreate(
                provider=request.locator.provider,
                provider_tenant_id=request.locator.provider_tenant_id,
                provider_user_id=provider_user_id,
                author_type=ExternalChannelPrincipalAuthorType.HUMAN,
                display_name=None,
                avatar_url=None,
                profile=None,
            ),
        )
        return principal.id

    async def _ensure_selector(
        self,
        session: AsyncSession,
        *,
        request: ExternalChannelIngestionRequest,
        connection: ExternalChannelConnection,
        resource: ExternalChannelResource,
        position: ExternalChannelConversationPosition,
        principal_id: str,
        setup_claim_id: str | None,
        now: datetime.datetime,
    ) -> ExternalChannelInteraction:
        provider_key = selector_provider_interaction_key(
            connection_id=connection.id,
            trigger_provider_message_key=request.locator.trigger_provider_message_key,
        )
        existing = await self.repository.get_interaction_by_provider_key(
            session,
            connection_id=connection.id,
            provider_interaction_key=provider_key,
        )
        expected = ExternalChannelSelectorState(
            connection_id=connection.id,
            resource_id=resource.id,
            principal_id=principal_id,
            conversation_position_id=position.id,
            trigger_provider_message_key=request.locator.trigger_provider_message_key,
            range_start_position=position.read_through_position,
            trigger_position=request.locator.trigger_position,
            selected_route_id=None,
        )
        if existing is not None:
            state = selector_state_from_interaction(existing)
            if (
                state.model_copy(update={"selected_route_id": None}) != expected
                or existing.setup_claim_id != setup_claim_id
            ):
                raise ValueError("External Channel selector retry is incompatible.")
            return existing
        admitted = await self.repository.admit_interaction(
            session,
            ExternalChannelInteractionCreate(
                connection_id=connection.id,
                transport=connection.transport,
                provider_interaction_key=provider_key,
                interaction_type=ExternalChannelInteractionType.MANAGEMENT_ACTION,
                callback_id=None,
                action_id="agent_selector",
                principal_id=principal_id,
                setup_claim_id=setup_claim_id,
                resource_correlation_key=None,
                projection=projection_with_selector_state({}, expected),
                status=ExternalChannelInteractionStatus.ACCEPTED,
                expires_at=now + _ACCESS_REQUEST_AGE,
                error_kind=None,
                error_summary=None,
            ),
        )
        return admitted.interaction

    async def _create_binding(
        self,
        session: AsyncSession,
        *,
        route: ExternalChannelAgentRoute,
        resource: ExternalChannelResource,
        response_mode: ExternalChannelResponseMode | None,
    ) -> _BindingCreation:
        agent_id = route.require_active_agent_id()
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
        binding = await self.repository.create_binding_idempotent(
            session,
            ExternalChannelBindingCreate(
                resource_id=resource.id,
                route_id=route.id,
                agent_session_id=root.agent_session.id,
                response_mode=(
                    agent.external_channel_default_response_mode
                    if response_mode is None
                    else response_mode
                ),
                disconnected_at=None,
                disconnect_reason=None,
            ),
            expected_access_request_id=None,
        )
        return _BindingCreation(
            binding=binding,
            session_created=root.created,
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

    def _replay_source_matches(
        self,
        *,
        request: ExternalChannelIngestionRequest,
        resource: ExternalChannelResource,
    ) -> bool:
        boundary = request.replay_boundary
        if boundary is None:
            return True
        return (
            boundary.resource_id == resource.id
            and boundary.connection_id == resource.connection_id
            and boundary.trigger_provider_message_key
            == request.locator.trigger_provider_message_key
            and boundary.trigger_position == request.locator.trigger_position
        )

    async def _initialize_thread_position(
        self,
        session: AsyncSession,
        *,
        request: ExternalChannelIngestionRequest,
        resource: ExternalChannelResource,
        parent_position: ExternalChannelConversationPosition,
        trigger_position: str,
    ) -> None:
        delivery_thread_key = request.locator.delivery_thread_key
        if (
            request.locator.provider is ExternalChannelProvider.DISCORD
            and resource.labels is not None
        ):
            retained = resource.labels.get("delivery_channel_id")
            if isinstance(retained, str) and retained:
                delivery_thread_key = retained
        if (
            parent_position.scope_kind
            is not ExternalChannelConversationScopeKind.PARENT_CHANNEL
            or delivery_thread_key is None
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
                    else delivery_thread_key
                ),
                provider_thread_key=delivery_thread_key,
                read_through_position=(
                    trigger_position
                    if request.locator.provider is ExternalChannelProvider.SLACK
                    else None
                ),
            ),
        )

    async def _create_selector_control_intent(
        self,
        session: AsyncSession,
        *,
        request: ExternalChannelIngestionRequest,
        selector_id: str,
    ) -> str | None:
        delivery_channel_id = request.locator.delivery_thread_key
        if delivery_channel_id is None:
            raise RuntimeError("External Channel selector target is unavailable.")
        if request.locator.provider is ExternalChannelProvider.SLACK:
            payload: dict[str, object] = {
                "provider": "slack",
                "control_kind": "agent_selector",
                "tenant_id": request.locator.provider_tenant_id,
                "channel_id": request.locator.provider_channel_id,
                "thread_ts": delivery_channel_id,
                "selector_interaction_id": selector_id,
            }
        else:
            payload = {
                "provider": "discord",
                "control_kind": "agent_selector",
                "guild_id": request.locator.provider_tenant_id,
                "channel_id": delivery_channel_id,
                "selector_interaction_id": selector_id,
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
                                    selector_interaction_id=selector_id,
                                    action="open",
                                ),
                            }
                        ],
                    }
                ],
            }
        attempt = await self.repository.create_delivery_attempt_idempotent(
            session,
            ExternalChannelDeliveryAttemptCreate(
                origin_type=ExternalChannelDeliveryOriginType.MANAGER_OPERATION,
                origin_id=selector_id,
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
        return (
            attempt.id
            if attempt.status is ExternalChannelDeliveryStatus.PENDING
            else None
        )

    async def _create_access_control_intent(
        self,
        session: AsyncSession,
        *,
        request_id: str,
        request: ExternalChannelIngestionRequest,
        binding: ExternalChannelBinding | None,
        principal_provider_user_id: str,
        participant_label: str,
        now: datetime.datetime,
    ) -> str | None:
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
        else:
            channel_id = request.locator.delivery_thread_key
            if channel_id is None:
                raise RuntimeError(
                    "External Channel Discord access target is unavailable."
                )
            payload = {
                "provider": "discord",
                "guild_id": request.locator.provider_tenant_id,
                "channel_id": channel_id,
                "access_request_id": request_id,
                "participant_provider_user_id": principal_provider_user_id,
                "text": _render_discord_access_request_control(approval_url),
                "embeds": _discord_access_request_embeds() if approval_url else None,
                "components": (
                    _discord_link_button(label="Review access", url=approval_url)
                    if approval_url
                    else None
                ),
            }
            _add_discord_thread_provisioning(payload, request=request)
        attempt = await self.repository.create_delivery_attempt_idempotent(
            session,
            ExternalChannelDeliveryAttemptCreate(
                origin_type=ExternalChannelDeliveryOriginType.ACCESS_REQUEST,
                origin_id=request_id,
                channel_action_id=None,
                binding_id=None if binding is None else binding.id,
                operation=ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
                request_payload=payload,
                status=(
                    ExternalChannelDeliveryStatus.PENDING
                    if approval_url is not None
                    else ExternalChannelDeliveryStatus.NOT_ATTEMPTED
                ),
                provider_message_key=None,
                error_kind=None if approval_url else "web_url_unavailable",
                error_summary=None
                if approval_url
                else "Azents Web URL is not configured.",
                attempted_at=None,
                completed_at=None if approval_url else now,
            ),
        )
        return (
            attempt.id
            if attempt.status is ExternalChannelDeliveryStatus.PENDING
            else None
        )

    async def _create_session_presence_intent(
        self,
        session: AsyncSession,
        *,
        resource: ExternalChannelResource,
        binding: ExternalChannelBinding,
    ) -> str | None:
        attempt = await self.repository.create_delivery_attempt_idempotent(
            session,
            ExternalChannelDeliveryAttemptCreate(
                origin_type=ExternalChannelDeliveryOriginType.MANAGER_OPERATION,
                origin_id=binding.id,
                channel_action_id=None,
                binding_id=binding.id,
                operation=ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
                request_payload=session_presence_payload(
                    resource.labels,
                    state="joined",
                ),
                status=ExternalChannelDeliveryStatus.PENDING,
                provider_message_key=None,
                error_kind=None,
                error_summary=None,
                attempted_at=None,
                completed_at=None,
            ),
        )
        return (
            attempt.id
            if attempt.status is ExternalChannelDeliveryStatus.PENDING
            else None
        )

    async def _create_binding_settings_on_demand_intent(
        self,
        session: AsyncSession,
        *,
        resource: ExternalChannelResource,
        binding: ExternalChannelBinding,
    ) -> str | None:
        """Create settings access after the next eligible mention, at most once."""
        attempt = await self.repository.create_delivery_attempt_idempotent(
            session,
            ExternalChannelDeliveryAttemptCreate(
                origin_type=(
                    ExternalChannelDeliveryOriginType.BINDING_SETTINGS_AVAILABLE
                ),
                origin_id=binding.id,
                channel_action_id=None,
                binding_id=binding.id,
                operation=ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
                part_ordinal=3,
                request_payload=binding_settings_on_demand_payload(resource.labels),
                status=ExternalChannelDeliveryStatus.PENDING,
                provider_message_key=None,
                error_kind=None,
                error_summary=None,
                attempted_at=None,
                completed_at=None,
            ),
        )
        return (
            attempt.id
            if attempt.status is ExternalChannelDeliveryStatus.PENDING
            else None
        )

    async def _create_setup_control_intent(
        self,
        session: AsyncSession,
        *,
        resource: ExternalChannelResource,
        claim: ExternalChannelSetupClaim,
    ) -> str | None:
        """Create the current first-mention setup control once per source revision."""
        attempt = await self.repository.create_delivery_attempt_idempotent(
            session,
            ExternalChannelDeliveryAttemptCreate(
                origin_type=ExternalChannelDeliveryOriginType.SETUP_CLAIM,
                origin_id=claim.id,
                channel_action_id=None,
                binding_id=None,
                operation=ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
                part_ordinal=claim.source_revision,
                request_payload=setup_required_payload(
                    resource.labels,
                    setup_claim_id=claim.id,
                    claim_generation=claim.claim_generation,
                    source_revision=claim.source_revision,
                ),
                status=ExternalChannelDeliveryStatus.PENDING,
                provider_message_key=None,
                error_kind=None,
                error_summary=None,
                attempted_at=None,
                completed_at=None,
            ),
        )
        return (
            attempt.id
            if attempt.status is ExternalChannelDeliveryStatus.PENDING
            else None
        )

    async def _create_initial_progress_intent(
        self,
        session: AsyncSession,
        *,
        request: ExternalChannelIngestionRequest,
        resource: ExternalChannelResource,
        binding: ExternalChannelBinding,
        work: ExternalChannelWork,
    ) -> str | None:
        if request.locator.provider is ExternalChannelProvider.DISCORD:
            delivery_attempt_ids = (
                await self.work_repository.ensure_initial_discord_progress(
                    session,
                    work_id=work.id,
                    binding_id=binding.id,
                    labels=resource.labels,
                )
            )
            return delivery_attempt_ids[0] if delivery_attempt_ids else None
        presentation = render_slack_progress(
            checking_progress(),
            work_id=work.id,
            desired_progress_revision=work.desired_progress_revision,
        )
        thread_key = request.locator.delivery_thread_key
        if thread_key is None:
            raise RuntimeError("External Channel Slack progress target is unavailable.")
        attempt = await self.repository.create_delivery_attempt_idempotent(
            session,
            ExternalChannelDeliveryAttemptCreate(
                origin_type=ExternalChannelDeliveryOriginType.MANAGER_OPERATION,
                origin_id=work.id,
                channel_action_id=None,
                binding_id=binding.id,
                operation=ExternalChannelDeliveryOperation.PROGRESS_CREATE,
                request_payload={
                    "tenant_id": request.locator.provider_tenant_id,
                    "channel_id": request.locator.provider_channel_id,
                    "thread_ts": thread_key,
                    "work_id": work.id,
                    "text": presentation.text,
                    "blocks": presentation.blocks,
                    "desired_progress_revision": work.desired_progress_revision,
                },
                status=ExternalChannelDeliveryStatus.PENDING,
                provider_message_key=None,
                error_kind=None,
                error_summary=None,
                attempted_at=None,
                completed_at=None,
            ),
        )
        return (
            attempt.id
            if attempt.status is ExternalChannelDeliveryStatus.PENDING
            else None
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
            is ExternalChannelIngressProfile.SLACK_SOCKET
            and (
                request.authority.lease_owner is None
                or request.authority.lease_generation is not None
                or connection.socket_lease_owner != request.authority.lease_owner
                or connection.socket_lease_until is None
                or connection.socket_lease_until < now
            )
        ):
            return None
        if (
            request.authority.kind is ExternalChannelIngressAuthorityKind.LEASE
            and request.authority.ingress_profile
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

    async def _commit_ignored(
        self,
        session: AsyncSession,
        reason: ExternalChannelIngestionReason,
    ) -> ExternalChannelIngestionAcceptance:
        await session.commit()
        return ExternalChannelIngestionAcceptance(
            status="ignored",
            reason=reason,
            mailbox_item_id=None,
            session_id=None,
            control_delivery_attempt_id=None,
            connection_id=None,
        )


def _mailbox_idempotency_key(
    *,
    request: ExternalChannelIngestionRequest,
    position_id: str,
) -> str:
    digest = hashlib.sha256(
        "\0".join(
            (
                request.locator.connection_id,
                position_id,
                request.locator.trigger_provider_message_key,
                request.locator.trigger_position,
            )
        ).encode()
    ).hexdigest()
    return f"external-channel:{digest}"


def _invocation_projection(
    *,
    request: ExternalChannelIngestionRequest,
    history: ExternalChannelHistoryRange[ExternalChannelCanonicalHistoryMessage],
    resource: ExternalChannelResource,
    binding: ExternalChannelBinding,
    trigger_principal_id: str,
    invocation_id: str,
) -> list[ExternalChannelMailboxProjectionItem]:
    return [
        ExternalChannelMailboxProjectionItem(
            invocation_id=invocation_id,
            binding_id=binding.id,
            trigger_provider_message_key=(request.locator.trigger_provider_message_key),
            context_omitted=history.context_omitted,
            sequence=sequence,
            revision_kind=message.revision_kind,
            body=message.normalized_body,
            attachment_metadata=message.attachment_metadata,
            reference_mappings=message.reference_mappings,
            resource_id=resource.id,
            provider_resource_key=resource.provider_resource_key,
            resource_type=resource.resource_type,
            resource_labels=resource.labels,
            provider=request.locator.provider,
            provider_tenant_id=request.locator.provider_tenant_id,
            provider_message_key=message.provider_message_key,
            provider_position=message.provider_position,
            principal_id=(
                trigger_principal_id
                if message.provider_message_key
                == request.locator.trigger_provider_message_key
                else None
            ),
            provider_user_id=message.provider_user_id,
            sender_display_name=message.sender_display_name,
            author_type=message.author_type,
            provider_created_at=message.provider_created_at,
            provider_updated_at=message.provider_updated_at,
            original_url=message.original_url,
        )
        for sequence, message in enumerate(history.messages)
    ]


def _resource_labels(request: ExternalChannelIngestionRequest) -> dict[str, object]:
    locator = request.locator
    if locator.provider is ExternalChannelProvider.SLACK:
        return {
            "provider": "slack",
            "provider_event_type": locator.provider_event_type,
            "tenant_id": locator.provider_tenant_id,
            "channel_id": locator.provider_channel_id,
            "thread_ts": locator.delivery_thread_key,
        }
    delivery_thread_key = locator.delivery_thread_key
    provisioned_delivery_channel = (
        delivery_thread_key
        if locator.provider_thread_key is not None
        or delivery_thread_key != locator.trigger_provider_message_id
        else None
    )
    return {
        "provider": "discord",
        "provider_event_type": locator.provider_event_type,
        "guild_id": locator.provider_tenant_id,
        "source_channel_id": locator.provider_channel_id,
        "parent_channel_id": locator.provider_parent_channel_id,
        "root_message_id": locator.trigger_provider_message_id,
        "thread_id": delivery_thread_key,
        "delivery_channel_id": provisioned_delivery_channel,
    }


def _provider_parent_channel_id(
    request: ExternalChannelIngestionRequest,
) -> str:
    """Return the stable provider parent-channel identity."""
    value = request.locator.provider_parent_channel_id
    if value:
        return value
    if request.locator.provider is ExternalChannelProvider.SLACK:
        return request.locator.provider_channel_id
    if request.scope.kind is ExternalChannelConversationScopeKind.PARENT_CHANNEL:
        return request.scope.provider_channel_id
    raise ValueError("External Channel parent-channel identity is unavailable.")


def _parent_resource_labels(
    request: ExternalChannelIngestionRequest,
) -> dict[str, object]:
    """Build explicit labels for one first-class parent-channel Resource."""
    parent_channel_id = _provider_parent_channel_id(request)
    if request.locator.provider is ExternalChannelProvider.SLACK:
        return {
            "provider": "slack",
            "provider_event_type": request.locator.provider_event_type,
            "tenant_id": request.locator.provider_tenant_id,
            "channel_id": parent_channel_id,
            "conversation_scope": ExternalChannelResourceType.PARENT_CHANNEL.value,
        }
    return {
        "provider": "discord",
        "provider_event_type": request.locator.provider_event_type,
        "guild_id": request.locator.provider_tenant_id,
        "parent_channel_id": parent_channel_id,
        "source_channel_id": parent_channel_id,
        "conversation_scope": ExternalChannelResourceType.PARENT_CHANNEL.value,
    }


def _add_discord_thread_provisioning(
    payload: dict[str, object],
    *,
    request: ExternalChannelIngestionRequest,
) -> None:
    """Attach root-thread provisioning identity without provider credentials."""
    if (
        request.locator.provider_thread_key is not None
        or request.locator.delivery_thread_key
        != request.locator.trigger_provider_message_id
    ):
        return
    parent_channel_id = request.locator.provider_parent_channel_id
    root_message_id = request.locator.delivery_thread_key
    if parent_channel_id is None or root_message_id is None:
        raise RuntimeError("External Channel Discord thread target is unavailable.")
    payload["thread_parent_channel_id"] = parent_channel_id
    payload["thread_root_message_id"] = root_message_id


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
            mailbox_item_id=None,
            control_delivery_attempt_id=None,
            connection_id=None,
        ),
        wake_mailbox_item_id=None,
        wake_session_id=None,
        priority_request=None,
    )


def _position_mismatch() -> ExternalChannelIngestionAcceptance:
    return _rejected(
        ExternalChannelIngestionReason.POSITION_CHANGED,
        status="position_mismatch",
    )


def _rejected(
    reason: ExternalChannelIngestionReason,
    *,
    status: str = "terminal_rejection",
) -> ExternalChannelIngestionAcceptance:
    return ExternalChannelIngestionAcceptance(
        status=status,  # type: ignore[arg-type]
        reason=reason,
        mailbox_item_id=None,
        session_id=None,
        control_delivery_attempt_id=None,
        connection_id=None,
    )


def _route_has_automatic_access(route: ExternalChannelAgentRoute) -> bool:
    return route.open_access_enabled


def _response_mode_ignored_reason(
    *,
    request: ExternalChannelIngestionRequest,
    binding: ExternalChannelBinding | None,
) -> ExternalChannelIngestionReason | None:
    """Return why a current provider message cannot trigger shared ingestion."""
    if (
        request.operation is not ExternalChannelIngestionOperation.CURRENT_TRIGGER
        or request.locator.invocation
    ):
        return None
    if binding is None:
        return ExternalChannelIngestionReason.NOT_AN_INVOCATION
    if binding.response_mode is ExternalChannelResponseMode.MENTION_ONLY:
        return ExternalChannelIngestionReason.RESPONSE_MODE_NOT_TRIGGERED
    return None


def _approval_url(web_url: str, access_request_id: str) -> str | None:
    parsed = urlparse(web_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return urlunparse(
        parsed._replace(
            path=f"/external-channel/access/{quote(access_request_id)}",
            query="",
            fragment="",
        )
    )


def _render_discord_access_request_control(approval_url: str | None) -> str:
    if approval_url is None:
        return "Access approval is required in Azents Web."
    return "Access approval is required before this Agent can continue."


def _discord_access_request_embeds() -> list[dict[str, object]]:
    return [
        {
            "title": "Access approval required",
            "description": "Review this participant's access request in Azents Web.",
            "color": 0xF0B232,
        }
    ]


def _discord_link_button(*, label: str, url: str) -> list[dict[str, object]]:
    return [
        {
            "type": 1,
            "components": [{"type": 2, "style": 5, "label": label, "url": url}],
        }
    ]


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)
