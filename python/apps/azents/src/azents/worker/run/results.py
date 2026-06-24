"""Worker run execution result types."""

import dataclasses

from azents.engine.run.contracts import ToolkitBinding


@dataclasses.dataclass(frozen=True)
class RunExecutionResult:
    """Result of one wake-up run execution."""

    toolkits: list[ToolkitBinding]
    terminal_event_observed: bool
    no_actionable_work: bool
    run_id: str | None = None
