"""Non-consuming process lifecycle observation contract."""

from dataclasses import dataclass
from typing import Literal

from azents_runtime_control.runner import JsonValue


@dataclass(frozen=True)
class ProcessCompletion:
    """One retained terminal process observation, without output."""

    process_id: str
    status: Literal["exited", "terminated", "expired"]

    def to_payload(self) -> dict[str, JsonValue]:
        return {"process_id": self.process_id, "status": self.status}


@dataclass(frozen=True)
class ProcessObservation:
    """Session-scoped lifecycle snapshot and acknowledgement position."""

    revision: int
    running_count: int
    completed: tuple[ProcessCompletion, ...]

    def to_payload(self) -> dict[str, JsonValue]:
        return {
            "revision": self.revision,
            "running_count": self.running_count,
            "completed": [item.to_payload() for item in self.completed],
        }

    @classmethod
    def from_payload(cls, value: JsonValue) -> "ProcessObservation":
        """Validate the operation result once at ingress."""
        if not isinstance(value, dict) or set(value) != {
            "revision",
            "running_count",
            "completed",
        }:
            raise ValueError("Invalid process observation fields")
        revision = value["revision"]
        count = value["running_count"]
        rows = value["completed"]
        if (
            not isinstance(revision, int)
            or isinstance(revision, bool)
            or revision < 0
            or not isinstance(count, int)
            or isinstance(count, bool)
            or count < 0
            or not isinstance(rows, list)
        ):
            raise ValueError("Invalid process observation state")
        completed: list[ProcessCompletion] = []
        for row in rows:
            if not isinstance(row, dict) or set(row) != {"process_id", "status"}:
                raise ValueError("Invalid process completion fields")
            process_id, status = row["process_id"], row["status"]
            if not isinstance(process_id, str) or not process_id:
                raise ValueError("Invalid process completion identity")
            if status not in ("exited", "terminated", "expired"):
                raise ValueError("Invalid process completion status")
            # Equality narrowing is explicit for type-checkers and wire validation.
            if status == "exited":
                completion = ProcessCompletion(process_id, "exited")
            elif status == "terminated":
                completion = ProcessCompletion(process_id, "terminated")
            else:
                completion = ProcessCompletion(process_id, "expired")
            completed.append(completion)
        return cls(revision=revision, running_count=count, completed=tuple(completed))
