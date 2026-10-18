"""The normal Scheduler admits sources while the ordinary Run loop owns judgment."""

import datetime
from unittest.mock import AsyncMock, Mock

from azcommon import di

from azents.core.routine import ROUTINE_TICK_INTERVAL
from azents.scheduler import registry
from azents.scheduler.routine_source_dispatch import (
    get_routine_source_dispatcher,
    routine_source_dispatch_handler,
)
from azents.scheduler.types import TaskContext
from azents.services.routine.source_dispatch import (
    RoutineSourceDispatcher,
    RoutineSourceDispatchSummary,
)


def test_source_dispatch_is_registered_once_at_the_fixed_checking_interval() -> None:
    definitions = [
        item
        for item in registry.get_task_definitions()
        if item.key == "routine_source_dispatch"
    ]
    assert definitions == [registry.ROUTINE_SOURCE_DISPATCH_TASK]
    definition = definitions[0]
    assert definition.interval == ROUTINE_TICK_INTERVAL
    assert definition.timeout == datetime.timedelta(minutes=2)
    assert definition.retry_policy.kind == "next_interval"
    assert definition.enabled_by_default


async def test_handler_forwards_only_the_source_opportunity_and_existing_deadline() -> (
    None
):
    dispatcher = Mock(spec=RoutineSourceDispatcher)
    dispatcher.dispatch_once = AsyncMock(
        return_value=RoutineSourceDispatchSummary(
            checked=3, enqueued=2, unavailable=1, deadline_reached=False
        )
    )
    container = Mock(spec=di.Container)
    container.solve = AsyncMock(return_value=dispatcher)
    now = datetime.datetime(2026, 10, 18, tzinfo=datetime.UTC)
    deadline = now + datetime.timedelta(minutes=2)
    context = TaskContext(
        task_key="routine_source_dispatch",
        attempt_started_at=now,
        lease_owner="ordinary-scheduler-owner",
        deadline=deadline,
        manual_triggered=False,
        container=container,
    )
    result = await routine_source_dispatch_handler(context)
    container.solve.assert_awaited_once_with(get_routine_source_dispatcher)
    dispatcher.dispatch_once.assert_awaited_once_with(now=now, deadline=deadline)
    assert result.summary == {
        "task_key": context.task_key,
        "attempt_started_at": now.isoformat(),
        "manual_triggered": False,
        "checked": 3,
        "enqueued": 2,
        "unavailable": 1,
        "deadline_reached": False,
    }
