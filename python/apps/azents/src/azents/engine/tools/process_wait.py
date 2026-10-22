"""Runtime projection boundary used by shared waiting."""

from dataclasses import dataclass
from typing import Protocol

from azents_runtime_control.process_observation import ProcessObservation


@dataclass(frozen=True)
class ProcessWaitTarget:
    runtime_id: str
    runner_generation: int
    owner_session_id: str


class ProcessWaitSource(Protocol):
    async def process_wait_target(self) -> ProcessWaitTarget | None:
        """Project existing Runtime authority without provisioning compute."""
        ...

    async def wait_processes(
        self, target: ProcessWaitTarget, *, after_revision: int, timeout_ms: int
    ) -> ProcessObservation:
        """Observe lifecycle changes without consuming process output."""
        ...
