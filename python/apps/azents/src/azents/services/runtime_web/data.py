"""Runtime Web service data and outcomes."""

import dataclasses
import datetime
from typing import Literal

from pydantic import BaseModel

from azents.rdb.models.runtime_web import RuntimeWebRequesterKind
from azents.repos.runtime_web.data import (
    RuntimeWebCycle,
    RuntimeWebEndpoint,
    RuntimeWebOperationIdentity,
    RuntimeWebRequest,
)


class RuntimeWebActor(BaseModel):
    """Actor requesting a Runtime Web operation."""

    kind: RuntimeWebRequesterKind
    actor_id: str
    execution_id: str
    call_id: str | None


class RuntimeWebOperation(BaseModel):
    """Client idempotency key."""

    operation_key: str


class RuntimeWebServiceProjection(BaseModel):
    """Current orthogonal service state."""

    endpoint: RuntimeWebEndpoint
    url: str | None
    configuration_state: Literal["configured", "unconfigured"]
    current_request: RuntimeWebRequest | None
    current_cycle: RuntimeWebCycle | None
    active: bool
    duration_seconds: int
    duration_configuration_revision: int
    observed_at: datetime.datetime


class RuntimeWebServicePage(BaseModel):
    """Bounded current service projections."""

    items: list[RuntimeWebServiceProjection]
    total_count: int


@dataclasses.dataclass(frozen=True)
class RuntimeWebNotFound:
    """The requested resource is absent or intentionally hidden."""


@dataclasses.dataclass(frozen=True)
class RuntimeWebAccessDenied:
    """The authenticated user lacks disclosed Session access."""


@dataclasses.dataclass(frozen=True)
class RuntimeWebConflict:
    """The expected revision or current resource changed."""


@dataclasses.dataclass(frozen=True)
class RuntimeWebQuotaExceeded:
    """A logical endpoint or active-service quota is exhausted."""

    scope: str


@dataclasses.dataclass(frozen=True)
class RuntimeWebConfigurationUnavailable:
    """Runtime Web has no usable current durable configuration."""


type RuntimeWebError = (
    RuntimeWebNotFound
    | RuntimeWebAccessDenied
    | RuntimeWebConflict
    | RuntimeWebQuotaExceeded
    | RuntimeWebConfigurationUnavailable
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
