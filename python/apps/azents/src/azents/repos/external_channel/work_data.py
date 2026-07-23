"""Channel Work, Channel Action, and delivery repository records."""

import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from azents.core.enums import (
    ExternalChannelActionMode,
    ExternalChannelDeliveryOperation,
    ExternalChannelDeliveryStatus,
    ExternalChannelProvider,
    ExternalChannelWorkStatus,
    ExternalChannelWorkTaskStatus,
)


class _Record(BaseModel):
    """Immutable repository data base."""

    model_config = ConfigDict(frozen=True)


class ChannelWorkTask(_Record):
    """One ordered task within binding-scoped Channel Work."""

    id: str
    title: str
    status: ExternalChannelWorkTaskStatus


class ChannelWorkDelivery(_Record):
    """Safe delivery outcome exposed to model and management projections."""

    id: str
    operation: ExternalChannelDeliveryOperation
    status: ExternalChannelDeliveryStatus
    provider_message_key: str | None
    error_kind: str | None
    error_summary: str | None
    created_at: datetime.datetime
    completed_at: datetime.datetime | None


class ChannelWorkSnapshot(_Record):
    """Bounded model-visible state for one active External Channel binding."""

    binding_id: str
    provider: ExternalChannelProvider
    resource_label: str
    tasks: list[ChannelWorkTask]
    state_revision: int
    desired_progress_revision: int
    progress_provider_message_key: str | None
    projection_drift: str
    latest_action_mode: ExternalChannelActionMode | None
    latest_deliveries: list[ChannelWorkDelivery]


class ChannelActionCommit(_Record):
    """Committed canonical Channel Action and its provider intents."""

    action_id: str
    binding_id: str
    work_id: str
    work_status: ExternalChannelWorkStatus
    state_revision: int
    deliveries: list[ChannelWorkDelivery]


class ChannelDeliveryTarget(_Record):
    """Internal provider target reconstructed for one delivery attempt."""

    delivery_attempt_id: str
    operation: ExternalChannelDeliveryOperation
    status: ExternalChannelDeliveryStatus
    binding_id: str | None
    connection_id: str
    provider: ExternalChannelProvider
    encrypted_credentials: str | None
    provider_tenant_id: str | None
    request_payload: dict[str, Any]
