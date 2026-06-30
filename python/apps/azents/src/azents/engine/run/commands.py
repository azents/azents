"""Session command handlers.

Handles user slash commands such as /compact.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from azents.engine.run.contracts import AgentEngineProtocol, RunRequest
from azents.engine.run.emit import Emit


@dataclass(frozen=True)
class SlashCommandDefinition:
    """Slash command metadata."""

    name: str
    description: str


class CommandHandler(Protocol):
    """Command handler protocol."""

    definition: SlashCommandDefinition

    def execute(
        self,
        engine: AgentEngineProtocol,
        request: RunRequest,
    ) -> AsyncIterator[Emit]: ...


class CompactCommand:
    """Forced compaction command."""

    definition = SlashCommandDefinition(
        name="compact",
        description="Compact chat context.",
    )

    async def execute(
        self,
        engine: AgentEngineProtocol,
        request: RunRequest,
    ) -> AsyncIterator[Emit]:
        """Run compaction and yield events."""
        async for event in engine.compact(request):
            yield event


COMMAND_REGISTRY: dict[str, CommandHandler] = {
    "compact": CompactCommand(),
}


def list_registered_commands() -> list[SlashCommandDefinition]:
    """Return registered slash command metadata."""
    return [handler.definition for handler in COMMAND_REGISTRY.values()]


def parse_command(text: str) -> str | None:
    """Parse slash command.

    :param text: User message
    :return: Command name if registered, otherwise None
    """
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None
    command = stripped.lstrip("/").split()[0].lower()
    if command in COMMAND_REGISTRY:
        return command
    return None
