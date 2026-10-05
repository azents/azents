"""Detached outcomes from completed Runtime Web operations."""

import dataclasses
import datetime
import enum

from azents.rdb.models.runtime_web import RuntimeWebActorKind
from azents.repos.runtime_web.data import RuntimeWebServiceRecord


@dataclasses.dataclass(frozen=True)
class RuntimeWebCommandIdentity:
    """Unvalidated caller identity; receipt validation follows authorization."""

    actor_kind: RuntimeWebActorKind
    actor_id: str
    execution_id: str
    operation_key: str


class RuntimeWebOperationCode(enum.StrEnum):
    NOT_FOUND = "not_found"
    ACCESS_DENIED = "access_denied"
    CONFLICT = "conflict"
    QUOTA_EXCEEDED = "quota_exceeded"
    CONFIGURATION_UNAVAILABLE = "configuration_unavailable"
    CAPABILITY_UNAVAILABLE = "capability_unavailable"


@dataclasses.dataclass(frozen=True)
class RuntimeWebOperationError:
    code: RuntimeWebOperationCode
    scope: str | None


@dataclasses.dataclass(frozen=True)
class RuntimeWebObservedService:
    record: RuntimeWebServiceRecord
    observed_at: datetime.datetime


@dataclasses.dataclass(frozen=True)
class RuntimeWebObservedPage:
    items: list[RuntimeWebObservedService]
    total_count: int
