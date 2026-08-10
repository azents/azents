"""Common Job Runtime contracts."""

import datetime
import enum
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from azcommon import di
from pydantic import TypeAdapter

type JobScalar = str | int | float | bool | None
type JobValue = JobScalar | list[JobValue] | dict[str, JobValue]
type JobPayload = dict[str, JobValue]

_JOB_PAYLOAD_ADAPTER = TypeAdapter(JobPayload)


class JobOutcomeStatus(enum.StrEnum):
    """Structured terminal state of one local execution attempt."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True)
class JobRequest:
    """Typed request submitted to one registered background handler."""

    handler_key: str
    execution_key: str
    deadline: datetime.datetime
    payload: JobPayload

    def __post_init__(self) -> None:
        """Validate stable identity, deadline, and JSON-safe payload."""
        if not self.handler_key:
            raise ValueError("Job handler key must not be blank.")
        if not self.execution_key:
            raise ValueError("Job execution key must not be blank.")
        if self.deadline.tzinfo is None or self.deadline.utcoffset() is None:
            raise ValueError("Job deadline must be timezone-aware.")
        validate_job_payload(self.payload)


@dataclass(frozen=True)
class JobOutcome:
    """Structured result returned by one Job Runtime handle."""

    status: JobOutcomeStatus
    result: JobPayload | None
    error_code: str | None
    error_message: str | None

    @classmethod
    def succeeded(cls, result: JobPayload | None) -> "JobOutcome":
        """Build one successful structured outcome."""
        return cls(
            status=JobOutcomeStatus.SUCCEEDED,
            result=result,
            error_code=None,
            error_message=None,
        )

    @classmethod
    def failed(cls, error: Exception) -> "JobOutcome":
        """Build one failed structured outcome."""
        return cls(
            status=JobOutcomeStatus.FAILED,
            result=None,
            error_code=type(error).__name__,
            error_message=str(error),
        )

    @classmethod
    def timed_out(cls) -> "JobOutcome":
        """Build one absolute-deadline timeout outcome."""
        return cls(
            status=JobOutcomeStatus.TIMED_OUT,
            result=None,
            error_code="TimeoutError",
            error_message="Registered job handler exceeded its absolute deadline.",
        )


@dataclass(frozen=True)
class JobExecutionContext:
    """Runtime-owned resources supplied to one registered handler."""

    request: JobRequest
    container: di.Container


type JobHandler = Callable[[JobExecutionContext], Awaitable[JobPayload | None]]


@dataclass(frozen=True)
class JobHandlerDefinition:
    """One closed code-owned handler registration."""

    key: str
    handler: JobHandler


class JobHandlerRegistry:
    """Closed lookup table for registered background handlers."""

    def __init__(self, definitions: tuple[JobHandlerDefinition, ...]) -> None:
        """Validate and retain unique handler definitions."""
        handlers: dict[str, JobHandler] = {}
        for definition in definitions:
            if not definition.key:
                raise ValueError("Registered job handler key must not be blank.")
            if definition.key in handlers:
                raise ValueError(
                    f"Duplicate registered job handler key: {definition.key}"
                )
            handlers[definition.key] = definition.handler
        self._handlers: Mapping[str, JobHandler] = handlers

    def get(self, key: str) -> JobHandler | None:
        """Return one registered handler by its closed key."""
        return self._handlers.get(key)


class JobHandle(Protocol):
    """Awaitable handle for one accepted execution."""

    async def wait(self) -> JobOutcome:
        """Wait for the structured terminal outcome."""
        ...


class JobRuntime(Protocol):
    """Common backend boundary for registered background execution."""

    async def submit(self, request: JobRequest) -> JobHandle:
        """Accept or coalesce one process-local execution request."""
        ...


def validate_job_payload(value: object) -> JobPayload:
    """Validate and return one JSON-safe object payload."""
    return _JOB_PAYLOAD_ADAPTER.validate_python(value)
