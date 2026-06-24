"""Scheduled task execution backends."""

import abc
import asyncio

from azents.scheduler.types import ScheduledTaskDefinition, TaskContext, TaskResult


class TaskExecutor(abc.ABC):
    """Execution backend for scheduled tasks."""

    @abc.abstractmethod
    async def execute(
        self,
        definition: ScheduledTaskDefinition,
        context: TaskContext,
    ) -> TaskResult:
        """Execute a task definition.

        :param definition: Task definition
        :param context: Task context
        :return: Task result
        """


class LocalTaskExecutor(TaskExecutor):
    """Task executor that calls handlers in the scheduler process."""

    async def execute(
        self,
        definition: ScheduledTaskDefinition,
        context: TaskContext,
    ) -> TaskResult:
        """Execute task handler locally with timeout."""
        return await asyncio.wait_for(
            definition.handler(context),
            timeout=definition.timeout.total_seconds(),
        )
