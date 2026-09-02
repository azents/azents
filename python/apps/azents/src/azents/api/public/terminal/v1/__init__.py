"""Public Runtime Terminal v1 REST and WebSocket API."""

import asyncio
import dataclasses
import json
import time
from collections.abc import AsyncIterator, Mapping
from textwrap import dedent
from typing import Annotated, Any, NoReturn, Protocol, assert_never

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ValidationError

from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.services.runtime_terminal.data import (
    RuntimeTerminalAttachment,
    RuntimeTerminalAttachRequest,
    RuntimeTerminalErrorEvent,
    RuntimeTerminalExited,
    RuntimeTerminalInputAcknowledged,
    RuntimeTerminalOutput,
    RuntimeTerminalReasonCode,
    RuntimeTerminalResource,
    RuntimeTerminalRevoked,
    RuntimeTerminalServerEvent,
    RuntimeTerminalSocketAdmission,
    RuntimeTerminalStatusChanged,
)
from azents.services.runtime_terminal.deps import (
    get_runtime_terminal_service,
    get_runtime_terminal_web_origin,
)
from azents.services.runtime_terminal.service import (
    RuntimeTerminalAdmissionError,
    RuntimeTerminalService,
)
from azents.utils.fastapi.route import RouteMounter

from .data import (
    TERMINAL_CLIENT_CONTROL_ADAPTER,
    RuntimeTerminalProjectionResponse,
    RuntimeTerminalTicketResponse,
    TerminalAcceptedControl,
    TerminalAttachControl,
    TerminalClientControl,
    TerminalErrorControl,
    TerminalExitControl,
    TerminalHeartbeatAckControl,
    TerminalHeartbeatControl,
    TerminalInputAckControl,
    TerminalOutputAckControl,
    TerminalReplayBeginControl,
    TerminalReplayEndControl,
    TerminalReplayTruncatedControl,
    TerminalResizeControl,
    TerminalRevokedControl,
    TerminalStatusControl,
    TerminalTerminateControl,
)
from .wire import (
    TERMINAL_WEBSOCKET_SUBPROTOCOL,
    RuntimeTerminalBinaryFrameInvalid,
    encode_terminal_output_frame,
    parse_terminal_input_frame,
)

router = APIRouter()

_MAX_CONTROL_BYTES = 4 * 1024
_CONTROL_RATE_PER_SECOND = 20.0
_CONTROL_RATE_BURST = 20.0
_INPUT_RATE_BYTES_PER_SECOND = 256 * 1024.0
_INPUT_RATE_BURST_BYTES = 64 * 1024.0
_REVALIDATION_SECONDS = 5.0
_SLOW_CONSUMER_SECONDS = 30.0
_ATTACH_TIMEOUT_SECONDS = 10.0

_CLOSE_PROTOCOL = 4400
_CLOSE_UNAUTHENTICATED = 4401
_CLOSE_REVOKED = 4403
_CLOSE_TIMEOUT = 4408
_CLOSE_RESOURCE_EXHAUSTED = 4429
_CLOSE_UNAVAILABLE = 4500


@router.get(
    "/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}",
    response_model=RuntimeTerminalProjectionResponse,
)
async def get_terminal_projection(
    handle: str,
    agent_id: str,
    session_id: str,
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[RuntimeTerminalService, Depends(get_runtime_terminal_service)],
) -> RuntimeTerminalProjectionResponse:
    """Return current Terminal availability without starting the Runtime."""
    projection = await service.projection(
        user_id=member.user_id,
        authentication_session_id=member.session_id,
        resource=RuntimeTerminalResource(
            workspace_handle=handle,
            agent_id=agent_id,
            session_id=session_id,
        ),
    )
    return RuntimeTerminalProjectionResponse.convert_from(projection)


@router.post(
    "/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}/ticket",
    response_model=RuntimeTerminalTicketResponse,
)
async def issue_terminal_ticket(
    handle: str,
    agent_id: str,
    session_id: str,
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[RuntimeTerminalService, Depends(get_runtime_terminal_service)],
) -> RuntimeTerminalTicketResponse:
    """Issue a one-time resource-bound ticket without Runtime auto-start."""
    result = await service.issue_ticket(
        user_id=member.user_id,
        authentication_session_id=member.session_id,
        resource=RuntimeTerminalResource(
            workspace_handle=handle,
            agent_id=agent_id,
            session_id=session_id,
        ),
    )
    return RuntimeTerminalTicketResponse.convert_from(result)


@router.websocket("/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}/ws")
async def terminal_websocket(
    websocket: WebSocket,
    handle: str,
    agent_id: str,
    session_id: str,
    service: Annotated[RuntimeTerminalService, Depends(get_runtime_terminal_service)],
    expected_origin: Annotated[str, Depends(get_runtime_terminal_web_origin)],
) -> None:
    """Run one dedicated resource-bound Terminal WebSocket."""
    resource = RuntimeTerminalResource(
        workspace_handle=handle,
        agent_id=agent_id,
        session_id=session_id,
    )
    ticket = websocket.query_params.get("ticket")
    websocket.scope["query_string"] = b""
    if websocket.headers.get("origin") != expected_origin:
        await _close_unaccepted(
            websocket,
            code=_CLOSE_REVOKED,
            reason="Terminal WebSocket origin is not allowed",
        )
        return
    if TERMINAL_WEBSOCKET_SUBPROTOCOL not in websocket.scope.get("subprotocols", []):
        await _close_unaccepted(
            websocket,
            code=_CLOSE_PROTOCOL,
            reason="Terminal WebSocket subprotocol is required",
        )
        return
    if ticket is None:
        await _close_unaccepted(
            websocket,
            code=_CLOSE_UNAUTHENTICATED,
            reason="Terminal ticket is required",
        )
        return
    try:
        admission = await service.consume_ticket(ticket=ticket, resource=resource)
    except RuntimeTerminalAdmissionError:
        await _close_unaccepted(
            websocket,
            code=_CLOSE_UNAUTHENTICATED,
            reason="Terminal ticket is invalid or unavailable",
        )
        return
    await websocket.accept(subprotocol=TERMINAL_WEBSOCKET_SUBPROTOCOL)
    try:
        try:
            async with asyncio.timeout(_ATTACH_TIMEOUT_SECONDS):
                attach = await _receive_attach(websocket)
        except TimeoutError:
            await websocket.close(
                code=_CLOSE_TIMEOUT,
                reason="Terminal attach control timed out",
            )
            return
        revoked = await service.revalidate(admission)
        if revoked is not None:
            raise RuntimeTerminalAdmissionError(revoked)
        attachment = await service.attach(
            admission,
            RuntimeTerminalAttachRequest(
                columns=attach.columns,
                rows=attach.rows,
                last_output_sequence=attach.last_output_sequence,
            ),
        )
    except RuntimeTerminalAdmissionError as error:
        await websocket.close(
            code=_close_code(error.reason_code),
            reason="Terminal is unavailable",
        )
        return
    except _TerminalSocketProtocolError as error:
        await websocket.close(code=error.code, reason=error.reason)
        return
    await _send_initial_state(websocket, attachment)
    await _run_terminal_socket(websocket, service, admission, attachment)


def mount(mounter: RouteMounter) -> None:
    """Mount Public Runtime Terminal v1 routes."""
    mounter(
        router,
        prefix="/terminal/v1",
        tag="Terminal v1",
        description=dedent(
            """
            Runtime Terminal API (Public)

            Session-owned interactive Terminal projection, ticket, and dedicated
            WebSocket transport for managed Agent Runtimes.
            """
        ),
    )


@dataclasses.dataclass
class _SocketProgress:
    """Bounded socket flow-control progress."""

    highest_output_sent: int
    highest_output_acknowledged: int
    output_acknowledged_at: float
    changed: asyncio.Event


class _TerminalSocketProtocolError(RuntimeError):
    def __init__(self, *, code: int, reason: str) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason


class _TerminalSocketComplete(Exception):
    """Signal normal Terminal socket completion after the final control."""


class _TerminalWebSocket(Protocol):
    async def accept(self, subprotocol: str | None = None) -> None: ...

    async def close(self, code: int = 1000, reason: str | None = None) -> None: ...

    async def receive(self) -> Mapping[str, Any]: ...

    async def send_text(self, data: str) -> None: ...

    async def send_bytes(self, data: bytes) -> None: ...


class _TokenBucket:
    def __init__(self, *, rate: float, burst: float) -> None:
        self.rate = rate
        self.burst = burst
        self.tokens = burst
        self.updated_at = time.monotonic()

    def consume(self, amount: float) -> bool:
        now = time.monotonic()
        self.tokens = min(
            self.burst,
            self.tokens + (now - self.updated_at) * self.rate,
        )
        self.updated_at = now
        if amount > self.tokens:
            return False
        self.tokens -= amount
        return True


async def _receive_attach(websocket: _TerminalWebSocket) -> TerminalAttachControl:
    message = await websocket.receive()
    text = message.get("text")
    if not isinstance(text, str) or len(text.encode()) > _MAX_CONTROL_BYTES:
        raise _TerminalSocketProtocolError(
            code=_CLOSE_PROTOCOL,
            reason="Terminal attach control is invalid",
        )
    try:
        return TerminalAttachControl.model_validate_json(text)
    except ValidationError as error:
        raise _TerminalSocketProtocolError(
            code=_CLOSE_PROTOCOL,
            reason="Terminal attach control is invalid",
        ) from error


async def _send_initial_state(
    websocket: _TerminalWebSocket,
    attachment: RuntimeTerminalAttachment,
) -> None:
    accepted = attachment.accepted
    await _send_control(websocket, TerminalAcceptedControl.convert_from(accepted))
    await _send_control(
        websocket,
        TerminalReplayBeginControl(
            minimum_sequence=accepted.replay_min_sequence,
            maximum_sequence=accepted.replay_max_sequence,
        ),
    )
    if accepted.replay_truncated:
        await _send_control(
            websocket,
            TerminalReplayTruncatedControl(
                minimum_sequence=accepted.replay_min_sequence
            ),
        )
    for output in attachment.replay():
        await websocket.send_bytes(
            encode_terminal_output_frame(sequence=output.sequence, data=output.data)
        )
    await _send_control(
        websocket,
        TerminalReplayEndControl(maximum_sequence=accepted.replay_max_sequence),
    )


async def _run_terminal_socket(
    websocket: _TerminalWebSocket,
    service: RuntimeTerminalService,
    admission: RuntimeTerminalSocketAdmission,
    attachment: RuntimeTerminalAttachment,
) -> None:
    progress = _SocketProgress(
        highest_output_sent=attachment.accepted.replay_max_sequence,
        highest_output_acknowledged=0,
        output_acknowledged_at=time.monotonic(),
        changed=asyncio.Event(),
    )
    receive_task = asyncio.create_task(
        _receive_loop(websocket, attachment, progress),
        name=f"terminal-browser-receive:{attachment.accepted.terminal_id}",
    )
    send_task = asyncio.create_task(
        _send_loop(websocket, attachment, progress),
        name=f"terminal-browser-send:{attachment.accepted.terminal_id}",
    )
    revalidate_task = asyncio.create_task(
        _revalidate_loop(websocket, service, admission, attachment),
        name=f"terminal-browser-revalidate:{attachment.accepted.terminal_id}",
    )
    slow_task = asyncio.create_task(
        _slow_consumer_loop(progress),
        name=f"terminal-browser-slow:{attachment.accepted.terminal_id}",
    )
    tasks = (receive_task, send_task, revalidate_task, slow_task)
    try:
        done, _pending = await asyncio.wait(
            tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in done:
            task.result()
    except WebSocketDisconnect:
        pass
    except _TerminalSocketComplete:
        await websocket.close(reason="Terminal exited")
    except _TerminalSocketProtocolError as error:
        await websocket.close(code=error.code, reason=error.reason)
    except RuntimeTerminalAdmissionError as error:
        await websocket.close(
            code=_close_code(error.reason_code),
            reason="Terminal authority is unavailable",
        )
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await attachment.close()


async def _receive_loop(
    websocket: _TerminalWebSocket,
    attachment: RuntimeTerminalAttachment,
    progress: _SocketProgress,
) -> None:
    control_rate = _TokenBucket(
        rate=_CONTROL_RATE_PER_SECOND,
        burst=_CONTROL_RATE_BURST,
    )
    input_rate = _TokenBucket(
        rate=_INPUT_RATE_BYTES_PER_SECOND,
        burst=_INPUT_RATE_BURST_BYTES,
    )
    async for message in _websocket_messages(websocket):
        data = message.get("bytes")
        if isinstance(data, bytes):
            try:
                frame = parse_terminal_input_frame(data)
            except RuntimeTerminalBinaryFrameInvalid as error:
                raise _TerminalSocketProtocolError(
                    code=_CLOSE_PROTOCOL,
                    reason="Terminal input frame is invalid",
                ) from error
            if not input_rate.consume(len(frame.data)):
                raise _TerminalSocketProtocolError(
                    code=_CLOSE_RESOURCE_EXHAUSTED,
                    reason="Terminal input rate is exceeded",
                )
            await attachment.input(sequence=frame.sequence, data=frame.data)
            continue
        text = message.get("text")
        if not isinstance(text, str) or len(text.encode()) > _MAX_CONTROL_BYTES:
            raise _TerminalSocketProtocolError(
                code=_CLOSE_PROTOCOL,
                reason="Terminal control is invalid",
            )
        if not control_rate.consume(1):
            raise _TerminalSocketProtocolError(
                code=_CLOSE_RESOURCE_EXHAUSTED,
                reason="Terminal control rate is exceeded",
            )
        try:
            control: TerminalClientControl = (
                TERMINAL_CLIENT_CONTROL_ADAPTER.validate_json(text)
            )
        except (ValidationError, json.JSONDecodeError) as error:
            raise _TerminalSocketProtocolError(
                code=_CLOSE_PROTOCOL,
                reason="Terminal control is invalid",
            ) from error
        match control:
            case TerminalResizeControl():
                await attachment.resize(
                    sequence=control.sequence,
                    columns=control.columns,
                    rows=control.rows,
                )
            case TerminalOutputAckControl():
                await attachment.acknowledge_output(sequence=control.sequence)
                progress.highest_output_acknowledged = max(
                    progress.highest_output_acknowledged,
                    control.sequence,
                )
                progress.output_acknowledged_at = time.monotonic()
                progress.changed.set()
            case TerminalHeartbeatControl():
                await attachment.heartbeat(sequence=control.sequence)
                await _send_control(
                    websocket,
                    TerminalHeartbeatAckControl(sequence=control.sequence),
                )
            case TerminalTerminateControl():
                await attachment.terminate()
                # Keep the receive side alive until the send loop delivers the
                # asynchronous Runner exit event and owns socket completion.
                await asyncio.Future()
            case _ as unreachable:
                assert_never(unreachable)


async def _send_loop(
    websocket: _TerminalWebSocket,
    attachment: RuntimeTerminalAttachment,
    progress: _SocketProgress,
) -> None:
    async for event in attachment.events():
        await _send_server_event(websocket, event, progress)


async def _send_server_event(
    websocket: _TerminalWebSocket,
    event: RuntimeTerminalServerEvent,
    progress: _SocketProgress,
) -> None:
    match event:
        case RuntimeTerminalOutput():
            await websocket.send_bytes(
                encode_terminal_output_frame(sequence=event.sequence, data=event.data)
            )
            progress.highest_output_sent = event.sequence
            progress.changed.set()
        case RuntimeTerminalInputAcknowledged():
            await _send_control(
                websocket,
                TerminalInputAckControl(sequence=event.sequence),
            )
        case RuntimeTerminalStatusChanged():
            await _send_control(
                websocket,
                TerminalStatusControl(
                    lifecycle=event.lifecycle,
                    reason=event.reason,
                ),
            )
        case RuntimeTerminalExited():
            await _send_control(
                websocket,
                TerminalExitControl(reason=event.reason, exit_code=event.exit_code),
            )
            raise _TerminalSocketComplete
        case RuntimeTerminalRevoked():
            await _send_control(
                websocket,
                TerminalRevokedControl(reason_code=event.reason_code),
            )
            raise _TerminalSocketProtocolError(
                code=_CLOSE_REVOKED,
                reason="Terminal authority is revoked",
            )
        case RuntimeTerminalErrorEvent():
            await _send_control(websocket, TerminalErrorControl(code=event.code))
        case _ as unreachable:
            assert_never(unreachable)


async def _revalidate_loop(
    websocket: _TerminalWebSocket,
    service: RuntimeTerminalService,
    admission: RuntimeTerminalSocketAdmission,
    attachment: RuntimeTerminalAttachment,
) -> None:
    while True:
        await asyncio.sleep(_REVALIDATION_SECONDS)
        reason = await service.revalidate(admission)
        if reason is not None:
            try:
                await _send_control(
                    websocket,
                    TerminalRevokedControl(reason_code=reason),
                )
            finally:
                await attachment.revoke(reason)
            raise _TerminalSocketProtocolError(
                code=_CLOSE_REVOKED,
                reason="Terminal authority is revoked",
            )


async def _slow_consumer_loop(progress: _SocketProgress) -> None:
    while True:
        progress.changed.clear()
        if progress.highest_output_sent <= progress.highest_output_acknowledged:
            await progress.changed.wait()
            continue
        remaining = (
            progress.output_acknowledged_at + _SLOW_CONSUMER_SECONDS - time.monotonic()
        )
        if remaining <= 0:
            raise _TerminalSocketProtocolError(
                code=_CLOSE_TIMEOUT,
                reason="Terminal output acknowledgement timed out",
            )
        try:
            await asyncio.wait_for(progress.changed.wait(), timeout=remaining)
        except TimeoutError:
            raise _TerminalSocketProtocolError(
                code=_CLOSE_TIMEOUT,
                reason="Terminal output acknowledgement timed out",
            ) from None


async def _websocket_messages(
    websocket: _TerminalWebSocket,
) -> AsyncIterator[Mapping[str, Any]]:
    while True:
        message = await websocket.receive()
        if message.get("type") == "websocket.disconnect":
            raise WebSocketDisconnect
        yield message


async def _send_control(websocket: _TerminalWebSocket, control: BaseModel) -> None:
    payload = control.model_dump_json()
    if len(payload.encode()) > _MAX_CONTROL_BYTES:
        raise RuntimeError("Terminal server control exceeds the wire bound")
    await websocket.send_text(payload)


async def _close_unaccepted(
    websocket: _TerminalWebSocket,
    *,
    code: int,
    reason: str,
) -> None:
    await websocket.accept()
    await websocket.close(code=code, reason=reason)


def _close_code(reason: RuntimeTerminalReasonCode) -> int:
    if reason in {
        RuntimeTerminalReasonCode.SESSION_LIMIT,
        RuntimeTerminalReasonCode.USER_LIMIT,
        RuntimeTerminalReasonCode.RUNTIME_LIMIT,
    }:
        return _CLOSE_RESOURCE_EXHAUSTED
    if reason in {
        RuntimeTerminalReasonCode.ACCESS_DENIED,
        RuntimeTerminalReasonCode.TERMINAL_DISABLED,
    }:
        return _CLOSE_REVOKED
    return _CLOSE_UNAVAILABLE


def _raise_protocol(*, code: int, reason: str) -> NoReturn:
    raise _TerminalSocketProtocolError(code=code, reason=reason)
