"""Typed client for representative authenticated Session Browser journeys."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from dataclasses import asdict
from typing import Annotated, Literal

import requests
from azents_runtime_control.browser_viewer_contract import (
    MAX_VIEWER_MESSAGE_BYTES,
    ViewerFrame,
    ViewerSource,
    ViewerTarget,
    decode_viewer_frame,
)
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from websockets.sync.client import ClientConnection, connect
from websockets.typing import Origin, Subprotocol


class _WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class _Ticket(_WireModel):
    ticket: str


class BrowserDialog(_WireModel):
    id: str
    type: str
    message: str


class BrowserViewport(_WireModel):
    width: int
    height: int


class BrowserStatus(_WireModel):
    type: Literal["status"]
    attachment_id: str
    target: ViewerTarget
    state: Literal["connected", "unavailable", "closed"]
    allow_input: bool
    viewport: BrowserViewport
    navigation_id: str
    dialog: BrowserDialog | None
    conflict: bool
    opened_target: ViewerTarget | None


class BrowserInputAck(_WireModel):
    type: Literal["input_ack"]
    attachment_id: str
    sequence: int
    accepted: bool
    reason_code: str | None
    outcome: Literal["dispatched", "rejected", "outcome_unknown"]


_EVENT = TypeAdapter(
    Annotated[BrowserStatus | BrowserInputAck, Field(discriminator="type")]
)


class BrowserSocket:
    """Use fresh normal Chat tickets and acknowledge only received native frames."""

    def __init__(self, connection: ClientConnection) -> None:
        self.connection = connection
        self.status: BrowserStatus | None = None
        self.frame: ViewerFrame | None = None
        self.sequence = 0

    @classmethod
    def open(
        cls,
        *,
        public_url: str,
        token: str,
        resource_path: str,
        target: ViewerTarget,
        origin: str,
    ) -> BrowserSocket:
        ticket = requests.post(
            f"{public_url}/chat/v1/ticket",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        ticket.raise_for_status()
        issued = _Ticket.model_validate(ticket.json())
        socket_url = public_url.replace("http://", "ws://").replace(
            "https://", "wss://"
        )
        connection = connect(
            f"{socket_url}{resource_path}/ws",
            origin=Origin(origin),
            subprotocols=[Subprotocol("azents.browser.v1")],
            open_timeout=10,
            max_size=MAX_VIEWER_MESSAGE_BYTES,
        )
        try:
            connection.send(
                json.dumps(
                    {
                        "type": "attach",
                        "ticket": issued.ticket,
                        "target": asdict(target),
                    }
                )
            )
            client = cls(connection)
            client.next_frame()
            assert client.status is not None
            assert client.status.state == "connected"
            assert client.status.target == target
            assert client.frame is not None
            assert client.frame.target == target
            return client
        except BaseException:
            connection.close()
            raise

    def receive(
        self, *, timeout: float
    ) -> BrowserStatus | BrowserInputAck | ViewerFrame:
        message = self.connection.recv(timeout=timeout)
        if isinstance(message, bytes):
            frame = decode_viewer_frame(message)
            assert frame.image.startswith(b"\xff\xd8")
            self.frame = frame
            self.connection.send(
                json.dumps(
                    {
                        "type": "frame_ack",
                        "attachment_id": frame.attachment_id,
                        "frame_sequence": frame.source.frame_sequence,
                    }
                )
            )
            return frame
        event = _EVENT.validate_json(message)
        if isinstance(event, BrowserStatus):
            self.status = event
        return event

    def next_frame(self) -> ViewerFrame:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            event = self.receive(timeout=max(0.01, deadline - time.monotonic()))
            if isinstance(event, ViewerFrame):
                return event
        raise TimeoutError("Browser frame was not received")

    def input(
        self,
        action: Mapping[str, object],
        *,
        source: ViewerSource | None,
    ) -> BrowserInputAck:
        assert self.status is not None
        self.sequence += 1
        self.connection.send(
            json.dumps(
                {
                    "type": "input",
                    "attachment_id": self.status.attachment_id,
                    "sequence": self.sequence,
                    "source": None if source is None else asdict(source),
                    "action": dict(action),
                }
            )
        )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            event = self.receive(timeout=max(0.01, deadline - time.monotonic()))
            if isinstance(event, BrowserInputAck):
                assert event.sequence == self.sequence
                return event
        raise TimeoutError("Browser input acknowledgement was not received")

    def click(self, *, x: int, y: int) -> None:
        assert self.frame is not None
        for phase in ("down", "up"):
            ack = self.input(
                {"kind": "pointer", "phase": phase, "x": x, "y": y, "button": "left"},
                source=self.frame.source,
            )
            assert ack.accepted, ack.reason_code

    def close(self) -> None:
        self.connection.close()
