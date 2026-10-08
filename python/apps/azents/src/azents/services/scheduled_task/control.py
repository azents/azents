"""Signed External Channel controls for Scheduled Task registrations."""

from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.scheduled_task_control import (
    ScheduledTaskControlAction,
    ScheduledTaskControlLocator,
    ScheduledTaskEditInput,
    ScheduledTaskProviderControlResult,
    ScheduledTaskProviderRender,
    ScheduledTaskSlackEditMetadata,
)
from azents.repos.scheduled_task.control_operations import (
    ScheduledTaskProviderControlRepository,
)
from azents.repos.scheduled_task.data import ScheduledTask
from azents.repos.scheduled_task.presentation import (
    ScheduledTaskSchedulePresentation,
    render_scheduled_task_schedule,
)

_CONTROL_PREFIX = "st1"
_CONTROL_SIGNATURE_BYTES = 12
_MAX_IDENTIFIER_LENGTH = 64
_MAX_DISCORD_CUSTOM_ID_LENGTH = 100


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
) -> ScheduledTaskProviderRender:
    """Render one bounded Slack Block Kit Task registration with controls."""
    _validate_slack_render_locators(task, edit_locator, delete_locator)
    text = f"Scheduled Task registered: {task.title}"
    schedule = _schedule_presentation(task)
    return ScheduledTaskProviderRender(
        text=text,
        payload=[
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
                        "text": {"type": "plain_text", "text": "Cancel"},
                        "value": delete_locator,
                        "confirm": {
                            "title": {
                                "type": "plain_text",
                                "text": "Cancel Scheduled Task?",
                            },
                            "text": {
                                "type": "mrkdwn",
                                "text": (
                                    "Future runs will stop. Work that has already "
                                    "started continues."
                                ),
                            },
                            "confirm": {"type": "plain_text", "text": "Cancel task"},
                            "deny": {"type": "plain_text", "text": "Keep task"},
                        },
                    },
                ],
            },
        ],
    )


def render_scheduled_task_discord_registration(
    *,
    task: ScheduledTask,
) -> ScheduledTaskProviderRender:
    """Render one Discord registration message before current Web URL resolution."""
    schedule = _schedule_presentation(task)
    return ScheduledTaskProviderRender(
        text="",
        payload=[
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
    )


def render_scheduled_task_slack_deletion(
    *,
    task: ScheduledTask,
) -> ScheduledTaskProviderRender:
    """Render one bounded Slack Block Kit Task deletion notice."""
    text = f"Scheduled Task deleted: {task.title}"
    return ScheduledTaskProviderRender(
        text=text,
        payload=[
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "Scheduled Task deleted",
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
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            "Future runs are cancelled. Work that has already "
                            "started continues."
                        ),
                    }
                ],
            },
        ],
    )


def render_scheduled_task_discord_deletion(
    *,
    task: ScheduledTask,
) -> ScheduledTaskProviderRender:
    """Render one bounded Discord Task deletion notice."""
    return ScheduledTaskProviderRender(
        text="",
        payload=[
            {
                "title": task.title[:256],
                "description": "Scheduled Task deleted",
                "color": 0xED4245,
                "fields": [
                    {
                        "name": "Status",
                        "value": (
                            "Future runs are cancelled. Work that has already "
                            "started continues."
                        ),
                    }
                ],
            }
        ],
    )


def render_scheduled_task_discord_controls(
    *,
    edit_url: str,
    delete_locator: str,
) -> list[dict[str, object]]:
    """Render a Web Edit link and one provider-authorized Cancel request."""
    _validate_delete_locator(delete_locator)
    return [
        {
            "type": 1,
            "components": [
                {
                    "type": 2,
                    "style": 5,
                    "label": "Edit",
                    "url": edit_url,
                },
                {
                    "type": 2,
                    "style": 4,
                    "label": "Cancel",
                    "custom_id": delete_locator,
                },
            ],
        }
    ]


@dataclass
class ScheduledTaskProviderControlService:
    """Sequence completed provider-control authorization and atomic mutations."""

    config: Annotated[Config, Depends(get_config)]

    operations: Annotated[
        ScheduledTaskProviderControlRepository,
        Depends(ScheduledTaskProviderControlRepository),
    ]

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
        """Return the completed mutate operation."""
        return await self.operations.mutate(
            interaction_id=interaction_id,
            locator=locator,
            provider_parent_channel_id=provider_parent_channel_id,
            provider_thread_resource_key=provider_thread_resource_key,
            origin_interaction_id=origin_interaction_id,
            edit=edit,
            now=now,
        )

    async def load_for_control(
        self,
        *,
        interaction_id: str,
        locator: ScheduledTaskControlLocator,
        provider_parent_channel_id: str | None,
        provider_thread_resource_key: str | None,
    ) -> ScheduledTask:
        """Return the completed load_for_control operation."""
        return await self.operations.load_for_control(
            interaction_id=interaction_id,
            locator=locator,
            provider_parent_channel_id=provider_parent_channel_id,
            provider_thread_resource_key=provider_thread_resource_key,
        )


def _validate_slack_render_locators(
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


def _validate_delete_locator(delete_locator: str) -> None:
    if not delete_locator:
        raise ValueError("Scheduled Task registration controls are incomplete.")
    if len(delete_locator) > _MAX_DISCORD_CUSTOM_ID_LENGTH:
        raise ValueError("Scheduled Task registration controls exceed provider limits.")


def _action_code(action: ScheduledTaskControlAction) -> str:
    return {"edit": "e", "delete": "d", "confirm_delete": "c"}[action]


def _action_from_code(value: str) -> ScheduledTaskControlAction:
    if value == "e":
        return "edit"
    if value == "d":
        return "delete"
    if value == "c":
        return "confirm_delete"
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
