"""Runtime Web service data and outcomes."""

import dataclasses
import datetime
from typing import Literal

from pydantic import BaseModel

from azents.rdb.models.runtime_web import RuntimeWebActorKind
from azents.repos.runtime_web.data import (
    RuntimeWebOperationIdentity,
    RuntimeWebServiceRecord,
)


class RuntimeWebActor(BaseModel):
    """Actor requesting a Runtime Web operation."""

    kind: RuntimeWebActorKind
    actor_id: str
    execution_id: str
    call_id: str | None


class RuntimeWebOperation(BaseModel):
    """Client idempotency key."""

    operation_key: str


class RuntimeWebServiceProjection(BaseModel):
    """Current user-relevant service state."""

    id: str
    port: int
    label: str | None
    url: str | None
    configuration_state: Literal["configured", "unconfigured"]
    on: bool
    selected_duration_seconds: int
    expires_at: datetime.datetime | None
    revision: int
    created_at: datetime.datetime
    updated_at: datetime.datetime
    observed_at: datetime.datetime

    @classmethod
    def from_record(
        cls,
        record: RuntimeWebServiceRecord,
        *,
        url: str | None,
        observed_at: datetime.datetime,
    ) -> "RuntimeWebServiceProjection":
        """Project effective state from one service row and database time."""
        on = (
            record.exposure_deadline_at is not None
            and record.exposure_deadline_at > observed_at
        )
        return cls(
            id=record.id,
            port=record.port,
            label=record.label,
            url=url,
            configuration_state="configured" if url is not None else "unconfigured",
            on=on,
            selected_duration_seconds=record.selected_duration_seconds,
            expires_at=record.exposure_deadline_at if on else None,
            revision=record.revision,
            created_at=record.created_at,
            updated_at=record.updated_at,
            observed_at=observed_at,
        )


class RuntimeWebServicePage(BaseModel):
    """Bounded current service projections."""

    items: list[RuntimeWebServiceProjection]
    total_count: int


@dataclasses.dataclass(frozen=True)
class RuntimeWebNotFound:
    """The requested resource is absent or intentionally hidden."""


@dataclasses.dataclass(frozen=True)
class RuntimeWebAccessDenied:
    """The actor lacks current Agent access."""


@dataclasses.dataclass(frozen=True)
class RuntimeWebConflict:
    """The expected revision, operation input, or current state changed."""


@dataclasses.dataclass(frozen=True)
class RuntimeWebQuotaExceeded:
    """A logical service or active-service quota is exhausted."""

    scope: str


@dataclasses.dataclass(frozen=True)
class RuntimeWebConfigurationUnavailable:
    """Runtime Web has no usable current durable configuration."""


@dataclasses.dataclass(frozen=True)
class RuntimeWebCapabilityUnavailable:
    """The Agent does not currently have a managed Runtime capability."""


type RuntimeWebError = (
    RuntimeWebNotFound
    | RuntimeWebAccessDenied
    | RuntimeWebConflict
    | RuntimeWebQuotaExceeded
    | RuntimeWebConfigurationUnavailable
    | RuntimeWebCapabilityUnavailable
)


def operation_identity(
    actor: RuntimeWebActor,
    operation: RuntimeWebOperation,
) -> RuntimeWebOperationIdentity:
    """Build repository idempotency identity."""
    return RuntimeWebOperationIdentity(
        actor_kind=actor.kind,
        actor_id=actor.actor_id,
        execution_id=actor.execution_id,
        operation_key=operation.operation_key,
    )
