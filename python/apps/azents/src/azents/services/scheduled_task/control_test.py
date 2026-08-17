"""Scheduled Task External Channel control locator and rendering tests."""

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.enums import ExternalChannelResourceType, ScheduledTaskScheduleType
from azents.core.external_channel_projection import is_external_channel_projection
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import ExternalChannelInteraction
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.scheduled_task.data import ScheduledTask
from azents.repos.scheduled_task.repository import ScheduledTaskRepository
from azents.repos.scheduled_task_cycle import ScheduledTaskCycleRepository
from azents.services.scheduled_task.control import (
    ScheduledTaskControlLocator,
    ScheduledTaskProviderControlService,
    _provider_context_matches_binding,
    build_scheduled_task_control_locator,
    parse_scheduled_task_control_locator,
    render_scheduled_task_discord_controls,
    render_scheduled_task_discord_registration,
    render_scheduled_task_slack_registration,
)
from azents.services.scheduled_task.service import (
    ScheduledTaskMutationTarget,
    ScheduledTaskService,
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


class _ControlSession:
    """Record the provider control transaction commit."""

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    async def commit(self) -> None:
        """Record a committed provider mutation."""
        self.calls.append("commit")


class _ControlSessionManager:
    """Yield one deterministic provider control transaction."""

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, _ControlSession(self.calls))


class _ControlTaskRepository:
    """Return the pre-lock candidate without acquiring Task locks."""

    def __init__(self, task: ScheduledTask, calls: list[str]) -> None:
        self.task = task
        self.calls = calls

    async def get_by_id(
        self,
        session: AsyncSession,
        task_id: str,
    ) -> ScheduledTask | None:
        del session
        self.calls.append("candidate")
        return self.task if task_id == self.task.id else None


class _ControlTaskService:
    """Record the Scheduled mutation lock after Binding authorization."""

    def __init__(self, task: ScheduledTask, calls: list[str]) -> None:
        self.task = task
        self.calls = calls

    async def lock_provider_mutation_target(
        self,
        session: AsyncSession,
        *,
        task_id: str,
        expected_binding_id: str,
    ) -> ScheduledTaskMutationTarget | None:
        del session
        assert task_id == self.task.id
        assert expected_binding_id == self.task.binding_id
        self.calls.append("scheduled-lock")
        return ScheduledTaskMutationTarget(
            task=self.task,
            cycle=None,
            trigger_id=None,
        )

    async def delete_locked_provider_target(
        self,
        session: AsyncSession,
        *,
        target: ScheduledTaskMutationTarget,
        expected_binding_id: str,
    ) -> bool:
        del session
        assert target.task == self.task
        assert expected_binding_id == self.task.binding_id
        self.calls.append("delete")
        return True


@pytest.mark.asyncio
async def test_provider_mutation_authorizes_binding_before_scheduled_locks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider mutation follows Binding then Mailbox/cycle/Task lock order."""
    calls: list[str] = []
    task = _task()
    task_repository = _ControlTaskRepository(task, calls)
    task_service = _ControlTaskService(task, calls)
    service = ScheduledTaskProviderControlService(
        session_manager=cast(
            SessionManager[AsyncSession],
            _ControlSessionManager(calls),
        ),
        external_repository=cast(ExternalChannelRepository, object()),
        task_repository=cast(ScheduledTaskRepository, task_repository),
        cycle_repository=cast(ScheduledTaskCycleRepository, object()),
        mailbox_repository=cast(MailboxRepository, object()),
        config=cast(Config, object()),
    )

    async def authorize(
        control_service: ScheduledTaskProviderControlService,
        session: AsyncSession,
        **kwargs: object,
    ) -> ExternalChannelInteraction:
        del control_service, session, kwargs
        calls.append("binding-authorization")
        return cast(ExternalChannelInteraction, object())

    monkeypatch.setattr(
        ScheduledTaskProviderControlService,
        "_task_service",
        lambda control_service: cast(ScheduledTaskService, task_service),
    )
    monkeypatch.setattr(
        ScheduledTaskProviderControlService,
        "_authorize",
        authorize,
    )

    result = await service.mutate(
        interaction_id="interaction-1",
        locator=ScheduledTaskControlLocator(
            action="delete",
            task_id=task.id,
            binding_id=_BINDING_ID,
        ),
        provider_parent_channel_id="channel-1",
        provider_thread_resource_key=None,
        origin_interaction_id=None,
        edit=None,
        now=_NOW,
    )

    assert result.action == "delete"
    assert calls == [
        "candidate",
        "binding-authorization",
        "scheduled-lock",
        "delete",
        "commit",
    ]


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


def test_signed_locator_round_trips_discord_cancel_confirmation() -> None:
    """The second Discord cancellation step remains signed and task-scoped."""
    locator = build_scheduled_task_control_locator(
        secret=_SECRET,
        action="confirm_delete",
        task_id=_TASK_ID,
        binding_id=_BINDING_ID,
    )

    parsed = parse_scheduled_task_control_locator(locator=locator, secret=_SECRET)
    assert (parsed.action, parsed.task_id, parsed.binding_id) == (
        "confirm_delete",
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


def test_registration_renderers_use_web_edit_and_cancel_controls() -> None:
    """Registration controls use Web edit and provider-authorized cancellation."""
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
    discord_text, embeds = render_scheduled_task_discord_registration(task=task)
    components = render_scheduled_task_discord_controls(
        edit_url="https://azents.example/task",
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
    assert delete_button["text"] == {"type": "plain_text", "text": "Cancel"}
    assert "Objective" not in str(slack_blocks)
    assert task.objective not in str(slack_blocks)
    assert slack_blocks[0] == {
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": "Scheduled Task registered",
        },
    }
    assert "Daily report" in str(slack_blocks)
    assert "Every weekday at 9:00 AM PDT" in str(slack_blocks)
    assert "0 9 * * 1-5 (America/Los_Angeles)" in str(slack_blocks)
    assert embeds[0]["title"] == task.title
    assert embeds[0]["description"] == "Scheduled Task registered"
    assert "Every weekday at 9:00 AM PDT" in str(embeds)
    assert "0 9 * * 1-5 (America/Los_Angeles)" in str(embeds)
    assert task.objective not in str(embeds)
    discord_actions = components[0]["components"]
    assert isinstance(discord_actions, list)
    edit_button, cancel_button = discord_actions
    assert is_external_channel_projection(edit_button)
    assert is_external_channel_projection(cancel_button)
    assert edit_button["url"] == "https://azents.example/task"
    assert "custom_id" not in edit_button
    assert cancel_button["label"] == "Cancel"
    assert cancel_button["custom_id"] == delete


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
