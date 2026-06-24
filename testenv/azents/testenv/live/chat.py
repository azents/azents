"""Live chat helpers.

`Chat` is constructed with `TestenvConfig` and exposes the following methods:

- `start_session(user, agent)` returns a Session value object for the user and
  agent. It does not open a WebSocket.
- `stream(session, message)` commits a REST write and yields WebSocket events.
- `collect(session, message)` wraps `stream` and returns when the `until` event
  arrives.

Server model: a REST write endpoint commits the turn, while WebSocket streaming
receives live events. Since each turn starts with a REST write, `start_session`
does not need to contact the devserver.

Normally use this through `TestenvClient.chat`.

Details: `docs/azents/design/llm-pipeline.md`
"""

import json
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import requests
from azentspublicclient.api.chat_v1_api import ChatV1Api
from websockets.exceptions import WebSocketException
from websockets.sync.client import connect as ws_connect

from testenv.runtime_config import TestenvConfig
from testenv.seed.client import public_client
from testenv.seed.types import Agent, User

from .errors import ChatConnectionError, ChatTimeout
from .types import Session


def _ws_url(http_url: str) -> str:
    """Convert an HTTP(S) URL to the matching WebSocket scheme."""
    if http_url.startswith("https://"):
        return "wss://" + http_url.removeprefix("https://")
    if http_url.startswith("http://"):
        return "ws://" + http_url.removeprefix("http://")
    return http_url


@dataclass(frozen=True)
class Chat:
    """Live chat helper used by `TestenvClient.chat`."""

    config: TestenvConfig

    def start_session(self, user: User, agent: Agent) -> Session:
        """Return a `Session` value object.

        The id is a client-side placeholder. The actual server session_id is
        obtained from the REST write response. `start_session` does not call the
        devserver.
        """
        return Session(
            id=uuid.uuid4().hex,
            user=user,
            agent=agent,
            public_url=self.config.public_url,
        )

    def _issue_ticket(self, user: User) -> str:
        """Issue a WebSocket ticket for the user."""
        chat_api = ChatV1Api(public_client(self.config))
        try:
            resp = chat_api.chat_v1_issue_ws_ticket(
                _headers={"Authorization": f"Bearer {user.access_token}"},
            )
        except Exception as exc:
            raise ChatConnectionError(
                "failed to issue ws ticket. Is devserver up?\n  uv run devserver.py status",
            ) from exc
        return resp.ticket

    def stream(
        self,
        session: Session,
        message: str,
        *,
        timeout: float = 60.0,
    ) -> Iterator[dict[str, object]]:
        """Commit a message for a session and yield live events.

        The REST write endpoint records the message, then a session WebSocket
        connection streams live events. Because each turn is committed by REST,
        `start_session` only needs to provide a Session value object.

        Raises `ChatTimeout(collected_events=...)` on timeout and
        `ChatConnectionError` for REST/WS failures.
        """
        try:
            response = requests.post(
                f"{session.public_url}/chat/v1/sessions/new/messages",
                headers={
                    "Authorization": f"Bearer {session.user.access_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "agent_id": session.agent.id,
                    "client_request_id": f"testenv-live-chat-{uuid.uuid4().hex}",
                    "message": message,
                },
                timeout=10,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ChatConnectionError(
                "failed to commit chat write. Is devserver up?\n  uv run devserver.py status",
            ) from exc
        payload = response.json()
        session_id = payload.get("session_id")
        if not isinstance(session_id, str):
            raise ChatConnectionError(
                f"REST write response did not include session_id: {payload!r}",
            )

        ticket = self._issue_ticket(session.user)
        ws_uri = f"{_ws_url(session.public_url)}/chat/v1/sessions/{session_id}?ticket={ticket}"

        collected: list[dict[str, object]] = []
        deadline = time.monotonic() + timeout

        try:
            with ws_connect(ws_uri) as ws:
                yield {"type": "session_created", "session_id": session_id}
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ChatTimeout(
                            f"no event received within {timeout}s",
                            collected_events=collected,
                        )
                    try:
                        raw = ws.recv(timeout=max(remaining, 0.1))
                    except TimeoutError as exc:
                        raise ChatTimeout(
                            f"no event received within {timeout}s",
                            collected_events=collected,
                        ) from exc
                    event: dict[str, object] = json.loads(raw)
                    collected.append(event)
                    yield event
        except (WebSocketException, OSError) as exc:
            raise ChatConnectionError(
                f"ws error during stream ({ws_uri})",
            ) from exc

    def collect(
        self,
        session: Session,
        message: str,
        *,
        until: str = "run_complete",
        timeout: float = 60.0,
    ) -> list[dict[str, object]]:
        """Collect events until the requested `until` event arrives.

        The default covers the common case: assert one completed turn. Use
        `stream` directly when the caller needs incremental event handling.
        """
        collected: list[dict[str, object]] = []
        for event in self.stream(session, message, timeout=timeout):
            collected.append(event)
            if event.get("type") == until:
                return collected
        raise ChatTimeout(
            f"stream ended without reaching '{until}'",
            collected_events=collected,
        )
