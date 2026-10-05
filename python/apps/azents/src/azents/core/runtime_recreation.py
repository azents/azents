"""Detached recreation results and operation errors."""

import dataclasses

from azents.repos.runtime_profile.data import (
    RuntimeRecreationOperation,
    RuntimeRecreationOperationItem,
)


@dataclasses.dataclass(frozen=True)
class RuntimeRecreationProjection:
    """One operation and its bounded non-success item details."""

    operation: RuntimeRecreationOperation
    items: tuple[RuntimeRecreationOperationItem, ...]


@dataclasses.dataclass
class RuntimeRecreationUnavailable(Exception):
    """One bounded recreation operation failure."""

    code: str
    message: str
    current_version: int | None = None

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)


@dataclasses.dataclass(frozen=True)
class RuntimeRecreationReconcileResult:
    """One bounded recreation reconciliation result."""

    operations: int
    processed_items: int
    dispatched_items: int
    completed_items: int


@dataclasses.dataclass(frozen=True)
class RuntimeRecreationItemProcessResult:
    """Outcome of processing one Runtime recreation item."""

    dispatched: bool
    completed: bool
    invalidated_runtime_id: str | None
