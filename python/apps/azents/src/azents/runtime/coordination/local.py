"""Explicit shared Runtime state for a co-located application/Control root."""

from dataclasses import dataclass

from azents.runtime.coordination.store import RuntimeCoordinationStore
from azents.runtime.terminal_coordination.store import RuntimeTerminalCoordinationStore


@dataclass(frozen=True)
class LocalRuntimeStores:
    """Pass the exact process-local state owners into Runtime Control."""

    coordination: RuntimeCoordinationStore
    terminal: RuntimeTerminalCoordinationStore
