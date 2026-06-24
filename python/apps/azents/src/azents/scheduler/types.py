"""Scheduler domain types."""

import datetime
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from azcommon import di

RetryPolicyKind = Literal["next_interval", "bounded_backoff"]


@dataclass(frozen=True)
class RetryPolicy:
    """Retry policy for a scheduled task definition."""

    kind: RetryPolicyKind
    min_delay: datetime.timedelta | None = None
    max_delay: datetime.timedelta | None = None


@dataclass(frozen=True)
class TaskContext:
    """Context passed to a scheduled task handler."""

    task_key: str
    attempt_started_at: datetime.datetime
    lease_owner: str
    deadline: datetime.datetime
    manual_triggered: bool
    container: di.Container


@dataclass(frozen=True)
class TaskResult:
    """Scheduled task execution result."""

    summary: dict[str, Any] | None = None


TaskHandler = Callable[[TaskContext], Awaitable[TaskResult]]


@dataclass(frozen=True)
class ScheduledTaskDefinition:
    """Code-registered system scheduled task definition."""

    key: str
    description: str
    interval: datetime.timedelta
    timeout: datetime.timedelta
    retry_policy: RetryPolicy
    handler: TaskHandler
    enabled_by_default: bool
