"""Collaborator contracts around SessionRunner."""

from collections.abc import Awaitable, Callable, Sequence

from azents.engine.run.contracts import ToolkitBinding

PrepareToolkits = Callable[
    [Sequence[ToolkitBinding]],
    Awaitable[list[ToolkitBinding]],
]
