"""Chat v1 Public API.

WebSocket chat and REST message lookup endpoints.
"""

import asyncio
import io
import logging
import re
from collections.abc import AsyncIterator
from datetime import datetime
from textwrap import dedent
from typing import Annotated, NoReturn, assert_never
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from azcommon.result import Failure, Result, Success
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import StreamingResponse

from azents.broker.broadcast import WebSocketBroadcast
from azents.broker.deps import get_broker
from azents.broker.serialization import serialize_event
from azents.broker.types import (
    SessionBroker,
    SessionStopSignal,
    SessionWakeUp,
)
from azents.core.auth.deps import (
    CurrentUser,
    WorkspaceMember,
    get_current_user,
    get_workspace_member,
)
from azents.core.auth.jwt import (
    ExpiredTokenError,
    InvalidTokenError,
    create_ws_ticket,
    verify_ws_ticket,
)
from azents.core.config import AuthConfig, Config
from azents.core.deps import get_appctx, get_auth_config
from azents.core.redis import create_redis_client
from azents.engine.run.commands import COMMAND_REGISTRY, list_registered_commands
from azents.engine.run.input import InputMessage
from azents.engine.run.resolve import (
    materialize_user_input_exchange_file_attachments,
)
from azents.services.agent_session_input import (
    AgentSessionInputError,
    AgentSessionInputInactiveSession,
    AgentSessionInputService,
    AgentSessionInputSessionNotFound,
    AgentSessionInputWrongAgent,
    BufferedAgentSessionInputResult,
)
from azents.services.chat import ChatSessionService
from azents.services.chat.context import SessionContextService
from azents.services.chat.data import (
    AgentNotFound,
    DeleteInputBufferError,
    DeleteSessionError,
    EnsureSessionInput,
    InvalidGoalStatusTransition,
    NotWorkspaceMember,
    SessionAccessDenied,
    SessionNotFound,
    UpdateGoalStatusInput,
)
from azents.services.chat.live_events import (
    LiveEventStore,
    get_live_event_store,
    input_buffer_to_live_event,
)
from azents.services.chat.workspace import (
    AgentWorkspaceDirectory,
    AgentWorkspaceError,
    AgentWorkspaceFile,
    AgentWorkspaceFileNotFound,
    AgentWorkspaceFileReadError,
    AgentWorkspaceFileResult,
    AgentWorkspaceFileService,
    AgentWorkspaceFileTooLarge,
    AgentWorkspacePathDenied,
    AgentWorkspacePathUnavailable,
    AgentWorkspaceRuntimeInactive,
    AgentWorkspaceState,
)
from azents.services.chat_write import ChatWriteService
from azents.services.exchange_file import (
    ExchangeFileError,
    ExchangeFileService,
    FileAccessDenied,
    FileExpired,
    FileNotFound,
    FileUnavailable,
)
from azents.services.exchange_file import (
    SessionNotFound as ExchangeSessionNotFound,
)
from azents.services.model_file import ModelFileService
from azents.services.session_storage import guess_media_type
from azents.services.session_workspace_project import (
    AgentNotFound as ProjectAgentNotFound,
)
from azents.services.session_workspace_project import (
    InvalidProjectPath,
    ProjectAccessDenied,
    ProjectNotFound,
    ProjectPathConflict,
    RegistrationRequestAlreadyResolved,
    RegistrationRequestNotFound,
    SessionWorkspaceProjectService,
)
from azents.transport.chat import (
    chat_history_event_appended_dump,
    chat_live_event_removed_dump,
    chat_live_event_upserted_dump,
    chat_subscription_ack_dump,
    chat_subscription_health_check_ack_dump,
)
from azents.utils.appctx import AppContext
from azents.utils.fastapi.route import RouteMounter

from .data import (
    AgentSessionListResponse,
    AgentSessionResponse,
    AgentWorkspaceActionResponse,
    AgentWorkspaceDirectoryResponse,
    AgentWorkspaceFileResponse,
    AgentWorkspaceFileResponseUnion,
    AgentWorkspaceInactiveErrorResponse,
    AgentWorkspaceResponse,
    ChatCommandWriteRequest,
    ChatEditMessageWriteRequest,
    ChatEventPageResponse,
    ChatEventResponse,
    ChatLiveRunStateResponse,
    ChatMessageWriteRequest,
    ChatStopResponse,
    ChatWriteAcceptedResponse,
    ChatWriteResponse,
    ChatWriteSnapshotResponse,
    GoalStateResponse,
    GoalStatusUpdateRequest,
    GoalUpdateRequest,
    LiveEventListResponse,
    PartialHistoryResponse,
    SessionContextResponse,
    SessionWorkspaceProjectListResponse,
    SessionWorkspaceProjectRegisterRequest,
    SessionWorkspaceProjectRegistrationRequestListResponse,
    SessionWorkspaceProjectRegistrationRequestResponse,
    SessionWorkspaceProjectResponse,
    SlashCommandListResponse,
    SlashCommandResponse,
    TodoStateResponse,
    UploadResponse,
    WsTicketResponse,
)

logger = logging.getLogger(__name__)


_SESSION_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


def _validate_session_id(session_id: str) -> None:
    """Validate session_id format to prevent path traversal.

    :param session_id: Session ID to validate
    :raises HTTPException: If the format is invalid
    """
    if not _SESSION_ID_PATTERN.match(session_id):
        raise HTTPException(status_code=400, detail="Invalid session ID format.")


def _validate_uuid7_hex(value: str, *, label: str) -> None:
    """Validate uuid7 hex path parameter format."""
    if not _SESSION_ID_PATTERN.match(value):
        raise HTTPException(status_code=400, detail=f"Invalid {label} format.")


router = APIRouter()


async def get_ws_broadcast(
    appctx: Annotated[AppContext[Config], Depends(get_appctx)],
) -> WebSocketBroadcast:
    """WebSocketBroadcast dependency for Web API, cached by AppContext."""

    async def create() -> AsyncIterator[WebSocketBroadcast]:
        redis = create_redis_client(appctx.config.redis.url)
        broadcast = WebSocketBroadcast(redis)
        try:
            yield broadcast
        finally:
            await redis.aclose()

    return await appctx.get_variable(f"{__name__}.get_ws_broadcast", create)


# ---------------------------------------------------------------------------
# WebSocket authentication
# ---------------------------------------------------------------------------


async def _authenticate_websocket(
    websocket: WebSocket,
    auth_config: AuthConfig,
) -> CurrentUser | None:
    """Extract and authenticate an HMAC ticket from WebSocket query parameters.

    If authentication fails after accept(), close normally with close().
    Avoid raising before accept(), because uvicorn logs that as ERROR.

    :param websocket: WebSocket connection
    :param auth_config: Authentication settings
    :return: Authenticated user info, or None on authentication failure
    """
    ticket = websocket.query_params.get("ticket")
    if ticket is None:
        await websocket.accept()
        await websocket.close(code=4001, reason="Missing ticket")
        return None
    try:
        payload = verify_ws_ticket(auth_config.jwt, ticket)
    except ExpiredTokenError, InvalidTokenError:
        await websocket.accept()
        await websocket.close(code=4003, reason="Invalid ticket")
        return None
    return CurrentUser(
        user_id=payload.user_id,
        session_id=payload.session_id,
    )


# ---------------------------------------------------------------------------
# WebSocket endpoints
# ---------------------------------------------------------------------------


def _parse_timezone(timezone: str | None) -> ZoneInfo:
    """Parse an IANA timezone string. Return UTC when invalid."""
    try:
        return ZoneInfo(timezone) if timezone else ZoneInfo("UTC")
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


async def _run_session_loops(
    websocket: WebSocket,
    broadcast: WebSocketBroadcast,
    *,
    session_id: str,
    send_lock: asyncio.Lock,
) -> None:
    """Run broadcast subscription and send loop for existing sessions."""
    async with broadcast.subscribe(session_id) as events:
        async with send_lock:
            await websocket.send_json(chat_subscription_ack_dump(session_id))
        async for event_json in events:
            async with send_lock:
                await websocket.send_json(event_json)


async def _run_session_receive_loop(
    websocket: WebSocket,
    *,
    session_id: str,
    send_lock: asyncio.Lock,
) -> None:
    """Handle client session control messages."""
    while True:
        message = await websocket.receive_json()
        if not isinstance(message, dict):
            continue
        if message.get("type") != "subscription_health_check":
            continue
        request_id = message.get("request_id")
        async with send_lock:
            await websocket.send_json(
                chat_subscription_health_check_ack_dump(
                    session_id,
                    request_id if isinstance(request_id, str) else None,
                )
            )


@router.websocket("/sessions/{session_id}")
async def chat_websocket(
    websocket: WebSocket,
    session_id: str,
    auth_config: Annotated[AuthConfig, Depends(get_auth_config)],
    chat_service: Annotated[ChatSessionService, Depends()],
    broadcast: Annotated[WebSocketBroadcast, Depends(get_ws_broadcast)],
) -> None:
    """WebSocket endpoint for existing sessions.

    After JWT authentication, subscribes only to live events.
    """
    if not _SESSION_ID_PATTERN.match(session_id):
        await websocket.accept()
        await websocket.close(code=4400, reason="Invalid session ID format.")
        return

    current_user = await _authenticate_websocket(websocket, auth_config)
    if current_user is None:
        return

    # Validate session ownership. Existing sessions are checked; new sessions pass.
    # Agent/session match validation is performed only on writes in
    # _handle_ensure_session.
    # Allow the WS connection itself so azents-web can subscribe to real-time events
    # for AgentSessions linked to external interface input.
    session_result = await chat_service.get_session(
        session_id, user_id=current_user.user_id
    )
    match session_result:
        case Failure(error):
            match error:
                case SessionAccessDenied():
                    await websocket.close(code=4003, reason="Session access denied.")
                    return
                case SessionNotFound():
                    pass  # New session; created by ensure_session
                case _:
                    assert_never(error)
        case Success():
            pass
        case _:
            assert_never(session_result)

    await websocket.accept()

    send_lock = asyncio.Lock()
    send_task = asyncio.create_task(
        _run_session_loops(
            websocket,
            broadcast,
            session_id=session_id,
            send_lock=send_lock,
        )
    )
    receive_task = asyncio.create_task(
        _run_session_receive_loop(
            websocket,
            session_id=session_id,
            send_lock=send_lock,
        )
    )
    try:
        done, pending = await asyncio.wait(
            {send_task, receive_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            task.result()
    except WebSocketDisconnect:
        logger.debug(
            "WebSocket disconnected",
            extra={"session_id": session_id},
        )
    finally:
        for task in (send_task, receive_task):
            if not task.done():
                task.cancel()


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------


@router.post("/ticket")
async def issue_ws_ticket(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    auth_config: Annotated[AuthConfig, Depends(get_auth_config)],
) -> WsTicketResponse:
    """Issue a short-lived HMAC ticket for WebSocket connections.

    After JWT authentication, returns a signed ticket valid for 30 seconds.
    The client connects to WebSocket with this ticket, without exposing the raw JWT.
    """
    ticket = create_ws_ticket(
        auth_config.jwt,
        user_id=current_user.user_id,
        session_id=current_user.session_id,
    )
    return WsTicketResponse(ticket=ticket)


@router.get("/workspaces/{handle}/sessions")
async def list_sessions(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    chat_service: Annotated[ChatSessionService, Depends()],
) -> AgentSessionListResponse:
    """List the current user's conversation sessions in a workspace."""
    sessions = await chat_service.list_sessions(
        user_id=member.user_id,
        workspace_id=member.workspace_id,
    )
    return AgentSessionListResponse(
        items=[
            AgentSessionResponse(
                id=s.id,
                agent_id=s.agent_id,
                created_at=s.created_at,
                updated_at=s.updated_at,
            )
            for s in sessions
        ]
    )


async def _build_chat_write_snapshot(
    chat_service: ChatSessionService,
    live_event_store: LiveEventStore,
    *,
    session_id: str,
    user_id: str,
) -> ChatWriteSnapshotResponse:
    """Build the live snapshot used for REST write responses."""
    live_result = await chat_service.list_live_events(
        session_id,
        user_id=user_id,
        live_event_store=live_event_store,
    )
    match live_result:
        case Success(live):
            partial_history_events = [
                ChatEventResponse.from_domain(event)
                for event in live.partial_history_events
            ]
            input_buffer_events = [
                ChatEventResponse.from_domain(event)
                for event in live.input_buffer_events
            ]
            return ChatWriteSnapshotResponse(
                partial_history_events=partial_history_events,
                input_buffer_events=input_buffer_events,
                run=(
                    ChatLiveRunStateResponse.from_domain(live.run)
                    if live.run is not None
                    else None
                ),
                session_run_state=live.session_run_state,
                todo=(
                    TodoStateResponse.from_domain(live.todo)
                    if live.todo is not None
                    else None
                ),
                goal=(
                    GoalStateResponse.from_domain(live.goal)
                    if live.goal is not None
                    else None
                ),
            )
        case Failure(error):
            match error:
                case SessionNotFound():
                    raise HTTPException(status_code=404, detail="Session not found.")
                case SessionAccessDenied():
                    raise HTTPException(status_code=404, detail="Session not found.")
                case _:
                    assert_never(error)
        case _:
            assert_never(live_result)


async def _write_message_via_rest(
    chat_service: ChatSessionService,
    agent_session_input_service: AgentSessionInputService,
    exchange_file_service: ExchangeFileService,
    model_file_service: ModelFileService,
    broker: SessionBroker,
    broadcast: WebSocketBroadcast,
    live_event_store: LiveEventStore,
    request: ChatMessageWriteRequest,
    *,
    session_id: str | None,
    user_id: str,
    tz: ZoneInfo,
) -> ChatWriteResponse:
    """Handle REST message writes as input buffer commit boundaries."""
    resolved_session_id = await _handle_ensure_session_for_rest(
        chat_service,
        session_id=session_id,
        agent_id=request.agent_id,
        user_id=user_id,
    )
    materialized = await materialize_user_input_exchange_file_attachments(
        request.attachments or [],
        agent_id=request.agent_id,
        session_id=resolved_session_id,
        exchange_file_service=exchange_file_service,
        model_file_service=model_file_service,
        user_id=user_id,
    )
    message = InputMessage(
        text=request.message,
        user_id=user_id,
        headers=[],
        metadata={
            "timestamp": datetime.now(tz).isoformat(),
            "source": "chat",
        },
        attachments=[attachment.uri for attachment in materialized.attachments],
        file_parts=materialized.file_parts,
    )
    input_result = await agent_session_input_service.create_buffered_agent_input(
        agent_id=request.agent_id,
        agent_session_id=resolved_session_id,
        message=message,
        user_id=user_id,
        client_request_id=request.client_request_id,
    )
    result = _handle_agent_session_input_result(input_result)
    if result.agent_session_id != resolved_session_id:
        raise RuntimeError("AgentSession input target changed during REST write")
    live_event_upserted = chat_live_event_upserted_dump(
        input_buffer_to_live_event(result.input_buffer)
    )
    await broadcast.publish(result.agent_session_id, live_event_upserted)
    broker_message = SessionWakeUp(
        agent_id=request.agent_id,
        session_id=result.agent_session_id,
        user_id=user_id,
        additional_system_prompt=None,
        interface=None,
        workspace_id=None,
        workspace_handle=None,
    )
    await broker.send_message(broker_message)
    snapshot = await _build_chat_write_snapshot(
        chat_service,
        live_event_store,
        session_id=result.agent_session_id,
        user_id=user_id,
    )
    return ChatWriteResponse(
        session_id=result.agent_session_id,
        client_request_id=request.client_request_id,
        accepted=ChatWriteAcceptedResponse(
            type="input_buffer",
            id=result.input_buffer.id,
        ),
        snapshot=snapshot,
        history_reload_required=False,
    )


def _handle_agent_session_input_result(
    result: Result[BufferedAgentSessionInputResult, AgentSessionInputError],
) -> BufferedAgentSessionInputResult:
    """Convert AgentSession input service result to REST response semantics."""
    match result:
        case Success(value):
            return value
        case Failure(error):
            match error:
                case AgentSessionInputSessionNotFound():
                    raise HTTPException(status_code=404, detail="Session not found.")
                case AgentSessionInputWrongAgent():
                    raise HTTPException(status_code=404, detail="Session not found.")
                case AgentSessionInputInactiveSession():
                    raise HTTPException(
                        status_code=409,
                        detail="Session is not active.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


async def _handle_ensure_session_for_rest(
    chat_service: ChatSessionService,
    *,
    session_id: str | None,
    agent_id: str,
    user_id: str,
) -> str:
    """Convert ensure_session results for REST writes to HTTP errors."""
    result = await chat_service.ensure_session(
        EnsureSessionInput(
            session_id=session_id,
            agent_id=agent_id,
            user_id=user_id,
        )
    )
    match result:
        case Success(agent_session):
            return agent_session.id
        case Failure(error):
            match error:
                case AgentNotFound():
                    raise HTTPException(status_code=404, detail="Agent not found.")
                case NotWorkspaceMember():
                    raise HTTPException(status_code=404, detail="Session not found.")
                case SessionAccessDenied():
                    raise HTTPException(status_code=404, detail="Session not found.")
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.patch("/sessions/{session_id}/goal")
async def update_session_goal(
    session_id: str,
    request: GoalUpdateRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    chat_service: Annotated[ChatSessionService, Depends()],
    broker: Annotated[SessionBroker, Depends(get_broker)],
    broadcast: Annotated[WebSocketBroadcast, Depends(get_ws_broadcast)],
) -> GoalStateResponse:
    """Update or delete the goal of an existing session."""
    _validate_session_id(session_id)
    result = await chat_service.update_goal(
        session_id,
        user_id=current_user.user_id,
        objective=request.objective.strip() if request.objective is not None else None,
    )
    match result:
        case Success(update_result):
            if update_result.event is not None:
                await broadcast.publish(
                    session_id, serialize_event(update_result.event)
                )
                await broadcast.publish(
                    session_id, chat_history_event_appended_dump(update_result.event)
                )
            if update_result.wake_up:
                await broker.send_message(
                    SessionWakeUp(
                        agent_id=update_result.agent_id,
                        session_id=session_id,
                        user_id=current_user.user_id,
                        additional_system_prompt=None,
                        interface=None,
                        workspace_id=update_result.workspace_id,
                        workspace_handle=None,
                    )
                )
            return GoalStateResponse.from_domain(update_result.goal)
        case Failure(error):
            match error:
                case SessionNotFound():
                    raise HTTPException(status_code=404, detail="Session not found.")
                case SessionAccessDenied():
                    raise HTTPException(status_code=404, detail="Session not found.")
                case InvalidGoalStatusTransition():
                    raise HTTPException(
                        status_code=409,
                        detail="Invalid goal status transition.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.patch("/sessions/{session_id}/goal/status")
async def update_session_goal_status(
    session_id: str,
    request: GoalStatusUpdateRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    chat_service: Annotated[ChatSessionService, Depends()],
    broker: Annotated[SessionBroker, Depends(get_broker)],
    broadcast: Annotated[WebSocketBroadcast, Depends(get_ws_broadcast)],
) -> GoalStateResponse:
    """Pause or resume the goal state of an existing session under user control."""
    _validate_session_id(session_id)
    result = await chat_service.update_goal_status(
        session_id,
        user_id=current_user.user_id,
        input=UpdateGoalStatusInput(
            status=request.status,
            resume_hint=(
                request.resume_hint.strip() if request.resume_hint is not None else None
            ),
        ),
    )
    match result:
        case Success(update_result):
            if update_result.event is not None:
                await broadcast.publish(
                    session_id, serialize_event(update_result.event)
                )
                await broadcast.publish(
                    session_id, chat_history_event_appended_dump(update_result.event)
                )
            if update_result.wake_up:
                await broker.send_message(
                    SessionWakeUp(
                        agent_id=update_result.agent_id,
                        session_id=session_id,
                        user_id=current_user.user_id,
                        additional_system_prompt=None,
                        interface=None,
                        workspace_id=update_result.workspace_id,
                        workspace_handle=None,
                    )
                )
            return GoalStateResponse.from_domain(update_result.goal)
        case Failure(error):
            match error:
                case SessionNotFound():
                    raise HTTPException(status_code=404, detail="Session not found.")
                case SessionAccessDenied():
                    raise HTTPException(status_code=404, detail="Session not found.")
                case InvalidGoalStatusTransition():
                    raise HTTPException(
                        status_code=409,
                        detail="Invalid goal status transition.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.post("/sessions/{session_id}/stop")
async def stop_session_run(
    session_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    chat_service: Annotated[ChatSessionService, Depends()],
    chat_write_service: Annotated[ChatWriteService, Depends()],
    broker: Annotated[SessionBroker, Depends(get_broker)],
) -> ChatStopResponse:
    """Request active run stop for an existing session at the REST control boundary."""
    _validate_session_id(session_id)
    result = await chat_service.get_session(
        session_id,
        user_id=current_user.user_id,
    )
    match result:
        case Success(agent_session):
            await chat_write_service.request_session_stop(
                session_id=agent_session.id,
                user_id=current_user.user_id,
            )
            await broker.send_message(
                SessionStopSignal(
                    session_id=agent_session.id,
                    user_id=current_user.user_id,
                )
            )
            return ChatStopResponse(session_id=agent_session.id)
        case Failure(error):
            match error:
                case SessionNotFound():
                    raise HTTPException(status_code=404, detail="Session not found.")
                case SessionAccessDenied():
                    raise HTTPException(status_code=404, detail="Session not found.")
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.post("/sessions/{session_id}/messages")
async def create_message(
    session_id: str,
    request: ChatMessageWriteRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    chat_service: Annotated[ChatSessionService, Depends()],
    agent_session_input_service: Annotated[AgentSessionInputService, Depends()],
    exchange_file_service: Annotated[ExchangeFileService, Depends()],
    model_file_service: Annotated[ModelFileService, Depends()],
    broker: Annotated[SessionBroker, Depends(get_broker)],
    broadcast: Annotated[WebSocketBroadcast, Depends(get_ws_broadcast)],
    live_event_store: Annotated[LiveEventStore, Depends(get_live_event_store)],
    timezone: str | None = None,
) -> ChatWriteResponse:
    """Accept an existing session message at the REST input buffer boundary."""
    _validate_session_id(session_id)
    return await _write_message_via_rest(
        chat_service,
        agent_session_input_service,
        exchange_file_service,
        model_file_service,
        broker,
        broadcast,
        live_event_store,
        request,
        session_id=session_id,
        user_id=current_user.user_id,
        tz=_parse_timezone(timezone),
    )


async def _write_edit_message_via_rest(
    chat_service: ChatSessionService,
    chat_write_service: ChatWriteService,
    exchange_file_service: ExchangeFileService,
    model_file_service: ModelFileService,
    broker: SessionBroker,
    live_event_store: LiveEventStore,
    request: ChatEditMessageWriteRequest,
    *,
    session_id: str,
    user_id: str,
    tz: ZoneInfo,
) -> ChatWriteResponse:
    """Handle REST edit writes as idle-only input buffer boundaries."""
    resolved_session_id = await _handle_ensure_session_for_rest(
        chat_service,
        session_id=session_id,
        agent_id=request.agent_id,
        user_id=user_id,
    )
    payload = request.model_dump(mode="json")
    materialized = await materialize_user_input_exchange_file_attachments(
        request.attachments or [],
        agent_id=request.agent_id,
        session_id=resolved_session_id,
        exchange_file_service=exchange_file_service,
        model_file_service=model_file_service,
        user_id=user_id,
    )
    metadata = {
        "timestamp": datetime.now(tz).isoformat(),
        "source": "chat",
        "edit_message_id": request.message_id,
    }
    try:
        accepted = await chat_write_service.create_idempotent_edit_input(
            agent_id=request.agent_id,
            session_id=resolved_session_id,
            user_id=user_id,
            client_request_id=request.client_request_id,
            message_id=request.message_id,
            text=request.message,
            metadata=metadata,
            attachments=[attachment.uri for attachment in materialized.attachments],
            file_parts=materialized.file_parts,
            payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if accepted.request.created:
        if accepted.input_buffer is not None:
            await broker.send_message(
                SessionWakeUp(
                    agent_id=request.agent_id,
                    session_id=resolved_session_id,
                    user_id=user_id,
                    additional_system_prompt=None,
                    interface=None,
                    workspace_id=None,
                    workspace_handle=None,
                )
            )
    snapshot = await _build_chat_write_snapshot(
        chat_service,
        live_event_store,
        session_id=resolved_session_id,
        user_id=user_id,
    )
    return ChatWriteResponse(
        session_id=resolved_session_id,
        client_request_id=request.client_request_id,
        accepted=ChatWriteAcceptedResponse(type="edit_message", id=request.message_id),
        snapshot=snapshot,
        history_reload_required=True,
    )


async def _write_command_via_rest(
    chat_service: ChatSessionService,
    chat_write_service: ChatWriteService,
    broker: SessionBroker,
    live_event_store: LiveEventStore,
    request: ChatCommandWriteRequest,
    *,
    session_id: str,
    user_id: str,
) -> ChatWriteResponse:
    """Handle REST command writes as idle-only pending command boundaries."""
    if request.command not in COMMAND_REGISTRY:
        raise HTTPException(
            status_code=400, detail=f"Unknown command: /{request.command}"
        )
    resolved_session_id = await _handle_ensure_session_for_rest(
        chat_service,
        session_id=session_id,
        agent_id=request.agent_id,
        user_id=user_id,
    )
    payload = request.model_dump(mode="json")
    try:
        accepted = await chat_write_service.create_idempotent_pending_command(
            agent_id=request.agent_id,
            session_id=resolved_session_id,
            user_id=user_id,
            client_request_id=request.client_request_id,
            command_name=request.command,
            payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if accepted.request.created:
        await broker.send_message(
            SessionWakeUp(
                agent_id=request.agent_id,
                session_id=resolved_session_id,
                user_id=user_id,
                additional_system_prompt=None,
                interface=None,
                workspace_id=None,
                workspace_handle=None,
            )
        )
    snapshot = await _build_chat_write_snapshot(
        chat_service,
        live_event_store,
        session_id=resolved_session_id,
        user_id=user_id,
    )
    return ChatWriteResponse(
        session_id=resolved_session_id,
        client_request_id=request.client_request_id,
        accepted=ChatWriteAcceptedResponse(
            type="command",
            id=accepted.request.record.accepted_id,
        ),
        snapshot=snapshot,
        history_reload_required=True,
    )


@router.post("/sessions/{session_id}/edit-message")
async def edit_message(
    session_id: str,
    request: ChatEditMessageWriteRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    chat_service: Annotated[ChatSessionService, Depends()],
    chat_write_service: Annotated[ChatWriteService, Depends()],
    exchange_file_service: Annotated[ExchangeFileService, Depends()],
    model_file_service: Annotated[ModelFileService, Depends()],
    broker: Annotated[SessionBroker, Depends(get_broker)],
    live_event_store: Annotated[LiveEventStore, Depends(get_live_event_store)],
    timezone: str | None = None,
) -> ChatWriteResponse:
    """Accept an existing user message edit at the REST boundary."""
    _validate_session_id(session_id)
    return await _write_edit_message_via_rest(
        chat_service,
        chat_write_service,
        exchange_file_service,
        model_file_service,
        broker,
        live_event_store,
        request,
        session_id=session_id,
        user_id=current_user.user_id,
        tz=_parse_timezone(timezone),
    )


@router.post("/sessions/{session_id}/commands")
async def create_command(
    session_id: str,
    request: ChatCommandWriteRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    chat_service: Annotated[ChatSessionService, Depends()],
    chat_write_service: Annotated[ChatWriteService, Depends()],
    broker: Annotated[SessionBroker, Depends(get_broker)],
    live_event_store: Annotated[LiveEventStore, Depends(get_live_event_store)],
) -> ChatWriteResponse:
    """Accept a slash command at the REST boundary."""
    _validate_session_id(session_id)
    return await _write_command_via_rest(
        chat_service,
        chat_write_service,
        broker,
        live_event_store,
        request,
        session_id=session_id,
        user_id=current_user.user_id,
    )


@router.get("/agents/{agent_id}/context")
async def get_agent_session_context(
    agent_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    context_service: Annotated[SessionContextService, Depends()],
    limit: Annotated[int, Query(ge=1, le=500)] = 300,
) -> SessionContextResponse:
    """Return Agent team primary session context inspector information."""
    result = await context_service.get_agent_context(
        agent_id=agent_id,
        user_id=current_user.user_id,
        limit=limit,
    )
    match result:
        case Success(context):
            return SessionContextResponse.from_domain(context)
        case Failure(error):
            match error:
                case AgentNotFound():
                    raise HTTPException(status_code=404, detail="Agent not found.")
                case NotWorkspaceMember():
                    raise HTTPException(status_code=404, detail="Session not found.")
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.get("/agents/{agent_id}/team-primary-session")
async def get_team_primary_agent_session(
    agent_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    chat_service: Annotated[ChatSessionService, Depends()],
) -> AgentSessionResponse:
    """Get an Agent's team primary AgentSession, creating one if absent."""
    result = await chat_service.get_team_primary_session(
        agent_id=agent_id,
        user_id=current_user.user_id,
    )
    match result:
        case Success(session):
            return AgentSessionResponse.from_domain(session)
        case Failure(error):
            match error:
                case AgentNotFound() | NotWorkspaceMember() | SessionAccessDenied():
                    raise HTTPException(status_code=404, detail="Session not found.")
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.get("/agents/{agent_id}/sessions/{session_id}")
async def get_agent_session(
    agent_id: str,
    session_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    chat_service: Annotated[ChatSessionService, Depends()],
) -> AgentSessionResponse:
    """Get a URL-selected AgentSession by agent/session pair."""
    _validate_session_id(session_id)
    result = await chat_service.get_agent_session(
        agent_id=agent_id,
        session_id=session_id,
        user_id=current_user.user_id,
    )
    match result:
        case Success(session):
            return AgentSessionResponse.from_domain(session)
        case Failure(error):
            match error:
                case SessionNotFound():
                    raise HTTPException(status_code=404, detail="Session not found.")
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.get("/commands")
async def list_slash_commands() -> SlashCommandListResponse:
    """Return the list of available slash commands."""
    return SlashCommandListResponse(
        items=[
            SlashCommandResponse(
                name=command.name,
                description=command.description,
            )
            for command in list_registered_commands()
        ]
    )


@router.get("/agents/{agent_id}/projects")
async def list_agent_projects(
    agent_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    project_service: Annotated[SessionWorkspaceProjectService, Depends()],
) -> SessionWorkspaceProjectListResponse:
    """List Agent Workspace Projects for an Agent."""
    result = await project_service.list_projects_for_agent(
        agent_id=agent_id,
        user_id=current_user.user_id,
    )
    match result:
        case Success(projects):
            return SessionWorkspaceProjectListResponse(
                items=[
                    SessionWorkspaceProjectResponse.from_domain(project)
                    for project in projects
                ]
            )
        case Failure(error):
            _raise_project_access_error(error)
        case _:
            assert_never(result)


@router.get("/agents/{agent_id}/project-registration-requests")
async def list_agent_project_registration_requests(
    agent_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    project_service: Annotated[SessionWorkspaceProjectService, Depends()],
) -> SessionWorkspaceProjectRegistrationRequestListResponse:
    """List Project registration requests for an Agent."""
    result = await project_service.list_registration_requests_for_agent(
        agent_id=agent_id,
        user_id=current_user.user_id,
    )
    match result:
        case Success(requests):
            return SessionWorkspaceProjectRegistrationRequestListResponse(
                items=[
                    SessionWorkspaceProjectRegistrationRequestResponse.from_domain(
                        request
                    )
                    for request in requests
                ]
            )
        case Failure(error):
            _raise_project_access_error(error)
        case _:
            assert_never(result)


@router.post("/agents/{agent_id}/project-registration-requests/{request_id}/approve")
async def approve_agent_project_registration_request(
    agent_id: str,
    request_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    project_service: Annotated[SessionWorkspaceProjectService, Depends()],
) -> SessionWorkspaceProjectResponse:
    """Approve an Agent Project registration request."""
    result = await project_service.approve_registration_request_for_agent(
        agent_id=agent_id,
        user_id=current_user.user_id,
        request_id=request_id,
    )
    match result:
        case Success(project):
            return SessionWorkspaceProjectResponse.from_domain(project)
        case Failure(error):
            match error:
                case RegistrationRequestNotFound():
                    raise HTTPException(
                        status_code=404,
                        detail="Project registration request not found.",
                    )
                case RegistrationRequestAlreadyResolved():
                    raise HTTPException(
                        status_code=409,
                        detail="Project registration request is already resolved.",
                    )
                case InvalidProjectPath():
                    raise HTTPException(status_code=400, detail=error.reason)
                case ProjectPathConflict():
                    raise HTTPException(
                        status_code=409,
                        detail="Project path conflicts with an existing Project.",
                    )
                case ProjectAgentNotFound() | ProjectAccessDenied():
                    _raise_project_access_error(error)
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.post(
    "/agents/{agent_id}/project-registration-requests/{request_id}/reject",
    status_code=204,
)
async def reject_agent_project_registration_request(
    agent_id: str,
    request_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    project_service: Annotated[SessionWorkspaceProjectService, Depends()],
) -> None:
    """Reject an Agent Project registration request."""
    result = await project_service.reject_registration_request_for_agent(
        agent_id=agent_id,
        user_id=current_user.user_id,
        request_id=request_id,
    )
    match result:
        case Success():
            return
        case Failure(error):
            match error:
                case RegistrationRequestNotFound():
                    raise HTTPException(
                        status_code=404,
                        detail="Project registration request not found.",
                    )
                case RegistrationRequestAlreadyResolved():
                    raise HTTPException(
                        status_code=409,
                        detail="Project registration request is already resolved.",
                    )
                case ProjectAgentNotFound() | ProjectAccessDenied():
                    _raise_project_access_error(error)
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.post("/agents/{agent_id}/projects/register")
async def register_agent_project(
    agent_id: str,
    request: SessionWorkspaceProjectRegisterRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    project_service: Annotated[SessionWorkspaceProjectService, Depends()],
) -> SessionWorkspaceProjectResponse:
    """Register an existing directory in Agent Workspace as a Project."""
    result = await project_service.register_existing_folder_for_agent(
        agent_id=agent_id,
        user_id=current_user.user_id,
        path=request.path,
    )
    match result:
        case Success(project):
            return SessionWorkspaceProjectResponse.from_domain(project)
        case Failure(error):
            match error:
                case InvalidProjectPath():
                    raise HTTPException(status_code=400, detail=error.reason)
                case ProjectPathConflict():
                    raise HTTPException(
                        status_code=409,
                        detail="Project path conflicts with an existing Project.",
                    )
                case ProjectAgentNotFound() | ProjectAccessDenied():
                    _raise_project_access_error(error)
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.delete("/agents/{agent_id}/projects/{project_id}", status_code=204)
async def delete_agent_project(
    agent_id: str,
    project_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    project_service: Annotated[SessionWorkspaceProjectService, Depends()],
) -> None:
    """Delete a Project registry row for an Agent."""
    result = await project_service.delete_project_for_agent(
        agent_id=agent_id,
        user_id=current_user.user_id,
        project_id=project_id,
    )
    match result:
        case Success():
            return
        case Failure(error):
            match error:
                case ProjectNotFound():
                    raise HTTPException(status_code=404, detail="Project not found.")
                case ProjectAgentNotFound() | ProjectAccessDenied():
                    _raise_project_access_error(error)
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.get("/sessions/{session_id}/history")
async def list_history_events(
    session_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    chat_service: Annotated[ChatSessionService, Depends()],
    limit: Annotated[
        int, Query(ge=1, le=100, description="Number of events to query")
    ] = 50,
    before: Annotated[
        str | None,
        Query(description="Query only events before this ID, as a backward cursor"),
    ] = None,
    after: Annotated[
        str | None,
        Query(description="Query only events after this ID, as a forward cursor"),
    ] = None,
) -> ChatEventPageResponse:
    """Page through persisted event history for a session."""
    _validate_session_id(session_id)
    if before is not None and after is not None:
        raise HTTPException(
            status_code=400,
            detail="before and after cursors cannot be used together.",
        )
    result = await chat_service.list_history_events(
        session_id,
        user_id=current_user.user_id,
        limit=limit,
        before=before,
        after=after,
    )
    match result:
        case Success(value):
            next_cursor: str | None = None
            previous_cursor: str | None = None
            if value.items:
                next_cursor = value.items[0].id
                previous_cursor = value.items[-1].id
            return ChatEventPageResponse(
                items=[ChatEventResponse.from_domain(event) for event in value.items],
                has_more=value.has_more,
                has_newer=value.has_newer,
                next_cursor=next_cursor,
                previous_cursor=previous_cursor,
            )
        case Failure(error):
            match error:
                case SessionNotFound():
                    raise HTTPException(
                        status_code=404,
                        detail="Session not found.",
                    )
                case SessionAccessDenied():
                    raise HTTPException(status_code=404, detail="Session not found.")
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.get("/sessions/{session_id}/live")
async def list_live_events(
    session_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    chat_service: Annotated[ChatSessionService, Depends()],
    live_event_store: Annotated[LiveEventStore, Depends(get_live_event_store)],
) -> LiveEventListResponse:
    """Get the current live event projection for a session."""
    _validate_session_id(session_id)
    result = await chat_service.list_live_events(
        session_id,
        user_id=current_user.user_id,
        live_event_store=live_event_store,
    )
    match result:
        case Success(value):
            partial_history = [
                ChatEventResponse.from_domain(event)
                for event in value.partial_history_events
            ]
            input_buffers = [
                ChatEventResponse.from_domain(event)
                for event in value.input_buffer_events
            ]
            return LiveEventListResponse(
                partial_history=PartialHistoryResponse(
                    items=partial_history,
                ),
                input_buffers=input_buffers,
                run=None
                if value.run is None
                else ChatLiveRunStateResponse.from_domain(value.run),
                session_run_state=value.session_run_state,
                todo=(
                    TodoStateResponse.from_domain(value.todo)
                    if value.todo is not None
                    else None
                ),
                goal=(
                    GoalStateResponse.from_domain(value.goal)
                    if value.goal is not None
                    else None
                ),
            )
        case Failure(error):
            match error:
                case SessionNotFound():
                    raise HTTPException(
                        status_code=404,
                        detail="Session not found.",
                    )
                case SessionAccessDenied():
                    raise HTTPException(status_code=404, detail="Session not found.")
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.get("/agents/{agent_id}/workspace")
async def get_agent_workspace(
    agent_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    workspace_service: Annotated[AgentWorkspaceFileService, Depends()],
) -> AgentWorkspaceResponse:
    """Get Agent Workspace bootstrap status."""
    _validate_uuid7_hex(agent_id, label="agent ID")
    result = await workspace_service.get_workspace(
        agent_id=agent_id,
        user_id=current_user.user_id,
    )
    match result:
        case Success(value):
            return _workspace_response_from_domain(value)
        case Failure(error):
            _raise_workspace_error(error)
            raise AssertionError("unreachable")
        case _:
            assert_never(result)


@router.delete("/sessions/{session_id}/input-buffers/{buffer_id}", status_code=204)
async def delete_input_buffer(
    session_id: str,
    buffer_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    chat_service: Annotated[ChatSessionService, Depends()],
    broadcast: Annotated[WebSocketBroadcast, Depends(get_ws_broadcast)],
) -> None:
    """Idempotently delete the pending input buffer."""
    _validate_session_id(session_id)
    _validate_uuid7_hex(buffer_id, label="buffer ID")
    result: Result[
        None, DeleteInputBufferError
    ] = await chat_service.delete_input_buffer(
        session_id,
        buffer_id,
        user_id=current_user.user_id,
    )
    match result:
        case Success():
            await broadcast.publish(
                session_id,
                chat_live_event_removed_dump(session_id, buffer_id),
            )
            return
        case Failure(error):
            match error:
                case SessionNotFound():
                    raise HTTPException(status_code=404, detail="Session not found.")
                case SessionAccessDenied():
                    raise HTTPException(status_code=404, detail="Session not found.")
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.get("/agents/{agent_id}/workspace/files")
async def read_agent_workspace_path(
    agent_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    workspace_service: Annotated[AgentWorkspaceFileService, Depends()],
    path: Annotated[
        str | None,
        Query(description="Agent Workspace path to query"),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=1_048_576, description="Text preview byte limit"),
    ] = 65536,
) -> AgentWorkspaceFileResponseUnion:
    """Get an Agent Workspace directory or file preview."""
    _validate_uuid7_hex(agent_id, label="agent ID")
    result = await workspace_service.read_path(
        agent_id=agent_id,
        user_id=current_user.user_id,
        raw_path=path,
        limit=limit,
    )
    match result:
        case Success(value):
            return _workspace_file_response_from_domain(value)
        case Failure(error):
            _raise_workspace_error(error)
            raise AssertionError("unreachable")
        case _:
            assert_never(result)


@router.get("/agents/{agent_id}/workspace/download")
async def download_agent_workspace_file(
    agent_id: str,
    path: Annotated[str, Query(description="Agent Workspace file path to download")],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    workspace_service: Annotated[AgentWorkspaceFileService, Depends()],
) -> StreamingResponse:
    """Download an Agent Workspace file."""
    _validate_uuid7_hex(agent_id, label="agent ID")
    result = await workspace_service.download_file(
        agent_id=agent_id,
        user_id=current_user.user_id,
        raw_path=path,
    )
    match result:
        case Success((resolved_path, data, media_type)):
            return StreamingResponse(
                io.BytesIO(data),
                media_type=media_type,
                headers={
                    "Content-Disposition": (
                        f"attachment; filename*=UTF-8''{quote(resolved_path.name)}"
                    ),
                },
            )
        case Failure(error):
            _raise_workspace_error(error)
            raise AssertionError("unreachable")
        case _:
            assert_never(result)


def _workspace_action_response(
    error: AgentWorkspaceRuntimeInactive,
) -> AgentWorkspaceInactiveErrorResponse:
    """Create a RUNTIME_INACTIVE error response."""
    return AgentWorkspaceInactiveErrorResponse(
        code="RUNTIME_INACTIVE",
        message="Runtime is not running.",
        action=AgentWorkspaceActionResponse(
            type=error.action.type,
            method=error.action.method,
            path=error.action.path,
        ),
    )


def _raise_workspace_error(error: AgentWorkspaceError) -> None:
    """Convert Agent Workspace service errors to HTTPException."""
    match error:
        case AgentNotFound():
            raise HTTPException(status_code=404, detail="Agent not found.")
        case NotWorkspaceMember():
            raise HTTPException(status_code=403, detail="Not a workspace member.")
        case SessionNotFound():
            raise HTTPException(status_code=404, detail="Session not found.")
        case SessionAccessDenied():
            raise HTTPException(status_code=403, detail="Session access denied.")
        case AgentWorkspacePathDenied():
            raise HTTPException(
                status_code=403,
                detail="Agent Workspace path access denied.",
            )
        case AgentWorkspacePathUnavailable():
            raise HTTPException(
                status_code=409,
                detail="Provider has not reported Agent Workspace path yet.",
            )
        case AgentWorkspaceRuntimeInactive():
            raise HTTPException(
                status_code=409,
                detail=_workspace_action_response(error).model_dump(mode="json"),
            )
        case AgentWorkspaceFileNotFound():
            raise HTTPException(status_code=404, detail="File not found.")
        case AgentWorkspaceFileReadError():
            raise HTTPException(status_code=400, detail=error.detail)
        case AgentWorkspaceFileTooLarge():
            raise HTTPException(
                status_code=413,
                detail=(
                    f"File is too large to preview. Size {error.size} bytes exceeds "
                    f"the {error.limit} byte preview limit."
                ),
            )
        case _:
            assert_never(error)


def _workspace_response_from_domain(
    state: AgentWorkspaceState,
) -> AgentWorkspaceResponse:
    """Convert Agent Workspace state service model to API response."""
    return AgentWorkspaceResponse.from_domain(state)


def _workspace_file_response_from_domain(
    value: AgentWorkspaceFileResult,
) -> AgentWorkspaceFileResponseUnion:
    """Convert Agent Workspace file service model to API response."""
    match value:
        case AgentWorkspaceDirectory():
            return AgentWorkspaceDirectoryResponse.from_domain(value)
        case AgentWorkspaceFile():
            return AgentWorkspaceFileResponse.from_domain(value)
        case _:
            assert_never(value)


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    chat_service: Annotated[ChatSessionService, Depends()],
) -> None:
    """Delete a session and related files. Only the owner can delete it."""
    _validate_session_id(session_id)
    result: Result[None, DeleteSessionError] = await chat_service.delete_session(
        session_id,
        user_id=current_user.user_id,
    )
    match result:
        case Success():
            return
        case Failure(error):
            match error:
                case SessionAccessDenied():
                    raise HTTPException(status_code=404, detail="Session not found.")
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


_MAX_UPLOAD_SIZE = 20 * 1024 * 1024  # 20 MB


async def _read_upload_file(file: UploadFile) -> tuple[bytes, str | None, str]:
    """Read an upload within size limits and infer media type from filename."""
    if file.size is not None and file.size > _MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail="File size exceeds the 20 MB limit.",
        )
    data = await file.read(_MAX_UPLOAD_SIZE + 1)
    if len(data) > _MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail="File size exceeds the 20 MB limit.",
        )
    original_filename = file.filename
    media_type = guess_media_type(original_filename or "upload")
    return data, original_filename, media_type


@router.post("/agents/{agent_id}/upload")
async def upload_file_for_agent(
    agent_id: str,
    file: UploadFile,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    exchange_file_service: Annotated[ExchangeFileService, Depends()],
) -> UploadResponse:
    """Upload only Exchange attachments scoped to the Agent."""
    _validate_uuid7_hex(agent_id, label="agent ID")
    data, original_filename, media_type = await _read_upload_file(file)
    result = await exchange_file_service.create_agent_upload(
        agent_id=agent_id,
        user_id=current_user.user_id,
        filename=original_filename,
        media_type=media_type,
        body=data,
    )
    match result:
        case Success(value):
            return UploadResponse(
                attachment_id=value.id,
                uri=value.uri,
                media_type=value.media_type,
                size=value.size_bytes,
                name=value.filename,
            )
        case Failure(error):
            match error:
                case ExchangeSessionNotFound():
                    raise HTTPException(status_code=404, detail="Agent not found.")
                case FileAccessDenied():
                    logger.warning(
                        "Chat upload denied by agent workspace access check",
                        extra={
                            "agent_id": agent_id,
                            "user_id": current_user.user_id,
                        },
                    )
                    raise HTTPException(
                        status_code=403,
                        detail="Workspace membership required.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.get(
    "/exchange-files/{file_id}/download",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "Exchange file bytes",
            "content": {
                "application/octet-stream": {
                    "schema": {"type": "string", "format": "binary"}
                }
            },
        }
    },
)
async def download_exchange_file(
    file_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    exchange_file_service: Annotated[ExchangeFileService, Depends()],
) -> StreamingResponse:
    """Download an Exchange file."""
    result = await exchange_file_service.download(
        file_id=file_id,
        user_id=current_user.user_id,
    )
    match result:
        case Success(value):
            return StreamingResponse(
                io.BytesIO(value.body),
                media_type=value.file.media_type,
                headers={
                    "Content-Disposition": (
                        f"attachment; filename*=UTF-8''{quote(value.file.filename)}"
                    ),
                },
            )
        case Failure(error):
            _raise_exchange_file_error(error)
        case _:
            assert_never(result)


@router.delete("/exchange-files/{file_id}", status_code=204)
async def delete_exchange_file(
    file_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    exchange_file_service: Annotated[ExchangeFileService, Depends()],
) -> None:
    """Delete an Exchange file."""
    result = await exchange_file_service.delete(
        file_id=file_id,
        user_id=current_user.user_id,
    )
    match result:
        case Success():
            return
        case Failure(error):
            _raise_exchange_file_error(error)
        case _:
            assert_never(result)


def _raise_exchange_file_error(error: ExchangeFileError) -> NoReturn:
    """Convert Exchange file service errors to HTTPException."""
    match error:
        case FileNotFound():
            raise HTTPException(status_code=404, detail="File not found.")
        case FileAccessDenied():
            raise HTTPException(status_code=403, detail="File access denied.")
        case FileExpired():
            raise HTTPException(status_code=410, detail="File is expired.")
        case FileUnavailable():
            raise HTTPException(status_code=410, detail="File is no longer available.")
        case ExchangeSessionNotFound():
            raise HTTPException(status_code=404, detail="Session not found.")
        case _:
            assert_never(error)


def _raise_project_access_error(
    error: ProjectAgentNotFound | ProjectAccessDenied,
) -> NoReturn:
    """Convert project access errors to HTTPException."""
    match error:
        case ProjectAgentNotFound():
            raise HTTPException(status_code=404, detail="Agent not found.")
        case ProjectAccessDenied():
            raise HTTPException(
                status_code=403,
                detail="Workspace membership required.",
            )
        case _:
            assert_never(error)


def mount(mounter: RouteMounter) -> None:
    """Mount Chat v1 routes."""
    mounter(
        router,
        prefix="/chat/v1",
        tag="Chat v1",
        description=dedent(
            """
            Chat API (Public)

            WebSocket chat and REST message lookup endpoints.
            """
        ),
    )
