"""LLM-driven tool-call helpers over the current typed Chat transport."""

from dataclasses import dataclass

from testenv.runtime_config import TestenvConfig

from .chat import Chat
from .events import ChatAction, event_name
from .types import Session


@dataclass(frozen=True)
class Tools:
    """Share the injected Chat helper while allowing longer tool-run timeouts."""

    config: TestenvConfig
    chat: Chat

    def run_and_collect(
        self,
        session: Session,
        message: str,
        *,
        timeout: float = 120.0,
        until: str = "run_complete",
    ) -> list[ChatAction]:
        """Collect canonical actions until the selected completion condition."""
        return self.chat.collect(session, message, until=until, timeout=timeout)

    def types_only(self, events: list[ChatAction]) -> list[str]:
        """Return canonical event kinds or action names."""
        return [event_name(event) for event in events]
