"""Typed access and selector replay for synchronous conversation ingestion."""

import dataclasses
import datetime
from typing import Annotated

from fastapi import Depends

from azents.core.enums import (
    ExternalChannelIngressAuthorityKind,
    ExternalChannelProvider,
)
from azents.core.external_channel_conversation_data import (
    ExternalChannelConversationScope,
    ExternalChannelOperationDeadline,
)
from azents.core.external_channel_ingestion import (
    ExternalChannelIngestionOperation,
    ExternalChannelIngestionOutcome,
    ExternalChannelIngestionOutcomeKind,
    ExternalChannelIngestionReason,
    ExternalChannelIngestionRequest,
    ExternalChannelIngressAuthority,
    ExternalChannelReplayBoundary,
    ExternalChannelTriggerLocator,
)
from azents.core.external_channel_participation_state import (
    build_setup_continuation_request,
    setup_source_from_projection,
)
from azents.core.external_channel_replay import (
    ExternalChannelIngestionReplayUnavailable,
    ExternalChannelReplaySource,
)
from azents.repos.external_channel.data import (
    ExternalChannelAccessRequest,
    ExternalChannelConversationPosition,
)
from azents.repos.external_channel.ingestion_replay_operations import (
    ExternalChannelReplayOperations,
)
from azents.services.external_channel.ingestion import (
    ExternalChannelConversationIngestionService,
)
from azents.services.external_channel.ingestion_deps import (
    get_external_channel_conversation_ingestion_service,
)

_REPLAY_OPERATION_BUDGET = datetime.timedelta(seconds=30)


def external_channel_replay_deadline(
    *,
    now: datetime.datetime,
) -> ExternalChannelOperationDeadline:
    """Build one bounded absolute deadline for an authenticated replay."""
    return ExternalChannelOperationDeadline(now + _REPLAY_OPERATION_BUDGET)


def access_request_uses_typed_replay(
    request: ExternalChannelAccessRequest,
) -> bool:
    """Return whether an access request carries any typed replay identity."""
    return (
        request.conversation_position_id is not None
        or request.trigger_position is not None
    )


@dataclasses.dataclass
class ExternalChannelIngestionReplayService:
    """Reconstruct immutable access, selector, and setup replay."""

    operations: Annotated[
        ExternalChannelReplayOperations, Depends(ExternalChannelReplayOperations)
    ]
    ingestion_service: Annotated[
        ExternalChannelConversationIngestionService,
        Depends(get_external_channel_conversation_ingestion_service),
    ]

    async def replay_access_allow(
        self,
        *,
        access_request_id: str,
        deadline: ExternalChannelOperationDeadline,
        initial_title_eligible: bool,
    ) -> ExternalChannelIngestionOutcome:
        """Replay one committed Allow through its retained original boundary."""
        source = await self.operations.read_access_allow(
            access_request_id=access_request_id
        )
        return await self._ingest_source(
            source,
            operation=ExternalChannelIngestionOperation.ACCESS_ALLOW,
            deadline=deadline,
            provider_user_id=source.principal.provider_user_id,
            initial_title_eligible=initial_title_eligible,
        )

    async def replay_selected_interaction(
        self,
        *,
        selector_interaction_id: str,
        principal_id: str,
        deadline: ExternalChannelOperationDeadline,
    ) -> ExternalChannelIngestionOutcome:
        """Replay one immutable selected route through interaction-owned state."""
        source = await self.operations.read_selected_interaction(
            selector_interaction_id=selector_interaction_id, principal_id=principal_id
        )
        return await self._ingest_source(
            source,
            operation=ExternalChannelIngestionOperation.SELECTOR_CONTINUATION,
            deadline=deadline,
            provider_user_id=None,
            initial_title_eligible=False,
        )

    async def replay_setup_claim(
        self,
        *,
        setup_claim_id: str,
        deadline: ExternalChannelOperationDeadline,
    ) -> ExternalChannelIngestionOutcome:
        """Replay one selected setup claim through its frozen source."""
        source = await self.operations.read_setup_claim(setup_claim_id=setup_claim_id)
        request = build_setup_continuation_request(
            configuration=source.configuration,
            claim=source.claim,
            setting=source.setting,
            source_resource=source.source_resource,
            principal=source.principal,
            source=setup_source_from_projection(source.claim.source_projection),
            deadline=deadline,
        )
        return await self.ingestion_service.ingest(request)

    async def recover_selected_setup_claims(
        self,
        *,
        limit: int,
        now: datetime.datetime,
    ) -> tuple[ExternalChannelIngestionOutcome, ...]:
        """Attempt a bounded oldest-first selected-setup recovery pass."""
        claim_ids = await self.operations.list_selected_setup_claim_ids(limit=limit)
        outcomes: list[ExternalChannelIngestionOutcome] = []
        for claim_id in claim_ids:
            outcomes.append(
                await self.replay_setup_claim(
                    setup_claim_id=claim_id,
                    deadline=external_channel_replay_deadline(now=now),
                )
            )
        return tuple(outcomes)

    async def _ingest_source(
        self,
        source: ExternalChannelReplaySource,
        *,
        operation: ExternalChannelIngestionOperation,
        deadline: ExternalChannelOperationDeadline,
        provider_user_id: str | None,
        initial_title_eligible: bool,
    ) -> ExternalChannelIngestionOutcome:
        delivery_thread_key = await self._resolve_delivery_thread_key(
            source,
            deadline=deadline,
        )
        if (
            source.configuration.provider is ExternalChannelProvider.DISCORD
            and delivery_thread_key is None
        ):
            return _retryable_failure()
        return await self.ingestion_service.ingest(
            _build_request(
                source,
                operation=operation,
                deadline=deadline,
                provider_user_id=provider_user_id,
                delivery_thread_key=delivery_thread_key,
                initial_title_eligible=initial_title_eligible,
            )
        )

    async def _resolve_delivery_thread_key(
        self,
        source: ExternalChannelReplaySource,
        *,
        deadline: ExternalChannelOperationDeadline,
    ) -> str | None:
        configuration = source.configuration
        initial = _delivery_thread_key(
            provider=configuration.provider,
            labels=source.resource.labels or {},
            position=source.position,
        )
        if configuration.provider is not ExternalChannelProvider.DISCORD or initial:
            return initial
        del deadline
        labels = source.resource.labels or {}
        tenant_id = configuration.provider_tenant_id
        if tenant_id is None:
            raise ExternalChannelIngestionReplayUnavailable(
                "External Channel replay tenant is unavailable."
            )
        parent_channel_id = _provider_parent_channel_id(
            provider=configuration.provider,
            labels=labels,
        )
        root_message_id = _provider_message_id(
            provider=configuration.provider,
            tenant_id=tenant_id,
            provider_message_key=source.trigger_provider_message_key,
        )
        if parent_channel_id is None:
            return None
        return root_message_id


def _build_request(
    source: ExternalChannelReplaySource,
    *,
    operation: ExternalChannelIngestionOperation,
    deadline: ExternalChannelOperationDeadline,
    provider_user_id: str | None,
    delivery_thread_key: str | None,
    initial_title_eligible: bool,
) -> ExternalChannelIngestionRequest:
    configuration = source.configuration
    tenant_id = configuration.provider_tenant_id
    if tenant_id is None:
        raise ExternalChannelIngestionReplayUnavailable(
            "External Channel replay tenant is unavailable."
        )
    labels = source.resource.labels or {}
    locator = ExternalChannelTriggerLocator(
        connection_id=configuration.id,
        provider=configuration.provider,
        provider_event_type=_provider_event_type(
            provider=configuration.provider,
            labels=labels,
        ),
        provider_tenant_id=tenant_id,
        provider_channel_id=source.position.provider_channel_id,
        provider_parent_channel_id=_provider_parent_channel_id(
            provider=configuration.provider,
            labels=labels,
        ),
        provider_thread_key=source.position.provider_thread_key,
        delivery_thread_key=delivery_thread_key,
        provider_resource_key=source.resource.provider_resource_key,
        trigger_provider_message_key=source.trigger_provider_message_key,
        trigger_provider_message_id=_provider_message_id(
            provider=configuration.provider,
            tenant_id=tenant_id,
            provider_message_key=source.trigger_provider_message_key,
        ),
        trigger_position=source.trigger_position,
        provider_user_id=provider_user_id,
        invocation=True,
        expected_file_count=None,
    )
    return ExternalChannelIngestionRequest(
        locator=locator,
        scope=ExternalChannelConversationScope(
            connection_id=configuration.id,
            kind=source.position.scope_kind,
            provider_channel_id=source.position.provider_channel_id,
            provider_thread_key=source.position.provider_thread_key,
        ),
        authority=ExternalChannelIngressAuthority(
            kind=ExternalChannelIngressAuthorityKind.DURABLE_REPLAY,
            ingress_profile=configuration.ingress_profile,
            configuration_generation=configuration.configuration_generation,
            lease_owner=None,
            lease_generation=None,
        ),
        deadline=deadline,
        operation=operation,
        selected_route_id=source.route_id,
        replay_boundary=ExternalChannelReplayBoundary(
            connection_id=configuration.id,
            source_resource_id=source.resource.id,
            target_resource_id=source.target_resource_id,
            principal_id=source.principal.id,
            trigger_provider_message_key=source.trigger_provider_message_key,
            conversation_position_id=source.position.id,
            range_start_position=source.range_start_position,
            trigger_position=source.trigger_position,
        ),
        initial_title_eligible=initial_title_eligible,
    )


def _provider_event_type(
    *,
    provider: ExternalChannelProvider,
    labels: dict[str, object],
) -> str:
    value = labels.get("provider_event_type")
    expected = {
        ExternalChannelProvider.SLACK: {"app_mention", "message"},
        ExternalChannelProvider.DISCORD: {"discord_message_create"},
    }
    return (
        value if isinstance(value, str) and value in expected[provider] else "unknown"
    )


def _provider_message_id(
    *,
    provider: ExternalChannelProvider,
    tenant_id: str,
    provider_message_key: str,
) -> str:
    prefix = f"{provider.value}:{tenant_id}:"
    if not provider_message_key.startswith(prefix):
        raise ExternalChannelIngestionReplayUnavailable(
            "External Channel replay message identity is invalid."
        )
    remainder = provider_message_key.removeprefix(prefix)
    if provider is ExternalChannelProvider.SLACK:
        parts = remainder.split(":", 1)
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise ExternalChannelIngestionReplayUnavailable(
                "External Channel Slack replay identity is invalid."
            )
        return parts[1]
    if not remainder or ":" in remainder:
        raise ExternalChannelIngestionReplayUnavailable(
            "External Channel Discord replay identity is invalid."
        )
    return remainder


def _delivery_thread_key(
    *,
    provider: ExternalChannelProvider,
    labels: dict[str, object],
    position: ExternalChannelConversationPosition,
) -> str | None:
    if provider is ExternalChannelProvider.SLACK:
        value = labels.get("thread_ts")
    else:
        value = labels.get("delivery_channel_id") or labels.get("thread_channel_id")
        if value is None:
            thread_id = labels.get("thread_id")
            root_message_id = labels.get("root_message_id")
            if root_message_id is None or root_message_id != thread_id:
                value = thread_id
    if isinstance(value, str) and value:
        return value
    return position.provider_thread_key


def _provider_parent_channel_id(
    *,
    provider: ExternalChannelProvider,
    labels: dict[str, object],
) -> str | None:
    if provider is ExternalChannelProvider.SLACK:
        return None
    value = labels.get("parent_channel_id") or labels.get("channel_id")
    return value if isinstance(value, str) and value else None


def _retryable_failure() -> ExternalChannelIngestionOutcome:
    return ExternalChannelIngestionOutcome(
        kind=ExternalChannelIngestionOutcomeKind.RETRYABLE_FAILURE,
        reason=ExternalChannelIngestionReason.HISTORY_UNAVAILABLE,
        mailbox_item_id=None,
        control_plans=(),
        connection_id=None,
    )
