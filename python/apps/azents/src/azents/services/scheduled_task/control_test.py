"""Scheduled Task External Channel control locator and rendering tests."""

import datetime

import pytest

from azents.core.enums import ExternalChannelResourceType, ScheduledTaskScheduleType
from azents.core.external_channel_projection import is_external_channel_projection
from azents.repos.scheduled_task.data import ScheduledTask
from azents.services.scheduled_task.control import (
    _provider_context_matches_binding,
    build_scheduled_task_control_locator,
    parse_scheduled_task_control_locator,
    render_scheduled_task_discord_registration,
    render_scheduled_task_slack_registration,
)

_NOW = datetime.datetime(2026, 8, 16, tzinfo=datetime.UTC)
_SECRET = "scheduled-task-control-test-secret"
_TASK_ID = "01828d10-b4c3-7a12-94d6-8f43c4e195ce"
_BINDING_ID = "01828d10-b4c3-7a12-94d6-8f43c4e195cf"


def _task() -> ScheduledTask:
    return ScheduledTask(
        id=_TASK_ID,
        workspace_id="workspace-1",
        agent_id="agent-1",
        session_id="session-1",
        binding_id=_BINDING_ID,
        title="Daily report",
        objective="Prepare the daily operating report.",
        schedule_type=ScheduledTaskScheduleType.CRON,
        scheduled_at=None,
        cron_expression="0 9 * * 1-5",
        timezone="America/Los_Angeles",
        next_eligible_at=_NOW,
        active_cycle_id=None,
        active_scheduled_for=None,
        pending_scheduled_for=None,
        lease_owner=None,
        lease_until=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def test_signed_locator_round_trips_exact_action_task_and_binding() -> None:
    """The provider receives only a bounded signed opaque action identity."""
    locator = build_scheduled_task_control_locator(
        secret=_SECRET,
        action="edit",
        task_id=_TASK_ID,
        binding_id=_BINDING_ID,
    )

    assert len(locator) <= 100
    parsed = parse_scheduled_task_control_locator(locator=locator, secret=_SECRET)
    assert (parsed.action, parsed.task_id, parsed.binding_id) == (
        "edit",
        _TASK_ID,
        _BINDING_ID,
    )


@pytest.mark.parametrize("part", [1, 2, 3, 4])
def test_signed_locator_rejects_tampering(part: int) -> None:
    """Changing version, action, Task, Binding, or signature denies mutation."""
    locator = build_scheduled_task_control_locator(
        secret=_SECRET,
        action="delete",
        task_id=_TASK_ID,
        binding_id=_BINDING_ID,
    )
    fields = locator.split(":")
    fields[part] = "x" if fields[part] != "x" else "y"

    with pytest.raises(ValueError, match="control locator is invalid"):
        parse_scheduled_task_control_locator(
            locator=":".join(fields),
            secret=_SECRET,
        )


def test_registration_renderers_include_exact_edit_and_delete_controls() -> None:
    """Slack Block Kit and Discord components retain distinct signed actions."""
    task = _task()
    edit = build_scheduled_task_control_locator(
        secret=_SECRET,
        action="edit",
        task_id=task.id,
        binding_id=_BINDING_ID,
    )
    delete = build_scheduled_task_control_locator(
        secret=_SECRET,
        action="delete",
        task_id=task.id,
        binding_id=_BINDING_ID,
    )

    slack_text, slack_blocks = render_scheduled_task_slack_registration(
        task=task,
        edit_locator=edit,
        delete_locator=delete,
    )
    discord_text, embeds, components = render_scheduled_task_discord_registration(
        task=task,
        edit_locator=edit,
        delete_locator=delete,
    )

    assert slack_text == discord_text == "Scheduled Task registered: Daily report"
    slack_actions = slack_blocks[-1]["elements"]
    assert isinstance(slack_actions, list)
    edit_button, delete_button = slack_actions
    assert is_external_channel_projection(edit_button)
    assert is_external_channel_projection(delete_button)
    assert edit_button["value"] == edit
    assert delete_button["value"] == delete
    assert "Objective" not in str(slack_blocks)
    assert task.objective not in str(slack_blocks)
    assert embeds[0]["title"] == "Scheduled Task registered"
    assert "description" not in embeds[0]
    assert task.objective not in str(embeds)
    discord_actions = components[0]["components"]
    assert isinstance(discord_actions, list)
    discord_action_ids: list[object] = []
    for button in discord_actions:
        assert is_external_channel_projection(button)
        discord_action_ids.append(button["custom_id"])
    assert discord_action_ids == [edit, delete]


def test_provider_context_matches_exact_parent_or_thread_binding_only() -> None:
    """A registration control may target its exact parent or exact thread scope."""
    assert _provider_context_matches_binding(
        resource_type=ExternalChannelResourceType.PARENT_CHANNEL,
        resource_key="channel-1",
        provider_parent_channel_id="channel-1",
        provider_thread_resource_key="slack:tenant-1:channel-1:1.000000",
    )
    assert not _provider_context_matches_binding(
        resource_type=ExternalChannelResourceType.PARENT_CHANNEL,
        resource_key="channel-1",
        provider_parent_channel_id="channel-2",
        provider_thread_resource_key="slack:tenant-1:channel-1:1.000000",
    )
    assert _provider_context_matches_binding(
        resource_type=ExternalChannelResourceType.THREAD,
        resource_key="slack:tenant-1:channel-1:1.000000",
        provider_parent_channel_id="channel-1",
        provider_thread_resource_key="slack:tenant-1:channel-1:1.000000",
    )
    assert not _provider_context_matches_binding(
        resource_type=ExternalChannelResourceType.THREAD,
        resource_key="slack:tenant-1:channel-1:1.000000",
        provider_parent_channel_id="channel-1",
        provider_thread_resource_key="slack:tenant-1:channel-1:2.000000",
    )
