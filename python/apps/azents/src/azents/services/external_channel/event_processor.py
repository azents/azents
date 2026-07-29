"""Durable External Channel event processing, hydration, and authorization."""

import asyncio
import dataclasses
import datetime
import logging
import secrets
from collections.abc import AsyncIterator
from typing import Annotated, Literal

import httpx
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.types import SessionWakeUp
from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.enums import (
    AgentLifecycleStatus,
    AgentSessionStartReason,
    ExternalChannelAccessRequestStatus,
    ExternalChannelAppMode,
    ExternalChannelBindingActivationStatus,
    ExternalChannelBindingStatus,
    ExternalChannelConnectionStatus,
    ExternalChannelConversationAdmissionOrigin,
    ExternalChannelConversationAdmissionStatus,
    ExternalChannelDeliveryOperation,
    ExternalChannelDeliveryOriginType,
    ExternalChannelDeliveryStatus,
    ExternalChannelEventEligibilityState,
    ExternalChannelEventStatus,
    ExternalChannelHydrationStatus,
    ExternalChannelMessageRevisionKind,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
    MailboxItemKind,
    MailboxSchedulingMode,
)
from azents.core.external_channel_progress import checking_progress
from azents.core.slack_external_channel_progress import (
    SlackProgressPresentation,
    render_slack_persisted_progress,
    render_slack_progress,
    render_slack_session_link,
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
    ExternalChannelConnectionConfiguration,
    ExternalChannelConversationAdmission,
    ExternalChannelConversationAdmissionCreate,
    ExternalChannelDeliveryAttemptCreate,
    ExternalChannelEvent,
    ExternalChannelEventBoundary,
    ExternalChannelInvocationBatch,
    ExternalChannelInvocationBatchCreate,
    ExternalChannelInvocationBatchItemCreate,
    ExternalChannelMessage,
    ExternalChannelMessageCreate,
    ExternalChannelMessageRevisionCreate,
    ExternalChannelPendingContextCreate,
    ExternalChannelPendingContextTrim,
    ExternalChannelPrincipalCreate,
    ExternalChannelResource,
    ExternalChannelResourceCreate,
    ExternalChannelWork,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.external_channel.work import ExternalChannelWorkRepository
from azents.repos.external_channel.work_data import ChannelDeliveryTarget
from azents.repos.workspace import WorkspaceRepository
from azents.services.external_channel.channel_action import (
    ExternalChannelActionService,
)
from azents.services.external_channel.connection import (
    get_external_channel_credentials_codec,
)
from azents.services.external_channel.credentials import ExternalChannelCredentialsCodec
from azents.services.external_channel.discord_events import (
    DiscordEventExcluded,
    DiscordEventNormalizationError,
    DiscordMessageContentUnavailable,
    DiscordNormalizedMessage,
    normalize_projected_discord_event,
)
from azents.services.external_channel.discord_history import (
    DiscordConversationHistoryClient,
    DiscordHistoryCredentialsInvalid,
    DiscordHistoryPermissionDenied,
    DiscordHistoryProviderError,
    DiscordHistoryRateLimited,
    DiscordHistoryResourceUnavailable,
    DiscordHistoryResponseMalformed,
)
from azents.services.external_channel.discord_selector_scope import (
    build_discord_selector_custom_id,
)
from azents.services.external_channel.presentation import (
    normalize_slack_agent_name,
    prepend_agent_blocks,
    prepend_agent_fallback,
    resolve_slack_agent_name_presentation,
    resolve_slack_agent_presentation,
)
from azents.services.external_channel.slack_events import (
    SlackConnectionRevocation,
    SlackConversationAccess,
    SlackConversationClient,
    SlackEventExcluded,
    SlackEventNormalizationError,
    SlackNormalizedMessage,
    SlackProviderCredentialsInvalid,
    SlackProviderPermissionDenied,
    SlackProviderRateLimited,
    SlackProviderResourceUnavailable,
    SlackProviderTemporaryError,
    normalize_projected_slack_event,
    slack_message_reference_ids,
)
from azents.services.external_channel.slack_sdk_client import create_slack_web_client
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
from azents.worker.session.lifecycle import SessionLifecycleService

logger = logging.getLogger(__name__)

_EVENT_CLAIM_DURATION = datetime.timedelta(minutes=10)
_UNLINKED_EVENT_WAIT = datetime.timedelta(minutes=5)
_PENDING_CONTEXT_AGE = datetime.timedelta(days=7)
_PENDING_CONTEXT_MAX_MESSAGES = 100
_PENDING_CONTEXT_MAX_SIZE = 256 * 1024
_ACCESS_REQUEST_AGE = datetime.timedelta(days=7)
_EVENT_BATCH_SIZE = 20
_WAITING_BINDING_BATCH_SIZE = 20
_HYDRATION_PAGE_SIZE = 100
_HYDRATION_MAX_PAGES = 20
_IDLE_POLL_SECONDS = 0.5
_MAX_RETRY_SECONDS = 300


async def get_slack_processing_http_client() -> AsyncIterator[httpx.AsyncClient]:
    """Provide bounded Slack private-file HTTP transport."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        yield client


def get_slack_conversation_client(
    http_client: Annotated[
        httpx.AsyncClient,
        Depends(get_slack_processing_http_client),
    ],
) -> SlackConversationClient:
    """Provide the Slack conversation adapter."""
    return SlackConversationClient(
        web_client=create_slack_web_client(),
        http_client=http_client,
    )


async def get_discord_history_http_client() -> AsyncIterator[httpx.AsyncClient]:
    """Provide bounded Discord history-hydration HTTP transport."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        yield client


def get_discord_conversation_history_client(
    http_client: Annotated[
        httpx.AsyncClient,
        Depends(get_discord_history_http_client),
    ],
) -> DiscordConversationHistoryClient:
    """Provide the Discord bounded-history adapter."""
    return DiscordConversationHistoryClient(http_client)


@dataclasses.dataclass(frozen=True)
class ExternalChannelPersistedMessage:
    """Committed message-domain effects needed after the transaction."""

    resource_id: str
    hydration_required: bool
    control_delivery_attempt_id: str | None
    activity_delivery_attempt_id: str | None
    wake_up: SessionWakeUp | None


@dataclasses.dataclass(frozen=True)
class ExternalChannelReleasedInvocation:
    """Committed invocation batch and optional initial Tracker intent."""

    batch: ExternalChannelInvocationBatch
    session_link_delivery_attempt_id: str | None
    activity_delivery_attempt_id: str | None


@dataclasses.dataclass(frozen=True)
class ExternalChannelPersistedRevision:
    """One normalized revision application and pending-context result."""

    message: ExternalChannelMessage
    trim: ExternalChannelPendingContextTrim
    applied: bool


@dataclasses.dataclass(frozen=True)
class ExternalChannelSelectedAdmissionContinuation:
    """Committed post-selection state with an optional approval-control delivery."""

    status: Literal["bound", "awaiting_access", "already_bound", "expired", "rejected"]
    control_delivery_attempt_id: str | None


@dataclasses.dataclass(frozen=True)
class _SlackSelectorControlPresentation:
    """One bounded thread control that opens the shared Agent selector."""

    text: str
    blocks: list[dict[str, object]]


@dataclasses.dataclass
class _DeferredEvent(Exception):
    """Controlled event deferral with a stable retry reason."""

    retry_at: datetime.datetime
    error_kind: str
    error_summary: str


@dataclasses.dataclass
class _ConnectionUnavailable(Exception):
    """Provider processing cannot continue until connection health recovers."""

    reason: str


class _HydrationRoutingUnavailable(Exception):
    """Hydration cannot continue after routing eligibility is lost."""


@dataclasses.dataclass
class ExternalChannelEventProcessorService:
    """Claim admitted provider events and apply idempotent domain effects."""

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
    action_service: Annotated[
        ExternalChannelActionService,
        Depends(ExternalChannelActionService),
    ]
    credentials_codec: Annotated[
        ExternalChannelCredentialsCodec,
        Depends(get_external_channel_credentials_codec),
    ]
    slack_client: Annotated[
        SlackConversationClient,
        Depends(get_slack_conversation_client),
    ]
    discord_history_client: Annotated[
        DiscordConversationHistoryClient,
        Depends(get_discord_conversation_history_client),
    ]
    agent_repository: Annotated[
        AgentRepository,
        Depends(AgentRepository),
    ]
    agent_session_repository: Annotated[
        AgentSessionRepository,
        Depends(AgentSessionRepository),
    ]
    root_agent_session_creation_service: Annotated[
        RootAgentSessionCreationService,
        Depends(RootAgentSessionCreationService),
    ]
    workspace_repository: Annotated[
        WorkspaceRepository,
        Depends(WorkspaceRepository),
    ]
    config: Annotated[Config, Depends(get_config)]
    mailbox_item_service: Annotated[
        MailboxService,
        Depends(MailboxService),
    ]
    session_lifecycle: Annotated[
        SessionLifecycleService,
        Depends(SessionLifecycleService),
    ]
    claim_owner: str = dataclasses.field(
        init=False,
        default_factory=lambda: f"external-channel-{secrets.token_hex(8)}",
    )

    async def run(self, shutdown_event: asyncio.Event) -> None:
        """Process admitted events and approval activations until shutdown."""
        while not shutdown_event.is_set():
            try:
                processed = await self.process_once()
                reconciled = await self.reconcile_waiting_bindings()
            except Exception:
                logger.exception("External Channel event processor iteration failed")
                processed = 0
                reconciled = 0
            if processed or reconciled:
                continue
            try:
                await asyncio.wait_for(
                    shutdown_event.wait(),
                    timeout=_IDLE_POLL_SECONDS,
                )
            except TimeoutError:
                continue

    async def process_once(self) -> int:
        """Claim and process one bounded event batch."""
        now = _now()
        async with self.session_manager() as session:
            events = await self.repository.claim_events(
                session,
                claim_owner=self.claim_owner,
                now=now,
                claim_until=now + _EVENT_CLAIM_DURATION,
                limit=_EVENT_BATCH_SIZE,
            )
            await session.commit()
        for event in events:
            await self._process_claimed_event_safely(event)
        return len(events)

    async def continue_selected_admission(
        self,
        *,
        admission_id: str,
        principal_id: str,
        now: datetime.datetime,
    ) -> ExternalChannelSelectedAdmissionContinuation:
        """Continue one selected source through existing grant or approval policy."""
        async with self.session_manager() as session:
            snapshot = await self.repository.get_conversation_admission(
                session,
                admission_id=admission_id,
            )
            if snapshot is None:
                raise SlackEventExcluded("The selected Slack admission is unavailable.")
            connection = await self.repository.lock_connection_for_routing(
                session,
                connection_id=snapshot.connection_id,
            )
            if connection is None:
                raise SlackEventExcluded(
                    "The selected Slack connection is unavailable."
                )
            if snapshot.selected_route_id is None:
                raise SlackEventExcluded("The selected Slack route is unavailable.")
            route = await self.repository.get_routable_route_by_id(
                session,
                route_id=snapshot.selected_route_id,
            )
            if route is None or route.connection_id != connection.id:
                raise SlackEventExcluded("The selected Slack route is unavailable.")
            resource = await self.repository.lock_resource(
                session,
                resource_id=snapshot.resource_id,
            )
            if resource is None or resource.connection_id != connection.id:
                raise SlackEventExcluded("The selected Slack resource is unavailable.")
            binding = await self.repository.lock_active_binding_by_resource(
                session,
                resource_id=resource.id,
            )
            admission = await self.repository.lock_open_conversation_admission(
                session,
                resource_id=resource.id,
            )
            if (
                admission is None
                or admission.id != snapshot.id
                or admission.initiating_principal_id != principal_id
                or admission.selected_route_id != route.id
                or admission.status
                is not ExternalChannelConversationAdmissionStatus.SELECTED
            ):
                raise SlackEventExcluded("The selected Slack admission changed.")
            if admission.expires_at <= now:
                await self.repository.transition_conversation_admission(
                    session,
                    admission_id=admission.id,
                    status=ExternalChannelConversationAdmissionStatus.EXPIRED,
                    selected_route_id=route.id,
                )
                await session.commit()
                return ExternalChannelSelectedAdmissionContinuation(
                    status="expired",
                    control_delivery_attempt_id=None,
                )
            if binding is not None:
                await session.commit()
                return ExternalChannelSelectedAdmissionContinuation(
                    status="already_bound",
                    control_delivery_attempt_id=None,
                )
            source_message = await self.repository.get_message(
                session,
                message_id=admission.source_message_id,
            )
            if (
                source_message is None
                or source_message.resource_id != resource.id
                or source_message.current_revision_id is None
            ):
                await self.repository.transition_conversation_admission(
                    session,
                    admission_id=admission.id,
                    status=ExternalChannelConversationAdmissionStatus.REJECTED,
                    selected_route_id=route.id,
                )
                await session.commit()
                return ExternalChannelSelectedAdmissionContinuation(
                    status="rejected",
                    control_delivery_attempt_id=None,
                )
            active_agent_id = route.require_active_agent_id()
            if (
                await self.repository.get_active_block(
                    session,
                    agent_id=active_agent_id,
                    principal_id=principal_id,
                )
                is not None
            ):
                await self.repository.transition_conversation_admission(
                    session,
                    admission_id=admission.id,
                    status=ExternalChannelConversationAdmissionStatus.REJECTED,
                    selected_route_id=route.id,
                )
                await session.commit()
                return ExternalChannelSelectedAdmissionContinuation(
                    status="rejected",
                    control_delivery_attempt_id=None,
                )
            trim = await self._project_current_revision(
                session,
                route=route,
                resource=resource,
                message=source_message,
                provider_position=source_message.provider_position,
                now=now,
                applied=True,
            )
            grant = await self.repository.get_active_access_grant(
                session,
                agent_id=active_agent_id,
                principal_id=principal_id,
                agent_session_id=None,
            )
            if grant is not None or _route_has_automatic_access(
                route,
                source_message.author_type,
            ):
                binding = await self._create_granted_initial_binding(
                    session,
                    route=route,
                    resource=resource,
                    trigger_message=source_message,
                    expected_admission_id=admission.id,
                    provider=connection.provider,
                    now=now,
                )
                await self._record_trim(
                    session,
                    route=route,
                    resource=resource,
                    binding=binding,
                    trim=trim,
                )
                await self.repository.transition_conversation_admission(
                    session,
                    admission_id=admission.id,
                    status=ExternalChannelConversationAdmissionStatus.BOUND,
                    selected_route_id=route.id,
                )
                await session.commit()
                return ExternalChannelSelectedAdmissionContinuation(
                    status="bound",
                    control_delivery_attempt_id=None,
                )
            principal = await self.repository.get_principal(
                session,
                principal_id=principal_id,
            )
            if principal is None or not principal.provider_user_id:
                excluded = (
                    DiscordEventExcluded
                    if connection.provider is ExternalChannelProvider.DISCORD
                    else SlackEventExcluded
                )
                raise excluded("The selected external-channel source is unavailable.")
            if connection.provider is ExternalChannelProvider.DISCORD:
                try:
                    target = _provider_thread_target(resource)
                except RuntimeError as error:
                    raise DiscordEventExcluded(
                        "The selected external-channel source is unavailable."
                    ) from error
                tenant_id = target.get("guild_id")
                channel_id = target.get("channel_id")
                thread_ts = None
                if (
                    not isinstance(tenant_id, str)
                    or not tenant_id
                    or not isinstance(channel_id, str)
                    or not channel_id
                ):
                    raise DiscordEventExcluded(
                        "The selected external-channel source is unavailable."
                    )
            else:
                labels = resource.labels or {}
                tenant_id = labels.get("tenant_id")
                channel_id = labels.get("channel_id")
                thread_ts = labels.get("thread_ts")
                if (
                    not isinstance(tenant_id, str)
                    or not tenant_id
                    or not isinstance(channel_id, str)
                    or not channel_id
                    or not isinstance(thread_ts, str)
                    or not thread_ts
                ):
                    raise SlackEventExcluded(
                        "The selected external-channel source is unavailable."
                    )
            control_delivery_attempt_id = (
                await self._create_access_request_and_control_intent(
                    session,
                    route=route,
                    resource=resource,
                    binding=None,
                    source_message=source_message,
                    principal_id=principal_id,
                    participant_provider_user_id=principal.provider_user_id,
                    participant_label=(
                        principal.display_name or principal.provider_user_id
                    ),
                    tenant_id=tenant_id,
                    channel_id=channel_id,
                    thread_ts=thread_ts,
                    trim=trim,
                    now=now,
                    provider=connection.provider,
                )
            )
            await self.repository.transition_conversation_admission(
                session,
                admission_id=admission.id,
                status=ExternalChannelConversationAdmissionStatus.AWAITING_ACCESS,
                selected_route_id=route.id,
            )
            await session.commit()
            return ExternalChannelSelectedAdmissionContinuation(
                status="awaiting_access",
                control_delivery_attempt_id=control_delivery_attempt_id,
            )

    async def attempt_selected_admission_control_delivery(
        self,
        *,
        connection_id: str,
        delivery_attempt_id: str,
    ) -> None:
        """Attempt one committed post-selection approval control without a DB lock."""
        configuration = await self._connection_configuration(connection_id)
        if configuration.encrypted_credentials is None:
            raise RuntimeError("External Channel delivery credentials are unavailable.")
        credentials = self.credentials_codec.decrypt(
            configuration.encrypted_credentials
        )
        if configuration.provider is ExternalChannelProvider.DISCORD:
            await self.action_service.attempt_delivery(delivery_attempt_id)
        else:
            await self._attempt_control_delivery(
                configuration=configuration,
                delivery_attempt_id=delivery_attempt_id,
                bot_token=credentials.bot_token,
            )

    async def reconcile_waiting_bindings(self) -> int:
        """Activate allowed bindings only after hydration reconciliation completes."""
        async with self.session_manager() as session:
            binding_ids = await self.repository.list_waiting_binding_ids(
                session,
                limit=_WAITING_BINDING_BATCH_SIZE,
            )
        reconciled = 0
        for binding_id in binding_ids:
            await self._hydrate_waiting_discord_binding(binding_id=binding_id)
            if await self.reconcile_binding(binding_id=binding_id):
                reconciled += 1
        return reconciled

    async def _hydrate_waiting_discord_binding(self, *, binding_id: str) -> None:
        """Start deferred Discord history only after a durable binding exists."""
        async with self.session_manager() as session:
            binding = await self.repository.get_binding(session, binding_id=binding_id)
            if binding is None:
                return
            route = await self.repository.get_agent_route(
                session,
                route_id=binding.route_id,
            )
            resource = await self.repository.get_resource(
                session,
                resource_id=binding.resource_id,
            )
            if (
                route is None
                or resource is None
                or _hydration_terminal(resource.hydration_status)
            ):
                return
            configuration = await self.repository.get_connection_configuration(
                session,
                connection_id=route.connection_id,
            )
        if (
            configuration is None
            or configuration.provider is not ExternalChannelProvider.DISCORD
            or configuration.encrypted_credentials is None
        ):
            return
        credentials = self.credentials_codec.decrypt(
            configuration.encrypted_credentials
        )
        try:
            await self._hydrate_discord_resource(
                configuration=configuration,
                resource_id=resource.id,
                bot_token=credentials.bot_token,
            )
        except DiscordHistoryRateLimited:
            logger.info(
                "Deferred Discord waiting-binding hydration due to rate limiting",
                extra={"external_channel_binding_id": binding_id},
            )
        except DiscordHistoryPermissionDenied:
            await self._mark_connection_reconnect_required(
                connection_id=configuration.id,
                reason="permission_denied",
            )
        except DiscordHistoryCredentialsInvalid:
            await self._mark_connection_reconnect_required(
                connection_id=configuration.id,
                reason="credentials_invalid",
            )
        except DiscordHistoryResponseMalformed:
            await self._complete_hydration(
                configuration=configuration,
                resource_id=resource.id,
                status=ExternalChannelHydrationStatus.INCOMPLETE,
                error_kind="response_malformed",
                error_summary=(
                    "Discord history response failed safe boundary validation."
                ),
            )
        except DiscordHistoryProviderError:
            logger.info(
                "Deferred Discord waiting-binding hydration is temporarily unavailable",
                extra={"external_channel_binding_id": binding_id},
            )

    async def reconcile_binding(self, *, binding_id: str) -> bool:
        """Create the initial invocation batch when every activation fence passes."""
        now = _now()
        async with self.session_manager() as session:
            binding_snapshot = await self.repository.get_binding(
                session,
                binding_id=binding_id,
            )
            if binding_snapshot is None:
                return False
            route_snapshot = await self.repository.get_agent_route(
                session,
                route_id=binding_snapshot.route_id,
            )
            if route_snapshot is None:
                return False
            connection = await self.repository.lock_connection_for_routing(
                session,
                connection_id=route_snapshot.connection_id,
            )
            if connection is None:
                return False
            route = await self.repository.get_routable_route_by_id(
                session,
                route_id=binding_snapshot.route_id,
            )
            if route is None or route.connection_id != connection.id:
                return False
            active_agent_id = route.require_active_agent_id()
            resource = await self.repository.lock_resource(
                session,
                resource_id=binding_snapshot.resource_id,
            )
            if resource is None:
                return False
            binding = await self.repository.lock_binding(
                session,
                binding_id=binding_id,
            )
            if (
                binding is None
                or binding.status is not ExternalChannelBindingStatus.ACTIVE
                or binding.activation_status
                not in (
                    ExternalChannelBindingActivationStatus.WAITING_HYDRATION,
                    ExternalChannelBindingActivationStatus.WAKE_PENDING,
                )
                or binding.activation_trigger_message_id is None
                or binding.route_id != route.id
                or binding.resource_id != resource.id
            ):
                return False
            if not _hydration_activation_ready(resource.hydration_status):
                return False
            boundary = _resource_boundary(resource)
            if boundary is None:
                return False
            if binding.route_id != route.id:
                return False
            unresolved = await self.repository.correlated_event_count_before_boundary(
                session,
                connection_id=route.connection_id,
                resource_correlation_key=_resource_correlation_key(resource),
                boundary=boundary,
                terminal=False,
            )
            if unresolved:
                return False
            trigger = await self.repository.get_message(
                session,
                message_id=binding.activation_trigger_message_id,
            )
            if trigger is None or trigger.principal_id is None:
                return False
            if (
                await self.repository.get_active_block(
                    session,
                    agent_id=active_agent_id,
                    principal_id=trigger.principal_id,
                )
                is not None
            ):
                return False
            grant = await self.repository.get_active_access_grant(
                session,
                agent_id=active_agent_id,
                principal_id=trigger.principal_id,
                agent_session_id=binding.agent_session_id,
            )
            if grant is None and not _route_has_automatic_access(
                route,
                trigger.author_type,
            ):
                return False
            configuration = await self.repository.get_connection_configuration(
                session,
                connection_id=route.connection_id,
            )
            if configuration is None or configuration.encrypted_credentials is None:
                return False
            if (
                binding.activation_status
                is ExternalChannelBindingActivationStatus.WAKE_PENDING
            ):
                if configuration.provider is not ExternalChannelProvider.DISCORD:
                    return False
                projected_position = binding.projected_through_position
                if projected_position is None:
                    return False
                await session.commit()
                return await self._wake_discord_binding(
                    binding_id=binding.id,
                    agent_session_id=binding.agent_session_id,
                    projected_through_position=projected_position,
                )
            released = await self._release_pending_context(
                session,
                binding=binding,
                trigger_message_id=trigger.id,
                now=now,
                initial_activation=True,
                workspace_id=configuration.workspace_id,
                agent_id=active_agent_id,
                provider=configuration.provider,
            )
            if released is None:
                return False
            await session.commit()
            if configuration.provider is ExternalChannelProvider.DISCORD:
                await self._attempt_discord_initial_deliveries(
                    binding_id=binding.id,
                )
                if not await self._discord_initial_deliveries_delivered(
                    binding_id=binding.id,
                ):
                    return False
                return await self._wake_discord_binding(
                    binding_id=binding.id,
                    agent_session_id=binding.agent_session_id,
                    projected_through_position=released.batch.last_provider_position,
                )
            await self.session_lifecycle.mark_session_running_for_input_wakeup(
                binding.agent_session_id
            )
            await self.session_lifecycle.send_session_wake_up(
                SessionWakeUp(session_id=binding.agent_session_id)
            )
            credentials = None
            if (
                released.session_link_delivery_attempt_id is not None
                or released.activity_delivery_attempt_id is not None
            ):
                credentials = self.credentials_codec.decrypt(
                    configuration.encrypted_credentials
                )
            if released.session_link_delivery_attempt_id is not None:
                if credentials is None:
                    raise RuntimeError(
                        "External Channel delivery credentials are unavailable."
                    )
                await self._attempt_session_link_delivery(
                    configuration=configuration,
                    delivery_attempt_id=released.session_link_delivery_attempt_id,
                    bot_token=credentials.bot_token,
                )
            if released.activity_delivery_attempt_id is not None:
                if credentials is None:
                    raise RuntimeError(
                        "External Channel delivery credentials are unavailable."
                    )
                await self._attempt_activity_delivery(
                    configuration=configuration,
                    delivery_attempt_id=released.activity_delivery_attempt_id,
                    bot_token=credentials.bot_token,
                )
            return await self._activate_binding_after_wake(
                binding_id=binding.id,
                now=now,
                projected_through_position=released.batch.last_provider_position,
            )

    async def _wake_discord_binding(
        self,
        *,
        binding_id: str,
        agent_session_id: str,
        projected_through_position: str,
    ) -> bool:
        """Claim, durably wake, and activate one Discord binding."""
        claim_now = _now()
        async with self.session_manager() as session:
            binding, should_wake = await self.repository.claim_binding_wake(
                session,
                binding_id=binding_id,
                now=claim_now,
                projected_through_position=projected_through_position,
            )
            if binding is None:
                await session.rollback()
                return False
            if not should_wake:
                await session.commit()
                return False
            await self.agent_session_repository.mark_running_for_input_wakeup(
                session,
                agent_session_id,
            )
            await session.commit()
        await self.session_lifecycle.send_session_wake_up(
            SessionWakeUp(session_id=agent_session_id)
        )
        return await self._activate_binding_after_wake(
            binding_id=binding_id,
            now=_now(),
            projected_through_position=projected_through_position,
        )

    async def _attempt_discord_initial_deliveries(
        self,
        *,
        binding_id: str,
    ) -> None:
        """Attempt pending initial Discord intents without replaying terminal rows."""
        async with self.session_manager() as session:
            attempts = await self.repository.list_initial_delivery_attempts(
                session,
                binding_id=binding_id,
            )
        for attempt in attempts:
            if attempt.status is not ExternalChannelDeliveryStatus.PENDING:
                continue
            await self.action_service.attempt_delivery(attempt.id)

    async def _discord_initial_deliveries_delivered(
        self,
        *,
        binding_id: str,
    ) -> bool:
        """Require the Session link and every initial progress part to be delivered."""
        async with self.session_manager() as session:
            attempts = await self.repository.list_initial_delivery_attempts(
                session,
                binding_id=binding_id,
            )
        return bool(attempts) and all(
            attempt.status is ExternalChannelDeliveryStatus.DELIVERED
            for attempt in attempts
        )

    async def _process_claimed_event_safely(
        self,
        event: ExternalChannelEvent,
    ) -> None:
        try:
            await self._process_claimed_event(event)
        except (SlackEventExcluded, DiscordEventExcluded) as error:
            await self._complete_event(
                event,
                eligibility_state=ExternalChannelEventEligibilityState.IGNORED,
                status=ExternalChannelEventStatus.IGNORED_UNLINKED,
                purge_envelope=True,
            )
            logger.info(
                "Ignored out-of-scope Slack event",
                extra={
                    "external_channel_event_id": event.id,
                    "reason": str(error),
                },
            )
        except (SlackEventNormalizationError, DiscordEventNormalizationError) as error:
            await self._complete_event(
                event,
                eligibility_state=ExternalChannelEventEligibilityState.IGNORED,
                status=ExternalChannelEventStatus.IGNORED_UNLINKED,
                purge_envelope=True,
            )
            logger.info(
                "Ignored malformed Slack event",
                extra={
                    "external_channel_event_id": event.id,
                    "reason": str(error),
                },
            )
        except _DeferredEvent as error:
            async with self.session_manager() as session:
                await self.repository.defer_event(
                    session,
                    event_id=event.id,
                    claim_owner=self.claim_owner,
                    now=_now(),
                    retry_at=error.retry_at,
                    error_kind=error.error_kind,
                    error_summary=error.error_summary,
                )
                await session.commit()
        except _ConnectionUnavailable:
            await self._complete_event(
                event,
                eligibility_state=ExternalChannelEventEligibilityState.PROCESSED,
                status=ExternalChannelEventStatus.PROCESSED,
                purge_envelope=False,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "External Channel event processing failed",
                extra={
                    "external_channel_event_id": event.id,
                    "attempt_count": event.attempt_count,
                },
            )
            now = _now()
            async with self.session_manager() as session:
                await self.repository.fail_event(
                    session,
                    event_id=event.id,
                    claim_owner=self.claim_owner,
                    now=now,
                    retry_at=now + _retry_delay(event.attempt_count),
                    error_kind="processor_error",
                    error_summary="External Channel event processing failed.",
                )
                await session.commit()

    async def _process_claimed_event(self, event: ExternalChannelEvent) -> None:
        configuration = await self._connection_configuration(event.connection_id)
        if configuration.provider is ExternalChannelProvider.DISCORD:
            await self._process_discord_claimed_event(
                event=event,
                configuration=configuration,
            )
            return
        if configuration.provider is not ExternalChannelProvider.SLACK:
            raise SlackEventExcluded("External Channel provider is not supported.")
        if configuration.encrypted_credentials is None:
            raise SlackEventExcluded("External Channel credentials are unavailable.")
        if event.provider_tenant_id is None:
            raise SlackEventNormalizationError("Slack tenant identity is missing.")
        credentials = self.credentials_codec.decrypt(
            configuration.encrypted_credentials
        )
        normalized = normalize_projected_slack_event(
            event_type=event.event_type,
            tenant_id=event.provider_tenant_id,
            envelope=event.envelope,
        )
        if isinstance(normalized, SlackConnectionRevocation):
            await self._apply_connection_revocation(
                event=event,
                revocation=normalized,
            )
            return
        access: SlackConversationAccess | None = None
        original_url = None
        if normalized.invocation:
            access = await self._validate_invocation_channel(
                event=event,
                message=normalized,
                bot_token=credentials.bot_token,
            )
            original_url = await self._resolve_original_url(
                message=normalized,
                bot_token=credentials.bot_token,
            )
        reference_mappings = await self._resolve_reference_mappings(
            message=normalized,
            bot_token=credentials.bot_token,
            channel_display_name=None if access is None else access.display_name,
            cache={"users": {}, "channels": {}},
        )

        persisted = await self._persist_message_event(
            event=event,
            configuration=configuration,
            message=normalized,
            original_url=original_url,
            channel_display_name=None if access is None else access.display_name,
            reference_mappings=reference_mappings,
        )
        if persisted.control_delivery_attempt_id is not None:
            await self._attempt_control_delivery(
                configuration=configuration,
                delivery_attempt_id=persisted.control_delivery_attempt_id,
                bot_token=credentials.bot_token,
            )
        if persisted.activity_delivery_attempt_id is not None:
            await self._attempt_activity_delivery(
                configuration=configuration,
                delivery_attempt_id=persisted.activity_delivery_attempt_id,
                bot_token=credentials.bot_token,
            )
        if persisted.wake_up is not None:
            await self.session_lifecycle.mark_session_running_for_input_wakeup(
                persisted.wake_up.session_id
            )
            await self.session_lifecycle.send_session_wake_up(persisted.wake_up)
        if persisted.hydration_required:
            try:
                await self._hydrate_resource(
                    event=event,
                    configuration=configuration,
                    resource_id=persisted.resource_id,
                    bot_token=credentials.bot_token,
                )
            except SlackProviderRateLimited as error:
                now = _now()
                raise _DeferredEvent(
                    retry_at=now
                    + datetime.timedelta(seconds=error.retry_after_seconds),
                    error_kind="slack_rate_limited",
                    error_summary="Slack delayed inbound thread hydration.",
                ) from error
            except SlackProviderTemporaryError as error:
                now = _now()
                raise _DeferredEvent(
                    retry_at=now + _retry_delay(event.attempt_count),
                    error_kind="slack_temporarily_unavailable",
                    error_summary="Slack thread hydration is temporarily unavailable.",
                ) from error
            except SlackProviderPermissionDenied as error:
                await self._mark_connection_reconnect_required(
                    connection_id=event.connection_id,
                    reason="missing_scope",
                )
                raise _ConnectionUnavailable("missing_scope") from error
            except SlackProviderCredentialsInvalid as error:
                await self._mark_connection_reconnect_required(
                    connection_id=event.connection_id,
                    reason="credentials_invalid",
                )
                raise _ConnectionUnavailable("credentials_invalid") from error

        await self._complete_event(
            event,
            eligibility_state=ExternalChannelEventEligibilityState.PROCESSED,
            status=ExternalChannelEventStatus.PROCESSED,
            purge_envelope=False,
        )

    async def _process_discord_claimed_event(
        self,
        *,
        event: ExternalChannelEvent,
        configuration: ExternalChannelConnectionConfiguration,
    ) -> None:
        """Persist, authorize, and release one eligible Discord message."""
        tenant_id = configuration.provider_tenant_id
        if tenant_id is None:
            raise DiscordEventNormalizationError(
                "Discord connection Guild identity is missing."
            )
        try:
            normalized = normalize_projected_discord_event(
                event_type=event.event_type,
                tenant_id=tenant_id,
                envelope=event.envelope,
                connected_bot_user_id=configuration.provider_bot_user_id,
            )
        except DiscordMessageContentUnavailable as error:
            await self._mark_connection_reconnect_required(
                connection_id=event.connection_id,
                reason="discord_message_content_unavailable",
            )
            raise _ConnectionUnavailable(
                "discord_message_content_unavailable"
            ) from error
        if normalized.author_type is ExternalChannelPrincipalAuthorType.SYSTEM:
            raise DiscordEventExcluded("Discord system messages are ignored.")
        if connection_authored(configuration, normalized):
            raise DiscordEventExcluded(
                "Connection-authored Discord message was ignored."
            )
        existing_resource_key = _discord_resource_key(
            tenant_id=tenant_id,
            thread_id=normalized.thread_id or normalized.channel_id,
        )
        now = _now()
        async with self.session_manager() as session:
            connection = await self.repository.lock_connection_for_routing(
                session,
                connection_id=event.connection_id,
            )
            if connection is None:
                raise DiscordEventExcluded("Discord connection is unavailable.")
            resource = await self.repository.get_resource_by_provider_key(
                session,
                connection_id=event.connection_id,
                provider_resource_key=existing_resource_key,
            )
            if resource is None:
                resource = (
                    await self.repository.get_discord_resource_by_delivery_channel(
                        session,
                        connection_id=event.connection_id,
                        guild_id=tenant_id,
                        delivery_channel_id=(
                            normalized.thread_id or normalized.channel_id
                        ),
                    )
                )
            if resource is None:
                if not normalized.invocation:
                    if now - event.received_at < _UNLINKED_EVENT_WAIT:
                        raise _DeferredEvent(
                            retry_at=now + datetime.timedelta(seconds=5),
                            error_kind="awaiting_discord_thread_admission",
                            error_summary=(
                                "Waiting for a correlated Discord mention or binding."
                            ),
                        )
                    raise DiscordEventExcluded(
                        "Discord message is not linked to a tracked conversation."
                    )
                resource_key = _discord_resource_key(
                    tenant_id=tenant_id,
                    thread_id=normalized.thread_id or normalized.message_id,
                )
                if resource_key != existing_resource_key:
                    resource = await self.repository.get_resource_by_provider_key(
                        session,
                        connection_id=event.connection_id,
                        provider_resource_key=resource_key,
                    )
                if resource is None:
                    source_channel_id = normalized.channel_id
                    thread_channel_id = normalized.thread_id
                    parent_channel_id = (
                        normalized.parent_channel_id or source_channel_id
                    )
                    root_message_id = normalized.thread_id or normalized.message_id
                    resource = await self.repository.create_resource_idempotent(
                        session,
                        ExternalChannelResourceCreate(
                            connection_id=event.connection_id,
                            resource_type=ExternalChannelResourceType.THREAD,
                            provider_resource_key=resource_key,
                            labels={
                                "provider": "discord",
                                "guild_id": tenant_id,
                                "source_channel_id": source_channel_id,
                                "parent_channel_id": parent_channel_id,
                                "root_message_id": root_message_id,
                                **(
                                    {"display_name": (normalized.channel_display_name)}
                                    if normalized.channel_display_name is not None
                                    else {}
                                ),
                                **(
                                    {"thread_channel_id": thread_channel_id}
                                    if thread_channel_id is not None
                                    else {}
                                ),
                                **(
                                    {"delivery_channel_id": thread_channel_id}
                                    if thread_channel_id is not None
                                    else {}
                                ),
                                # Existing delivery payload construction uses this
                                # canonical root identity until thread provisioning.
                                "channel_id": parent_channel_id,
                                "thread_id": root_message_id,
                            },
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
                            latest_activity_at=normalized.provider_created_at,
                            unavailable_at=None,
                            deleted_at=None,
                        ),
                    )
            if resource.status is not ExternalChannelResourceStatus.ACTIVE:
                raise DiscordEventExcluded("Discord conversation is unavailable.")
            persisted = await self._persist_discord_message_event(
                session=session,
                event=event,
                configuration=configuration,
                connection=connection,
                resource=resource,
                message=normalized,
                now=now,
            )
        if persisted.control_delivery_attempt_id is not None:
            await self.action_service.attempt_delivery(
                persisted.control_delivery_attempt_id
            )
        if persisted.activity_delivery_attempt_id is not None:
            await self.action_service.attempt_delivery(
                persisted.activity_delivery_attempt_id
            )
        if persisted.wake_up is not None:
            await self.session_lifecycle.mark_session_running_for_input_wakeup(
                persisted.wake_up.session_id
            )
            await self.session_lifecycle.send_session_wake_up(persisted.wake_up)
        if persisted.hydration_required:
            if configuration.encrypted_credentials is None:
                raise DiscordEventExcluded(
                    "Discord history credentials are unavailable."
                )
            credentials = self.credentials_codec.decrypt(
                configuration.encrypted_credentials
            )
            try:
                await self._hydrate_discord_resource(
                    configuration=configuration,
                    resource_id=persisted.resource_id,
                    bot_token=credentials.bot_token,
                )
            except DiscordHistoryRateLimited as error:
                now = _now()
                raise _DeferredEvent(
                    retry_at=now
                    + datetime.timedelta(seconds=error.retry_after_seconds),
                    error_kind="discord_rate_limited",
                    error_summary="Discord delayed inbound conversation hydration.",
                ) from error
            except DiscordHistoryPermissionDenied as error:
                await self._mark_connection_reconnect_required(
                    connection_id=event.connection_id,
                    reason="permission_denied",
                )
                raise _ConnectionUnavailable("permission_denied") from error
            except DiscordHistoryCredentialsInvalid as error:
                await self._mark_connection_reconnect_required(
                    connection_id=event.connection_id,
                    reason="credentials_invalid",
                )
                raise _ConnectionUnavailable("credentials_invalid") from error
            except DiscordHistoryProviderError as error:
                now = _now()
                raise _DeferredEvent(
                    retry_at=now + _retry_delay(event.attempt_count),
                    error_kind="discord_temporarily_unavailable",
                    error_summary=(
                        "Discord conversation hydration is temporarily unavailable."
                    ),
                ) from error
        await self._complete_event(
            event,
            eligibility_state=ExternalChannelEventEligibilityState.PROCESSED,
            status=ExternalChannelEventStatus.PROCESSED,
            purge_envelope=False,
        )

    async def _persist_discord_message_event(
        self,
        *,
        session: AsyncSession,
        event: ExternalChannelEvent,
        configuration: ExternalChannelConnectionConfiguration,
        connection: ExternalChannelConnection,
        resource: ExternalChannelResource,
        message: DiscordNormalizedMessage,
        now: datetime.datetime,
    ) -> ExternalChannelPersistedMessage:
        """Apply the canonical route, access, binding, and invocation flow."""
        connection_id = connection.id
        app_mode = connection.app_mode
        binding_snapshot = await self.repository.get_active_binding_by_resource(
            session,
            resource_id=resource.id,
        )
        admission_snapshot = (
            None
            if binding_snapshot is not None
            else await self.repository.get_open_conversation_admission(
                session,
                resource_id=resource.id,
            )
        )
        route: ExternalChannelAgentRoute | None = None
        if binding_snapshot is not None:
            route = await self.repository.get_routable_route_by_id(
                session,
                route_id=binding_snapshot.route_id,
            )
        elif (
            admission_snapshot is not None
            and admission_snapshot.selected_route_id is not None
        ):
            route = await self.repository.get_routable_route_by_id(
                session,
                route_id=admission_snapshot.selected_route_id,
            )
        elif admission_snapshot is None:
            if app_mode is ExternalChannelAppMode.SINGLE:
                route = await self.repository.lock_routable_single_route(
                    session,
                    connection_id=connection_id,
                )
            else:
                route = await self.repository.lock_routable_channel_default(
                    session,
                    connection_id=connection_id,
                    provider_channel_id=message.channel_id,
                )
        locked_resource = await self.repository.lock_resource(
            session,
            resource_id=resource.id,
        )
        if locked_resource is None:
            raise RuntimeError("External Channel resource disappeared.")
        resource = locked_resource
        if resource.status is not ExternalChannelResourceStatus.ACTIVE:
            raise DiscordEventExcluded("Discord conversation is unavailable.")
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
        if binding is not None and (route is None or binding.route_id != route.id):
            raise _DeferredEvent(
                retry_at=now + datetime.timedelta(seconds=1),
                error_kind="routing_state_changed",
                error_summary="External Channel routing changed during admission.",
            )
        if binding is None and binding_snapshot is not None:
            raise _DeferredEvent(
                retry_at=now + datetime.timedelta(seconds=1),
                error_kind="routing_state_changed",
                error_summary="External Channel binding changed during admission.",
            )
        if binding is None and (
            (admission_snapshot is None) != (admission is None)
            or (
                admission_snapshot is not None
                and admission is not None
                and (
                    admission_snapshot.id != admission.id
                    or admission_snapshot.status is not admission.status
                    or admission_snapshot.selected_route_id
                    != admission.selected_route_id
                )
            )
            or (
                admission is not None
                and admission.selected_route_id is not None
                and (route is None or route.id != admission.selected_route_id)
            )
        ):
            raise _DeferredEvent(
                retry_at=now + datetime.timedelta(seconds=1),
                error_kind="routing_state_changed",
                error_summary="External Channel admission changed during routing.",
            )
        recovery_attempt_id = None
        if (
            binding is not None
            and message.revision_kind is ExternalChannelMessageRevisionKind.DELETE
        ):
            recovery_attempt_id = (
                await self.work_repository.recover_deleted_discord_progress(
                    session,
                    binding_id=binding.id,
                    resource_labels=resource.labels,
                    deleted_provider_message_key=message.provider_message_key,
                    origin_id=event.id,
                    now=now,
                )
            )
        if recovery_attempt_id is not None:
            await session.commit()
            return ExternalChannelPersistedMessage(
                resource_id=resource.id,
                hydration_required=False,
                control_delivery_attempt_id=None,
                activity_delivery_attempt_id=recovery_attempt_id,
                wake_up=None,
            )
        persisted_revision = await self._persist_normalized_message(
            session,
            resource=resource,
            message=message,
            source_event_id=event.id,
            now=now,
            original_url=_discord_original_url(message),
            reference_mappings=message.reference_mappings,
            provider=ExternalChannelProvider.DISCORD,
        )
        canonical_message = persisted_revision.message
        route, admission = await self._resolve_route_for_resource(
            session,
            connection_id=connection_id,
            app_mode=app_mode,
            resource=resource,
            binding=binding,
            route=route,
            admission=admission,
            canonical_message=canonical_message,
            message=message,
            now=now,
        )
        if route is None:
            control_delivery_attempt_id = (
                await self._create_selector_control_intent(
                    session,
                    resource=resource,
                    admission=admission,
                    provider=ExternalChannelProvider.DISCORD,
                )
                if (
                    admission is not None
                    and admission.status
                    is ExternalChannelConversationAdmissionStatus.PENDING_SELECTION
                    and message.invocation
                )
                else None
            )
            await session.commit()
            return ExternalChannelPersistedMessage(
                resource_id=resource.id,
                hydration_required=(
                    message.invocation
                    and not _hydration_terminal(resource.hydration_status)
                ),
                control_delivery_attempt_id=control_delivery_attempt_id,
                activity_delivery_attempt_id=None,
                wake_up=None,
            )
        active_agent_id = route.require_active_agent_id()
        trim = await self._project_current_revision(
            session,
            route=route,
            resource=resource,
            message=canonical_message,
            provider_position=message.provider_position,
            now=now,
            applied=persisted_revision.applied,
        )
        binding = await self._record_trim(
            session,
            route=route,
            resource=resource,
            binding=binding,
            trim=trim,
        )
        control_delivery_attempt_id = None
        activity_delivery_attempt_id = None
        wake_session_id: str | None = None
        principal_id = canonical_message.principal_id
        if principal_id is not None and _route_accepts_author(
            route,
            message.author_type,
        ):
            blocked = (
                await self.repository.get_active_block(
                    session,
                    agent_id=active_agent_id,
                    principal_id=principal_id,
                )
                is not None
            )
            grant = None
            if not blocked:
                grant = await self.repository.get_active_access_grant(
                    session,
                    agent_id=active_agent_id,
                    principal_id=principal_id,
                    agent_session_id=(
                        binding.agent_session_id if binding is not None else None
                    ),
                )
            authorized = not blocked and (
                grant is not None
                or _route_has_automatic_access(
                    route,
                    message.author_type,
                )
            )
            if (
                binding is not None
                and binding.activation_status
                is ExternalChannelBindingActivationStatus.ACTIVE
                and authorized
                and persisted_revision.applied
                and message.revision_kind is ExternalChannelMessageRevisionKind.ORIGINAL
            ):
                released = await self._release_pending_context(
                    session,
                    binding=binding,
                    trigger_message_id=canonical_message.id,
                    now=now,
                    initial_activation=False,
                    workspace_id=configuration.workspace_id,
                    agent_id=active_agent_id,
                    provider=ExternalChannelProvider.DISCORD,
                )
                if released is not None:
                    activity_delivery_attempt_id = released.activity_delivery_attempt_id
                    wake_session_id = binding.agent_session_id
            elif message.invocation and not blocked:
                if binding is None and authorized:
                    binding = await self._create_granted_initial_binding(
                        session,
                        route=route,
                        resource=resource,
                        trigger_message=canonical_message,
                        expected_admission_id=(
                            None if admission is None else admission.id
                        ),
                        provider=ExternalChannelProvider.DISCORD,
                        now=now,
                    )
                    binding = await self._record_trim(
                        session,
                        route=route,
                        resource=resource,
                        binding=binding,
                        trim=trim,
                    )
                    if binding is None:
                        raise RuntimeError(
                            "Discord binding disappeared during routing."
                        )
                    if admission is not None:
                        await self.repository.transition_conversation_admission(
                            session,
                            admission_id=admission.id,
                            status=ExternalChannelConversationAdmissionStatus.BOUND,
                            selected_route_id=route.id,
                        )
                elif not authorized and grant is None:
                    participant_provider_user_id = message.provider_user_id
                    if participant_provider_user_id is None:
                        raise RuntimeError(
                            "Discord human participant identity is missing."
                        )
                    control_delivery_attempt_id = (
                        await self._create_access_request_and_control_intent(
                            session,
                            route=route,
                            resource=resource,
                            binding=binding,
                            source_message=canonical_message,
                            principal_id=principal_id,
                            participant_provider_user_id=participant_provider_user_id,
                            participant_label=participant_provider_user_id,
                            tenant_id=message.tenant_id,
                            channel_id=message.thread_id or message.channel_id,
                            thread_ts=None,
                            trim=trim,
                            now=now,
                            provider=ExternalChannelProvider.DISCORD,
                        )
                    )
                    if admission is not None:
                        await self.repository.transition_conversation_admission(
                            session,
                            admission_id=admission.id,
                            status=(
                                ExternalChannelConversationAdmissionStatus.AWAITING_ACCESS
                            ),
                            selected_route_id=route.id,
                        )
        await session.commit()
        return ExternalChannelPersistedMessage(
            resource_id=resource.id,
            hydration_required=(
                message.invocation
                and not _hydration_terminal(resource.hydration_status)
            ),
            control_delivery_attempt_id=control_delivery_attempt_id,
            activity_delivery_attempt_id=activity_delivery_attempt_id,
            wake_up=(
                SessionWakeUp(session_id=wake_session_id)
                if wake_session_id is not None
                else None
            ),
        )

    async def _validate_invocation_channel(
        self,
        *,
        event: ExternalChannelEvent,
        message: SlackNormalizedMessage,
        bot_token: str,
    ) -> SlackConversationAccess:
        """Require an App-member non-Connect public or private channel."""
        try:
            access = await self.slack_client.fetch_conversation_access(
                bot_token=bot_token,
                channel_id=message.channel_id,
            )
        except SlackProviderRateLimited as error:
            now = _now()
            raise _DeferredEvent(
                retry_at=now + datetime.timedelta(seconds=error.retry_after_seconds),
                error_kind="slack_rate_limited",
                error_summary="Slack delayed conversation eligibility validation.",
            ) from error
        except SlackProviderTemporaryError as error:
            now = _now()
            raise _DeferredEvent(
                retry_at=now + _retry_delay(event.attempt_count),
                error_kind="slack_temporarily_unavailable",
                error_summary="Slack conversation validation is unavailable.",
            ) from error
        except SlackProviderPermissionDenied as error:
            await self._mark_connection_reconnect_required(
                connection_id=event.connection_id,
                reason="missing_scope",
            )
            raise _ConnectionUnavailable("missing_scope") from error
        except SlackProviderCredentialsInvalid as error:
            await self._mark_connection_reconnect_required(
                connection_id=event.connection_id,
                reason="credentials_invalid",
            )
            raise _ConnectionUnavailable("credentials_invalid") from error
        except SlackProviderResourceUnavailable as error:
            raise SlackEventExcluded(
                "The Slack conversation is unavailable to the App."
            ) from error
        if access.external_shared:
            raise SlackEventExcluded("Slack Connect conversations are not supported.")
        if not access.public_or_private_channel:
            raise SlackEventExcluded(
                "Slack direct and group messages are not supported."
            )
        if not access.app_member:
            raise SlackEventExcluded(
                "The Slack App must be a channel member before tracking."
            )
        return access

    async def _resolve_original_url(
        self,
        *,
        message: SlackNormalizedMessage,
        bot_token: str,
    ) -> str | None:
        """Resolve an optional provider permalink without blocking ingestion."""
        try:
            return await self.slack_client.get_permalink(
                bot_token=bot_token,
                channel_id=message.channel_id,
                message_ts=message.message_ts,
            )
        except (
            SlackProviderCredentialsInvalid,
            SlackProviderPermissionDenied,
            SlackProviderRateLimited,
            SlackProviderResourceUnavailable,
            SlackProviderTemporaryError,
        ):
            return None

    async def _resolve_reference_mappings(
        self,
        *,
        message: SlackNormalizedMessage,
        bot_token: str,
        channel_display_name: str | None,
        cache: dict[str, dict[str, str]],
    ) -> dict[str, dict[str, str]]:
        """Resolve bounded Slack IDs without making message ingestion depend on it."""
        user_ids, channel_ids = slack_message_reference_ids(message.normalized_body)
        if message.provider_user_id is not None:
            user_ids.add(message.provider_user_id)
        channel_ids.add(message.channel_id)
        mappings: dict[str, dict[str, str]] = {"users": {}, "channels": {}}
        if channel_display_name is not None:
            cache["channels"][message.channel_id] = channel_display_name
        for user_id in sorted(user_ids):
            display_name = cache["users"].get(user_id)
            if display_name is None:
                try:
                    display_name = await self.slack_client.fetch_user_display_name(
                        bot_token=bot_token,
                        provider_user_id=user_id,
                    )
                except (
                    SlackProviderCredentialsInvalid,
                    SlackProviderPermissionDenied,
                    SlackProviderRateLimited,
                    SlackProviderResourceUnavailable,
                    SlackProviderTemporaryError,
                ):
                    continue
                if display_name is not None:
                    cache["users"][user_id] = display_name
            if display_name is not None:
                mappings["users"][user_id] = display_name
        for channel_id in sorted(channel_ids):
            display_name = cache["channels"].get(channel_id)
            if display_name is None:
                try:
                    display_name = await self.slack_client.fetch_channel_display_name(
                        bot_token=bot_token,
                        channel_id=channel_id,
                    )
                except (
                    SlackProviderCredentialsInvalid,
                    SlackProviderPermissionDenied,
                    SlackProviderRateLimited,
                    SlackProviderResourceUnavailable,
                    SlackProviderTemporaryError,
                ):
                    continue
                if display_name is not None:
                    cache["channels"][channel_id] = display_name
            if display_name is not None:
                mappings["channels"][channel_id] = display_name
        return {category: entries for category, entries in mappings.items() if entries}

    async def _persist_message_event(
        self,
        *,
        event: ExternalChannelEvent,
        configuration: ExternalChannelConnectionConfiguration,
        message: SlackNormalizedMessage,
        original_url: str | None,
        channel_display_name: str | None,
        reference_mappings: dict[str, dict[str, str]],
    ) -> ExternalChannelPersistedMessage:
        now = _now()
        async with self.session_manager() as session:
            connection = await self.repository.lock_connection_for_routing(
                session,
                connection_id=event.connection_id,
            )
            if connection is None:
                raise SlackEventExcluded("The Slack connection is unavailable.")
            resource = await self.repository.get_resource_by_provider_key(
                session,
                connection_id=event.connection_id,
                provider_resource_key=message.provider_resource_key,
            )
            if resource is None:
                if not message.invocation:
                    if now - event.received_at < _UNLINKED_EVENT_WAIT:
                        raise _DeferredEvent(
                            retry_at=now + datetime.timedelta(seconds=5),
                            error_kind="awaiting_thread_mention",
                            error_summary=(
                                "Waiting for a correlated Slack mention or binding."
                            ),
                        )
                    raise SlackEventExcluded(
                        "Slack message is not linked to a tracked conversation."
                    )
                resource = await self.repository.create_resource_idempotent(
                    session,
                    ExternalChannelResourceCreate(
                        connection_id=event.connection_id,
                        resource_type=ExternalChannelResourceType.THREAD,
                        provider_resource_key=message.provider_resource_key,
                        labels={
                            "provider": "slack",
                            "tenant_id": message.tenant_id,
                            "channel_id": message.channel_id,
                            "thread_ts": message.root_thread_ts,
                            **(
                                {"channel_name": channel_display_name}
                                if channel_display_name is not None
                                else {}
                            ),
                        },
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
                        latest_activity_at=message.provider_created_at,
                        unavailable_at=None,
                        deleted_at=None,
                    ),
                )
            if resource.status is not ExternalChannelResourceStatus.ACTIVE:
                raise SlackEventExcluded("The external conversation is unavailable.")
            binding_snapshot = await self.repository.get_active_binding_by_resource(
                session,
                resource_id=resource.id,
            )
            admission_snapshot = (
                None
                if binding_snapshot is not None
                else await self.repository.get_open_conversation_admission(
                    session,
                    resource_id=resource.id,
                )
            )
            route: ExternalChannelAgentRoute | None = None
            if binding_snapshot is not None:
                route = await self.repository.get_routable_route_by_id(
                    session,
                    route_id=binding_snapshot.route_id,
                )
            elif (
                admission_snapshot is not None
                and admission_snapshot.selected_route_id is not None
            ):
                route = await self.repository.get_routable_route_by_id(
                    session,
                    route_id=admission_snapshot.selected_route_id,
                )
            elif admission_snapshot is None:
                if connection.app_mode is ExternalChannelAppMode.SINGLE:
                    route = await self.repository.lock_routable_single_route(
                        session,
                        connection_id=connection.id,
                    )
                else:
                    route = await self.repository.lock_routable_channel_default(
                        session,
                        connection_id=connection.id,
                        provider_channel_id=message.channel_id,
                    )
            locked_resource = await self.repository.lock_resource(
                session,
                resource_id=resource.id,
            )
            if locked_resource is None:
                raise RuntimeError("External Channel resource disappeared.")
            resource = locked_resource
            if resource.status is not ExternalChannelResourceStatus.ACTIVE:
                raise SlackEventExcluded("The external conversation is unavailable.")
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
            if binding is not None and (route is None or binding.route_id != route.id):
                raise _DeferredEvent(
                    retry_at=now + datetime.timedelta(seconds=1),
                    error_kind="routing_state_changed",
                    error_summary="External Channel routing changed during admission.",
                )
            if binding is None and binding_snapshot is not None:
                raise _DeferredEvent(
                    retry_at=now + datetime.timedelta(seconds=1),
                    error_kind="routing_state_changed",
                    error_summary="External Channel binding changed during admission.",
                )
            if binding is None and (
                (admission_snapshot is None) != (admission is None)
                or (
                    admission_snapshot is not None
                    and admission is not None
                    and (
                        admission_snapshot.id != admission.id
                        or admission_snapshot.status is not admission.status
                        or admission_snapshot.selected_route_id
                        != admission.selected_route_id
                    )
                )
                or (
                    admission is not None
                    and admission.selected_route_id is not None
                    and (route is None or route.id != admission.selected_route_id)
                )
            ):
                raise _DeferredEvent(
                    retry_at=now + datetime.timedelta(seconds=1),
                    error_kind="routing_state_changed",
                    error_summary="External Channel admission changed during routing.",
                )
            recovery_attempt_id = None
            if (
                binding is not None
                and message.revision_kind is ExternalChannelMessageRevisionKind.DELETE
            ):
                recovery_attempt_id = (
                    await self._create_deleted_activity_recovery_intent(
                        session,
                        event=event,
                        binding=binding,
                        resource=resource,
                        deleted_provider_message_key=message.provider_message_key,
                    )
                )
            if recovery_attempt_id is not None:
                await session.commit()
                return ExternalChannelPersistedMessage(
                    resource_id=resource.id,
                    hydration_required=False,
                    control_delivery_attempt_id=None,
                    activity_delivery_attempt_id=recovery_attempt_id,
                    wake_up=None,
                )
            if connection_authored(configuration, message):
                raise SlackEventExcluded(
                    "Connection-authored Slack message was ignored."
                )
            wake_session_id: str | None = None
            activity_delivery_attempt_id: str | None = None

            persisted_revision = await self._persist_normalized_message(
                session,
                resource=resource,
                message=message,
                source_event_id=event.id,
                now=now,
                original_url=original_url,
                reference_mappings=_resource_reference_mappings(
                    reference_mappings,
                    resource.labels,
                ),
            )
            canonical_message = persisted_revision.message
            if binding is not None and _is_shortcut_source_event(event):
                assert route is not None
                control_delivery_attempt_id = (
                    await self._create_bound_shortcut_control_intent(
                        session,
                        event=event,
                        resource=resource,
                        binding=binding,
                        route=route,
                    )
                )
                await session.commit()
                return ExternalChannelPersistedMessage(
                    resource_id=resource.id,
                    hydration_required=False,
                    control_delivery_attempt_id=control_delivery_attempt_id,
                    activity_delivery_attempt_id=None,
                    wake_up=None,
                )
            route, admission = await self._resolve_route_for_resource(
                session,
                connection_id=connection.id,
                app_mode=connection.app_mode,
                resource=resource,
                binding=binding,
                route=route,
                admission=admission,
                canonical_message=canonical_message,
                message=message,
                now=now,
            )
            if route is None:
                control_delivery_attempt_id = (
                    await self._create_selector_control_intent(
                        session,
                        resource=resource,
                        admission=admission,
                        provider=ExternalChannelProvider.SLACK,
                    )
                    if (
                        admission is not None
                        and admission.status
                        is ExternalChannelConversationAdmissionStatus.PENDING_SELECTION
                        and not _is_shortcut_source_event(event)
                    )
                    else None
                )
                await session.commit()
                return ExternalChannelPersistedMessage(
                    resource_id=resource.id,
                    hydration_required=(
                        message.invocation
                        and not _hydration_terminal(resource.hydration_status)
                    ),
                    control_delivery_attempt_id=control_delivery_attempt_id,
                    activity_delivery_attempt_id=None,
                    wake_up=None,
                )
            active_agent_id = route.require_active_agent_id()
            trim = await self._project_current_revision(
                session,
                route=route,
                resource=resource,
                message=canonical_message,
                provider_position=message.provider_position,
                now=now,
                applied=persisted_revision.applied,
            )
            binding = await self._record_trim(
                session,
                route=route,
                resource=resource,
                binding=binding,
                trim=trim,
            )
            control_delivery_attempt_id = None
            principal_id = canonical_message.principal_id
            if principal_id is not None and _route_accepts_author(
                route,
                message.author_type,
            ):
                blocked = (
                    await self.repository.get_active_block(
                        session,
                        agent_id=active_agent_id,
                        principal_id=principal_id,
                    )
                    is not None
                )
                grant = None
                if not blocked:
                    grant = await self.repository.get_active_access_grant(
                        session,
                        agent_id=active_agent_id,
                        principal_id=principal_id,
                        agent_session_id=(
                            binding.agent_session_id if binding is not None else None
                        ),
                    )
                authorized = not blocked and (
                    grant is not None
                    or _route_has_automatic_access(
                        route,
                        message.author_type,
                    )
                )
                if (
                    binding is not None
                    and binding.activation_status
                    is ExternalChannelBindingActivationStatus.ACTIVE
                    and authorized
                    and persisted_revision.applied
                    and message.revision_kind
                    is ExternalChannelMessageRevisionKind.ORIGINAL
                ):
                    released = await self._release_pending_context(
                        session,
                        binding=binding,
                        trigger_message_id=canonical_message.id,
                        now=now,
                        initial_activation=False,
                        workspace_id=configuration.workspace_id,
                        agent_id=active_agent_id,
                    )
                    if released is not None:
                        wake_session_id = binding.agent_session_id
                        activity_delivery_attempt_id = (
                            released.activity_delivery_attempt_id
                        )
                elif message.invocation and not blocked:
                    if binding is None and authorized:
                        binding = await self._create_granted_initial_binding(
                            session,
                            route=route,
                            resource=resource,
                            trigger_message=canonical_message,
                            expected_admission_id=(
                                None if admission is None else admission.id
                            ),
                        )
                        binding = await self._record_trim(
                            session,
                            route=route,
                            resource=resource,
                            binding=binding,
                            trim=trim,
                        )
                        if admission is not None:
                            await self.repository.transition_conversation_admission(
                                session,
                                admission_id=admission.id,
                                status=ExternalChannelConversationAdmissionStatus.BOUND,
                                selected_route_id=route.id,
                            )
                    elif not authorized and grant is None:
                        participant_provider_user_id = message.provider_user_id
                        if participant_provider_user_id is None:
                            raise RuntimeError(
                                "Slack human participant identity is missing."
                            )
                        control_delivery_attempt_id = (
                            await self._create_access_request_and_control_intent(
                                session,
                                route=route,
                                resource=resource,
                                binding=binding,
                                source_message=canonical_message,
                                principal_id=principal_id,
                                participant_provider_user_id=(
                                    participant_provider_user_id
                                ),
                                participant_label=(
                                    reference_mappings.get("users", {}).get(
                                        participant_provider_user_id
                                    )
                                    or participant_provider_user_id
                                ),
                                tenant_id=message.tenant_id,
                                channel_id=message.channel_id,
                                thread_ts=message.root_thread_ts,
                                trim=trim,
                                now=now,
                            )
                        )
                        if admission is not None:
                            await self.repository.transition_conversation_admission(
                                session,
                                admission_id=admission.id,
                                status=(
                                    ExternalChannelConversationAdmissionStatus.AWAITING_ACCESS
                                ),
                                selected_route_id=route.id,
                            )
            await session.commit()
            return ExternalChannelPersistedMessage(
                resource_id=resource.id,
                hydration_required=(
                    message.invocation
                    and not _hydration_terminal(resource.hydration_status)
                ),
                control_delivery_attempt_id=control_delivery_attempt_id,
                activity_delivery_attempt_id=activity_delivery_attempt_id,
                wake_up=(
                    SessionWakeUp(session_id=wake_session_id)
                    if wake_session_id is not None
                    else None
                ),
            )

    async def _persist_normalized_message(
        self,
        session: AsyncSession,
        *,
        resource: ExternalChannelResource,
        message: SlackNormalizedMessage | DiscordNormalizedMessage,
        source_event_id: str | None,
        now: datetime.datetime,
        original_url: str | None,
        reference_mappings: dict[str, dict[str, str]],
        provider: ExternalChannelProvider = ExternalChannelProvider.SLACK,
    ) -> ExternalChannelPersistedRevision:
        principal_id = None
        if message.provider_user_id is not None:
            display_name = reference_mappings.get("users", {}).get(
                message.provider_user_id
            )
            if isinstance(message, DiscordNormalizedMessage):
                display_name = message.sender_display_name or display_name
            principal = await self.repository.create_principal_idempotent(
                session,
                ExternalChannelPrincipalCreate(
                    provider=provider,
                    provider_tenant_id=message.tenant_id,
                    provider_user_id=message.provider_user_id,
                    author_type=message.author_type,
                    display_name=display_name,
                    avatar_url=None,
                    profile=None,
                ),
            )
            principal_id = principal.id
        canonical = await self.repository.create_message_idempotent(
            session,
            ExternalChannelMessageCreate(
                resource_id=resource.id,
                provider_message_key=message.provider_message_key,
                provider_position=message.provider_position,
                principal_id=principal_id,
                author_type=message.author_type,
                current_revision_id=None,
                original_url=original_url,
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
                reference_mappings=reference_mappings or None,
                source_event_id=source_event_id,
                provider_occurred_at=(
                    message.provider_updated_at or message.provider_created_at
                ),
            ),
        )
        current = await self.repository.apply_message_revision(
            session,
            message_id=canonical.id,
            revision_id=revision.id,
            principal_id=principal_id,
            author_type=message.author_type,
            lifecycle=message.lifecycle,
            pending_size=message.normalized_size,
            provider_created_at=message.provider_created_at,
            provider_updated_at=message.provider_updated_at,
            original_url=original_url,
        )
        if current is None:
            raise RuntimeError("External Channel message disappeared during update.")
        if current.current_revision_id != revision.id:
            return ExternalChannelPersistedRevision(
                message=current,
                trim=ExternalChannelPendingContextTrim(
                    deleted_message_count=0,
                    deleted_size=0,
                    retained_message_count=0,
                    retained_size=0,
                ),
                applied=False,
            )
        return ExternalChannelPersistedRevision(
            message=current,
            trim=ExternalChannelPendingContextTrim(
                deleted_message_count=0,
                deleted_size=0,
                retained_message_count=0,
                retained_size=0,
            ),
            applied=True,
        )

    async def _resolve_route_for_resource(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        app_mode: ExternalChannelAppMode,
        resource: ExternalChannelResource,
        binding: ExternalChannelBinding | None,
        route: ExternalChannelAgentRoute | None,
        admission: ExternalChannelConversationAdmission | None,
        canonical_message: ExternalChannelMessage,
        message: SlackNormalizedMessage | DiscordNormalizedMessage,
        now: datetime.datetime,
    ) -> tuple[
        ExternalChannelAgentRoute | None,
        ExternalChannelConversationAdmission | None,
    ]:
        """Resolve one route from durable binding, admission, or App mode state."""
        if binding is not None:
            if route is None or route.connection_id != connection_id:
                self.log_route_resolution(
                    connection_id=connection_id,
                    resource_id=resource.id,
                    app_mode=app_mode,
                    source="binding",
                    route_id=binding.route_id,
                    reason="bound_route_unavailable",
                )
                raise SlackEventExcluded("The bound Slack route is unavailable.")
            self.log_route_resolution(
                connection_id=connection_id,
                resource_id=resource.id,
                app_mode=app_mode,
                source="binding",
                route_id=route.id,
                reason=None,
            )
            return route, None

        if admission is not None:
            if admission.expires_at <= now:
                await self.repository.transition_conversation_admission(
                    session,
                    admission_id=admission.id,
                    status=ExternalChannelConversationAdmissionStatus.EXPIRED,
                    selected_route_id=admission.selected_route_id,
                )
                self.log_route_resolution(
                    connection_id=connection_id,
                    resource_id=resource.id,
                    app_mode=app_mode,
                    source="selected_admission",
                    route_id=admission.selected_route_id,
                    reason="admission_expired",
                )
                return None, admission
            if admission.selected_route_id is None:
                self.log_route_resolution(
                    connection_id=connection_id,
                    resource_id=resource.id,
                    app_mode=app_mode,
                    source="pending_selection",
                    route_id=None,
                    reason="selection_required",
                )
                return None, admission
            if route is None or route.connection_id != connection_id:
                self.log_route_resolution(
                    connection_id=connection_id,
                    resource_id=resource.id,
                    app_mode=app_mode,
                    source="selected_admission",
                    route_id=admission.selected_route_id,
                    reason="selected_route_unavailable",
                )
                raise SlackEventExcluded("The selected Slack route is unavailable.")
            self.log_route_resolution(
                connection_id=connection_id,
                resource_id=resource.id,
                app_mode=app_mode,
                source="selected_admission",
                route_id=route.id,
                reason=None,
            )
            return route, admission

        if app_mode is ExternalChannelAppMode.SINGLE:
            origin = ExternalChannelConversationAdmissionOrigin.SINGLE_ROUTE
            if route is None:
                self.log_route_resolution(
                    connection_id=connection_id,
                    resource_id=resource.id,
                    app_mode=app_mode,
                    source="single_sole_route",
                    route_id=None,
                    reason="sole_route_unavailable",
                )
                raise SlackEventExcluded("The Single Slack App route is unavailable.")
        else:
            origin = ExternalChannelConversationAdmissionOrigin.CHANNEL_DEFAULT
            if route is None:
                create = ExternalChannelConversationAdmissionCreate(
                    connection_id=connection_id,
                    resource_id=resource.id,
                    source_message_id=canonical_message.id,
                    initiating_principal_id=canonical_message.principal_id,
                    origin=ExternalChannelConversationAdmissionOrigin.MENTION_SELECTOR,
                    status=ExternalChannelConversationAdmissionStatus.PENDING_SELECTION,
                    selected_route_id=None,
                    interaction_id=None,
                    expires_at=now + _ACCESS_REQUEST_AGE,
                )
                admission = (
                    await self.repository.create_conversation_admission_idempotent(
                        session,
                        create,
                    )
                )
                self.log_route_resolution(
                    connection_id=connection_id,
                    resource_id=resource.id,
                    app_mode=app_mode,
                    source="channel_default",
                    route_id=None,
                    reason="selection_required",
                )
                return None, admission

        admission = await self.repository.create_conversation_admission_idempotent(
            session,
            ExternalChannelConversationAdmissionCreate(
                connection_id=connection_id,
                resource_id=resource.id,
                source_message_id=canonical_message.id,
                initiating_principal_id=canonical_message.principal_id,
                origin=origin,
                status=ExternalChannelConversationAdmissionStatus.SELECTED,
                selected_route_id=route.id,
                interaction_id=None,
                expires_at=now + _ACCESS_REQUEST_AGE,
            ),
        )
        if admission.selected_route_id != route.id:
            self.log_route_resolution(
                connection_id=connection_id,
                resource_id=resource.id,
                app_mode=app_mode,
                source=(
                    "single_sole_route"
                    if app_mode is ExternalChannelAppMode.SINGLE
                    else "channel_default"
                ),
                route_id=route.id,
                reason="selected_route_conflict",
            )
            raise SlackEventExcluded(
                "The Slack conversation already selected another route."
            )
        self.log_route_resolution(
            connection_id=connection_id,
            resource_id=resource.id,
            app_mode=app_mode,
            source=(
                "single_sole_route"
                if app_mode is ExternalChannelAppMode.SINGLE
                else "channel_default"
            ),
            route_id=route.id,
            reason=None,
        )
        return route, admission

    async def _create_selector_control_intent(
        self,
        session: AsyncSession,
        *,
        resource: ExternalChannelResource,
        admission: ExternalChannelConversationAdmission,
        provider: ExternalChannelProvider,
    ) -> str | None:
        """Create or reuse the one thread selector control for a retained source."""
        if provider is ExternalChannelProvider.DISCORD:
            request_payload: dict[str, object] = {
                "provider": "discord",
                "control_kind": "agent_selector",
                **_provider_thread_target(resource),
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
            labels = resource.labels or {}
            tenant_id = labels.get("tenant_id")
            channel_id = labels.get("channel_id")
            thread_ts = labels.get("thread_ts")
            if (
                not isinstance(tenant_id, str)
                or not tenant_id
                or not isinstance(channel_id, str)
                or not channel_id
                or not isinstance(thread_ts, str)
                or not thread_ts
            ):
                return None
            request_payload = {
                "provider": "slack",
                "control_kind": "agent_selector",
                "tenant_id": tenant_id,
                "channel_id": channel_id,
                "thread_ts": thread_ts,
                "conversation_admission_id": admission.id,
            }
        attempt = await self.repository.create_delivery_attempt_idempotent(
            session,
            ExternalChannelDeliveryAttemptCreate(
                # The retained admission is the selector-control root.
                origin_type=ExternalChannelDeliveryOriginType.MANAGER_OPERATION,
                origin_id=admission.id,
                channel_action_id=None,
                binding_id=None,
                operation=ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
                request_payload=request_payload,
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

    async def _create_bound_shortcut_control_intent(
        self,
        session: AsyncSession,
        *,
        event: ExternalChannelEvent,
        resource: ExternalChannelResource,
        binding: ExternalChannelBinding,
        route: ExternalChannelAgentRoute,
    ) -> str | None:
        """Report the immutable existing binding without invoking its Session."""
        if binding.route_id != route.id:
            raise RuntimeError("External Channel binding route changed.")
        agent = await self.agent_repository.get_by_id(
            session,
            route.require_active_agent_id(),
        )
        recorded_agent_name = normalize_slack_agent_name(
            None if agent is None else agent.name
        )
        labels = resource.labels or {}
        tenant_id = labels.get("tenant_id")
        channel_id = labels.get("channel_id")
        thread_ts = labels.get("thread_ts")
        if (
            not isinstance(tenant_id, str)
            or not tenant_id
            or not isinstance(channel_id, str)
            or not channel_id
            or not isinstance(thread_ts, str)
            or not thread_ts
            or recorded_agent_name is None
        ):
            return None
        attempt = await self.repository.create_delivery_attempt_idempotent(
            session,
            ExternalChannelDeliveryAttemptCreate(
                origin_type=ExternalChannelDeliveryOriginType.MANAGER_OPERATION,
                origin_id=event.id,
                channel_action_id=None,
                binding_id=binding.id,
                operation=ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
                request_payload={
                    "provider": "slack",
                    "control_kind": "shortcut_already_bound",
                    "tenant_id": tenant_id,
                    "channel_id": channel_id,
                    "thread_ts": thread_ts,
                    "recorded_agent_name": recorded_agent_name,
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

    @staticmethod
    def log_route_resolution(
        *,
        connection_id: str,
        resource_id: str,
        app_mode: ExternalChannelAppMode,
        source: str,
        route_id: str | None,
        reason: str | None,
    ) -> None:
        """Emit a safe categorical routing decision without provider content."""
        logger.info(
            "External Channel route resolution",
            extra={
                "external_channel_connection_id": connection_id,
                "external_channel_resource_id": resource_id,
                "external_channel_route_id": route_id,
                "external_channel_app_mode": app_mode.value,
                "route_resolution_source": source,
                "route_resolution_reason": reason,
            },
        )

    async def _project_current_revision(
        self,
        session: AsyncSession,
        *,
        route: ExternalChannelAgentRoute,
        resource: ExternalChannelResource,
        message: ExternalChannelMessage,
        provider_position: str,
        now: datetime.datetime,
        applied: bool,
    ) -> ExternalChannelPendingContextTrim:
        """Materialize route-scoped pending context after route selection."""
        if (
            not applied
            or message.current_revision_id is None
            or not _route_accepts_author(route, message.author_type)
        ):
            return ExternalChannelPendingContextTrim(
                deleted_message_count=0,
                deleted_size=0,
                retained_message_count=0,
                retained_size=0,
            )
        await self.repository.create_pending_context_idempotent(
            session,
            ExternalChannelPendingContextCreate(
                route_id=route.id,
                resource_id=resource.id,
                message_revision_id=message.current_revision_id,
                provider_position=provider_position,
                normalized_size=message.pending_size,
                expires_at=(message.provider_created_at or now) + _PENDING_CONTEXT_AGE,
            ),
        )
        return await self.repository.trim_pending_context(
            session,
            route_id=route.id,
            resource_id=resource.id,
            now=now,
            max_message_count=_PENDING_CONTEXT_MAX_MESSAGES,
            max_size=_PENDING_CONTEXT_MAX_SIZE,
        )

    async def _record_trim(
        self,
        session: AsyncSession,
        *,
        route: ExternalChannelAgentRoute,
        resource: ExternalChannelResource,
        binding: ExternalChannelBinding | None,
        trim: ExternalChannelPendingContextTrim,
    ) -> ExternalChannelBinding | None:
        if trim.deleted_message_count == 0 and trim.deleted_size == 0:
            return binding
        if binding is not None:
            return await self.repository.record_binding_truncation(
                session,
                binding_id=binding.id,
                truncated_message_count=trim.deleted_message_count,
                truncated_size=trim.deleted_size,
            )
        await self.repository.record_pending_access_request_truncation(
            session,
            route_id=route.id,
            resource_id=resource.id,
            truncated_message_count=trim.deleted_message_count,
            truncated_size=trim.deleted_size,
        )
        return None

    async def _create_granted_initial_binding(
        self,
        session: AsyncSession,
        *,
        route: ExternalChannelAgentRoute,
        resource: ExternalChannelResource,
        trigger_message: ExternalChannelMessage,
        expected_admission_id: str | None,
        provider: ExternalChannelProvider = ExternalChannelProvider.SLACK,
        now: datetime.datetime | None = None,
    ) -> ExternalChannelBinding:
        locked_resource = await self.repository.lock_resource(
            session,
            resource_id=resource.id,
        )
        if locked_resource is None:
            raise RuntimeError("External Channel resource disappeared.")
        existing = await self.repository.get_active_binding_by_resource(
            session,
            resource_id=resource.id,
        )
        if existing is not None:
            if existing.route_id != route.id:
                raise SlackEventExcluded(
                    "The external conversation is already bound to another route."
                )
            return existing
        active_agent_id = route.require_active_agent_id()
        agent = await self.agent_repository.get_by_id(session, active_agent_id)
        if agent is None or agent.lifecycle_status is not AgentLifecycleStatus.ACTIVE:
            raise SlackEventExcluded("The routed Agent is not active.")
        if provider is ExternalChannelProvider.DISCORD and now is None:
            raise RuntimeError("Discord binding activation time is missing.")
        root_session = (
            await self.root_agent_session_creation_service.create_root_session(
                session,
                create=AgentSessionCreate(
                    workspace_id=agent.workspace_id,
                    agent_id=agent.id,
                    title=None,
                    start_reason=AgentSessionStartReason.EXTERNAL_CHANNEL,
                ),
                workspace_intent=AgentDefaultRootWorkspaceIntent(),
            )
        )
        return await self.repository.create_binding_idempotent(
            session,
            ExternalChannelBindingCreate(
                resource_id=resource.id,
                route_id=route.id,
                agent_session_id=root_session.agent_session.id,
                status=ExternalChannelBindingStatus.ACTIVE,
                activation_status=ExternalChannelBindingActivationStatus.WAITING_HYDRATION,
                activation_trigger_message_id=trigger_message.id,
                activated_at=None,
                projected_through_position=None,
                truncated_message_count=0,
                truncated_size=0,
                disconnected_at=None,
                disconnect_reason=None,
            ),
            expected_admission_id=expected_admission_id,
            expected_access_request_id=None,
        )

    async def _create_access_request_and_control_intent(
        self,
        session: AsyncSession,
        *,
        route: ExternalChannelAgentRoute,
        resource: ExternalChannelResource,
        binding: ExternalChannelBinding | None,
        source_message: ExternalChannelMessage,
        principal_id: str,
        participant_provider_user_id: str,
        participant_label: str,
        tenant_id: str,
        channel_id: str,
        thread_ts: str | None,
        trim: ExternalChannelPendingContextTrim,
        now: datetime.datetime,
        provider: ExternalChannelProvider = ExternalChannelProvider.SLACK,
    ) -> str | None:
        active_agent_id = route.require_active_agent_id()
        request = await self.repository.create_access_request_idempotent(
            session,
            ExternalChannelAccessRequestCreate(
                route_id=route.id,
                resource_id=resource.id,
                source_message_id=source_message.id,
                principal_id=principal_id,
                agent_session_id=(
                    binding.agent_session_id if binding is not None else None
                ),
                status=ExternalChannelAccessRequestStatus.PENDING,
                decision_policy_snapshot={
                    "version": 1,
                    "provider": provider.value,
                    "agent_id": active_agent_id,
                    "pending_truncation_message_count": (
                        trim.deleted_message_count if binding is None else 0
                    ),
                    "pending_truncation_size": (
                        trim.deleted_size if binding is None else 0
                    ),
                },
                decided_by_user_id=None,
                decision_summary=None,
                expires_at=now + _ACCESS_REQUEST_AGE,
                decided_at=None,
            ),
        )
        approval_url = _approval_url(self.config.web_url, request.id)
        if provider is ExternalChannelProvider.SLACK:
            if thread_ts is None:
                raise RuntimeError("Slack access-request thread identity is missing.")
            payload: dict[str, object] = {
                "provider": "slack",
                "tenant_id": tenant_id,
                "channel_id": channel_id,
                "thread_ts": thread_ts,
                "access_request_id": request.id,
                "participant_provider_user_id": participant_provider_user_id,
                "participant_label": participant_label,
            }
            if approval_url is not None:
                payload["approval_url"] = approval_url
        elif provider is ExternalChannelProvider.DISCORD:
            payload = {
                **_provider_thread_target(resource),
                "provider": "discord",
                "access_request_id": request.id,
                "participant_provider_user_id": participant_provider_user_id,
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
                    _discord_link_button(
                        label="Review access",
                        url=approval_url,
                    )
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
                origin_id=request.id,
                channel_action_id=None,
                binding_id=binding.id if binding is not None else None,
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
                completed_at=(None if approval_url is not None else now),
            ),
        )
        return (
            attempt.id
            if attempt.status is ExternalChannelDeliveryStatus.PENDING
            else None
        )

    async def _create_deleted_activity_recovery_intent(
        self,
        session: AsyncSession,
        *,
        event: ExternalChannelEvent,
        binding: ExternalChannelBinding,
        resource: ExternalChannelResource,
        deleted_provider_message_key: str,
    ) -> str | None:
        """Recreate a Tracker after Slack confirms external deletion."""
        work = await self.repository.get_work_by_progress_provider_message_key(
            session,
            binding_id=binding.id,
            provider_message_key=deleted_provider_message_key,
        )
        if work is None:
            return None
        cleared = await self.repository.clear_work_progress_provider_message_key(
            session,
            work_id=work.id,
            provider_message_key=deleted_provider_message_key,
        )
        if not cleared:
            return None
        if work.desired_progress_payload is None:
            return None
        presentation = _render_persisted_activity(work)
        attempt = await self.repository.create_delivery_attempt_idempotent(
            session,
            ExternalChannelDeliveryAttemptCreate(
                origin_type=ExternalChannelDeliveryOriginType.MANAGER_OPERATION,
                origin_id=event.id,
                channel_action_id=None,
                binding_id=binding.id,
                operation=ExternalChannelDeliveryOperation.PROGRESS_CREATE,
                request_payload={
                    **_activity_provider_target(resource, work),
                    "text": presentation.text,
                    "blocks": presentation.blocks,
                    "desired_progress_revision": work.desired_progress_revision,
                    "replaces_provider_message_key": deleted_provider_message_key,
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

    async def _attempt_activity_delivery(
        self,
        *,
        configuration: ExternalChannelConnectionConfiguration,
        delivery_attempt_id: str,
        bot_token: str,
    ) -> None:
        """Attempt one Activity Tracker mutation and durable reconciliation."""
        async with self.session_manager() as session:
            target = await self.work_repository.get_delivery_target(
                session,
                delivery_attempt_id=delivery_attempt_id,
            )
            attempt = await self.repository.start_delivery_attempt(
                session,
                delivery_attempt_id=delivery_attempt_id,
                attempted_at=_now(),
            )
            await session.commit()
        if attempt is None:
            return
        presentation = resolve_slack_agent_presentation(
            target,
            avatar_cdn_base_url=self.config.avatar_cdn_base_url,
        )
        payload = attempt.request_payload
        tenant_id = payload.get("tenant_id")
        channel_id = payload.get("channel_id")
        thread_ts = payload.get("thread_ts")
        text = payload.get("text")
        blocks = payload.get("blocks")
        if (
            not isinstance(tenant_id, str)
            or not tenant_id
            or not isinstance(channel_id, str)
            or not channel_id
            or not isinstance(thread_ts, str)
            or not thread_ts
            or not isinstance(text, str)
            or not text
            or not isinstance(blocks, list)
            or not all(isinstance(block, dict) for block in blocks)
        ):
            result_status = ExternalChannelDeliveryStatus.FAILED
            provider_message_key = None
            error_kind = "activity_payload_invalid"
            error_summary = "The persisted Activity Tracker payload is invalid."
        elif attempt.operation is ExternalChannelDeliveryOperation.PROGRESS_CREATE:
            result = await self.slack_client.post_blocks(
                bot_token=bot_token,
                tenant_id=tenant_id,
                channel_id=channel_id,
                thread_ts=thread_ts,
                text=prepend_agent_fallback(presentation, text),
                blocks=prepend_agent_blocks(
                    presentation,
                    [block for block in blocks if isinstance(block, dict)],
                ),
                icon_url=(None if presentation is None else presentation.icon_url),
            )
            result_status = ExternalChannelDeliveryStatus(result.status)
            provider_message_key = result.provider_message_key
            error_kind = result.error_kind
            error_summary = result.error_summary
        elif attempt.operation is ExternalChannelDeliveryOperation.PROGRESS_UPDATE:
            target_provider_message_key = payload.get("provider_message_key")
            message_ts = _provider_message_ts(target_provider_message_key)
            if message_ts is None:
                result_status = ExternalChannelDeliveryStatus.FAILED
                provider_message_key = None
                error_kind = "activity_payload_invalid"
                error_summary = "The persisted Activity Tracker payload is invalid."
            else:
                result = await self.slack_client.update_message(
                    bot_token=bot_token,
                    tenant_id=tenant_id,
                    channel_id=channel_id,
                    message_ts=message_ts,
                    text=prepend_agent_fallback(presentation, text),
                    blocks=prepend_agent_blocks(
                        presentation,
                        [block for block in blocks if isinstance(block, dict)],
                    ),
                )
                result_status = ExternalChannelDeliveryStatus(result.status)
                provider_message_key = result.provider_message_key
                error_kind = result.error_kind
                error_summary = result.error_summary
        else:
            result_status = ExternalChannelDeliveryStatus.FAILED
            provider_message_key = None
            error_kind = "activity_operation_invalid"
            error_summary = "The persisted Activity Tracker operation is invalid."
        async with self.session_manager() as session:
            followup_delivery_id = await self.work_repository.finish_delivery(
                session,
                delivery_attempt_id=delivery_attempt_id,
                status=result_status,
                provider_message_key=provider_message_key,
                error_kind=error_kind,
                error_summary=error_summary,
                now=_now(),
            )
            if error_kind in {"credentials_invalid", "missing_scope"}:
                await self.repository.mark_connection_reconnect_required(
                    session,
                    connection_id=configuration.id,
                    reason=error_kind,
                    now=_now(),
                    required_socket_lease_owner=None,
                )
            await session.commit()
        if followup_delivery_id is not None:
            await self._attempt_activity_delivery(
                configuration=configuration,
                delivery_attempt_id=followup_delivery_id,
                bot_token=bot_token,
            )

    async def _attempt_session_link_delivery(
        self,
        *,
        configuration: ExternalChannelConnectionConfiguration,
        delivery_attempt_id: str,
        bot_token: str,
    ) -> None:
        """Attempt the one-time Session link message for a new binding."""
        async with self.session_manager() as session:
            target = await self.work_repository.get_delivery_target(
                session,
                delivery_attempt_id=delivery_attempt_id,
            )
            attempt = await self.repository.start_delivery_attempt(
                session,
                delivery_attempt_id=delivery_attempt_id,
                attempted_at=_now(),
            )
            await session.commit()
        if attempt is None:
            return
        presentation = resolve_slack_agent_presentation(
            target,
            avatar_cdn_base_url=self.config.avatar_cdn_base_url,
        )
        payload = attempt.request_payload
        tenant_id = payload.get("tenant_id")
        channel_id = payload.get("channel_id")
        thread_ts = payload.get("thread_ts")
        text = payload.get("text")
        blocks = payload.get("blocks")
        if (
            attempt.operation is not ExternalChannelDeliveryOperation.CONTROL_MESSAGE
            or not isinstance(tenant_id, str)
            or not tenant_id
            or not isinstance(channel_id, str)
            or not channel_id
            or not isinstance(thread_ts, str)
            or not thread_ts
            or not isinstance(text, str)
            or not text
            or not isinstance(blocks, list)
            or not all(isinstance(block, dict) for block in blocks)
        ):
            result_status = ExternalChannelDeliveryStatus.FAILED
            provider_message_key = None
            error_kind = "session_link_payload_invalid"
            error_summary = "The persisted Session link payload is invalid."
        else:
            result = await self.slack_client.post_blocks(
                bot_token=bot_token,
                tenant_id=tenant_id,
                channel_id=channel_id,
                thread_ts=thread_ts,
                text=prepend_agent_fallback(presentation, text),
                blocks=prepend_agent_blocks(
                    presentation,
                    [block for block in blocks if isinstance(block, dict)],
                ),
                icon_url=(None if presentation is None else presentation.icon_url),
            )
            result_status = ExternalChannelDeliveryStatus(result.status)
            provider_message_key = result.provider_message_key
            error_kind = result.error_kind
            error_summary = result.error_summary
        async with self.session_manager() as session:
            await self.repository.finish_delivery_attempt(
                session,
                delivery_attempt_id=delivery_attempt_id,
                status=result_status,
                provider_message_key=provider_message_key,
                error_kind=error_kind,
                error_summary=error_summary,
                completed_at=_now(),
            )
            if error_kind in {"credentials_invalid", "missing_scope"}:
                await self.repository.mark_connection_reconnect_required(
                    session,
                    connection_id=configuration.id,
                    reason=error_kind,
                    now=_now(),
                    required_socket_lease_owner=None,
                )
            await session.commit()

    async def _attempt_control_delivery(
        self,
        *,
        configuration: ExternalChannelConnectionConfiguration,
        delivery_attempt_id: str,
        bot_token: str,
    ) -> None:
        now = _now()
        async with self.session_manager() as session:
            target = await self.work_repository.get_delivery_target(
                session,
                delivery_attempt_id=delivery_attempt_id,
            )
            attempt = await self.repository.start_delivery_attempt(
                session,
                delivery_attempt_id=delivery_attempt_id,
                attempted_at=now,
            )
            await session.commit()
        if attempt is None:
            return
        presentation = resolve_slack_agent_presentation(
            target,
            avatar_cdn_base_url=self.config.avatar_cdn_base_url,
        )
        payload = attempt.request_payload
        tenant_id = payload.get("tenant_id")
        channel_id = payload.get("channel_id")
        thread_ts = payload.get("thread_ts")
        control_kind = payload.get("control_kind")
        conversation_admission_id = payload.get("conversation_admission_id")
        approval_url = payload.get("approval_url")
        participant_provider_user_id = payload.get("participant_provider_user_id")
        participant_label = payload.get("participant_label")
        if control_kind == "agent_selector":
            if (
                not isinstance(tenant_id, str)
                or not tenant_id
                or not isinstance(channel_id, str)
                or not channel_id
                or not isinstance(thread_ts, str)
                or not thread_ts
                or not isinstance(conversation_admission_id, str)
                or not conversation_admission_id
            ):
                result_status = ExternalChannelDeliveryStatus.FAILED
                provider_message_key = None
                error_kind = "control_payload_invalid"
                error_summary = "The persisted Slack control payload is invalid."
            else:
                selector = _render_agent_selector_control(conversation_admission_id)
                result = await self.slack_client.post_blocks(
                    bot_token=bot_token,
                    tenant_id=tenant_id,
                    channel_id=channel_id,
                    thread_ts=thread_ts,
                    text=selector.text,
                    blocks=selector.blocks,
                    icon_url=None,
                )
                result_status = ExternalChannelDeliveryStatus(result.status)
                provider_message_key = result.provider_message_key
                error_kind = result.error_kind
                error_summary = result.error_summary
        elif control_kind == "shortcut_already_bound":
            recorded_presentation = resolve_slack_agent_name_presentation(
                payload.get("recorded_agent_name")
                if isinstance(payload.get("recorded_agent_name"), str)
                else None
            )
            bound_presentation = presentation or recorded_presentation
            if (
                not isinstance(tenant_id, str)
                or not tenant_id
                or not isinstance(channel_id, str)
                or not channel_id
                or not isinstance(thread_ts, str)
                or not thread_ts
                or bound_presentation is None
            ):
                result_status = ExternalChannelDeliveryStatus.FAILED
                provider_message_key = None
                error_kind = "control_payload_invalid"
                error_summary = "The persisted Slack control payload is invalid."
            else:
                text = (
                    "This conversation is already linked to the recorded Agent. "
                    "Start a separate top-level conversation to use another Agent."
                )
                result = await self.slack_client.post_blocks(
                    bot_token=bot_token,
                    tenant_id=tenant_id,
                    channel_id=channel_id,
                    thread_ts=thread_ts,
                    text=prepend_agent_fallback(bound_presentation, text),
                    blocks=prepend_agent_blocks(
                        bound_presentation,
                        [
                            {
                                "type": "section",
                                "text": {"type": "mrkdwn", "text": text},
                            }
                        ],
                    ),
                    icon_url=bound_presentation.icon_url,
                )
                result_status = ExternalChannelDeliveryStatus(result.status)
                provider_message_key = result.provider_message_key
                error_kind = result.error_kind
                error_summary = result.error_summary
        elif (
            not isinstance(tenant_id, str)
            or not tenant_id
            or not isinstance(channel_id, str)
            or not channel_id
            or not isinstance(thread_ts, str)
            or not thread_ts
            or not isinstance(approval_url, str)
            or not approval_url
            or not isinstance(participant_provider_user_id, str)
            or not participant_provider_user_id
            or not isinstance(participant_label, str)
            or not participant_label
        ):
            result_status = ExternalChannelDeliveryStatus.FAILED
            provider_message_key = None
            error_kind = "control_payload_invalid"
            error_summary = "The persisted Slack control payload is invalid."
        else:
            result = await self.slack_client.post_approval_control_message(
                bot_token=bot_token,
                tenant_id=tenant_id,
                channel_id=channel_id,
                thread_ts=thread_ts,
                approval_url=approval_url,
                participant_label=participant_label,
                participant_provider_user_id=participant_provider_user_id,
                agent_name=(
                    None
                    if presentation is None or not presentation.show_name
                    else presentation.name
                ),
                agent_markdown_line=(
                    None
                    if presentation is None or not presentation.show_name
                    else presentation.markdown_line
                ),
                icon_url=(None if presentation is None else presentation.icon_url),
            )
            result_status = ExternalChannelDeliveryStatus(result.status)
            provider_message_key = result.provider_message_key
            error_kind = result.error_kind
            error_summary = result.error_summary
        async with self.session_manager() as session:
            finished = await self.repository.finish_delivery_attempt(
                session,
                delivery_attempt_id=delivery_attempt_id,
                status=result_status,
                provider_message_key=provider_message_key,
                error_kind=error_kind,
                error_summary=error_summary,
                completed_at=_now(),
            )
            if error_kind in {"credentials_invalid", "missing_scope"}:
                await self.repository.mark_connection_reconnect_required(
                    session,
                    connection_id=configuration.id,
                    reason=error_kind,
                    now=_now(),
                    required_socket_lease_owner=None,
                )
            await session.commit()
        if (
            finished is not None
            and finished.origin_type is ExternalChannelDeliveryOriginType.ACCESS_REQUEST
            and result_status is ExternalChannelDeliveryStatus.DELIVERED
        ):
            async with self.session_manager() as session:
                delete_intent = (
                    await self.repository.create_access_request_control_delete_intent(
                        session,
                        access_request_id=finished.origin_id,
                    )
                )
                await session.commit()
            if (
                delete_intent is not None
                and delete_intent.status is ExternalChannelDeliveryStatus.PENDING
            ):
                await self._attempt_access_request_control_delete_delivery(
                    configuration=configuration,
                    delivery_attempt_id=delete_intent.id,
                    bot_token=bot_token,
                )

    async def _attempt_access_request_control_delete_delivery(
        self,
        *,
        configuration: ExternalChannelConnectionConfiguration,
        delivery_attempt_id: str,
        bot_token: str,
    ) -> None:
        """Delete one approval control message created after a decision race."""
        async with self.session_manager() as session:
            attempt = await self.repository.start_delivery_attempt(
                session,
                delivery_attempt_id=delivery_attempt_id,
                attempted_at=_now(),
            )
            await session.commit()
        if attempt is None:
            return
        tenant_id = configuration.provider_tenant_id
        channel_id = attempt.request_payload.get("channel_id")
        target_provider_message_key = attempt.request_payload.get(
            "provider_message_key"
        )
        message_ts = _provider_message_ts(target_provider_message_key)
        if (
            attempt.origin_type is not ExternalChannelDeliveryOriginType.ACCESS_REQUEST
            or attempt.operation is not ExternalChannelDeliveryOperation.PROGRESS_DELETE
            or not isinstance(tenant_id, str)
            or not tenant_id
            or not isinstance(channel_id, str)
            or not channel_id
            or message_ts is None
        ):
            result_status = ExternalChannelDeliveryStatus.FAILED
            provider_message_key = None
            error_kind = "control_delete_payload_invalid"
            error_summary = "The persisted Slack control delete payload is invalid."
        else:
            result = await self.slack_client.delete_message(
                bot_token=bot_token,
                tenant_id=tenant_id,
                channel_id=channel_id,
                message_ts=message_ts,
            )
            result_status = ExternalChannelDeliveryStatus(result.status)
            provider_message_key = result.provider_message_key
            error_kind = result.error_kind
            error_summary = result.error_summary
        async with self.session_manager() as session:
            await self.repository.finish_delivery_attempt(
                session,
                delivery_attempt_id=delivery_attempt_id,
                status=result_status,
                provider_message_key=provider_message_key,
                error_kind=error_kind,
                error_summary=error_summary,
                completed_at=_now(),
            )
            if error_kind in {"credentials_invalid", "missing_scope"}:
                await self.repository.mark_connection_reconnect_required(
                    session,
                    connection_id=configuration.id,
                    reason=error_kind,
                    now=_now(),
                    required_socket_lease_owner=None,
                )
            await session.commit()

    async def _hydrate_resource(
        self,
        *,
        event: ExternalChannelEvent,
        configuration: ExternalChannelConnectionConfiguration,
        resource_id: str,
        bot_token: str,
    ) -> None:
        now = _now()
        resource: ExternalChannelResource | None = None
        async with self.session_manager() as session:
            connection = await self.repository.lock_connection_for_routing(
                session,
                connection_id=configuration.id,
            )
            if connection is None:
                raise _HydrationRoutingUnavailable
            resource = await self.repository.mark_resource_hydration_running(
                session,
                resource_id=resource_id,
                started_at=now,
            )
            if resource is None:
                raise RuntimeError("External Channel resource disappeared.")
            await self.repository.lock_active_binding_by_resource(
                session,
                resource_id=resource_id,
            )
            await session.commit()
        if _hydration_terminal(resource.hydration_status):
            return
        labels = resource.labels or {}
        channel_id = labels.get("channel_id")
        thread_ts = labels.get("thread_ts")
        if not isinstance(channel_id, str) or not isinstance(thread_ts, str):
            raise RuntimeError("External Channel Slack resource labels are invalid.")
        channel_display_name = labels.get("channel_name")
        if not isinstance(channel_display_name, str) or not channel_display_name:
            channel_display_name = None
        reference_cache: dict[str, dict[str, str]] = {
            "users": {},
            "channels": (
                {channel_id: channel_display_name}
                if channel_display_name is not None
                else {}
            ),
        }
        cursor = resource.hydration_cursor
        bounded = False
        high_watermark = resource.hydration_high_watermark_position
        try:
            for _ in range(_HYDRATION_MAX_PAGES):
                page = await self.slack_client.fetch_thread_page(
                    bot_token=bot_token,
                    tenant_id=event.provider_tenant_id or "",
                    channel_id=channel_id,
                    root_thread_ts=thread_ts,
                    cursor=cursor,
                    limit=_HYDRATION_PAGE_SIZE,
                )
                latest_activity = None
                async with self.session_manager() as session:
                    connection = await self.repository.lock_connection_for_routing(
                        session,
                        connection_id=configuration.id,
                    )
                    if connection is None:
                        raise _HydrationRoutingUnavailable
                    binding_snapshot = (
                        await self.repository.get_active_binding_by_resource(
                            session,
                            resource_id=resource_id,
                        )
                    )
                    route = None
                    if binding_snapshot is not None:
                        route = await self.repository.get_routable_route_by_id(
                            session,
                            route_id=binding_snapshot.route_id,
                        )
                        if route is None or route.connection_id != connection.id:
                            raise _HydrationRoutingUnavailable
                    current_resource = await self.repository.lock_resource(
                        session,
                        resource_id=resource_id,
                    )
                    if current_resource is None:
                        raise RuntimeError("External Channel resource disappeared.")
                    binding = await self.repository.lock_active_binding_by_resource(
                        session,
                        resource_id=resource_id,
                    )
                    if (binding_snapshot is None) != (binding is None) or (
                        binding_snapshot is not None
                        and binding is not None
                        and (
                            binding_snapshot.id != binding.id
                            or binding_snapshot.route_id != binding.route_id
                        )
                    ):
                        raise _HydrationRoutingUnavailable
                    for history_message in page.messages:
                        if connection_authored(configuration, history_message):
                            continue
                        reference_mappings = await self._resolve_reference_mappings(
                            message=history_message,
                            bot_token=bot_token,
                            channel_display_name=channel_display_name,
                            cache=reference_cache,
                        )
                        persisted_revision = await self._persist_normalized_message(
                            session,
                            resource=current_resource,
                            message=history_message,
                            source_event_id=None,
                            now=_now(),
                            original_url=None,
                            reference_mappings=_resource_reference_mappings(
                                reference_mappings,
                                current_resource.labels,
                            ),
                        )
                        trim = (
                            ExternalChannelPendingContextTrim(
                                deleted_message_count=0,
                                deleted_size=0,
                                retained_message_count=0,
                                retained_size=0,
                            )
                            if route is None
                            else await self._project_current_revision(
                                session,
                                route=route,
                                resource=current_resource,
                                message=persisted_revision.message,
                                provider_position=history_message.provider_position,
                                now=_now(),
                                applied=persisted_revision.applied,
                            )
                        )
                        if route is not None:
                            binding = await self._record_trim(
                                session,
                                route=route,
                                resource=current_resource,
                                binding=binding,
                                trim=trim,
                            )
                        if trim.deleted_message_count or trim.deleted_size:
                            bounded = True
                        if (
                            latest_activity is None
                            or history_message.provider_created_at is not None
                            and history_message.provider_created_at > latest_activity
                        ):
                            latest_activity = history_message.provider_created_at
                        if (
                            high_watermark is None
                            or history_message.provider_position > high_watermark
                        ):
                            high_watermark = history_message.provider_position
                    cursor = page.next_cursor
                    await self.repository.update_resource_hydration_cursor(
                        session,
                        resource_id=resource_id,
                        cursor=cursor,
                        high_watermark_position=high_watermark,
                        latest_activity_at=latest_activity,
                    )
                    await session.commit()
                if cursor is None:
                    break
            else:
                bounded = True
        except _HydrationRoutingUnavailable:
            await self._complete_hydration(
                configuration=configuration,
                resource_id=resource_id,
                status=ExternalChannelHydrationStatus.INCOMPLETE,
                error_kind="routing_unavailable",
                error_summary="External Channel routing became unavailable.",
            )
            return
        except SlackProviderResourceUnavailable:
            await self._complete_hydration(
                configuration=configuration,
                resource_id=resource_id,
                status=ExternalChannelHydrationStatus.INCOMPLETE,
                error_kind="resource_unavailable",
                error_summary="Slack thread history is unavailable to the App.",
            )
            async with self.session_manager() as session:
                await self.repository.terminate_resource_for_provider_loss(
                    session,
                    resource_id=resource_id,
                    reason="resource_unavailable",
                    now=_now(),
                )
                await session.commit()
            return
        await self._complete_hydration(
            configuration=configuration,
            resource_id=resource_id,
            status=(
                ExternalChannelHydrationStatus.BOUNDED
                if bounded or cursor is not None
                else ExternalChannelHydrationStatus.COMPLETE
            ),
            error_kind=None,
            error_summary=None,
        )

    async def _hydrate_discord_resource(
        self,
        *,
        configuration: ExternalChannelConnectionConfiguration,
        resource_id: str,
        bot_token: str,
    ) -> None:
        """Reconcile bounded Discord root/thread history through canonical revisions."""
        now = _now()
        async with self.session_manager() as session:
            connection = await self.repository.lock_connection_for_routing(
                session,
                connection_id=configuration.id,
            )
            if connection is None:
                raise _HydrationRoutingUnavailable
            resource = await self.repository.mark_resource_hydration_running(
                session,
                resource_id=resource_id,
                started_at=now,
            )
            if resource is None:
                raise RuntimeError("External Channel resource disappeared.")
            await self.repository.lock_active_binding_by_resource(
                session,
                resource_id=resource_id,
            )
            await session.commit()
        if _hydration_terminal(resource.hydration_status):
            return
        labels = resource.labels or {}
        guild_id = labels.get("guild_id")
        source_channel_id = labels.get("source_channel_id")
        root_message_id = labels.get("root_message_id")
        thread_channel_id = labels.get("thread_channel_id")
        if (
            not isinstance(guild_id, str)
            or not guild_id
            or not isinstance(source_channel_id, str)
            or not source_channel_id
            or not isinstance(root_message_id, str)
            or not root_message_id
            or thread_channel_id is not None
            and (not isinstance(thread_channel_id, str) or not thread_channel_id)
        ):
            raise RuntimeError("External Channel Discord resource labels are invalid.")
        cursor = resource.hydration_cursor
        bounded = False
        high_watermark = resource.hydration_high_watermark_position
        try:
            for _ in range(_HYDRATION_MAX_PAGES):
                page = await self.discord_history_client.fetch_thread_page(
                    bot_token=bot_token,
                    guild_id=guild_id,
                    source_channel_id=source_channel_id,
                    root_message_id=root_message_id,
                    thread_channel_id=thread_channel_id,
                    cursor=cursor,
                    limit=_HYDRATION_PAGE_SIZE,
                    connected_bot_user_id=configuration.provider_bot_user_id,
                )
                latest_activity = None
                async with self.session_manager() as session:
                    connection = await self.repository.lock_connection_for_routing(
                        session,
                        connection_id=configuration.id,
                    )
                    if connection is None:
                        raise _HydrationRoutingUnavailable
                    binding_snapshot = (
                        await self.repository.get_active_binding_by_resource(
                            session,
                            resource_id=resource_id,
                        )
                    )
                    route = None
                    if binding_snapshot is not None:
                        route = await self.repository.get_routable_route_by_id(
                            session,
                            route_id=binding_snapshot.route_id,
                        )
                        if route is None or route.connection_id != connection.id:
                            raise _HydrationRoutingUnavailable
                    current_resource = await self.repository.lock_resource(
                        session,
                        resource_id=resource_id,
                    )
                    if current_resource is None:
                        raise RuntimeError("External Channel resource disappeared.")
                    binding = await self.repository.lock_active_binding_by_resource(
                        session,
                        resource_id=resource_id,
                    )
                    if (binding_snapshot is None) != (binding is None) or (
                        binding_snapshot is not None
                        and binding is not None
                        and (
                            binding_snapshot.id != binding.id
                            or binding_snapshot.route_id != binding.route_id
                        )
                    ):
                        raise _HydrationRoutingUnavailable
                    for history_message in page.messages:
                        if connection_authored(configuration, history_message):
                            continue
                        persisted_revision = await self._persist_normalized_message(
                            session,
                            resource=current_resource,
                            message=history_message,
                            source_event_id=None,
                            now=_now(),
                            original_url=_discord_original_url(history_message),
                            reference_mappings=history_message.reference_mappings,
                            provider=ExternalChannelProvider.DISCORD,
                        )
                        trim = (
                            ExternalChannelPendingContextTrim(
                                deleted_message_count=0,
                                deleted_size=0,
                                retained_message_count=0,
                                retained_size=0,
                            )
                            if route is None
                            else await self._project_current_revision(
                                session,
                                route=route,
                                resource=current_resource,
                                message=persisted_revision.message,
                                provider_position=history_message.provider_position,
                                now=_now(),
                                applied=persisted_revision.applied,
                            )
                        )
                        if route is not None:
                            binding = await self._record_trim(
                                session,
                                route=route,
                                resource=current_resource,
                                binding=binding,
                                trim=trim,
                            )
                        if trim.deleted_message_count or trim.deleted_size:
                            bounded = True
                        if (
                            latest_activity is None
                            or history_message.provider_created_at is not None
                            and history_message.provider_created_at > latest_activity
                        ):
                            latest_activity = history_message.provider_created_at
                        if (
                            high_watermark is None
                            or history_message.provider_position > high_watermark
                        ):
                            high_watermark = history_message.provider_position
                    cursor = page.next_cursor
                    await self.repository.update_resource_hydration_cursor(
                        session,
                        resource_id=resource_id,
                        cursor=cursor,
                        high_watermark_position=high_watermark,
                        latest_activity_at=latest_activity,
                    )
                    await session.commit()
                if cursor is None:
                    break
            else:
                bounded = True
        except _HydrationRoutingUnavailable:
            await self._complete_hydration(
                configuration=configuration,
                resource_id=resource_id,
                status=ExternalChannelHydrationStatus.INCOMPLETE,
                error_kind="routing_unavailable",
                error_summary="External Channel routing became unavailable.",
            )
            return
        except DiscordHistoryResourceUnavailable:
            await self._complete_hydration(
                configuration=configuration,
                resource_id=resource_id,
                status=ExternalChannelHydrationStatus.INCOMPLETE,
                error_kind="resource_unavailable",
                error_summary="Discord conversation history is unavailable to the App.",
            )
            async with self.session_manager() as session:
                await self.repository.terminate_resource_for_provider_loss(
                    session,
                    resource_id=resource_id,
                    reason="resource_unavailable",
                    now=_now(),
                )
                await session.commit()
            return
        await self._complete_hydration(
            configuration=configuration,
            resource_id=resource_id,
            status=(
                ExternalChannelHydrationStatus.BOUNDED
                if bounded or cursor is not None
                else ExternalChannelHydrationStatus.COMPLETE
            ),
            error_kind=None,
            error_summary=None,
        )

    async def _complete_hydration(
        self,
        *,
        configuration: ExternalChannelConnectionConfiguration,
        resource_id: str,
        status: ExternalChannelHydrationStatus,
        error_kind: str | None,
        error_summary: str | None,
    ) -> None:
        async with self.session_manager() as session:
            resource = await self.repository.get_resource(
                session,
                resource_id=resource_id,
            )
            if resource is None:
                raise RuntimeError("External Channel resource disappeared.")
            correlation_key = _resource_correlation_key(resource)
            boundary = await self.repository.latest_correlated_event_boundary(
                session,
                connection_id=configuration.id,
                resource_correlation_key=correlation_key,
            )
            if boundary is None:
                raise RuntimeError("Hydration reconciliation boundary is missing.")
            await self.repository.complete_resource_hydration(
                session,
                resource_id=resource_id,
                status=status,
                boundary=boundary,
                completed_at=_now(),
                error_kind=error_kind,
                error_summary=error_summary,
            )
            await session.commit()

    async def _release_pending_context(
        self,
        session: AsyncSession,
        *,
        binding: ExternalChannelBinding,
        trigger_message_id: str,
        now: datetime.datetime,
        initial_activation: bool,
        workspace_id: str,
        agent_id: str,
        provider: ExternalChannelProvider = ExternalChannelProvider.SLACK,
    ) -> ExternalChannelReleasedInvocation | None:
        existing = await self.repository.get_invocation_batch(
            session,
            binding_id=binding.id,
            trigger_message_id=trigger_message_id,
        )
        trigger = await self.repository.get_message(
            session,
            message_id=trigger_message_id,
        )
        if trigger is None:
            raise RuntimeError("External Channel invocation trigger disappeared.")
        if existing is not None and existing.mailbox_item_id is None:
            existing, _ = await self._ensure_invocation_mailbox_item(
                session,
                binding=binding,
                batch=existing,
            )
        pending = await self.repository.list_pending_context(
            session,
            route_id=binding.route_id,
            resource_id=binding.resource_id,
            now=now,
            through_provider_position=trigger.provider_position,
        )
        if not pending:
            session_link_delivery_attempt_id = None
            activity_delivery_attempt_id = None
            if existing is not None and initial_activation:
                (
                    session_link_delivery_attempt_id,
                    activity_delivery_attempt_id,
                ) = await self.repository.get_pending_initial_delivery_attempt_ids(
                    session,
                    binding_id=binding.id,
                )
            return (
                None
                if existing is None
                else ExternalChannelReleasedInvocation(
                    batch=existing,
                    session_link_delivery_attempt_id=(session_link_delivery_attempt_id),
                    activity_delivery_attempt_id=activity_delivery_attempt_id,
                )
            )
        if existing is None:
            batch = await self.repository.create_invocation_batch_idempotent(
                session,
                ExternalChannelInvocationBatchCreate(
                    binding_id=binding.id,
                    trigger_message_id=trigger_message_id,
                    first_provider_position=pending[0].provider_position,
                    last_provider_position=pending[-1].provider_position,
                    truncation_message_count=binding.truncated_message_count,
                    truncation_size=binding.truncated_size,
                    mailbox_item_id=None,
                ),
            )
            for sequence, item in enumerate(pending):
                await self.repository.create_invocation_batch_item_idempotent(
                    session,
                    ExternalChannelInvocationBatchItemCreate(
                        batch_id=batch.id,
                        message_revision_id=item.message_revision_id,
                        sequence=sequence,
                        provider_position=item.provider_position,
                    ),
                )
            released_pending = pending
        else:
            batch = existing
            batch_revision_ids = set(
                await self.repository.list_invocation_batch_revision_ids(
                    session,
                    batch_id=batch.id,
                )
            )
            released_pending = [
                item
                for item in pending
                if item.message_revision_id in batch_revision_ids
            ]
        batch, _ = await self._ensure_invocation_mailbox_item(
            session,
            binding=binding,
            batch=batch,
        )
        work = await self.repository.ensure_active_work(
            session,
            binding_id=binding.id,
            desired_progress_payload=checking_progress().model_dump(mode="json"),
        )
        resource = await self.repository.get_resource(
            session,
            resource_id=binding.resource_id,
        )
        if resource is None:
            raise RuntimeError("External Channel resource disappeared.")
        session_link_attempt_id = None
        if initial_activation:
            workspace = await self.workspace_repository.get_by_id(
                session,
                workspace_id,
            )
            if workspace is None:
                raise RuntimeError("External Channel Workspace disappeared.")
            session_url = _session_url(
                self.config.web_url,
                workspace.handle,
                agent_id,
                binding.agent_session_id,
            )
            if session_url is None:
                raise RuntimeError("External Channel Session URL is unavailable.")
            session_link_payload = _session_link_payload(
                provider=provider,
                resource=resource,
                session_url=session_url,
            )
            session_link_attempt = (
                await self.repository.create_delivery_attempt_idempotent(
                    session,
                    ExternalChannelDeliveryAttemptCreate(
                        origin_type=(
                            ExternalChannelDeliveryOriginType.MANAGER_OPERATION
                        ),
                        origin_id=binding.id,
                        channel_action_id=None,
                        binding_id=binding.id,
                        operation=(ExternalChannelDeliveryOperation.CONTROL_MESSAGE),
                        request_payload=session_link_payload,
                        status=ExternalChannelDeliveryStatus.PENDING,
                        provider_message_key=None,
                        error_kind=None,
                        error_summary=None,
                        attempted_at=None,
                        completed_at=None,
                    ),
                )
            )
            if session_link_attempt.status is ExternalChannelDeliveryStatus.PENDING:
                session_link_attempt_id = session_link_attempt.id
        if provider is ExternalChannelProvider.DISCORD:
            activity_delivery_attempt_id = (
                await self.work_repository.ensure_initial_discord_progress(
                    session,
                    work_id=work.id,
                    binding_id=binding.id,
                    labels=resource.labels,
                )
            )
        else:
            presentation = render_slack_progress(
                checking_progress(),
                work_id=work.id,
                desired_progress_revision=work.desired_progress_revision,
            )
            activity_attempt = await self.repository.create_delivery_attempt_idempotent(
                session,
                ExternalChannelDeliveryAttemptCreate(
                    origin_type=ExternalChannelDeliveryOriginType.MANAGER_OPERATION,
                    origin_id=work.id,
                    channel_action_id=None,
                    binding_id=binding.id,
                    operation=ExternalChannelDeliveryOperation.PROGRESS_CREATE,
                    request_payload={
                        **_activity_provider_target(resource, work),
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
            activity_delivery_attempt_id = (
                activity_attempt.id
                if activity_attempt.status is ExternalChannelDeliveryStatus.PENDING
                else None
            )
        await self.repository.delete_pending_context_ids(
            session,
            pending_context_ids=[item.id for item in released_pending],
        )
        if not initial_activation:
            await self.repository.advance_binding_projection(
                session,
                binding_id=binding.id,
                projected_through_position=batch.last_provider_position,
            )
        return ExternalChannelReleasedInvocation(
            batch=batch,
            session_link_delivery_attempt_id=session_link_attempt_id,
            activity_delivery_attempt_id=activity_delivery_attempt_id,
        )

    async def _activate_binding_after_wake(
        self,
        *,
        binding_id: str,
        now: datetime.datetime,
        projected_through_position: str,
    ) -> bool:
        """Complete activation only after the durable input has been woken."""
        async with self.session_manager() as session:
            binding = await self.repository.mark_binding_activated(
                session,
                binding_id=binding_id,
                now=now,
                projected_through_position=projected_through_position,
            )
            await session.commit()
        return binding is not None

    async def _ensure_invocation_mailbox_item(
        self,
        session: AsyncSession,
        *,
        binding: ExternalChannelBinding,
        batch: ExternalChannelInvocationBatch,
    ) -> tuple[ExternalChannelInvocationBatch, bool]:
        """Create and link one idempotent wake-producing batch MailboxItem."""
        locked = await self.repository.lock_invocation_batch(
            session,
            batch_id=batch.id,
        )
        if locked is None:
            raise RuntimeError("External Channel invocation batch disappeared.")
        if locked.mailbox_item_id is not None:
            return locked, False
        projection_items = await self.repository.list_invocation_projection_items(
            session,
            batch_id=batch.id,
        )
        enqueue = await self.mailbox_item_service.enqueue(
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
                payload=build_external_channel_mailbox_payload(projection_items),
            ),
        )
        linked = await self.repository.link_invocation_batch_mailbox_item(
            session,
            batch_id=batch.id,
            mailbox_item_id=enqueue.mailbox_item.id,
        )
        if linked is None:
            raise RuntimeError("External Channel invocation batch disappeared.")
        return linked, enqueue.created

    async def _apply_connection_revocation(
        self,
        *,
        event: ExternalChannelEvent,
        revocation: SlackConnectionRevocation,
    ) -> None:
        cleanup_targets: list[ChannelDeliveryTarget] = []
        async with self.session_manager() as session:
            if revocation.kind == "app_uninstalled":
                cleanup_ids = (
                    await self.repository.terminate_connection_for_provider_event(
                        session,
                        connection_id=event.connection_id,
                        status=ExternalChannelConnectionStatus.DISCONNECTED,
                        reason=revocation.kind,
                        now=_now(),
                        required_socket_lease_owner=None,
                        defer_provider_state_purge=True,
                    )
                )
                for delivery_id in cleanup_ids or ():
                    target = await self.action_service.prepare_delivery_in_session(
                        session,
                        delivery_id,
                    )
                    if target is not None:
                        cleanup_targets.append(target)
                purged = (
                    await self.repository.purge_disconnected_connection_provider_state(
                        session,
                        connection_id=event.connection_id,
                    )
                )
                if cleanup_ids is not None and not purged:
                    raise RuntimeError(
                        "Disconnected External Channel provider state disappeared."
                    )
            else:
                await self.repository.mark_connection_reconnect_required(
                    session,
                    connection_id=event.connection_id,
                    reason=revocation.kind,
                    now=_now(),
                    required_socket_lease_owner=None,
                )
            await session.commit()
        for target in cleanup_targets:
            await self.action_service.attempt_prepared_delivery(target)
        raise _ConnectionUnavailable(revocation.kind)

    async def _mark_connection_reconnect_required(
        self,
        *,
        connection_id: str,
        reason: str,
    ) -> None:
        async with self.session_manager() as session:
            await self.repository.mark_connection_reconnect_required(
                session,
                connection_id=connection_id,
                reason=reason,
                now=_now(),
                required_socket_lease_owner=None,
            )
            await session.commit()

    async def _complete_event(
        self,
        event: ExternalChannelEvent,
        *,
        eligibility_state: ExternalChannelEventEligibilityState,
        status: ExternalChannelEventStatus,
        purge_envelope: bool,
    ) -> None:
        async with self.session_manager() as session:
            await self.repository.complete_event(
                session,
                event_id=event.id,
                claim_owner=self.claim_owner,
                now=_now(),
                eligibility_state=eligibility_state,
                status=status,
                purge_envelope=purge_envelope,
            )
            await session.commit()

    async def _connection_configuration(
        self,
        connection_id: str,
    ) -> ExternalChannelConnectionConfiguration:
        async with self.session_manager() as session:
            configuration = await self.repository.get_connection_configuration(
                session,
                connection_id=connection_id,
            )
        if configuration is None:
            raise SlackEventExcluded("External Channel connection does not exist.")
        if configuration.status not in {
            ExternalChannelConnectionStatus.ACTIVE,
            ExternalChannelConnectionStatus.DEGRADED,
        }:
            raise SlackEventExcluded("External Channel connection is not active.")
        return configuration


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _retry_delay(attempt_count: int) -> datetime.timedelta:
    seconds = min(2 ** max(0, attempt_count - 1), _MAX_RETRY_SECONDS)
    return datetime.timedelta(seconds=seconds)


def _hydration_terminal(status: ExternalChannelHydrationStatus) -> bool:
    return status in {
        ExternalChannelHydrationStatus.COMPLETE,
        ExternalChannelHydrationStatus.BOUNDED,
        ExternalChannelHydrationStatus.INCOMPLETE,
    }


def _hydration_activation_ready(status: ExternalChannelHydrationStatus) -> bool:
    """Only complete or bounded history may release a waiting binding."""
    return status in {
        ExternalChannelHydrationStatus.COMPLETE,
        ExternalChannelHydrationStatus.BOUNDED,
    }


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


def _is_shortcut_source_event(event: ExternalChannelEvent) -> bool:
    """Avoid creating a mention selector control for a shortcut-owned source."""
    return event.provider_event_id.startswith("shortcut-")


def _render_agent_selector_control(
    conversation_admission_id: str,
) -> _SlackSelectorControlPresentation:
    """Render the one generic control for a retained Multi-App conversation."""
    return _SlackSelectorControlPresentation(
        text="Select an Agent to continue this conversation.",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "Select an Agent to continue this conversation.",
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Select Agent"},
                        "action_id": "azents_agent_selector_open",
                        "value": conversation_admission_id,
                    }
                ],
            },
        ],
    )


def _session_url(
    web_url: str,
    workspace_handle: str,
    agent_id: str,
    session_id: str,
) -> str | None:
    """Build the browser URL retained by an Activity Tracker."""
    normalized = web_url.rstrip("/")
    if not normalized:
        return None
    return f"{normalized}/w/{workspace_handle}/agents/{agent_id}/sessions/{session_id}"


def _activity_provider_target(
    resource: ExternalChannelResource,
    work: ExternalChannelWork,
) -> dict[str, object]:
    """Build the persisted provider target for one Activity Tracker."""
    return {
        "work_id": work.id,
        **_provider_thread_target(resource),
    }


def _provider_thread_target(
    resource: ExternalChannelResource,
) -> dict[str, object]:
    """Build one persisted provider conversation target without credentials."""
    labels = resource.labels or {}
    if labels.get("provider") == ExternalChannelProvider.DISCORD.value:
        guild_id = labels.get("guild_id")
        thread_id = labels.get("thread_id")
        if (
            not isinstance(guild_id, str)
            or not guild_id
            or not isinstance(thread_id, str)
            or not thread_id
        ):
            raise RuntimeError("External Channel Discord resource labels are invalid.")
        target: dict[str, object] = {
            "guild_id": guild_id,
            "channel_id": thread_id,
        }
        parent_channel_id = labels.get("parent_channel_id")
        root_message_id = labels.get("root_message_id")
        if (
            isinstance(parent_channel_id, str)
            and parent_channel_id
            and isinstance(root_message_id, str)
            and root_message_id == thread_id
        ):
            target["thread_parent_channel_id"] = parent_channel_id
            target["thread_root_message_id"] = root_message_id
        return target
    tenant_id = labels.get("tenant_id")
    channel_id = labels.get("channel_id")
    thread_ts = labels.get("thread_ts")
    if (
        not isinstance(tenant_id, str)
        or not tenant_id
        or not isinstance(channel_id, str)
        or not channel_id
        or not isinstance(thread_ts, str)
        or not thread_ts
    ):
        raise RuntimeError("External Channel Slack resource labels are invalid.")
    return {
        "tenant_id": tenant_id,
        "channel_id": channel_id,
        "thread_ts": thread_ts,
    }


def _session_link_payload(
    *,
    provider: ExternalChannelProvider,
    resource: ExternalChannelResource,
    session_url: str,
) -> dict[str, object]:
    """Build one provider-native Session-link control from canonical state."""
    if provider is ExternalChannelProvider.DISCORD:
        return {
            **_provider_thread_target(resource),
            "text": "",
            "components": _discord_link_button(
                label="Open Azents session",
                url=session_url,
            ),
        }
    session_link = render_slack_session_link(session_url)
    return {
        **_provider_thread_target(resource),
        "text": session_link.text,
        "blocks": session_link.blocks,
    }


def _render_persisted_activity(
    work: ExternalChannelWork,
) -> SlackProgressPresentation:
    """Render the latest desired Tracker state retained by one work cycle."""
    return render_slack_persisted_progress(
        work.desired_progress_payload,
        work_id=work.id,
        desired_progress_revision=work.desired_progress_revision,
    )


def _provider_message_ts(value: object) -> str | None:
    """Extract the provider timestamp from one durable Slack message identity."""
    if not isinstance(value, str) or ":" not in value:
        return None
    message_ts = value.rsplit(":", 1)[-1]
    return message_ts or None


def _resource_correlation_key(resource: ExternalChannelResource) -> str:
    labels = resource.labels or {}
    if labels.get("provider") == ExternalChannelProvider.DISCORD.value:
        guild_id = labels.get("guild_id")
        source_channel_id = labels.get("source_channel_id")
        if (
            isinstance(guild_id, str)
            and guild_id
            and isinstance(source_channel_id, str)
            and source_channel_id
        ):
            return f"{guild_id}:{source_channel_id}"
        raise RuntimeError("External Channel Discord resource labels are invalid.")
    channel_id = labels.get("channel_id")
    thread_ts = labels.get("thread_ts")
    if not isinstance(channel_id, str) or not isinstance(thread_ts, str):
        raise RuntimeError("External Channel Slack resource labels are invalid.")
    return f"{channel_id}:{thread_ts}"


def _discord_resource_key(*, tenant_id: str, thread_id: str) -> str:
    """Return the canonical connection-scoped key for one Discord thread."""
    return f"discord:{tenant_id}:{thread_id}"


def _discord_original_url(message: DiscordNormalizedMessage) -> str | None:
    """Return one canonical Discord message URL from validated snowflakes."""
    identifiers = (
        message.tenant_id,
        message.channel_id,
        message.message_id,
    )
    if not all(identifier.isdigit() for identifier in identifiers):
        return None
    return f"https://discord.com/channels/{'/'.join(identifiers)}"


def _resource_reference_mappings(
    mappings: dict[str, dict[str, str]],
    labels: dict[str, object] | None,
) -> dict[str, dict[str, str]]:
    """Add the tracked resource's retained channel label to one mapping."""
    merged = {category: dict(entries) for category, entries in mappings.items()}
    if not isinstance(labels, dict):
        return merged
    channel_id = labels.get("channel_id")
    channel_name = labels.get("channel_name")
    if (
        isinstance(channel_id, str)
        and channel_id
        and isinstance(channel_name, str)
        and channel_name
    ):
        merged.setdefault("channels", {})[channel_id] = channel_name
    return merged


def _resource_boundary(
    resource: ExternalChannelResource,
) -> ExternalChannelEventBoundary | None:
    if (
        resource.reconciliation_boundary_received_at is None
        or resource.reconciliation_boundary_event_id is None
    ):
        return None
    return ExternalChannelEventBoundary(
        received_at=resource.reconciliation_boundary_received_at,
        event_id=resource.reconciliation_boundary_event_id,
    )


def connection_authored(
    configuration: ExternalChannelConnectionConfiguration,
    message: SlackNormalizedMessage | DiscordNormalizedMessage,
) -> bool:
    provider_user_id = message.provider_user_id
    if provider_user_id is None:
        return False
    if provider_user_id.startswith("app:"):
        return provider_user_id.removeprefix("app:") == configuration.provider_app_id
    if provider_user_id.startswith("bot:"):
        return (
            provider_user_id.removeprefix("bot:") == configuration.provider_bot_user_id
        )
    return provider_user_id == configuration.provider_bot_user_id


def _route_accepts_author(
    route: ExternalChannelAgentRoute,
    author_type: ExternalChannelPrincipalAuthorType,
) -> bool:
    """Return whether this route admits a provider principal class."""
    if author_type is ExternalChannelPrincipalAuthorType.HUMAN:
        return True
    return (
        author_type is ExternalChannelPrincipalAuthorType.BOT
        and route.allow_bot_messages
    )


def _route_has_automatic_access(
    route: ExternalChannelAgentRoute,
    author_type: ExternalChannelPrincipalAuthorType,
) -> bool:
    """Return whether this route bypasses a per-principal access grant."""
    if author_type is ExternalChannelPrincipalAuthorType.HUMAN:
        return route.open_access_enabled
    return (
        author_type is ExternalChannelPrincipalAuthorType.BOT
        and route.allow_bot_messages
    )
