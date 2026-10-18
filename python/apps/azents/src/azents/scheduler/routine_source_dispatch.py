"""Scheduler composition for source-only Routine inbox admission."""

import dataclasses
import datetime
from typing import Annotated

from fastapi import Depends

from azents.broker.deps import get_broker
from azents.broker.types import SessionBroker
from azents.repos.routine.judgment_inbox import RoutineJudgmentInboxRepository
from azents.repos.routine.source_dispatch import RoutineSourceRepository
from azents.scheduler.types import TaskContext, TaskResult
from azents.services.routine.source_dispatch import RoutineSourceDispatcher


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def get_routine_source_dispatcher(
    sources: Annotated[RoutineSourceRepository, Depends()],
    inbox: Annotated[RoutineJudgmentInboxRepository, Depends()],
    broker: Annotated[SessionBroker, Depends(get_broker)],
) -> RoutineSourceDispatcher:
    """Compose source collection without provider, judgment owner or retry state."""
    return RoutineSourceDispatcher(
        sources=sources, inbox=inbox, broker=broker, clock=_utc_now, batch_size=64
    )


async def routine_source_dispatch_handler(context: TaskContext) -> TaskResult:
    """Admit checking opportunities; the ordinary Run loop executes judgment."""
    dispatcher = await context.container.solve(get_routine_source_dispatcher)
    summary = await dispatcher.dispatch_once(
        now=context.attempt_started_at, deadline=context.deadline
    )
    return TaskResult(
        summary={
            "task_key": context.task_key,
            "attempt_started_at": context.attempt_started_at.isoformat(),
            "manual_triggered": context.manual_triggered,
            **dataclasses.asdict(summary),
        }
    )
