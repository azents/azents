"""Authenticated bounded Browser WebSocket bridge with live immutable scope."""

import asyncio
import json
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated, Literal, Protocol

from azents_runtime_control.browser_source_contract import BrowserScopeState
from azents_runtime_control.browser_viewer_contract import (
    MAX_VIEWER_TEXT_BYTES,
    BrowserViewerContractError,
    ViewerFieldAttributes,
    ViewerFieldOpen,
    ViewerFrameAck,
    ViewerInput,
    ViewerInputReason,
    ViewerTarget,
    decode_viewer_field_attributes,
    decode_viewer_frame,
    decode_viewer_request,
    viewer_field_kind,
)
from azents_runtime_control.grpc_browser_source_client import (
    BrowserSourceError,
    BrowserSourceScopeRevoked,
    BrowserSourceWebSocketMessage,
)
from azents_runtime_control.runtime_stream_session import (
    BrowserStreamAuthority,
    WebSocketOpcode,
)
from fastapi import WebSocketDisconnect
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from azents.services.runtime_browser.authority import (
    DatabaseRuntimeBrowserStreamScopeValidator,
)
from azents.services.runtime_browser.data import (
    RuntimeBrowserOperationError,
    RuntimeBrowserRequestError,
    RuntimeBrowserResource,
    RuntimeBrowserStreamUnavailable,
    RuntimeBrowserTargetUnavailable,
)

BROWSER_WEBSOCKET_SUBPROTOCOL = "azents.browser.v1"


class BrowserSocketFailure(RuntimeError):
    """A fixed public close classification, without input/page/SDK error data."""

    def __init__(self, code: int, reason: str) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason


class RuntimeBrowserWebSocket(Protocol):
    async def receive(self) -> Mapping[str, object]: ...
    async def send_text(self, data: str) -> None: ...
    async def send_bytes(self, data: bytes) -> None: ...


class RuntimeBrowserStreamConnection(Protocol):
    async def send_websocket(
        self, *, opcode: WebSocketOpcode, payload: bytes
    ) -> None: ...
    async def receive_websocket(self) -> BrowserSourceWebSocketMessage: ...
    async def close(self) -> None: ...


class RuntimeBrowserSourceClient(Protocol):
    async def connect(
        self, *, authority: BrowserStreamAuthority
    ) -> RuntimeBrowserStreamConnection: ...


class _Target(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    task_id: str = Field(min_length=1, max_length=128)
    page_id: str = Field(min_length=1, max_length=128)
    resource_incarnation: str = Field(min_length=1, max_length=128)


class _Viewport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    width: int = Field(ge=1, le=32768)
    height: int = Field(ge=1, le=32768)


class _Dialog(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(min_length=1, max_length=128)
    type: str = Field(min_length=1, max_length=128)
    message: str = Field(max_length=32768)


class _Status(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["status"]
    attachment_id: str = Field(min_length=1, max_length=128)
    target: _Target
    state: Literal["connected", "unavailable", "closed"]
    allow_input: bool
    viewport: _Viewport
    navigation_id: str = Field(min_length=1, max_length=128)
    dialog: _Dialog | None
    conflict: bool
    opened_target: _Target | None


class _InputAck(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["input_ack"]
    attachment_id: str = Field(min_length=1, max_length=128)
    sequence: int = Field(ge=1, le=(1 << 53) - 1)
    accepted: bool
    reason_code: ViewerInputReason | None
    outcome: Literal["dispatched", "rejected", "outcome_unknown"]

    @model_validator(mode="after")
    def validate_outcome(self) -> "_InputAck":
        if (
            self.accepted
            and (self.reason_code is not None or self.outcome != "dispatched")
        ) or (
            not self.accepted
            and (self.reason_code is None or self.outcome == "dispatched")
        ):
            raise ValueError("Inconsistent Browser input outcome")
        return self


class _FieldValue(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    type: Literal["field_value"]
    attachment_id: str = Field(min_length=1, max_length=128)
    sequence: int = Field(ge=1, le=(1 << 53) - 1)
    editable_id: str = Field(min_length=1, max_length=48)
    edit_id: str = Field(min_length=1, max_length=48)
    kind: Literal["text", "password", "multiline"]
    attributes: ViewerFieldAttributes = Field(repr=False)
    value: str = Field(max_length=32768, repr=False)

    @field_validator("attributes", mode="before")
    @classmethod
    def validate_attributes(cls, value: object) -> ViewerFieldAttributes:
        return decode_viewer_field_attributes(value)

    @model_validator(mode="after")
    def validate_kind(self) -> "_FieldValue":
        if viewer_field_kind(self.attributes) != self.kind:
            raise ValueError("Inconsistent Browser native field kind")
        return self


_SERVER_MESSAGE = TypeAdapter(
    Annotated[_Status | _InputAck | _FieldValue, Field(discriminator="type")]
)


def unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate JSON fields before typed socket ingress decoding."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate Browser message field")
        result[key] = value
    return result


@dataclass
class _FieldRead:
    sequence: int
    editable_id: str
    navigation_id: str
    delivered: bool


@dataclass
class _SocketProgress:
    attachment_id: str | None
    last_frame_sequence: int
    last_input_sequence: int
    last_ack_sequence: int
    field_read: _FieldRead | None


@dataclass
class _RateBudget:
    updated_at: float
    messages: float
    size: float

    def consume(self, size: int, now: float) -> None:
        elapsed = max(0.0, now - self.updated_at)
        self.updated_at = now
        self.messages = min(120.0, self.messages + elapsed * 120.0)
        self.size = min(256 * 1024.0, self.size + elapsed * 256 * 1024.0)
        if self.messages < 1 or self.size < size:
            raise BrowserSocketFailure(4429, "Browser message rate exceeded")
        self.messages -= 1
        self.size -= size


@dataclass
class RuntimeBrowserSocketService:
    scope_validator: DatabaseRuntimeBrowserStreamScopeValidator
    source_client: RuntimeBrowserSourceClient | None
    clock: Callable[[], datetime]
    monotonic_clock: Callable[[], float]

    async def serve(
        self,
        *,
        socket: RuntimeBrowserWebSocket,
        resource: RuntimeBrowserResource,
        user_id: str,
        authentication_session_id: str,
        target: ViewerTarget,
    ) -> None:
        try:
            async with asyncio.timeout(5):
                admitted = await self.scope_validator.admit(
                    resource=resource,
                    user_id=user_id,
                    authentication_session_id=authentication_session_id,
                    target=target,
                )
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            raise BrowserSocketFailure(4408, "Browser admission timed out") from None
        except RuntimeBrowserStreamUnavailable:
            raise BrowserSocketFailure(4500, "Browser is unavailable") from None
        except RuntimeBrowserTargetUnavailable:
            raise BrowserSocketFailure(4409, "Browser target is stale") from None
        except RuntimeBrowserRequestError as error:
            raise BrowserSocketFailure(
                4401 if error.status_code == 401 else 4403,
                "Browser access is unavailable",
            ) from None
        except RuntimeBrowserOperationError:
            raise BrowserSocketFailure(4500, "Browser admission failed") from None
        if self.source_client is None:
            raise BrowserSocketFailure(4500, "Browser source is unavailable")
        now = self.clock()
        deadline = min(
            now + timedelta(hours=1), admitted.authentication_session_expires_at
        )
        if deadline <= now:
            raise BrowserSocketFailure(4408, "Browser authority expired")
        authority = BrowserStreamAuthority(
            correlation_id=uuid.uuid4().hex,
            authentication_session_id=authentication_session_id,
            user_id=user_id,
            agent_id=resource.agent_id,
            runtime_id=admitted.target.id,
            desired_generation=admitted.target.desired_generation,
            runner_generation=admitted.target.runner_generation,
            open_deadline_at=min(now + timedelta(seconds=10), deadline),
            transport_deadline_at=deadline,
            session_id=resource.session_id,
            task_id=target.task_id,
            page_id=target.page_id,
            resource_incarnation=target.resource_incarnation,
            allow_input=admitted.allow_input,
        )
        connection: RuntimeBrowserStreamConnection | None = None
        tasks: list[asyncio.Task[None]] = []
        try:
            async with asyncio.timeout(
                (authority.open_deadline_at - now).total_seconds()
            ):
                connection = await self.source_client.connect(authority=authority)
            await self._live(authority)
            progress = _SocketProgress(None, 0, 0, 0, None)
            tasks = [
                asyncio.create_task(
                    self._receive_client(socket, connection, authority, progress)
                ),
                asyncio.create_task(
                    self._send_client(socket, connection, authority, progress)
                ),
                asyncio.create_task(self._monitor(authority)),
            ]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            raise BrowserSocketFailure(4408, "Browser source timed out") from None
        except BrowserSourceScopeRevoked as error:
            raise BrowserSocketFailure(
                {
                    "unauthenticated": 4401,
                    "access_revoked": 4403,
                    "expired": 4408,
                    "stale_target": 4409,
                }[error.reason],
                "Browser source authority is unavailable",
            ) from None
        except BrowserSourceError:
            raise BrowserSocketFailure(4500, "Browser source is unavailable") from None
        finally:
            for task in tasks:
                task.cancel()
            try:
                if tasks:
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    for result in results:
                        if isinstance(result, BaseException) and not isinstance(
                            result,
                            (
                                asyncio.CancelledError,
                                BrowserSocketFailure,
                                BrowserSourceError,
                                WebSocketDisconnect,
                            ),
                        ):
                            raise result
            finally:
                if connection is not None:
                    try:
                        async with asyncio.timeout(5):
                            await connection.close()
                    except asyncio.CancelledError:
                        raise
                    except BrowserSourceError, TimeoutError:
                        raise BrowserSocketFailure(
                            4500, "Browser source cleanup failed"
                        ) from None

    async def _live(self, authority: BrowserStreamAuthority) -> None:
        if self.clock() >= authority.transport_deadline_at:
            raise BrowserSocketFailure(4408, "Browser authority expired")
        try:
            async with asyncio.timeout(2.5):
                valid = await self.scope_validator(authority)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            raise BrowserSocketFailure(
                4403, "Browser access revalidation failed"
            ) from None
        if valid is BrowserScopeState.UNAVAILABLE:
            raise BrowserSocketFailure(4500, "Browser connection authority changed")
        if valid is BrowserScopeState.EXPIRED:
            raise BrowserSocketFailure(4408, "Browser authority expired")
        if valid is not BrowserScopeState.CURRENT:
            raise BrowserSocketFailure(4403, "Browser access was revoked")
        if self.clock() >= authority.transport_deadline_at:
            raise BrowserSocketFailure(4408, "Browser authority expired")

    async def _monitor(self, authority: BrowserStreamAuthority) -> None:
        while True:
            remaining = (authority.transport_deadline_at - self.clock()).total_seconds()
            if remaining <= 0:
                raise BrowserSocketFailure(4408, "Browser authority expired")
            await asyncio.sleep(min(2.5, remaining))
            await self._live(authority)

    async def _receive_client(
        self,
        socket: RuntimeBrowserWebSocket,
        connection: RuntimeBrowserStreamConnection,
        authority: BrowserStreamAuthority,
        progress: _SocketProgress,
    ) -> None:
        budget = _RateBudget(self.monotonic_clock(), 120.0, 256 * 1024.0)
        while True:
            message = await socket.receive()
            if message.get("type") == "websocket.disconnect":
                raise WebSocketDisconnect()
            text = message.get("text")
            if message.get("type") != "websocket.receive" or not isinstance(text, str):
                raise BrowserSocketFailure(4400, "Browser text message required")
            data = text.encode()
            budget.consume(len(data), self.monotonic_clock())
            try:
                request = decode_viewer_request(data)
            except BrowserViewerContractError:
                raise BrowserSocketFailure(4400, "Invalid Browser message") from None
            if request.attachment_id != progress.attachment_id:
                raise BrowserSocketFailure(4409, "Browser attachment is stale")
            if isinstance(request, ViewerFrameAck):
                if request.frame_sequence > progress.last_frame_sequence:
                    raise BrowserSocketFailure(
                        4400, "Browser frame acknowledgement is invalid"
                    )
            elif isinstance(request, ViewerInput):
                if not authority.allow_input:
                    raise BrowserSocketFailure(4403, "Browser is read-only")
                if request.sequence <= progress.last_input_sequence:
                    raise BrowserSocketFailure(
                        4400, "Browser input sequence is invalid"
                    )
                await self._live(authority)
                progress.last_input_sequence = request.sequence
                if isinstance(request.action, ViewerFieldOpen):
                    if request.source is None:
                        raise BrowserSocketFailure(4400, "Invalid Browser field source")
                    progress.field_read = _FieldRead(
                        request.sequence,
                        request.action.editable_id,
                        request.source.navigation_id,
                        False,
                    )
            await connection.send_websocket(opcode=WebSocketOpcode.TEXT, payload=data)

    async def _send_client(
        self,
        socket: RuntimeBrowserWebSocket,
        connection: RuntimeBrowserStreamConnection,
        authority: BrowserStreamAuthority,
        progress: _SocketProgress,
    ) -> None:
        target = ViewerTarget(
            authority.task_id, authority.page_id, authority.resource_incarnation
        )
        while True:
            message = await connection.receive_websocket()
            if self.clock() >= authority.transport_deadline_at:
                raise BrowserSocketFailure(4408, "Browser authority expired")
            if message.opcode is WebSocketOpcode.BINARY:
                try:
                    frame = decode_viewer_frame(message.payload)
                except BrowserViewerContractError:
                    raise BrowserSocketFailure(4500, "Invalid Browser frame") from None
                if (
                    frame.target != target
                    or frame.attachment_id != progress.attachment_id
                ):
                    raise BrowserSocketFailure(4409, "Browser frame scope changed")
                if frame.source.frame_sequence <= progress.last_frame_sequence:
                    raise BrowserSocketFailure(
                        4500, "Browser frame sequence is invalid"
                    )
                progress.last_frame_sequence = frame.source.frame_sequence
                async with asyncio.timeout(10):
                    await socket.send_bytes(message.payload)
            elif message.opcode is WebSocketOpcode.TEXT:
                if len(message.payload) > MAX_VIEWER_TEXT_BYTES:
                    raise BrowserSocketFailure(
                        4500, "Browser metadata exceeds its bound"
                    )
                try:
                    json.loads(message.payload, object_pairs_hook=unique_json_object)
                    metadata = _SERVER_MESSAGE.validate_json(message.payload)
                except ValueError, ValidationError:
                    raise BrowserSocketFailure(
                        4500, "Invalid Browser metadata"
                    ) from None
                if isinstance(metadata, _Status):
                    opened = metadata.opened_target
                    if opened is not None and (
                        opened.task_id != target.task_id
                        or opened.resource_incarnation != target.resource_incarnation
                    ):
                        raise BrowserSocketFailure(4409, "Browser popup scope changed")
                    if (
                        metadata.target.task_id,
                        metadata.target.page_id,
                        metadata.target.resource_incarnation,
                    ) != (
                        target.task_id,
                        target.page_id,
                        target.resource_incarnation,
                    ) or metadata.allow_input != authority.allow_input:
                        raise BrowserSocketFailure(4403, "Browser scope changed")
                    if progress.attachment_id is None:
                        progress.attachment_id = metadata.attachment_id
                    if progress.attachment_id != metadata.attachment_id:
                        raise BrowserSocketFailure(4409, "Browser attachment changed")
                    if progress.field_read is not None and (
                        metadata.navigation_id != progress.field_read.navigation_id
                        or metadata.state != "connected"
                        or metadata.dialog is not None
                    ):
                        progress.field_read = None
                elif isinstance(metadata, _FieldValue):
                    read = progress.field_read
                    if (
                        not authority.allow_input
                        or metadata.attachment_id != progress.attachment_id
                        or read is None
                        or read.delivered
                        or metadata.sequence != read.sequence
                        or metadata.editable_id != read.editable_id
                        or metadata.sequence <= progress.last_ack_sequence
                    ):
                        raise BrowserSocketFailure(
                            4500, "Invalid Browser private field response"
                        )
                    await self._live(authority)
                    read.delivered = True
                elif (
                    metadata.attachment_id != progress.attachment_id
                    or not progress.last_ack_sequence
                    < metadata.sequence
                    <= progress.last_input_sequence
                ):
                    raise BrowserSocketFailure(
                        4500, "Invalid Browser input acknowledgement"
                    )
                else:
                    progress.last_ack_sequence = metadata.sequence
                    if (
                        progress.field_read is not None
                        and metadata.sequence >= progress.field_read.sequence
                    ):
                        progress.field_read = None
                async with asyncio.timeout(10):
                    await socket.send_text(message.payload.decode())
                if isinstance(metadata, _Status) and metadata.state != "connected":
                    raise BrowserSocketFailure(
                        1000 if metadata.state == "closed" else 4500,
                        "Browser page closed"
                        if metadata.state == "closed"
                        else "Browser is unavailable",
                    )
            else:
                raise BrowserSocketFailure(4500, "Invalid Browser source message")
