"""Independent aiohttp Runtime Web Gateway process."""

import asyncio
import contextlib
import datetime
import html
import logging
import signal
import urllib.parse
from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from typing import Protocol

import boto3
import grpc
from aiohttp import WSMessage, WSMsgType, web
from azcommon.logging import configure_logging_for_runtime
from azents_runtime_control.runner_web import (
    MAX_RUNTIME_WEB_FRAME_BYTES,
    RunnerWebBodyChunk,
    RunnerWebCancel,
    RunnerWebCancelReason,
    RunnerWebHeader,
    RunnerWebIdentity,
    RunnerWebProtocol,
    RunnerWebRequestHead,
    RunnerWebResponseHead,
    RunnerWebSocketFrame,
    RunnerWebSocketOpcode,
    RunnerWebStreamEnd,
    RunnerWebStreamError,
    RunnerWebStreamErrorCode,
)
from mypy_boto3_rds import RDSClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from azents.core.config import PostgreSQLConfig
from azents.rdb.session import SessionManager
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.runtime_web.data import RuntimeWebEndpoint
from azents.repos.runtime_web.gateway_data import (
    RuntimeWebAdmissionLimits,
    RuntimeWebBrokerBinding,
    RuntimeWebDesiredConfiguration,
    RuntimeWebRedeemedIdentity,
)
from azents.repos.runtime_web.gateway_data import (
    RuntimeWebGatewayAuthority as RuntimeWebGatewayAuthorityData,
)
from azents.repos.runtime_web.gateway_repository import (
    RuntimeWebGatewayCapacityExceeded,
    RuntimeWebGatewayRepository,
)
from azents.repos.runtime_web.repository import (
    RuntimeWebRepository,
    RuntimeWebRepositoryConflict,
)
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.runtime_web_gateway.policy import (
    RuntimeWebCorsDecision,
    RuntimeWebPolicyCode,
    RuntimeWebPolicyError,
    canonical_origin,
    evaluate_actual_origin,
    evaluate_preflight,
    normalize_request_headers,
    normalize_response_headers,
    parse_target_host,
    reject_service_worker_request,
    require_admitted_browser,
)
from azents.runtime_web_gateway.settings import (
    RuntimeWebGatewayConfig,
    RuntimeWebGatewaySettings,
)
from azents.runtime_web_gateway.transport import (
    GrpcRuntimeWebProxyClient,
    RuntimeWebProxyClosed,
    RuntimeWebProxySession,
)
from azents.services.runtime_web.gateway_auth import RuntimeWebGatewayAuthService
from azents.services.runtime_web.gateway_authority import (
    RuntimeWebGatewayAuthorityCode,
    RuntimeWebGatewayAuthorityError,
    RuntimeWebGatewayAuthorityService,
)

_LOGGER = logging.getLogger(__name__)
_BROKER_BINDING_COOKIE = "__Host-Azents-Runtime-Web-Broker-Binding"
_SECURITY_CSP = (
    "default-src 'none'; base-uri 'none'; form-action 'self'; "
    "frame-ancestors 'none'; script-src 'nonce-runtime-web'"
)


class RuntimeWebProxyClient(Protocol):
    """Process-owned trusted Control client."""

    def open(self) -> RuntimeWebProxySession: ...

    async def close(self) -> None: ...


class RuntimeWebGatewayAuth(Protocol):
    """Authentication operations used by broker HTTP handlers."""

    async def bind_broker(
        self,
        *,
        initiation_id: str,
        now: datetime.datetime,
    ) -> RuntimeWebBrokerBinding: ...

    async def redeem_ticket(
        self,
        *,
        ticket_secret: str,
        broker_binding_secret: str,
        browser_profile: str,
        now: datetime.datetime,
    ) -> RuntimeWebRedeemedIdentity: ...


class RuntimeWebGatewayAuthorityProvider(Protocol):
    """Current endpoint and transport authority used by HTTP handlers."""

    async def resolve_endpoint(
        self,
        *,
        hostname_key: str,
    ) -> RuntimeWebEndpoint | None: ...

    async def resolve_endpoint_by_id(
        self,
        *,
        endpoint_id: str,
    ) -> RuntimeWebEndpoint | None: ...

    async def source_endpoint_matches_root(
        self,
        *,
        source_hostname_key: str,
        target_endpoint: RuntimeWebEndpoint,
    ) -> bool: ...

    async def authorize(
        self,
        *,
        hostname_key: str,
        identity_secret: str,
        browser_profile: str,
        protocol: RunnerWebProtocol,
    ) -> RuntimeWebGatewayAuthorityData: ...

    def tunnel_identity(
        self,
        *,
        authority: RuntimeWebGatewayAuthorityData,
        protocol: RunnerWebProtocol,
        now: datetime.datetime,
    ) -> RunnerWebIdentity: ...

    async def acquire_admission(
        self,
        *,
        authority: RuntimeWebGatewayAuthorityData,
        identity: RunnerWebIdentity,
        protocol: RunnerWebProtocol,
        limits: RuntimeWebAdmissionLimits,
        now: datetime.datetime,
    ) -> None: ...

    async def release_admission(self, *, tunnel_id: str) -> None: ...

    async def identity_and_access_current(
        self,
        *,
        authority: RuntimeWebGatewayAuthorityData,
    ) -> bool: ...


class _GatewayState:
    """Typed process dependencies stored in the aiohttp application."""

    def __init__(
        self,
        *,
        config: RuntimeWebGatewayConfig,
        settings: RuntimeWebGatewaySettings,
        auth: RuntimeWebGatewayAuth,
        authority: RuntimeWebGatewayAuthorityProvider,
        proxy: RuntimeWebProxyClient,
    ) -> None:
        self.config = config
        self.settings = settings
        self.auth = auth
        self.authority = authority
        self.proxy = proxy


_STATE = web.AppKey("runtime-web-gateway-state", _GatewayState)


def create_runtime_web_gateway_application(
    *,
    config: RuntimeWebGatewayConfig,
    settings: RuntimeWebGatewaySettings,
    auth: RuntimeWebGatewayAuth,
    authority: RuntimeWebGatewayAuthorityProvider,
    proxy: RuntimeWebProxyClient,
) -> web.Application:
    """Create the independently deployable Gateway HTTP application."""
    application = web.Application(
        client_max_size=config.request_body_bytes,
    )
    application[_STATE] = _GatewayState(
        config=config,
        settings=settings,
        auth=auth,
        authority=authority,
        proxy=proxy,
    )
    application.router.add_get("/__azents/ready", _ready)
    application.router.add_route("*", "/{path:.*}", _dispatch)
    return application


@asynccontextmanager
async def runtime_web_gateway_lifespan(
    settings: RuntimeWebGatewaySettings,
) -> AsyncGenerator[web.AppRunner]:
    """Create Gateway authority, transport, and HTTP server resources."""
    if not settings.runtime_web_gateway_enabled:
        raise RuntimeError("Runtime Web Gateway is disabled")
    config = RuntimeWebGatewayConfig.from_settings(settings)
    engine = _create_engine(settings)
    session_manager = _session_manager(engine)
    gateway_repository = RuntimeWebGatewayRepository()
    desired_configuration = RuntimeWebDesiredConfiguration(
        enabled=True,
        mode=config.auth_mode,
        configuration_version=config.configuration_version,
        fingerprint=settings.security_fingerprint(),
        active_duration_seconds=settings.runtime_web_gateway_active_duration_seconds,
    )
    auth = RuntimeWebGatewayAuthService(
        session_manager=session_manager,
        repository=gateway_repository,
        agent_session_repository=AgentSessionRepository(),
        workspace_user_repository=WorkspaceUserRepository(),
        identity_lifetime=datetime.timedelta(seconds=config.identity_lifetime_seconds),
        desired_configuration=desired_configuration,
        chromium_min_version=config.chromium_min_version,
        chromium_max_version=config.chromium_max_version,
    )
    await auth.synchronize_configuration(desired_configuration)
    authority = RuntimeWebGatewayAuthorityService(
        session_manager=session_manager,
        gateway_repository=gateway_repository,
        runtime_web_repository=RuntimeWebRepository(),
        agent_session_repository=AgentSessionRepository(),
        workspace_user_repository=WorkspaceUserRepository(),
        runtime_repository=AgentRuntimeRepository(),
    )
    control_endpoint = settings.runtime_web_gateway_control_endpoint
    if control_endpoint is None:
        raise RuntimeError("Runtime Web Control endpoint is required")
    proxy = GrpcRuntimeWebProxyClient.from_endpoint(
        control_endpoint,
        allow_insecure=settings.runtime_web_gateway_control_allow_insecure,
        ca_file=settings.runtime_web_gateway_control_tls_ca_file,
        certificate_file=(settings.runtime_web_gateway_control_tls_certificate_file),
        private_key_file=(settings.runtime_web_gateway_control_tls_private_key_file),
    )
    application = create_runtime_web_gateway_application(
        config=config,
        settings=settings,
        auth=auth,
        authority=authority,
        proxy=proxy,
    )
    runner = web.AppRunner(
        application,
        access_log_class=_ContentFreeAccessLogger,
    )
    await runner.setup()
    site = web.TCPSite(
        runner,
        host="0.0.0.0",
        port=settings.runtime_web_gateway_port,
    )
    await site.start()
    _LOGGER.info(
        "Runtime Web Gateway started",
        extra={
            "port": settings.runtime_web_gateway_port,
            "auth_mode": config.auth_mode.value,
            "configuration_version": config.configuration_version,
            "service_suffix": config.service_suffix,
        },
    )
    try:
        yield runner
    finally:
        await runner.cleanup()
        await proxy.close()
        await engine.dispose()


async def run_runtime_web_gateway() -> None:
    """Run the standalone Runtime Web Gateway until process termination."""
    settings = RuntimeWebGatewaySettings()
    configure_logging_for_runtime(
        runtime_env=settings.runtime_env,
        inhouse_name="azents",
        configure_uvicorn=False,
        sentry_dsn=settings.sentry_dsn,
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    async with runtime_web_gateway_lifespan(settings):
        await stop.wait()


async def _ready(request: web.Request) -> web.Response:
    state = request.app[_STATE]
    return web.json_response(
        {
            "ready": True,
            "configuration_version": state.config.configuration_version,
            "auth_mode": state.config.auth_mode.value,
        },
        headers=_security_headers(state.config),
    )


async def _dispatch(request: web.Request) -> web.StreamResponse:
    state = request.app[_STATE]
    try:
        target = parse_target_host(
            request.headers.get("Host", ""),
            config=state.config,
        )
        if target.broker:
            return await _broker(request, state)
        endpoint_key = target.endpoint_label
        if endpoint_key is None:
            raise RuntimeWebPolicyError(RuntimeWebPolicyCode.FORBIDDEN)
        return await _endpoint(request, state, endpoint_key=endpoint_key)
    except RuntimeWebPolicyError as error:
        return _policy_error(request, state.config, error.code)


async def _broker(
    request: web.Request,
    state: _GatewayState,
) -> web.StreamResponse:
    if request.path == "/bind" and request.method == "POST":
        return await _broker_bind(request, state)
    if request.path == "/redeem" and request.method == "POST":
        return await _broker_redeem(request, state)
    return _bounded_error(
        request,
        state.config,
        status=404,
        code="not_found",
    )


async def _broker_bind(
    request: web.Request,
    state: _GatewayState,
) -> web.Response:
    _require_broker_request(request, state)
    form = await request.post()
    initiation_id = form.get("initiation_id")
    if not isinstance(initiation_id, str) or len(initiation_id) != 32:
        raise RuntimeWebPolicyError(RuntimeWebPolicyCode.BAD_REQUEST)
    try:
        binding = await state.auth.bind_broker(
            initiation_id=initiation_id,
            now=datetime.datetime.now(datetime.UTC),
        )
    except RuntimeWebRepositoryConflict:
        return _bounded_error(
            request,
            state.config,
            status=409,
            code="binding_unavailable",
        )
    destination = f"{state.config.main_web_origin}/runtime-web/auth/bound"
    response = web.Response(
        text=_auto_post_document(
            destination=destination,
            fields={"initiation_id": initiation_id},
        ),
        content_type="text/html",
        headers=_security_page_headers(
            form_action=state.config.main_web_origin,
        ),
    )
    response.set_cookie(
        _BROKER_BINDING_COOKIE,
        binding.broker_binding_secret,
        secure=True,
        httponly=True,
        samesite="None",
        path="/",
        max_age=120,
    )
    return response


async def _broker_redeem(
    request: web.Request,
    state: _GatewayState,
) -> web.Response:
    _require_broker_request(request, state)
    broker_binding = _exact_cookie(request, _BROKER_BINDING_COOKIE)
    if broker_binding is None:
        return _bounded_error(
            request,
            state.config,
            status=409,
            code="binding_unavailable",
        )
    browser_profile = require_admitted_browser(
        request.headers,
        config=state.config,
    )
    form = await request.post()
    ticket = form.get("ticket")
    if not isinstance(ticket, str):
        raise RuntimeWebPolicyError(RuntimeWebPolicyCode.BAD_REQUEST)
    try:
        identity = await state.auth.redeem_ticket(
            ticket_secret=ticket,
            broker_binding_secret=broker_binding,
            browser_profile=browser_profile,
            now=datetime.datetime.now(datetime.UTC),
        )
    except RuntimeWebRepositoryConflict:
        return _bounded_error(
            request,
            state.config,
            status=409,
            code="ticket_unavailable",
        )
    endpoint = await state.authority.resolve_endpoint_by_id(
        endpoint_id=identity.endpoint_id,
    )
    if endpoint is None:
        return _bounded_error(
            request,
            state.config,
            status=404,
            code="not_found",
        )
    destination = f"{_public_scheme(state.config)}://{endpoint.hostname_key}.{state.config.service_suffix}/"
    response = web.Response(
        text=_completion_document(destination),
        content_type="text/html",
        headers=_security_page_headers(),
    )
    response.set_cookie(
        state.config.identity_cookie_name,
        identity.secret,
        domain=state.config.cookie_domain,
        secure=True,
        httponly=True,
        samesite="Strict",
        path="/",
        max_age=state.config.identity_lifetime_seconds,
    )
    response.del_cookie(
        _BROKER_BINDING_COOKIE,
        secure=True,
        httponly=True,
        samesite="None",
        path="/",
    )
    return response


async def _endpoint(
    request: web.Request,
    state: _GatewayState,
    *,
    endpoint_key: str,
) -> web.StreamResponse:
    reject_service_worker_request(request.headers)
    endpoint = await state.authority.resolve_endpoint(hostname_key=endpoint_key)
    if endpoint is None:
        return _bounded_error(
            request,
            state.config,
            status=404,
            code="not_found",
        )
    origin = request.headers.get("Origin")
    requested_method = request.headers.get("Access-Control-Request-Method")
    if request.method == "OPTIONS" and origin and requested_method:
        source_key = _source_endpoint_key(origin, state.config)
        if source_key is None or not await state.authority.source_endpoint_matches_root(
            source_hostname_key=source_key,
            target_endpoint=endpoint,
        ):
            raise RuntimeWebPolicyError(RuntimeWebPolicyCode.FORBIDDEN)
        decision = evaluate_preflight(
            origin=origin,
            requested_method=requested_method,
            requested_headers=request.headers.get("Access-Control-Request-Headers"),
            source_origins=frozenset({canonical_origin(origin)}),
        )
        return web.Response(
            status=204,
            headers=(dict(decision.headers) | _security_headers(state.config)),
        )
    browser_profile = require_admitted_browser(
        request.headers,
        config=state.config,
    )
    identity_secret = _exact_cookie(
        request,
        state.config.identity_cookie_name,
    )
    navigation = _safe_navigation(request)
    if identity_secret is None:
        if navigation:
            return _auth_navigation(state.config, endpoint.id)
        return _bounded_error(
            request,
            state.config,
            status=401,
            code="unauthenticated",
        )
    protocol = (
        RunnerWebProtocol.WEBSOCKET
        if request.headers.get("Upgrade", "").lower() == "websocket"
        else RunnerWebProtocol.HTTP
    )
    try:
        authority = await state.authority.authorize(
            hostname_key=endpoint_key,
            identity_secret=identity_secret,
            browser_profile=browser_profile,
            protocol=protocol,
        )
    except RuntimeWebGatewayAuthorityError as error:
        return _authority_error(
            request,
            state.config,
            error.code,
            endpoint_id=endpoint.id,
        )
    target_origin = (
        f"{_public_scheme(state.config)}://"
        f"{endpoint.hostname_key}.{state.config.service_suffix}"
    )
    source_origins: frozenset[str] = frozenset()
    if origin is not None and canonical_origin(origin) != target_origin:
        source_key = _source_endpoint_key(origin, state.config)
        if source_key is None or not await state.authority.source_endpoint_matches_root(
            source_hostname_key=source_key,
            target_endpoint=endpoint,
        ):
            raise RuntimeWebPolicyError(RuntimeWebPolicyCode.FORBIDDEN)
        source_origins = frozenset({canonical_origin(origin)})
    cors = evaluate_actual_origin(
        origin=origin,
        fetch_site=request.headers.get("Sec-Fetch-Site"),
        fetch_mode=request.headers.get("Sec-Fetch-Mode"),
        method=request.method,
        target_origin=target_origin,
        source_origins=source_origins,
    )
    now = datetime.datetime.now(datetime.UTC)
    identity = state.authority.tunnel_identity(
        authority=authority,
        protocol=protocol,
        now=now,
    )
    headers = normalize_request_headers(
        request.raw_headers,
        port=endpoint.port,
        target_origin=target_origin,
        maximum_bytes=state.config.request_header_bytes,
    )
    target = request.raw_path.encode("ascii", errors="strict")
    if not target.startswith(b"/") or target.startswith(b"//"):
        raise RuntimeWebPolicyError(RuntimeWebPolicyCode.BAD_REQUEST)
    head = RunnerWebRequestHead(
        identity=identity,
        protocol=protocol,
        method=request.method.encode("ascii"),
        target=target,
        headers=tuple(
            RunnerWebHeader(name=name, value=value) for name, value in headers
        ),
    )
    limits = _admission_limits(state.settings, protocol)
    try:
        await state.authority.acquire_admission(
            authority=authority,
            identity=identity,
            protocol=protocol,
            limits=limits,
            now=now,
        )
    except RuntimeWebGatewayCapacityExceeded:
        return _bounded_error(
            request,
            state.config,
            status=429,
            code="capacity_exhausted",
        )
    try:
        if protocol is RunnerWebProtocol.WEBSOCKET:
            return await _proxy_websocket(
                request,
                state,
                head=head,
                cors=cors,
                target_origin=target_origin,
                authority=authority,
            )
        return await _proxy_http(
            request,
            state,
            head=head,
            cors=cors,
            target_origin=target_origin,
            authority=authority,
        )
    finally:
        await state.authority.release_admission(tunnel_id=identity.tunnel_id)


async def _proxy_http(
    request: web.Request,
    state: _GatewayState,
    *,
    head: RunnerWebRequestHead,
    cors: RuntimeWebCorsDecision,
    target_origin: str,
    authority: RuntimeWebGatewayAuthorityData,
) -> web.StreamResponse:
    session = state.proxy.open()
    response: web.StreamResponse | None = None
    body_task: asyncio.Task[None] | None = None
    guard_task: asyncio.Task[None] | None = None
    try:
        await session.start(head)
        guard_task = asyncio.create_task(
            _guard_identity_and_access(state.authority, authority, session),
            name=f"runtime-web-authority-guard:{head.identity.tunnel_id}",
        )
        body_task = asyncio.create_task(
            _send_request_body(request, session, state.config.request_body_bytes),
            name=f"runtime-web-request-body:{head.identity.tunnel_id}",
        )
        async for frame in session.events():
            if isinstance(frame, RunnerWebResponseHead):
                if response is not None:
                    raise RuntimeWebProxyClosed(
                        "Runtime Web response head was duplicated"
                    )
                response = web.StreamResponse(
                    status=frame.status,
                    headers=normalize_response_headers(
                        ((header.name, header.value) for header in frame.headers),
                        config=state.config,
                        cors=cors,
                        target_origin=target_origin,
                        port=head.identity.port,
                    ),
                )
                await response.prepare(request)
                continue
            if isinstance(frame, RunnerWebBodyChunk):
                if response is None:
                    raise RuntimeWebProxyClosed(
                        "Runtime Web response body preceded headers"
                    )
                await response.write(frame.data)
                continue
            if isinstance(frame, RunnerWebStreamEnd):
                break
            if isinstance(frame, RunnerWebStreamError):
                if response is None:
                    return _stream_error(request, state.config, frame.code)
                break
        if body_task is not None:
            await body_task
        if response is None:
            return _bounded_error(
                request,
                state.config,
                status=502,
                code="application_unavailable",
            )
        await response.write_eof()
        return response
    except grpc.aio.AioRpcError as error:
        if response is not None:
            await response.write_eof()
            return response
        return _grpc_error(request, state.config, error)
    finally:
        if body_task is not None and not body_task.done():
            body_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await body_task
        if guard_task is not None:
            guard_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await guard_task
        await session.close()


async def _send_request_body(
    request: web.Request,
    session: RuntimeWebProxySession,
    maximum_bytes: int,
) -> None:
    sequence = 0
    total = 0
    async for data in request.content.iter_chunked(MAX_RUNTIME_WEB_FRAME_BYTES):
        total += len(data)
        if total > maximum_bytes:
            await session.send(
                RunnerWebCancel(RunnerWebCancelReason.PROTOCOL_VIOLATION)
            )
            raise RuntimeWebPolicyError(RuntimeWebPolicyCode.BAD_REQUEST)
        sequence += 1
        await session.send(RunnerWebBodyChunk(sequence=sequence, data=data))
    await session.send(RunnerWebStreamEnd(final_sequence=sequence))
    await session.finish_input()


async def _proxy_websocket(
    request: web.Request,
    state: _GatewayState,
    *,
    head: RunnerWebRequestHead,
    cors: RuntimeWebCorsDecision,
    target_origin: str,
    authority: RuntimeWebGatewayAuthorityData,
) -> web.StreamResponse:
    session = state.proxy.open()
    websocket: web.WebSocketResponse | None = None
    client_task: asyncio.Task[None] | None = None
    guard_task: asyncio.Task[None] | None = None
    try:
        await session.start(head)
        guard_task = asyncio.create_task(
            _guard_identity_and_access(state.authority, authority, session),
            name=f"runtime-web-authority-guard:{head.identity.tunnel_id}",
        )
        async for frame in session.events():
            if isinstance(frame, RunnerWebResponseHead):
                if frame.status != 101:
                    return web.Response(
                        status=frame.status,
                        headers=normalize_response_headers(
                            ((header.name, header.value) for header in frame.headers),
                            config=state.config,
                            cors=cors,
                            target_origin=target_origin,
                            port=head.identity.port,
                        ),
                    )
                websocket = web.WebSocketResponse(
                    autoping=False,
                    heartbeat=None,
                    max_msg_size=8 * 1024 * 1024,
                    compress=False,
                )
                await websocket.prepare(request)
                client_task = asyncio.create_task(
                    _send_websocket_frames(websocket, session),
                    name=f"runtime-web-websocket-input:{head.identity.tunnel_id}",
                )
                continue
            if isinstance(frame, RunnerWebSocketFrame):
                if websocket is None:
                    raise RuntimeWebProxyClosed(
                        "Runtime WebSocket frame preceded upgrade"
                    )
                await _write_websocket_frame(websocket, frame)
                continue
            if isinstance(frame, RunnerWebStreamEnd):
                break
            if isinstance(frame, RunnerWebStreamError):
                break
        if client_task is not None and not client_task.done():
            client_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await client_task
        if websocket is None:
            return _bounded_error(
                request,
                state.config,
                status=502,
                code="application_unavailable",
            )
        await websocket.close(code=1001, message=b"Runtime Web transport closed")
        return websocket
    except grpc.aio.AioRpcError as error:
        if websocket is not None:
            await websocket.close(code=1011, message=b"Runtime Web unavailable")
            return websocket
        return _grpc_error(request, state.config, error)
    finally:
        if client_task is not None and not client_task.done():
            client_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await client_task
        if guard_task is not None:
            guard_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await guard_task
        await session.close()


async def _guard_identity_and_access(
    authority_service: RuntimeWebGatewayAuthorityProvider,
    authority: RuntimeWebGatewayAuthorityData,
    session: RuntimeWebProxySession,
) -> None:
    while True:
        await asyncio.sleep(5)
        try:
            current = await authority_service.identity_and_access_current(
                authority=authority
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("Runtime Web authority revalidation failed")
            current = False
        if current:
            continue
        await session.send(RunnerWebCancel(RunnerWebCancelReason.AUTHORITY_REVOKED))
        await session.finish_input()
        return


async def _send_websocket_frames(
    websocket: web.WebSocketResponse,
    session: RuntimeWebProxySession,
) -> None:
    sequence = 0
    async for message in websocket:
        opcode = {
            WSMsgType.TEXT: RunnerWebSocketOpcode.TEXT,
            WSMsgType.BINARY: RunnerWebSocketOpcode.BINARY,
            WSMsgType.PING: RunnerWebSocketOpcode.PING,
            WSMsgType.PONG: RunnerWebSocketOpcode.PONG,
            WSMsgType.CLOSE: RunnerWebSocketOpcode.CLOSE,
        }.get(message.type)
        if opcode is None:
            if message.type in {WSMsgType.CLOSED, WSMsgType.CLOSING}:
                break
            if message.type is WSMsgType.ERROR:
                raise RuntimeWebProxyClosed("Browser WebSocket failed")
            continue
        data = _websocket_data(message, opcode)
        chunks = _websocket_chunks(data, text=opcode is RunnerWebSocketOpcode.TEXT)
        for index, chunk in enumerate(chunks):
            sequence += 1
            await session.send(
                RunnerWebSocketFrame(
                    sequence=sequence,
                    opcode=opcode,
                    final=index == len(chunks) - 1,
                    data=chunk,
                )
            )
        if opcode is RunnerWebSocketOpcode.CLOSE:
            break
    await session.send(RunnerWebStreamEnd(final_sequence=sequence))
    await session.finish_input()


async def _write_websocket_frame(
    websocket: web.WebSocketResponse,
    frame: RunnerWebSocketFrame,
) -> None:
    if frame.opcode is RunnerWebSocketOpcode.TEXT:
        await websocket.send_str(frame.data.decode("utf-8"))
    elif frame.opcode is RunnerWebSocketOpcode.BINARY:
        await websocket.send_bytes(frame.data)
    elif frame.opcode is RunnerWebSocketOpcode.PING:
        await websocket.ping(frame.data)
    elif frame.opcode is RunnerWebSocketOpcode.PONG:
        await websocket.pong(frame.data)
    elif frame.opcode is RunnerWebSocketOpcode.CLOSE:
        code = int.from_bytes(frame.data[:2], "big") if len(frame.data) >= 2 else 1000
        await websocket.close(code=code, message=frame.data[2:125])


def _websocket_data(
    message: WSMessage,
    opcode: RunnerWebSocketOpcode,
) -> bytes:
    if opcode is RunnerWebSocketOpcode.TEXT:
        if not isinstance(message.data, str):
            raise RuntimeWebProxyClosed("Browser WebSocket text is invalid")
        return message.data.encode()
    if opcode is RunnerWebSocketOpcode.CLOSE:
        code = message.data if isinstance(message.data, int) else 1000
        reason = message.extra if isinstance(message.extra, str) else ""
        return code.to_bytes(2, "big") + reason.encode()
    if not isinstance(message.data, bytes):
        raise RuntimeWebProxyClosed("Browser WebSocket bytes are invalid")
    return message.data


def _websocket_chunks(data: bytes, *, text: bool) -> tuple[bytes, ...]:
    if not data:
        return (b"",)
    chunks: list[bytes] = []
    offset = 0
    while offset < len(data):
        end = min(offset + MAX_RUNTIME_WEB_FRAME_BYTES, len(data))
        if text:
            while end < len(data) and data[end] & 0xC0 == 0x80:
                end -= 1
            if end == offset:
                raise RuntimeWebProxyClosed(
                    "Browser WebSocket text cannot be fragmented"
                )
        chunks.append(data[offset:end])
        offset = end
    return tuple(chunks)


def _require_broker_request(
    request: web.Request,
    state: _GatewayState,
) -> None:
    if request.headers.get("Origin") != state.config.main_web_origin:
        raise RuntimeWebPolicyError(RuntimeWebPolicyCode.FORBIDDEN)
    content_type = request.content_type.lower()
    if content_type != "application/x-www-form-urlencoded":
        raise RuntimeWebPolicyError(RuntimeWebPolicyCode.BAD_REQUEST)
    if not _public_request_secure(request, state.settings):
        raise RuntimeWebPolicyError(RuntimeWebPolicyCode.FORBIDDEN)


def _exact_cookie(request: web.Request, name: str) -> str | None:
    values: list[str] = []
    for header_name, header_value in request.raw_headers:
        if header_name.lower() != b"cookie":
            continue
        try:
            text = header_value.decode("latin-1")
        except UnicodeDecodeError:
            raise RuntimeWebPolicyError(RuntimeWebPolicyCode.BAD_REQUEST) from None
        for item in text.split(";"):
            cookie_name, separator, value = item.strip().partition("=")
            if separator and cookie_name == name:
                values.append(value)
    if len(values) > 1:
        raise RuntimeWebPolicyError(RuntimeWebPolicyCode.BAD_REQUEST)
    return values[0] if values else None


def _authority_error(
    request: web.Request,
    config: RuntimeWebGatewayConfig,
    code: RuntimeWebGatewayAuthorityCode,
    *,
    endpoint_id: str,
) -> web.StreamResponse:
    if code is RuntimeWebGatewayAuthorityCode.UNAUTHENTICATED:
        if _safe_navigation(request):
            return _auth_navigation(config, endpoint_id)
        return _bounded_error(request, config, status=401, code=code.value)
    if code is RuntimeWebGatewayAuthorityCode.NOT_FOUND:
        return _bounded_error(request, config, status=404, code=code.value)
    if code is RuntimeWebGatewayAuthorityCode.PENDING_APPROVAL:
        if _safe_navigation(request):
            return _confirmation_navigation(config, endpoint_id)
        return _bounded_error(request, config, status=409, code=code.value)
    if code is RuntimeWebGatewayAuthorityCode.GONE:
        return _bounded_error(request, config, status=410, code=code.value)
    return _bounded_error(request, config, status=503, code=code.value)


def _policy_error(
    request: web.Request,
    config: RuntimeWebGatewayConfig,
    code: RuntimeWebPolicyCode,
) -> web.Response:
    status = {
        RuntimeWebPolicyCode.BAD_REQUEST: 400,
        RuntimeWebPolicyCode.FORBIDDEN: 403,
        RuntimeWebPolicyCode.HEADER_TOO_LARGE: 431,
        RuntimeWebPolicyCode.METHOD_NOT_ALLOWED: 405,
        RuntimeWebPolicyCode.UPGRADE_REQUIRED: 426,
    }[code]
    return _bounded_error(request, config, status=status, code=code.value)


def _stream_error(
    request: web.Request,
    config: RuntimeWebGatewayConfig,
    code: RunnerWebStreamErrorCode,
) -> web.Response:
    status = {
        RunnerWebStreamErrorCode.APPLICATION_UNAVAILABLE: 502,
        RunnerWebStreamErrorCode.TRANSPORT_UNAVAILABLE: 503,
        RunnerWebStreamErrorCode.RESOURCE_EXHAUSTED: 429,
        RunnerWebStreamErrorCode.DEADLINE_EXCEEDED: 410,
    }.get(code, 409)
    return _bounded_error(request, config, status=status, code=code.value)


def _grpc_error(
    request: web.Request,
    config: RuntimeWebGatewayConfig,
    error: grpc.aio.AioRpcError,
) -> web.Response:
    status = {
        grpc.StatusCode.RESOURCE_EXHAUSTED: 429,
        grpc.StatusCode.DEADLINE_EXCEEDED: 410,
        grpc.StatusCode.UNAVAILABLE: 503,
    }.get(error.code(), 409)
    return _bounded_error(
        request,
        config,
        status=status,
        code="transport_unavailable",
    )


def _bounded_error(
    request: web.Request,
    config: RuntimeWebGatewayConfig,
    *,
    status: int,
    code: str,
) -> web.Response:
    headers = _security_headers(config)
    if _safe_navigation(request):
        return web.Response(
            status=status,
            text=(
                "<!doctype html><meta charset=utf-8>"
                f"<title>Runtime Web</title><h1>{html.escape(code)}</h1>"
            ),
            content_type="text/html",
            headers=headers | {"Content-Security-Policy": _SECURITY_CSP},
        )
    return web.json_response(
        {"code": code},
        status=status,
        headers=headers,
    )


def _auth_navigation(
    config: RuntimeWebGatewayConfig,
    endpoint_id: str,
) -> web.Response:
    destination = (
        f"{config.main_web_origin}/runtime-web/auth?"
        f"endpoint_id={urllib.parse.quote(endpoint_id, safe='')}"
    )
    return web.HTTPSeeOther(
        destination,
        headers=_security_headers(config),
    )


def _confirmation_navigation(
    config: RuntimeWebGatewayConfig,
    endpoint_id: str,
) -> web.Response:
    destination = (
        f"{config.main_web_origin}/runtime-web/confirm?"
        f"endpoint_id={urllib.parse.quote(endpoint_id, safe='')}"
    )
    return web.HTTPSeeOther(
        destination,
        headers=_security_headers(config),
    )


def _safe_navigation(request: web.Request) -> bool:
    return (
        request.method in {"GET", "HEAD"}
        and request.headers.get("Sec-Fetch-Mode") == "navigate"
        and request.headers.get("Sec-Fetch-Dest") == "document"
    )


def _security_headers(config: RuntimeWebGatewayConfig) -> dict[str, str]:
    return {
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
        "X-Frame-Options": "DENY",
        "Cross-Origin-Opener-Policy": "same-origin",
        "Permissions-Policy": config.permissions_policy,
    }


def _security_page_headers(
    *,
    form_action: str = "'self'",
) -> dict[str, str]:
    csp = _SECURITY_CSP.replace("form-action 'self'", f"form-action {form_action}")
    return {
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
        "X-Frame-Options": "DENY",
        "Content-Security-Policy": csp,
    }


def _auto_post_document(
    *,
    destination: str,
    fields: Mapping[str, str],
) -> str:
    inputs = "".join(
        f'<input type="hidden" name="{html.escape(name)}" value="{html.escape(value)}">'
        for name, value in fields.items()
    )
    return (
        "<!doctype html><meta charset=utf-8><title>Runtime Web</title>"
        f'<form id="continue" method="post" action="{html.escape(destination)}">'
        f"{inputs}</form>"
        '<script nonce="runtime-web">document.getElementById("continue").submit()'
        "</script>"
    )


def _completion_document(destination: str) -> str:
    encoded = html.escape(destination)
    return (
        "<!doctype html><meta charset=utf-8><title>Runtime Web</title>"
        f'<a id="continue" href="{encoded}">Continue</a>'
        '<script nonce="runtime-web">document.getElementById("continue").click()'
        "</script>"
    )


def _public_scheme(config: RuntimeWebGatewayConfig) -> str:
    return urllib.parse.urlparse(config.broker_origin).scheme


def _source_endpoint_key(
    origin: str,
    config: RuntimeWebGatewayConfig,
) -> str | None:
    canonical = canonical_origin(origin)
    parsed = urllib.parse.urlparse(canonical)
    if parsed.scheme != _public_scheme(config) or parsed.port is not None:
        return None
    try:
        target = parse_target_host(parsed.netloc, config=config)
    except RuntimeWebPolicyError:
        return None
    if target.broker:
        return None
    return target.endpoint_label


def _admission_limits(
    settings: RuntimeWebGatewaySettings,
    protocol: RunnerWebProtocol,
) -> RuntimeWebAdmissionLimits:
    if protocol is RunnerWebProtocol.WEBSOCKET:
        return RuntimeWebAdmissionLimits(
            endpoint=(settings.runtime_web_gateway_websocket_endpoint_connections),
            user=settings.runtime_web_gateway_websocket_user_connections,
            agent=settings.runtime_web_gateway_websocket_agent_connections,
        )
    return RuntimeWebAdmissionLimits(
        endpoint=settings.runtime_web_gateway_http_endpoint_connections,
        user=settings.runtime_web_gateway_http_user_connections,
        agent=settings.runtime_web_gateway_http_agent_connections,
    )


def _public_request_secure(
    request: web.Request,
    settings: RuntimeWebGatewaySettings,
) -> bool:
    if request.secure or request.headers.get("X-Forwarded-Proto") == "https":
        return True
    return (
        settings.runtime_env.value == "local"
        and settings.runtime_web_gateway_control_allow_insecure
    )


class _ContentFreeAccessLogger(web.AbstractAccessLogger):
    """Log status and duration without paths, queries, headers, or cookies."""

    def log(
        self,
        request: web.BaseRequest,
        response: web.StreamResponse,
        time: float,
    ) -> None:
        self.logger.info(
            "Runtime Web request completed",
            extra={
                "method": request.method,
                "status": response.status,
                "duration_seconds": time,
            },
        )


def _postgres_config(
    settings: RuntimeWebGatewaySettings,
) -> PostgreSQLConfig:
    return PostgreSQLConfig(
        host=settings.rdb_host,
        port=settings.rdb_port,
        user=settings.rdb_user,
        password=settings.rdb_password,
        db_name=settings.rdb_db_name,
        use_iam_auth=settings.rdb_use_iam_auth,
        region=settings.rdb_region,
        ssl_mode=settings.rdb_ssl_mode,
        verbose=settings.rdb_verbose,
    )


def _create_engine(settings: RuntimeWebGatewaySettings) -> AsyncEngine:
    database = _postgres_config(settings)
    if database.use_iam_auth:
        rds_client: RDSClient = boto3.client("rds", region_name=database.region)
        engine = create_async_engine(
            database.get_sqlalchemy_uri(),
            connect_args={"sslmode": database.ssl_mode},
            echo=database.verbose,
            pool_pre_ping=True,
        )

        def _provide_token(
            dialect: object,
            conn_rec: object,
            cargs: object,
            cparams: dict[str, object],
        ) -> None:
            del dialect, conn_rec, cargs
            cparams["password"] = rds_client.generate_db_auth_token(
                DBHostname=database.host,
                Port=database.port,
                DBUsername=database.user,
                Region=database.region,
            )

        event.listen(engine.sync_engine, "do_connect", _provide_token)
        return engine
    return create_async_engine(
        database.get_sqlalchemy_uri(with_password=True),
        connect_args={"sslmode": database.ssl_mode},
        echo=database.verbose,
        pool_pre_ping=True,
    )


def _session_manager(
    engine: AsyncEngine,
) -> SessionManager[AsyncSession]:
    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession]:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            else:
                await session.commit()

    return session_manager
