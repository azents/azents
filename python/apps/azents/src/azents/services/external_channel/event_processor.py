"""Durable External Channel event processing, hydration, and authorization."""

import asyncio
import dataclasses
import datetime
import logging
import secrets
from collections.abc import AsyncIterator
from typing import Annotated

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
    ExternalChannelBindingActivationStatus,
    ExternalChannelBindingStatus,
    ExternalChannelConnectionStatus,
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
    InputBufferKind,
    InputBufferSchedulingMode,
)
from azents.core.external_channel_activity import (
    ActivityTrackerPresentation,
    activity_tracker_payload,
    render_activity_tracker,
    render_persisted_activity_tracker,
    render_session_link,
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
    ExternalChannelConnectionConfiguration,
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
from azents.repos.workspace import WorkspaceRepository
from azents.services.external_channel.connection import (
    get_external_channel_credentials_codec,
    get_slack_validation_http_client,
)
from azents.services.external_channel.credentials import ExternalChannelCredentialsCodec
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
    normalize_slack_event,
    slack_message_reference_ids,
)
from azents.services.input_buffer import (
    EXTERNAL_CHANNEL_INVOCATION_BATCH_ID_METADATA_KEY,
    InputBufferEnqueue,
    InputBufferService,
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
    """Provide bounded Slack processing HTTP transport."""
    async for client in get_slack_validation_http_client():
        yield client


def get_slack_conversation_client(
    http_client: Annotated[
        httpx.AsyncClient,
        Depends(get_slack_processing_http_client),
    ],
) -> SlackConversationClient:
    """Provide the Slack conversation adapter."""
    return SlackConversationClient(http_client)


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
class _DeferredEvent(Exception):
    """Controlled event deferral with a stable retry reason."""

    retry_at: datetime.datetime
    error_kind: str
    error_summary: str


@dataclasses.dataclass(frozen=True)
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
    credentials_codec: Annotated[
        ExternalChannelCredentialsCodec,
        Depends(get_external_channel_credentials_codec),
    ]
    slack_client: Annotated[
        SlackConversationClient,
        Depends(get_slack_conversation_client),
    ]
    agent_repository: Annotated[
        AgentRepository,
        Depends(AgentRepository),
    ]
    agent_session_repository: Annotated[
        AgentSessionRepository,
        Depends(AgentSessionRepository),
    ]
    workspace_repository: Annotated[
        WorkspaceRepository,
        Depends(WorkspaceRepository),
    ]
    config: Annotated[Config, Depends(get_config)]
    input_buffer_service: Annotated[
        InputBufferService,
        Depends(InputBufferService),
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
            processed = await self.process_once()
            reconciled = await self.reconcile_waiting_bindings()
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

    async def reconcile_waiting_bindings(self) -> int:
        """Activate allowed bindings only after hydration reconciliation completes."""
        async with self.session_manager() as session:
            binding_ids = await self.repository.list_waiting_binding_ids(
                session,
                limit=_WAITING_BINDING_BATCH_SIZE,
            )
        reconciled = 0
        for binding_id in binding_ids:
            if await self.reconcile_binding(binding_id=binding_id):
                reconciled += 1
        return reconciled

    async def reconcile_binding(self, *, binding_id: str) -> bool:
        """Create the initial invocation batch when every activation fence passes."""
        now = _now()
        async with self.session_manager() as session:
            route = await self.repository.get_routable_route_by_binding_id(
                session,
                binding_id=binding_id,
            )
            if route is None:
                return False
            binding = await self.repository.lock_binding(
                session,
                binding_id=binding_id,
            )
            if (
                binding is None
                or binding.status is not ExternalChannelBindingStatus.ACTIVE
                or binding.activation_status
                is not ExternalChannelBindingActivationStatus.WAITING_HYDRATION
                or binding.activation_trigger_message_id is None
            ):
                return False
            resource = await self.repository.get_resource(
                session,
                resource_id=binding.resource_id,
            )
            if resource is None or not _hydration_terminal(resource.hydration_status):
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
                    agent_id=route.agent_id,
                    principal_id=trigger.principal_id,
                )
                is not None
            ):
                return False
            grant = await self.repository.get_active_access_grant(
                session,
                agent_id=route.agent_id,
                principal_id=trigger.principal_id,
                agent_session_id=binding.agent_session_id,
            )
            if grant is None:
                return False
            configuration = await self.repository.get_connection_configuration(
                session,
                connection_id=route.connection_id,
            )
            if configuration is None or configuration.encrypted_credentials is None:
                return False
            released = await self._release_pending_context(
                session,
                binding=binding,
                trigger_message_id=trigger.id,
                now=now,
                initial_activation=True,
                workspace_id=configuration.workspace_id,
                agent_id=route.agent_id,
            )
            if released is None:
                return False
            await session.commit()
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
            await self.session_lifecycle.send_session_wake_up(
                SessionWakeUp(
                    agent_id=route.agent_id,
                    session_id=binding.agent_session_id,
                    user_id=None,
                    additional_system_prompt=None,
                    interface=None,
                    workspace_id=None,
                    workspace_handle=None,
                )
            )
            return True

    async def _process_claimed_event_safely(
        self,
        event: ExternalChannelEvent,
    ) -> None:
        try:
            await self._process_claimed_event(event)
        except SlackEventExcluded as error:
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
        except SlackEventNormalizationError as error:
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
        if configuration.provider is not ExternalChannelProvider.SLACK:
            raise SlackEventExcluded("External Channel provider is not supported.")
        if configuration.encrypted_credentials is None:
            raise SlackEventExcluded("External Channel credentials are unavailable.")
        if event.provider_tenant_id is None:
            raise SlackEventNormalizationError("Slack tenant identity is missing.")
        credentials = self.credentials_codec.decrypt(
            configuration.encrypted_credentials
        )
        normalized = normalize_slack_event(
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
            route = await self.repository.get_routable_route_by_connection_id(
                session,
                connection_id=event.connection_id,
            )
            if route is None:
                raise SlackEventExcluded("No active Agent owns the Slack connection.")
            agent = await self.agent_repository.get_by_id(session, route.agent_id)
            if (
                agent is None
                or agent.lifecycle_status is not AgentLifecycleStatus.ACTIVE
            ):
                raise SlackEventExcluded("The routed Agent is not active.")

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
            binding = await self.repository.lock_active_binding_by_route_resource(
                session,
                route_id=route.id,
                resource_id=resource.id,
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
                route=route,
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
            trim = persisted_revision.trim
            binding = await self._record_trim(
                session,
                route=route,
                resource=resource,
                binding=binding,
                trim=trim,
            )
            control_delivery_attempt_id = None
            principal_id = canonical_message.principal_id
            if (
                principal_id is not None
                and message.author_type is ExternalChannelPrincipalAuthorType.HUMAN
            ):
                blocked = (
                    await self.repository.get_active_block(
                        session,
                        agent_id=route.agent_id,
                        principal_id=principal_id,
                    )
                    is not None
                )
                grant = None
                if not blocked:
                    grant = await self.repository.get_active_access_grant(
                        session,
                        agent_id=route.agent_id,
                        principal_id=principal_id,
                        agent_session_id=(
                            binding.agent_session_id if binding is not None else None
                        ),
                    )
                if (
                    binding is not None
                    and binding.activation_status
                    is ExternalChannelBindingActivationStatus.ACTIVE
                    and grant is not None
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
                        agent_id=route.agent_id,
                    )
                    if released is not None:
                        wake_session_id = binding.agent_session_id
                        activity_delivery_attempt_id = (
                            released.activity_delivery_attempt_id
                        )
                elif message.invocation and not blocked:
                    if binding is None and grant is not None:
                        binding = await self._create_granted_initial_binding(
                            session,
                            route=route,
                            resource=resource,
                            trigger_message=canonical_message,
                        )
                        binding = await self._record_trim(
                            session,
                            route=route,
                            resource=resource,
                            binding=binding,
                            trim=trim,
                        )
                    elif grant is None:
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
                                message=message,
                                trim=trim,
                                now=now,
                            )
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
                    SessionWakeUp(
                        agent_id=route.agent_id,
                        session_id=wake_session_id,
                        user_id=None,
                        additional_system_prompt=None,
                        interface=None,
                        workspace_id=None,
                        workspace_handle=None,
                    )
                    if wake_session_id is not None
                    else None
                ),
            )

    async def _persist_normalized_message(
        self,
        session: AsyncSession,
        *,
        route: ExternalChannelAgentRoute,
        resource: ExternalChannelResource,
        message: SlackNormalizedMessage,
        source_event_id: str | None,
        now: datetime.datetime,
        original_url: str | None,
        reference_mappings: dict[str, dict[str, str]],
    ) -> ExternalChannelPersistedRevision:
        principal_id = None
        if message.provider_user_id is not None:
            principal = await self.repository.create_principal_idempotent(
                session,
                ExternalChannelPrincipalCreate(
                    provider=ExternalChannelProvider.SLACK,
                    provider_tenant_id=message.tenant_id,
                    provider_user_id=message.provider_user_id,
                    author_type=message.author_type,
                    display_name=reference_mappings.get("users", {}).get(
                        message.provider_user_id
                    ),
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
        provider_time = message.provider_created_at or now
        await self.repository.create_pending_context_idempotent(
            session,
            ExternalChannelPendingContextCreate(
                route_id=route.id,
                resource_id=resource.id,
                message_revision_id=revision.id,
                provider_position=message.provider_position,
                normalized_size=message.normalized_size,
                expires_at=provider_time + _PENDING_CONTEXT_AGE,
            ),
        )
        trim = await self.repository.trim_pending_context(
            session,
            route_id=route.id,
            resource_id=resource.id,
            now=now,
            max_message_count=_PENDING_CONTEXT_MAX_MESSAGES,
            max_size=_PENDING_CONTEXT_MAX_SIZE,
        )
        return ExternalChannelPersistedRevision(
            message=current,
            trim=trim,
            applied=True,
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
    ) -> ExternalChannelBinding:
        locked_resource = await self.repository.lock_resource(
            session,
            resource_id=resource.id,
        )
        if locked_resource is None:
            raise RuntimeError("External Channel resource disappeared.")
        existing = await self.repository.get_active_binding_by_route_resource(
            session,
            route_id=route.id,
            resource_id=resource.id,
        )
        if existing is not None:
            return existing
        agent = await self.agent_repository.get_by_id(session, route.agent_id)
        if agent is None or agent.lifecycle_status is not AgentLifecycleStatus.ACTIVE:
            raise SlackEventExcluded("The routed Agent is not active.")
        agent_session = await self.agent_session_repository.create(
            session,
            AgentSessionCreate(
                workspace_id=agent.workspace_id,
                agent_id=agent.id,
                title=None,
                start_reason=AgentSessionStartReason.EXTERNAL_CHANNEL,
            ),
        )
        return await self.repository.create_binding_idempotent(
            session,
            ExternalChannelBindingCreate(
                resource_id=resource.id,
                route_id=route.id,
                agent_session_id=agent_session.id,
                status=ExternalChannelBindingStatus.ACTIVE,
                activation_status=(
                    ExternalChannelBindingActivationStatus.WAITING_HYDRATION
                ),
                activation_trigger_message_id=trigger_message.id,
                activated_at=None,
                projected_through_position=None,
                truncated_message_count=0,
                truncated_size=0,
                disconnected_at=None,
                disconnect_reason=None,
            ),
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
        message: SlackNormalizedMessage,
        trim: ExternalChannelPendingContextTrim,
        now: datetime.datetime,
    ) -> str | None:
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
                    "provider": "slack",
                    "agent_id": route.agent_id,
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
        payload: dict[str, object] = {
            "provider": "slack",
            "tenant_id": message.tenant_id,
            "channel_id": message.channel_id,
            "thread_ts": message.root_thread_ts,
            "access_request_id": request.id,
            "participant_provider_user_id": participant_provider_user_id,
            "participant_label": participant_label,
        }
        if approval_url is not None:
            payload["approval_url"] = approval_url
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
            attempt = await self.repository.start_delivery_attempt(
                session,
                delivery_attempt_id=delivery_attempt_id,
                attempted_at=_now(),
            )
            await session.commit()
        if attempt is None:
            return
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
                text=text,
                blocks=[block for block in blocks if isinstance(block, dict)],
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
                    text=text,
                    blocks=[block for block in blocks if isinstance(block, dict)],
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
            attempt = await self.repository.start_delivery_attempt(
                session,
                delivery_attempt_id=delivery_attempt_id,
                attempted_at=_now(),
            )
            await session.commit()
        if attempt is None:
            return
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
                text=text,
                blocks=[block for block in blocks if isinstance(block, dict)],
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
            attempt = await self.repository.start_delivery_attempt(
                session,
                delivery_attempt_id=delivery_attempt_id,
                attempted_at=now,
            )
            await session.commit()
        if attempt is None:
            return
        payload = attempt.request_payload
        tenant_id = payload.get("tenant_id")
        channel_id = payload.get("channel_id")
        thread_ts = payload.get("thread_ts")
        approval_url = payload.get("approval_url")
        participant_provider_user_id = payload.get("participant_provider_user_id")
        participant_label = payload.get("participant_label")
        if (
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
        routing_unavailable = False
        resource: ExternalChannelResource | None = None
        async with self.session_manager() as session:
            route = await self.repository.get_routable_route_by_connection_id(
                session,
                connection_id=configuration.id,
            )
            if route is None:
                routing_unavailable = True
            else:
                await self.repository.lock_active_binding_by_route_resource(
                    session,
                    route_id=route.id,
                    resource_id=resource_id,
                )
                resource = await self.repository.mark_resource_hydration_running(
                    session,
                    resource_id=resource_id,
                    started_at=now,
                )
                if resource is None:
                    raise RuntimeError("External Channel resource disappeared.")
                await session.commit()
        if routing_unavailable:
            await self._complete_hydration(
                configuration=configuration,
                resource_id=resource_id,
                status=ExternalChannelHydrationStatus.INCOMPLETE,
                error_kind="routing_unavailable",
                error_summary="External Channel routing became unavailable.",
            )
            return
        if resource is None:
            raise RuntimeError("External Channel resource disappeared.")
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
                    route = await self.repository.get_routable_route_by_connection_id(
                        session,
                        connection_id=configuration.id,
                    )
                    if route is None:
                        raise _HydrationRoutingUnavailable
                    binding = (
                        await self.repository.lock_active_binding_by_route_resource(
                            session,
                            route_id=route.id,
                            resource_id=resource_id,
                        )
                    )
                    current_resource = await self.repository.lock_resource(
                        session,
                        resource_id=resource_id,
                    )
                    if current_resource is None:
                        raise RuntimeError("External Channel resource disappeared.")
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
                            route=route,
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
                        trim = persisted_revision.trim
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
        if existing is not None and existing.input_buffer_id is None:
            existing, _ = await self._ensure_invocation_input_buffer(
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
            return (
                None
                if existing is None
                else ExternalChannelReleasedInvocation(
                    batch=existing,
                    session_link_delivery_attempt_id=None,
                    activity_delivery_attempt_id=None,
                )
            )
        batch = await self.repository.create_invocation_batch_idempotent(
            session,
            ExternalChannelInvocationBatchCreate(
                binding_id=binding.id,
                trigger_message_id=trigger_message_id,
                first_provider_position=pending[0].provider_position,
                last_provider_position=pending[-1].provider_position,
                truncation_message_count=binding.truncated_message_count,
                truncation_size=binding.truncated_size,
                input_buffer_id=None,
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
        batch, _ = await self._ensure_invocation_input_buffer(
            session,
            binding=binding,
            batch=batch,
        )
        work = await self.repository.ensure_active_work(
            session,
            binding_id=binding.id,
            desired_progress_payload=activity_tracker_payload(
                state="checking",
                tasks=(),
            ),
        )
        presentation = render_activity_tracker(
            state="checking",
            tasks=(),
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
            session_link = render_session_link(session_url)
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
                        request_payload={
                            **_provider_thread_target(resource),
                            "text": session_link.text,
                            "blocks": session_link.blocks,
                        },
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
        await self.repository.delete_pending_context_ids(
            session,
            pending_context_ids=[item.id for item in pending],
        )
        if initial_activation:
            await self.repository.mark_binding_activated(
                session,
                binding_id=binding.id,
                now=now,
                projected_through_position=pending[-1].provider_position,
            )
        else:
            await self.repository.advance_binding_projection(
                session,
                binding_id=binding.id,
                projected_through_position=pending[-1].provider_position,
            )
        return ExternalChannelReleasedInvocation(
            batch=batch,
            session_link_delivery_attempt_id=session_link_attempt_id,
            activity_delivery_attempt_id=(
                activity_attempt.id
                if activity_attempt.status is ExternalChannelDeliveryStatus.PENDING
                else None
            ),
        )

    async def _ensure_invocation_input_buffer(
        self,
        session: AsyncSession,
        *,
        binding: ExternalChannelBinding,
        batch: ExternalChannelInvocationBatch,
    ) -> tuple[ExternalChannelInvocationBatch, bool]:
        """Create and link one idempotent wake-producing batch InputBuffer."""
        locked = await self.repository.lock_invocation_batch(
            session,
            batch_id=batch.id,
        )
        if locked is None:
            raise RuntimeError("External Channel invocation batch disappeared.")
        if locked.input_buffer_id is not None:
            return locked, False
        metadata = {EXTERNAL_CHANNEL_INVOCATION_BATCH_ID_METADATA_KEY: batch.id}
        enqueue = await self.input_buffer_service.enqueue(
            session,
            InputBufferEnqueue(
                session_id=binding.agent_session_id,
                kind=InputBufferKind.EXTERNAL_CHANNEL_INVOCATION,
                scheduling_mode=InputBufferSchedulingMode.WAKE_SESSION,
                requested_model_target_label=None,
                requested_reasoning_effort=None,
                actor_user_id=None,
                content="",
                idempotency_key=f"external-channel-invocation:{batch.id}",
                metadata=metadata,
                attachments=[],
                file_parts=[],
                action=None,
            ),
        )
        linked = await self.repository.link_invocation_batch_input_buffer(
            session,
            batch_id=batch.id,
            input_buffer_id=enqueue.input_buffer.id,
        )
        if linked is None:
            raise RuntimeError("External Channel invocation batch disappeared.")
        await self.agent_session_repository.mark_running_for_input_wakeup(
            session,
            binding.agent_session_id,
        )
        return linked, enqueue.created

    async def _apply_connection_revocation(
        self,
        *,
        event: ExternalChannelEvent,
        revocation: SlackConnectionRevocation,
    ) -> None:
        async with self.session_manager() as session:
            if revocation.kind == "app_uninstalled":
                await self.repository.terminate_connection_for_provider_event(
                    session,
                    connection_id=event.connection_id,
                    status=ExternalChannelConnectionStatus.DISCONNECTED,
                    reason=revocation.kind,
                    now=_now(),
                    required_socket_lease_owner=None,
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


def _approval_url(web_url: str, access_request_id: str) -> str | None:
    normalized = web_url.rstrip("/")
    if not normalized:
        return None
    return f"{normalized}/external-channel/access/{access_request_id}"


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
    """Build one persisted Slack thread target without credentials."""
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
        raise RuntimeError("External Channel Slack resource labels are invalid.")
    return {
        "tenant_id": tenant_id,
        "channel_id": channel_id,
        "thread_ts": thread_ts,
    }


def _render_persisted_activity(
    work: ExternalChannelWork,
) -> ActivityTrackerPresentation:
    """Render the latest desired Tracker state retained by one work cycle."""
    return render_persisted_activity_tracker(work.desired_progress_payload)


def _provider_message_ts(value: object) -> str | None:
    """Extract the provider timestamp from one durable Slack message identity."""
    if not isinstance(value, str) or ":" not in value:
        return None
    message_ts = value.rsplit(":", 1)[-1]
    return message_ts or None


def _resource_correlation_key(resource: ExternalChannelResource) -> str:
    labels = resource.labels or {}
    channel_id = labels.get("channel_id")
    thread_ts = labels.get("thread_ts")
    if not isinstance(channel_id, str) or not isinstance(thread_ts, str):
        raise RuntimeError("External Channel Slack resource labels are invalid.")
    return f"{channel_id}:{thread_ts}"


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
    message: SlackNormalizedMessage,
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
