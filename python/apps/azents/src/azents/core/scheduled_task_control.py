"""Scheduled provider control request data and stable errors."""

from dataclasses import dataclass
from typing import Literal

from azents.core.enums import ExternalChannelResourceType
from azents.repos.scheduled_task.data import ScheduledTask

ScheduledTaskControlAction = Literal["edit", "delete", "confirm_delete"]


class ScheduledTaskProviderControlError(ValueError):
    """A provider callback no longer has current Scheduled Task authority."""


@dataclass(frozen=True)
class ScheduledTaskControlLocator:
    """One bounded signed locator containing no actor or provider credential."""

    action: ScheduledTaskControlAction
    task_id: str
    binding_id: str


@dataclass(frozen=True)
class ScheduledTaskEditInput:
    """One bounded provider-modal replacement request, retained only in memory."""

    title: str
    objective: str
    at: str | None
    cron: str | None
    timezone: str | None


@dataclass(frozen=True)
class ScheduledTaskSlackEditMetadata:
    """Signed modal metadata binding a Task locator to its component claim."""

    locator: str
    origin_interaction_id: str


@dataclass(frozen=True)
class ScheduledTaskProviderControlResult:
    """Canonical mutation outcome rendered by the provider-specific caller."""

    action: ScheduledTaskControlAction
    task: ScheduledTask


@dataclass(frozen=True)
class ScheduledTaskProviderRender:
    """Provider-neutral text and structured payload for one Task message."""

    text: str
    payload: list[dict[str, object]]


def _provider_context_matches_binding(
    *,
    resource_type: ExternalChannelResourceType,
    resource_key: str,
    provider_parent_channel_id: str | None,
    provider_thread_resource_key: str | None,
) -> bool:
    if resource_type is ExternalChannelResourceType.PARENT_CHANNEL:
        return provider_parent_channel_id == resource_key
    if resource_type is ExternalChannelResourceType.THREAD:
        return provider_thread_resource_key == resource_key
    return False
