"""Explicit offline handover requests, not persisted activation modes."""

import dataclasses
import enum


class MemoryHandoverAction(enum.StrEnum):
    FORWARD = "forward"
    ROLLBACK = "rollback"
    REACTIVATE = "reactivate"


@dataclasses.dataclass(frozen=True)
class MemoryHandoverRequest:
    action: MemoryHandoverAction
    execution_quiesced: bool
    batch_size: int

    def validate(self) -> None:
        if not self.execution_quiesced:
            raise ValueError(
                "Memory handover requires affected execution admission and "
                "workers to be quiesced."
            )
        if not 1 <= self.batch_size <= 100:
            raise ValueError("Memory handover batch bounds are invalid.")


@dataclasses.dataclass(frozen=True)
class MemoryHandoverPage:
    count: int
    next_cursor: str | None


@dataclasses.dataclass(frozen=True)
class MemoryHandoverResult:
    snapshots_reset: int
    units_fenced: int
    sources_reconciled: int
