"""Typed content-free setup source retained for participation replay."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from azents.core.enums import (
    ExternalChannelConversationScopeKind,
    ExternalChannelProvider,
)
from azents.repos.external_channel.data import (
    ExternalChannelConnectionConfiguration,
    ExternalChannelParticipationSetting,
    ExternalChannelPrincipal,
    ExternalChannelResource,
    ExternalChannelSetupClaim,
)
from azents.services.external_channel.conversation import (
    ExternalChannelConversationScope,
    ExternalChannelOperationDeadline,
)
from azents.services.external_channel.ingestion import (
    ExternalChannelIngestionOperation,
    ExternalChannelIngestionRequest,
    ExternalChannelIngressAuthority,
    ExternalChannelIngressAuthorityKind,
    ExternalChannelSetupReplayBoundary,
    ExternalChannelTriggerLocator,
)


class ExternalChannelSetupSourceProjection(BaseModel):
    """Durable provider coordinates for one latest eligible setup mention."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1]
    provider: ExternalChannelProvider
    provider_event_type: str = Field(min_length=1)
    provider_tenant_id: str = Field(min_length=1)
    provider_channel_id: str = Field(min_length=1)
    provider_parent_channel_id: str = Field(min_length=1)
    scope_kind: ExternalChannelConversationScopeKind
    provider_thread_key: str | None
    delivery_thread_key: str | None
    provider_resource_key: str = Field(min_length=1)
    trigger_provider_message_key: str = Field(min_length=1)
    trigger_provider_message_id: str = Field(min_length=1)
    trigger_position: str = Field(min_length=1)
    range_start_position: str | None

    def __repr__(self) -> str:
        """Exclude provider coordinates from diagnostic representations."""
        return (
            "ExternalChannelSetupSourceProjection("
            f"provider={self.provider.value!r}, "
            f"scope_kind={self.scope_kind.value!r}, "
            f"schema_version={self.schema_version!r})"
        )


def setup_source_from_projection(
    projection: dict[str, object],
) -> ExternalChannelSetupSourceProjection:
    """Validate one persisted setup source projection."""
    value = projection.get("setup_source")
    if not isinstance(value, dict):
        raise ValueError("External Channel setup source is unavailable.")
    return ExternalChannelSetupSourceProjection.model_validate(value)


def projection_with_setup_source(
    source: ExternalChannelSetupSourceProjection,
) -> dict[str, object]:
    """Serialize one bounded setup source under its typed projection key."""
    return {"setup_source": source.model_dump(mode="json")}


def build_setup_continuation_request(
    *,
    configuration: ExternalChannelConnectionConfiguration,
    claim: ExternalChannelSetupClaim,
    setting: ExternalChannelParticipationSetting,
    source_resource: ExternalChannelResource,
    principal: ExternalChannelPrincipal,
    source: ExternalChannelSetupSourceProjection,
    deadline: ExternalChannelOperationDeadline,
) -> ExternalChannelIngestionRequest:
    """Build one immutable request from a selected setup claim."""
    if (
        configuration.provider_tenant_id is None
        or claim.route_id is None
        or claim.selected_resource_id is None
        or claim.selected_source_revision is None
        or claim.selected_setting_id != setting.id
        or claim.source_resource_id != source_resource.id
        or source.provider is not configuration.provider
        or source.provider_tenant_id != configuration.provider_tenant_id
        or source.provider_parent_channel_id != claim.provider_parent_channel_id
    ):
        raise ValueError("External Channel setup replay identity is invalid.")
    return ExternalChannelIngestionRequest(
        locator=ExternalChannelTriggerLocator(
            connection_id=configuration.id,
            provider=source.provider,
            provider_event_type=source.provider_event_type,
            provider_tenant_id=source.provider_tenant_id,
            provider_channel_id=source.provider_channel_id,
            provider_parent_channel_id=source.provider_parent_channel_id,
            provider_thread_key=source.provider_thread_key,
            delivery_thread_key=source.delivery_thread_key,
            provider_resource_key=source.provider_resource_key,
            trigger_provider_message_key=source.trigger_provider_message_key,
            trigger_provider_message_id=source.trigger_provider_message_id,
            trigger_position=source.trigger_position,
            provider_user_id=principal.provider_user_id,
            invocation=True,
            expected_file_count=None,
        ),
        scope=ExternalChannelConversationScope(
            connection_id=configuration.id,
            kind=source.scope_kind,
            provider_channel_id=source.provider_channel_id,
            provider_thread_key=source.provider_thread_key,
        ),
        authority=ExternalChannelIngressAuthority(
            kind=ExternalChannelIngressAuthorityKind.DURABLE_REPLAY,
            ingress_profile=configuration.ingress_profile,
            configuration_generation=configuration.configuration_generation,
            lease_owner=None,
            lease_generation=None,
        ),
        deadline=deadline,
        operation=ExternalChannelIngestionOperation.SETUP_CONTINUATION,
        selected_route_id=claim.route_id,
        replay_boundary=ExternalChannelSetupReplayBoundary(
            connection_id=configuration.id,
            claim_id=claim.id,
            expected_claim_generation=claim.claim_generation,
            selected_source_revision=claim.selected_source_revision,
            setting_id=setting.id,
            settings_generation=setting.settings_generation,
            location=setting.location,
            source_resource_id=source_resource.id,
            target_resource_id=claim.selected_resource_id,
            principal_id=principal.id,
            trigger_provider_message_key=source.trigger_provider_message_key,
            conversation_position_id=claim.conversation_position_id,
            range_start_position=source.range_start_position,
            trigger_position=source.trigger_position,
        ),
        initial_title_eligible=False,
    )
