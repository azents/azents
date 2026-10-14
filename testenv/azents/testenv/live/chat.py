"""Live Chat helpers using the current REST input and Chat action contracts."""

import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

from azentspublicclient.api.agent_v1_api import AgentV1Api
from azentspublicclient.api.chat_v1_api import ChatV1Api
from azentspublicclient.exceptions import ApiException
from azentspublicclient.models.chat_input_write_request import ChatInputWriteRequest
from azentspublicclient.models.requested_inference_profile import RequestedInferenceProfile
from pydantic import ValidationError
from urllib3.exceptions import HTTPError
from websockets.exceptions import WebSocketException
from websockets.sync.client import connect as ws_connect

from testenv.runtime_config import TestenvConfig
from testenv.seed.client import public_client
from testenv.seed.types import Agent, User

from .errors import ChatConnectionError, ChatTimeout
from .events import ChatAction, event_name, terminal_run
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
    """Live chat helper used by ``TestenvClient.chat``."""

    config: TestenvConfig

    def start_session(self, user: User, agent: Agent) -> Session:
        """Resolve the agent's team primary session through the generated API."""
        try:
            response = ChatV1Api(public_client(self.config)).chat_v1_get_team_primary_agent_session(
                agent.id,
                _headers={"Authorization": f"Bearer {user.access_token}"},
                _request_timeout=10.0,
            )
        except (ApiException, HTTPError, ValidationError) as exc:
            raise ChatConnectionError("failed to resolve team primary session") from exc
        return Session(
            id=response.id,
            user=user,
            agent=agent,
            public_url=self.config.public_url,
        )

    def _issue_ticket(self, user: User) -> str:
        """Issue a WebSocket ticket using the generated response contract."""
        try:
            response = ChatV1Api(public_client(self.config)).chat_v1_issue_ws_ticket(
                _headers={"Authorization": f"Bearer {user.access_token}"},
                _request_timeout=10.0,
            )
        except (ApiException, HTTPError, ValidationError) as exc:
            raise ChatConnectionError("failed to issue WebSocket ticket") from exc
        return response.ticket

    def stream(
        self,
        session: Session,
        message: str,
        *,
        timeout: float = 60.0,
    ) -> Iterator[ChatAction]:
        """Subscribe before committing REST input, then yield typed Chat actions.

        Waiting for the subscription acknowledgement prevents fast runs from
        completing between a REST write and WebSocket registration. The current
        Agent main model label is authoritative for the requested profile.
        """
        collected: list[ChatAction] = []
        deadline = time.monotonic() + timeout
        headers = {"Authorization": f"Bearer {session.user.access_token}"}
        try:
            client = public_client(self.config)
            agent = AgentV1Api(client).agent_v1_get_agent(
                session.agent.id,
                session.agent.workspace.handle,
                _headers=headers,
                _request_timeout=10.0,
            )
            profile = RequestedInferenceProfile(
                model_target_label=agent.main_model_label,
                reasoning_effort=None,
                enabled_execution_options=[],
            )
            ticket = self._issue_ticket(session.user)
            uri = f"{_ws_url(session.public_url)}/chat/v1/sessions/{session.id}?ticket={ticket}"
            with ws_connect(uri, open_timeout=timeout) as ws:
                committed = False
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ChatTimeout(
                            "timed out waiting for Chat action", collected_events=collected
                        )
                    try:
                        raw = ws.recv(timeout=remaining)
                    except TimeoutError as exc:
                        raise ChatTimeout(
                            "timed out waiting for Chat action",
                            collected_events=collected,
                        ) from exc
                    action = ChatAction.model_validate_json(raw)
                    if action.session_id is not None and action.session_id != session.id:
                        raise ChatConnectionError("received Chat action for another session")
                    if action.type == "subscribed" and not committed:
                        ChatV1Api(client).chat_v1_create_input(
                            session.id,
                            ChatInputWriteRequest(
                                agent_id=session.agent.id,
                                client_request_id=f"testenv-live-chat-{uuid.uuid4().hex}",
                                message=message,
                                inference_profile=profile,
                            ),
                            _headers=headers,
                            _request_timeout=10.0,
                        )
                        committed = True
                    collected.append(action)
                    yield action
        except (ApiException, HTTPError, ValidationError, WebSocketException, OSError) as exc:
            # Do not include the ticket-bearing URL or provider response in messages.
            raise ChatConnectionError("failed to commit or receive live Chat input") from exc

    def collect(
        self,
        session: Session,
        message: str,
        *,
        until: str = "run_complete",
        timeout: float = 60.0,
    ) -> list[ChatAction]:
        """Collect until a terminal durable run marker or a canonical event name.

        The established ``run_complete`` completion selector means a terminal
        run, including failed/interrupted dummy-key runs. Wire events retain
        their canonical ``run_marker`` name and status.
        """
        collected: list[ChatAction] = []
        for action in self.stream(session, message, timeout=timeout):
            collected.append(action)
            if (until == "run_complete" and terminal_run(action)) or event_name(action) == until:
                return collected
        raise ChatTimeout(
            "Chat stream ended before the requested event", collected_events=collected
        )
