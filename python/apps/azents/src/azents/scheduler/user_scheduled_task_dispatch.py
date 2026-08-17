"""User Scheduled Task dispatcher Scheduler composition."""

import dataclasses
import datetime
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.deps import get_broker
from azents.broker.types import SessionBroker
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.mailbox import MailboxRepository
from azents.repos.scheduled_task.repository import ScheduledTaskRepository
from azents.repos.scheduled_task_cycle import ScheduledTaskCycleRepository
from azents.scheduler.types import TaskContext, TaskResult
from azents.services.scheduled_task.service import (
    RDBScheduledTaskAuthorityValidator,
    ScheduledTaskDispatcher,
)


def _utc_now() -> datetime.datetime:
    """Return the timezone-aware Scheduler dispatcher clock."""
    return datetime.datetime.now(datetime.UTC)


def get_user_scheduled_task_dispatcher(
    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ],
    cycle_repository: Annotated[
        ScheduledTaskCycleRepository,
        Depends(ScheduledTaskCycleRepository),
    ],
    mailbox_repository: Annotated[
        MailboxRepository,
        Depends(MailboxRepository),
    ],
    broker: Annotated[SessionBroker, Depends(get_broker)],
    authority_validator: Annotated[
        RDBScheduledTaskAuthorityValidator,
        Depends(RDBScheduledTaskAuthorityValidator),
    ],
    task_repository: Annotated[
        ScheduledTaskRepository,
        Depends(ScheduledTaskRepository),
    ],
) -> ScheduledTaskDispatcher:
    """Compose the bounded user Scheduled Task dispatcher."""
    return ScheduledTaskDispatcher(
        session_manager=session_manager,
        cycle_repository=cycle_repository,
        mailbox_repository=mailbox_repository,
        broker=broker,
        authority_validator=authority_validator,
        task_repository=task_repository,
        clock=_utc_now,
    )


async def user_scheduled_task_dispatch_handler(
    context: TaskContext,
) -> TaskResult:
    """Dispatch one bounded pass of due user Scheduled Tasks."""
    dispatcher = await context.container.solve(get_user_scheduled_task_dispatcher)
    summary = await dispatcher.dispatch_once(lease_owner=context.lease_owner)
    return TaskResult(
        summary={
            "task_key": context.task_key,
            "attempt_started_at": context.attempt_started_at.isoformat(),
            "manual_triggered": context.manual_triggered,
            **dataclasses.asdict(summary),
        }
    )
