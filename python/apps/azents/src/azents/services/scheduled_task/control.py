"""Signed External Channel controls for Scheduled Task registrations."""

from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.enums import (
    ExternalChannelConnectionStatus,
    ExternalChannelInteractionStatus,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceType,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import ExternalChannelInteraction
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.scheduled_task.data import ScheduledTask
from azents.repos.scheduled_task.repository import ScheduledTaskRepository
from azents.repos.scheduled_task_cycle import ScheduledTaskCycleRepository
from azents.services.scheduled_task.rendering import (
    ScheduledTaskSchedulePresentation,
    render_scheduled_task_schedule,
)
from azents.services.scheduled_task.service import (
    RDBScheduledTaskAuthorityValidator,
    ScheduledTaskService,
)

_CONTROL_PREFIX = "st1"
_CONTROL_SIGNATURE_BYTES = 12
_MAX_IDENTIFIER_LENGTH = 64
_MAX_DISCORD_CUSTOM_ID_LENGTH = 100
ScheduledTaskControlAction = Literal["edit", "delete"]


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
    task: ScheduledTask | None


def build_scheduled_task_control_locator(
    *,
    secret: str,
    action: ScheduledTaskControlAction,
    task_id: str,
    binding_id: str,
) -> str:
    """Build a compact signed action identity for one exact Task Binding."""
    _require_identifier(task_id)
    _require_identifier(binding_id)
    action_code = _action_code(action)
    unsigned = (_CONTROL_PREFIX, action_code, task_id, binding_id)
    signature = _signature(secret=secret, fields=unsigned)
    locator = ":".join((*unsigned, signature))
    if len(locator) > _MAX_DISCORD_CUSTOM_ID_LENGTH:
        raise ValueError("Scheduled Task control locator exceeds provider limits.")
    return locator


def parse_scheduled_task_control_locator(
    *,
    locator: str,
    secret: str,
) -> ScheduledTaskControlLocator:
    """Verify one bounded opaque Scheduled Task control locator."""
    try:
        prefix, action_code, task_id, binding_id, signature = locator.split(":", 4)
    except ValueError as error:
        raise ValueError("Scheduled Task control locator is invalid.") from error
    if prefix != _CONTROL_PREFIX:
        raise ValueError("Scheduled Task control locator is invalid.")
    action = _action_from_code(action_code)
    _require_identifier(task_id)
    _require_identifier(binding_id)
    expected = _signature(
        secret=secret,
        fields=(prefix, action_code, task_id, binding_id),
    )
    if not hmac.compare_digest(signature, expected):
        raise ValueError("Scheduled Task control locator is invalid.")
    return ScheduledTaskControlLocator(
        action=action,
        task_id=task_id,
        binding_id=binding_id,
    )


def build_scheduled_task_slack_edit_metadata(
    *,
    secret: str,
    locator: str,
    origin_interaction_id: str,
) -> str:
    """Bind a signed Task locator to its durable Slack component interaction."""
    _require_identifier(origin_interaction_id)
    encoded = json.dumps(
        {"v": 1, "l": locator, "i": origin_interaction_id},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    signature = hmac.new(secret.encode(), encoded, hashlib.sha256).digest()
    return (
        base64.urlsafe_b64encode(encoded).decode().rstrip("=")
        + "."
        + base64.urlsafe_b64encode(signature).decode().rstrip("=")
    )


def parse_scheduled_task_slack_edit_metadata(
    *,
    metadata: str,
    secret: str,
) -> ScheduledTaskSlackEditMetadata:
    """Verify a bounded modal origin before reading a replacement request."""
    encoded_part, separator, signature_part = metadata.partition(".")
    if not separator or not encoded_part or not signature_part:
        raise ValueError("Scheduled Task edit metadata is invalid.")
    try:
        encoded = _base64url_decode(encoded_part)
        signature = _base64url_decode(signature_part)
        payload = json.loads(encoded)
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("Scheduled Task edit metadata is invalid.") from error
    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise ValueError("Scheduled Task edit metadata is invalid.")
    expected = hmac.new(secret.encode(), encoded, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        raise ValueError("Scheduled Task edit metadata is invalid.")
    locator = payload.get("l")
    origin_interaction_id = payload.get("i")
    if not isinstance(locator, str) or len(locator) > 100:
        raise ValueError("Scheduled Task edit metadata is invalid.")
    if not isinstance(origin_interaction_id, str):
        raise ValueError("Scheduled Task edit metadata is invalid.")
    _require_identifier(origin_interaction_id)
    return ScheduledTaskSlackEditMetadata(
        locator=locator,
        origin_interaction_id=origin_interaction_id,
    )


def render_scheduled_task_slack_registration(
    *,
    task: ScheduledTask,
    edit_locator: str,
    delete_locator: str,
) -> tuple[str, list[dict[str, object]]]:
    """Render one bounded Slack Block Kit Task registration with controls."""
    _validate_render_locators(task, edit_locator, delete_locator)
    text = f"Scheduled Task registered: {task.title}"
    schedule = _schedule_presentation(task)
    return (
        text,
        [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "Scheduled Task registered",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{_slack(task.title)}*",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Schedule:* {_slack(schedule.summary)}\n"
                        f"*Next run:* {_slack(schedule.occurrence)}"
                    ),
                },
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"Schedule details: `{_slack(schedule.canonical)}`",
                    }
                ],
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "action_id": "azents_scheduled_task_edit",
                        "text": {"type": "plain_text", "text": "Edit"},
                        "value": edit_locator,
                    },
                    {
                        "type": "button",
                        "action_id": "azents_scheduled_task_delete",
                        "style": "danger",
                        "text": {"type": "plain_text", "text": "Delete"},
                        "value": delete_locator,
                        "confirm": {
                            "title": {
                                "type": "plain_text",
                                "text": "Delete Scheduled Task?",
                            },
                            "text": {
                                "type": "mrkdwn",
                                "text": "This removes the Scheduled Task.",
                            },
                            "confirm": {"type": "plain_text", "text": "Delete"},
                            "deny": {"type": "plain_text", "text": "Cancel"},
                        },
                    },
                ],
            },
        ],
    )


def render_scheduled_task_discord_registration(
    *,
    task: ScheduledTask,
    edit_locator: str,
    delete_locator: str,
) -> tuple[str, list[dict[str, object]], list[dict[str, object]]]:
    """Render one Discord registration message with native Edit/Delete controls."""
    _validate_render_locators(task, edit_locator, delete_locator)
    text = f"Scheduled Task registered: {task.title}"
    schedule = _schedule_presentation(task)
    return (
        text,
        [
            {
                "title": task.title[:256],
                "description": "Scheduled Task registered",
                "color": 0x5865F2,
                "fields": [
                    {"name": "Schedule", "value": schedule.summary[:1_024]},
                    {"name": "Next run", "value": schedule.occurrence[:1_024]},
                    {
                        "name": "Schedule details",
                        "value": schedule.canonical[:1_024],
                    },
                ],
            }
        ],
        [
            {
                "type": 1,
                "components": [
                    {"type": 2, "style": 2, "label": "Edit", "custom_id": edit_locator},
                    {
                        "type": 2,
                        "style": 4,
                        "label": "Delete",
                        "custom_id": delete_locator,
                    },
                ],
            }
        ],
    )


@dataclass
class ScheduledTaskProviderControlService:
    """Reload and reauthorize registered Scheduled Task provider controls."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    external_repository: Annotated[
        ExternalChannelRepository, Depends(ExternalChannelRepository.create)
    ]
    task_repository: Annotated[
        ScheduledTaskRepository, Depends(ScheduledTaskRepository)
    ]
    cycle_repository: Annotated[
        ScheduledTaskCycleRepository, Depends(ScheduledTaskCycleRepository)
    ]
    mailbox_repository: Annotated[MailboxRepository, Depends(MailboxRepository)]
    config: Annotated[Config, Depends(get_config)]

    def _task_service(self) -> ScheduledTaskService:
        return ScheduledTaskService(
            repository=self.task_repository,
            cycle_repository=self.cycle_repository,
            mailbox_repository=self.mailbox_repository,
            authority_validator=RDBScheduledTaskAuthorityValidator(),
        )

    async def mutate(
        self,
        *,
        interaction_id: str,
        locator: ScheduledTaskControlLocator,
        provider_parent_channel_id: str | None,
        provider_thread_resource_key: str | None,
        origin_interaction_id: str | None,
        edit: ScheduledTaskEditInput | None,
        now: datetime.datetime,
    ) -> ScheduledTaskProviderControlResult:
        """Revalidate one claimed actor and apply exactly one current mutation."""
        if locator.action == "edit" and edit is None:
            raise ScheduledTaskProviderControlError(
                "Scheduled Task edit is incomplete."
            )
        if locator.action == "delete" and edit is not None:
            raise ScheduledTaskProviderControlError("Scheduled Task delete is invalid.")
        async with self.session_manager() as session:
            service = self._task_service()
            candidate = await self.task_repository.get_by_id(session, locator.task_id)
            if candidate is None or candidate.binding_id != locator.binding_id:
                raise ScheduledTaskProviderControlError(
                    "Scheduled Task control is unavailable."
                )
            interaction = await self._authorize(
                session,
                interaction_id=interaction_id,
                locator=locator,
                task=candidate,
                provider_parent_channel_id=provider_parent_channel_id,
                provider_thread_resource_key=provider_thread_resource_key,
                origin_interaction_id=origin_interaction_id,
            )
            del interaction
            target = await service.lock_provider_mutation_target(
                session,
                task_id=locator.task_id,
                expected_binding_id=locator.binding_id,
            )
            if target is None or target.task != candidate:
                raise ScheduledTaskProviderControlError(
                    "Scheduled Task control is unavailable."
                )
            if locator.action == "delete":
                deleted = await service.delete_locked_provider_target(
                    session,
                    target=target,
                    expected_binding_id=locator.binding_id,
                )
                if not deleted:
                    raise ScheduledTaskProviderControlError(
                        "Scheduled Task is no longer available."
                    )
                await session.commit()
                return ScheduledTaskProviderControlResult(action="delete", task=None)
            assert edit is not None
            replacement = await service.replace_locked_provider_target(
                session,
                target=target,
                expected_binding_id=locator.binding_id,
                title=edit.title,
                objective=edit.objective,
                at=edit.at,
                cron=edit.cron,
                timezone=edit.timezone,
                binding_id=locator.binding_id,
                now=now,
            )
            if replacement is None:
                raise ScheduledTaskProviderControlError(
                    "Scheduled Task is no longer available."
                )
            await session.commit()
            return ScheduledTaskProviderControlResult(action="edit", task=replacement)

    async def load_for_edit(
        self,
        *,
        interaction_id: str,
        locator: ScheduledTaskControlLocator,
        provider_parent_channel_id: str | None,
        provider_thread_resource_key: str | None,
    ) -> ScheduledTask:
        """Revalidate a claimed edit-open component before rendering its modal."""
        async with self.session_manager() as session:
            task = await self.task_repository.get_by_id(session, locator.task_id)
            if task is None or task.binding_id != locator.binding_id:
                raise ScheduledTaskProviderControlError(
                    "Scheduled Task control is unavailable."
                )
            await self._authorize(
                session,
                interaction_id=interaction_id,
                locator=locator,
                task=task,
                provider_parent_channel_id=provider_parent_channel_id,
                provider_thread_resource_key=provider_thread_resource_key,
                origin_interaction_id=None,
            )
            return task

    async def _authorize(
        self,
        session: AsyncSession,
        *,
        interaction_id: str,
        locator: ScheduledTaskControlLocator,
        task: ScheduledTask,
        provider_parent_channel_id: str | None,
        provider_thread_resource_key: str | None,
        origin_interaction_id: str | None,
    ) -> ExternalChannelInteraction:
        interaction = await self.external_repository.lock_interaction(
            session, interaction_id=interaction_id
        )
        if (
            interaction is None
            or interaction.status is not ExternalChannelInteractionStatus.PROCESSING
            or interaction.principal_id is None
        ):
            raise ScheduledTaskProviderControlError(
                "Scheduled Task control is unavailable."
            )
        connection = await self.external_repository.get_connection_configuration(
            session, connection_id=interaction.connection_id
        )
        principal = await self.external_repository.get_principal(
            session, principal_id=interaction.principal_id
        )
        binding = await self.external_repository.lock_binding(
            session, binding_id=locator.binding_id
        )
        if (
            connection is None
            or connection.status
            not in {
                ExternalChannelConnectionStatus.ACTIVE,
                ExternalChannelConnectionStatus.DEGRADED,
            }
            or principal is None
            or principal.provider is not connection.provider
            or principal.provider_tenant_id != connection.provider_tenant_id
            or principal.author_type is not ExternalChannelPrincipalAuthorType.HUMAN
            or task is None
            or task.binding_id != locator.binding_id
            or binding is None
            or binding.disconnected_at is not None
            or binding.agent_session_id != task.session_id
        ):
            raise ScheduledTaskProviderControlError(
                "Scheduled Task control is unavailable."
            )
        resource = await self.external_repository.get_resource(
            session, resource_id=binding.resource_id
        )
        route = await self.external_repository.get_routable_route_by_binding_id(
            session, binding_id=binding.id
        )
        context_matches = resource is not None and _provider_context_matches_binding(
            resource_type=resource.resource_type,
            resource_key=resource.provider_resource_key,
            provider_parent_channel_id=provider_parent_channel_id,
            provider_thread_resource_key=provider_thread_resource_key,
        )
        if not context_matches and resource is not None:
            context_matches = await self._slack_modal_origin_matches_binding(
                session,
                origin_interaction_id=origin_interaction_id,
                interaction=interaction,
                provider=connection.provider,
                provider_tenant_id=connection.provider_tenant_id,
                resource_key=resource.provider_resource_key,
            )
        if (
            resource is None
            or resource.connection_id != connection.id
            or route is None
            or route.id != binding.route_id
            or route.agent_id != task.agent_id
            or not context_matches
        ):
            raise ScheduledTaskProviderControlError(
                "Scheduled Task control is unavailable."
            )
        if (
            await self.external_repository.get_active_block(
                session, agent_id=task.agent_id, principal_id=principal.id
            )
            is not None
        ):
            raise ScheduledTaskProviderControlError(
                "Scheduled Task control is unavailable."
            )
        grant = await self.external_repository.get_active_access_grant(
            session,
            agent_id=task.agent_id,
            principal_id=principal.id,
            agent_session_id=task.session_id,
        )
        if grant is None and not route.open_access_enabled:
            raise ScheduledTaskProviderControlError(
                "Scheduled Task control is unavailable."
            )
        return interaction

    async def _slack_modal_origin_matches_binding(
        self,
        session: AsyncSession,
        *,
        origin_interaction_id: str | None,
        interaction: ExternalChannelInteraction,
        provider: ExternalChannelProvider,
        provider_tenant_id: str | None,
        resource_key: str,
    ) -> bool:
        """Require a signed Slack modal to originate from the exact prior thread."""
        if origin_interaction_id is None:
            return False
        origin = await self.external_repository.lock_interaction(
            session,
            interaction_id=origin_interaction_id,
        )
        if (
            origin is None
            or origin.id == interaction.id
            or origin.connection_id != interaction.connection_id
            or origin.principal_id != interaction.principal_id
            or origin.status
            not in {
                ExternalChannelInteractionStatus.PROCESSING,
                ExternalChannelInteractionStatus.COMPLETED,
            }
            or provider is not ExternalChannelProvider.SLACK
            or provider_tenant_id is None
            or origin.resource_correlation_key is None
        ):
            return False
        return resource_key == (
            f"slack:{provider_tenant_id}:{origin.resource_correlation_key}"
        )


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


def _validate_render_locators(
    task: ScheduledTask,
    edit_locator: str,
    delete_locator: str,
) -> None:
    if not task.binding_id or not edit_locator or not delete_locator:
        raise ValueError("Scheduled Task registration controls are incomplete.")
    if (
        len(edit_locator) > _MAX_DISCORD_CUSTOM_ID_LENGTH
        or len(delete_locator) > _MAX_DISCORD_CUSTOM_ID_LENGTH
    ):
        raise ValueError("Scheduled Task registration controls exceed provider limits.")


def _action_code(action: ScheduledTaskControlAction) -> str:
    return {"edit": "e", "delete": "d"}[action]


def _action_from_code(value: str) -> ScheduledTaskControlAction:
    if value == "e":
        return "edit"
    if value == "d":
        return "delete"
    raise ValueError("Scheduled Task control locator is invalid.")


def _signature(*, secret: str, fields: tuple[str, ...]) -> str:
    payload = ":".join(fields).encode()
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).digest()
    return (
        base64.urlsafe_b64encode(digest[:_CONTROL_SIGNATURE_BYTES]).decode().rstrip("=")
    )


def _base64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _require_identifier(value: str) -> None:
    if not value or len(value) > _MAX_IDENTIFIER_LENGTH or ":" in value:
        raise ValueError("Scheduled Task control locator is invalid.")


def _schedule_presentation(
    task: ScheduledTask,
) -> ScheduledTaskSchedulePresentation:
    return render_scheduled_task_schedule(
        schedule_type=task.schedule_type,
        scheduled_at=task.scheduled_at,
        cron_expression=task.cron_expression,
        timezone=task.timezone,
        scheduled_for=task.next_eligible_at,
    )


def _slack(value: str, limit: int = 500) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")[:limit]
