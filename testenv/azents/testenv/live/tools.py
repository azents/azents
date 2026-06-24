"""Live tool-call helpers for LLM-driven tool execution.

This wraps `Chat.collect()` from ``live.chat``. Tool-call chats often need a
longer timeout, so the default is 120 seconds. The helper also provides
``types_only`` for quick event type inspection.

This is a real LLM path. With real LLM keys, the model may decide whether to
emit function_call_item events; dummy-key environments remain deterministic.

Example::

    client = build_client_from_env()
    user = client.auth.create_user()
    workspace = client.workspace.create(user)
    agent = client.agent.create(user, workspace, ..., model="gpt-4o-mini")

    session = client.chat.start_session(user, agent)
    events = client.tools.run_and_collect(
        session,
        "run echo hello using shell",
    )

    has_function_call(events, name="shell_exec")
    function_call_succeeded(events)

Related document: ``docs/azents/design/llm-tool-execution.md``
"""

from dataclasses import dataclass
from typing import Any

from testenv.runtime_config import TestenvConfig

from .chat import Chat
from .types import Session


@dataclass(frozen=True)
class Tools:
    """Helper for testing LLM tool calls.

    Used as ``TestenvClient.tools``. It receives the same ``Chat`` instance used
    by ``TestenvClient.chat`` so WebSocket behavior stays on one injected path.
    """

    config: TestenvConfig
    chat: Chat

    def run_and_collect(
        self,
        session: Session,
        message: str,
        *,
        timeout: float = 120.0,
        until: str = "run_complete",
    ) -> list[dict[str, Any]]:
        """Send a message and collect events until the `until` event arrives.

        This delegates to ``Chat.collect`` with a longer default timeout for
        tool-call runs. Returned events can be checked with ``live.matchers``
        helpers such as ``has_function_call`` and ``function_call_succeeded``.
        """
        return self.chat.collect(
            session,
            message,
            until=until,
            timeout=timeout,
        )

    def types_only(self, events: list[dict[str, Any]]) -> list[str]:
        """Return a compact summary of event type fields."""
        return [str(e.get("type", "<no-type>")) for e in events]
