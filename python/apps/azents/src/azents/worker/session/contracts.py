"""Collaborator contracts around SessionRunner."""

from collections.abc import Awaitable, Callable, Sequence

from azents.engine.run.contracts import ToolkitBinding

PrepareToolkits = Callable[
    [Sequence[ToolkitBinding], str | None],
    Awaitable[list[ToolkitBinding]],
]
