"""Independent aiohttp Runtime Web Gateway process."""

import asyncio
import contextlib
import datetime
import html
import itertools
import logging
import os
import secrets
import signal
import sys
import urllib.parse
from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Protocol

import boto3
from aiohttp import WSMessage, WSMsgType, web
from azcommon.logging import configure_logging_for_runtime
from azents_runtime_control.runtime_web_session import (
    MANDATORY_DATA_FRAME_BYTES,
    MAX_WEBSOCKET_MESSAGE_BYTES,
    CloseReason,
    Header,
    RequestHead,
    StreamAuthority,
    StreamProtocol,
    WebSocketOpcode,
)
from mypy_boto3_rds import RDSClient
from sqlalchemy import event
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from azents.core.config import PostgreSQLConfig
from azents.rdb.session import SessionManager
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.runtime_web.data import RuntimeWebEndpoint
from azents.repos.runtime_web.gateway_data import (
    RuntimeWebBrokerBinding,
    RuntimeWebDesiredConfiguration,
    RuntimeWebRedeemedIdentity,
)
from azents.repos.runtime_web.gateway_data import (
    RuntimeWebGatewayAuthority as RuntimeWebGatewayAuthorityData,
)
from azents.repos.runtime_web.gateway_repository import (
    RuntimeWebGatewayRepository,
)
from azents.repos.runtime_web.repository import (
    RuntimeWebRepository,
    RuntimeWebRepositoryConflict,
)
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.runtime_web_gateway.operations import (
    RuntimeWebCapacityBackend,
    RuntimeWebDrainCoordinator,
    RuntimeWebDrainPolicy,
    RuntimeWebDrainRegistration,
    RuntimeWebDrainStreamKind,
    RuntimeWebGatewayDependencyEvidence,
    RuntimeWebGatewayHardLimits,
    RuntimeWebGatewayHealth,
    RuntimeWebGatewayOperationalState,
    RuntimeWebGatewayOperationsCoordinator,
    RuntimeWebGatewayPressure,
    RuntimeWebGatewayResourceTracker,
    render_openmetrics,
)
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
)
from azents.runtime_web_gateway.session_runtime import (
    RuntimeWebGatewayControlSessions,
)
from azents.runtime_web_gateway.settings import (
    RuntimeWebGatewayConfig,
    RuntimeWebGatewaySettings,
)
from azents.runtime_web_gateway.web_session_bridge import (
    BrowserStreamEvent,
    RuntimeWebBrowserStreamBridge,
    RuntimeWebGatewayResourceExhausted,
    RuntimeWebOpenRejected,
)
from azents.runtime_web_gateway.web_session_pool import RuntimeWebGatewaySessionPool
from azents.services.runtime_web.gateway_auth import RuntimeWebGatewayAuthService
from azents.services.runtime_web.gateway_authority import (
    RuntimeWebGatewayAuthorityCode,
    RuntimeWebGatewayAuthorityError,
    RuntimeWebGatewayAuthorityService,
)

_LOGGER = logging.getLogger(__name__)
_BROKER_BINDING_COOKIE = "__Host-Azents-Runtime-Web-Broker-Binding"
_WEBSOCKET_SUBPROTOCOL_HEADER = b"sec-websocket-protocol"
_WEBSOCKET_TOKEN_BYTES = frozenset(
    b"!#$%&'*+-.^_`|~0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
)
_SECURITY_CSP = (
    "default-src 'none'; base-uri 'none'; form-action 'self'; "
    "frame-ancestors 'none'; script-src 'nonce-runtime-web'"
)


class RuntimeWebResidentMemorySampler(Protocol):
    """Return current process resident memory without lifetime high-water state."""

    def current_bytes(self) -> int: ...


class _RuntimeWebSocketSubprotocolError(ValueError):
    """One bounded WebSocket subprotocol handshake rejection."""


class LinuxProcResidentMemorySampler:
    """Read current Linux resident pages from one injected procfs statm path."""

    def __init__(self, *, statm_path: Path, page_size_bytes: int) -> None:
        if page_size_bytes <= 0:
            raise ValueError("Runtime Web RSS page size must be positive")
        self.statm_path = statm_path
        self.page_size_bytes = page_size_bytes

    def current_bytes(self) -> int:
        """Return current RSS bytes from the Linux procfs resident-page field."""
        try:
            fields = self.statm_path.read_text(encoding="ascii").split()
        except OSError as error:
            raise RuntimeError(
                "Runtime Web current RSS sample is unavailable"
            ) from error
        if len(fields) < 2:
            raise RuntimeError("Runtime Web current RSS sample is invalid")
        try:
            resident_pages = int(fields[1])
        except ValueError as error:
            raise RuntimeError("Runtime Web current RSS sample is invalid") from error
        if resident_pages < 0:
            raise RuntimeError("Runtime Web current RSS sample is invalid")
        return resident_pages * self.page_size_bytes


def create_runtime_web_resident_memory_sampler(
    *,
    platform: str,
) -> RuntimeWebResidentMemorySampler:
    """Select one explicit current-RSS backend or fail safely."""
    if platform.startswith("linux"):
        return LinuxProcResidentMemorySampler(
            statm_path=Path("/proc/self/statm"),
            page_size_bytes=int(os.sysconf("SC_PAGE_SIZE")),
        )
    raise RuntimeError(
        f"Runtime Web current RSS sampling is unsupported on platform {platform!r}"
    )


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
        now: datetime.datetime,
    ) -> RuntimeWebRedeemedIdentity: ...


class RuntimeWebGatewaySessionProvider(Protocol):
    """Active replacement Control sessions used by public dispatch."""

    pool: RuntimeWebGatewaySessionPool


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
        protocol: StreamProtocol,
    ) -> RuntimeWebGatewayAuthorityData: ...

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
        control_sessions: RuntimeWebGatewaySessionProvider,
        operations: RuntimeWebGatewayOperationsCoordinator,
        operational_state: RuntimeWebGatewayOperationalState,
    ) -> None:
        self.config = config
        self.settings = settings
        self.auth = auth
        self.authority = authority
        self.control_sessions = control_sessions
        self.operations = operations
        self.operational_state = operational_state
        self.stream_ids = itertools.count(1)

    def next_stream_id(self) -> int:
        """Allocate one process-lifetime non-reusable logical stream ID."""
        return next(self.stream_ids)


_STATE = web.AppKey("runtime-web-gateway-state", _GatewayState)


class _OperationsState:
    """Typed dependencies exposed only by the internal operations server."""

    def __init__(
        self,
        *,
        config: RuntimeWebGatewayConfig,
        state: RuntimeWebGatewayOperationalState,
        operations: RuntimeWebGatewayOperationsCoordinator,
    ) -> None:
        self.config = config
        self.state = state
        self.operations = operations


_OPERATIONS_STATE = web.AppKey("runtime-web-gateway-operations", _OperationsState)


def create_runtime_web_gateway_application(
    *,
    config: RuntimeWebGatewayConfig,
    settings: RuntimeWebGatewaySettings,
    auth: RuntimeWebGatewayAuth,
    authority: RuntimeWebGatewayAuthorityProvider,
    control_sessions: RuntimeWebGatewaySessionProvider,
    operations: RuntimeWebGatewayOperationsCoordinator,
    operational_state: RuntimeWebGatewayOperationalState,
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
        control_sessions=control_sessions,
        operations=operations,
        operational_state=operational_state,
    )
    application.router.add_route("*", "/{path:.*}", _dispatch)
    return application


def create_runtime_web_gateway_operations_application(
    *,
    config: RuntimeWebGatewayConfig,
    state: RuntimeWebGatewayOperationalState,
    operations: RuntimeWebGatewayOperationsCoordinator,
) -> web.Application:
    """Create the internal-only health, metrics, and drain application."""
    application = web.Application(client_max_size=1024)
    application[_OPERATIONS_STATE] = _OperationsState(
        config=config,
        state=state,
        operations=operations,
    )
    application.router.add_get("/__azents/ready", _ready)
    application.router.add_get("/__azents/live", _live)
    application.router.add_get("/__azents/metrics", _metrics)
    application.router.add_route("*", "/__azents/drain", _drain)
    return application


@asynccontextmanager
async def runtime_web_gateway_lifespan(
    settings: RuntimeWebGatewaySettings,
) -> AsyncGenerator[web.AppRunner]:
    """Create Gateway authority, transport, and HTTP server resources."""
    if not settings.runtime_web_gateway_enabled:
        raise RuntimeError("Runtime Web Gateway is disabled")
    config = RuntimeWebGatewayConfig.from_settings(settings)
    resident_memory_sampler = create_runtime_web_resident_memory_sampler(
        platform=sys.platform,
    )
    engine = _create_engine(settings)
    session_manager = _session_manager(engine)
    gateway_repository = RuntimeWebGatewayRepository()
    desired_configuration = RuntimeWebDesiredConfiguration(
        enabled=True,
        mode=config.auth_mode,
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
    resources = RuntimeWebGatewayResourceTracker(
        RuntimeWebGatewayHardLimits(
            maximum_active_exchanges=(
                settings.runtime_web_gateway_maximum_active_exchanges
            ),
            maximum_application_buffer_bytes=(
                settings.runtime_web_gateway_maximum_application_buffer_bytes
            ),
            maximum_control_buffer_bytes=(
                settings.runtime_web_gateway_maximum_control_buffer_bytes
            ),
            maximum_pending_tasks=(settings.runtime_web_gateway_maximum_pending_tasks),
            maximum_scheduler_waiters=(
                settings.runtime_web_gateway_maximum_scheduler_waiters
            ),
            maximum_event_loop_lag_milliseconds=(
                settings.runtime_web_gateway_maximum_event_loop_lag_milliseconds
            ),
            maximum_resident_memory_bytes=(
                settings.runtime_web_gateway_maximum_resident_memory_bytes
            ),
        )
    )
    control_sessions = RuntimeWebGatewayControlSessions.from_endpoint(
        control_endpoint,
        allow_insecure=settings.runtime_web_gateway_control_allow_insecure,
        ca_file=settings.runtime_web_gateway_control_tls_ca_file,
        certificate_file=(settings.runtime_web_gateway_control_tls_certificate_file),
        private_key_file=(settings.runtime_web_gateway_control_tls_private_key_file),
        session_count=settings.runtime_web_gateway_control_session_pool_size,
        resources=resources,
    )
    await control_sessions.start()
    operational_state = RuntimeWebGatewayOperationalState(
        health=RuntimeWebGatewayHealth(
            configuration_valid=True,
            maintenance=settings.runtime_web_gateway_maintenance,
            draining=False,
            authority_query_available=False,
            replacement_protocol_compatible=False,
            local_pressure_acceptable=True,
            event_loop_responsive=True,
            redis_available=True,
        ),
        pressure=RuntimeWebGatewayPressure(0, 0, 0, 0, 0),
        backend=RuntimeWebCapacityBackend.MEMORY,
        capacity_degraded=False,
        resources=resources,
        local_open_count=0,
        relay_open_count=0,
        event_loop_lag_milliseconds=0,
        resident_memory_bytes=0,
    )
    drain = RuntimeWebDrainCoordinator(
        policy=RuntimeWebDrainPolicy(),
        resources=resources,
        begin_session_drain=control_sessions.begin_drain,
    )
    operations = RuntimeWebGatewayOperationsCoordinator(
        state=operational_state,
        drain=drain,
    )
    application = create_runtime_web_gateway_application(
        config=config,
        settings=settings,
        auth=auth,
        authority=authority,
        control_sessions=control_sessions,
        operations=operations,
        operational_state=operational_state,
    )
    operations_application = create_runtime_web_gateway_operations_application(
        config=config,
        state=operational_state,
        operations=operations,
    )
    runner = create_runtime_web_gateway_public_runner(application)
    operations_runner = web.AppRunner(
        operations_application,
        access_log_class=_ContentFreeAccessLogger,
    )
    await runner.setup()
    await operations_runner.setup()
    site = web.TCPSite(
        runner,
        host="0.0.0.0",
        port=settings.runtime_web_gateway_port,
    )
    operations_site = web.TCPSite(
        operations_runner,
        host="0.0.0.0",
        port=settings.runtime_web_gateway_metrics_port,
    )
    await site.start()
    await operations_site.start()
    sampler = asyncio.create_task(
        _refresh_operational_state(
            engine=engine,
            control_sessions=control_sessions,
            state=operational_state,
            resident_memory_sampler=resident_memory_sampler,
        ),
        name="runtime-web-gateway-operational-state",
    )
    _LOGGER.info(
        "Runtime Web Gateway started",
        extra={
            "port": settings.runtime_web_gateway_port,
            "operations_port": settings.runtime_web_gateway_metrics_port,
            "auth_mode": config.auth_mode.value,
            "service_suffix": config.service_suffix,
        },
    )
    try:
        yield runner
    finally:
        await operations.drain()
        sampler.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sampler
        await runner.cleanup()
        await operations_runner.cleanup()
        await control_sessions.close()
        await engine.dispose()


def create_runtime_web_gateway_public_runner(
    application: web.Application,
) -> web.AppRunner:
    """Create the public runner with immediate disconnected-handler cancellation."""
    return web.AppRunner(
        application,
        access_log_class=_ContentFreeAccessLogger,
        handler_cancellation=True,
    )


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
    operations = request.app[_OPERATIONS_STATE]
    state = operations.state
    state.refresh_resource_pressure()
    return web.json_response(
        {
            "ready": state.health.ready,
            "auth_mode": operations.config.auth_mode.value,
        },
        status=200 if state.health.ready else 503,
        headers=_security_headers(operations.config),
    )


async def _live(request: web.Request) -> web.Response:
    operations = request.app[_OPERATIONS_STATE]
    return web.json_response(
        {"live": operations.state.health.live},
        status=200 if operations.state.health.live else 503,
        headers=_security_headers(operations.config),
    )


async def _metrics(request: web.Request) -> web.Response:
    operations = request.app[_OPERATIONS_STATE]
    operations.state.refresh_resource_pressure()
    resources = operations.state.resources.snapshot()
    limits = operations.state.resources.limits
    return web.Response(
        text=render_openmetrics(
            pressure=operations.state.pressure,
            health=operations.state.health,
            backend=operations.state.backend,
            capacity_degraded=operations.state.capacity_degraded,
            active_exchanges=resources.active_exchanges,
            local_open_count=operations.state.local_open_count,
            relay_open_count=operations.state.relay_open_count,
            application_buffer_bytes=resources.application_buffer_bytes,
            application_buffer_limit_bytes=(limits.maximum_application_buffer_bytes),
            control_buffer_bytes=resources.control_buffer_bytes,
            scheduler_waiters=resources.scheduler_waiters,
            scheduler_waiter_limit=limits.maximum_scheduler_waiters,
            resident_memory_bytes=operations.state.resident_memory_bytes,
            resident_memory_limit_bytes=limits.maximum_resident_memory_bytes,
            transport=operations.state.resources,
        ),
        content_type="text/plain",
    )


async def _drain(request: web.Request) -> web.Response:
    operations = request.app[_OPERATIONS_STATE]
    result = await operations.operations.drain()
    return web.json_response(
        {
            "gracefully_closed": len(result.gracefully_closed),
            "force_closed": len(result.force_closed),
            "callback_failures": len(result.callback_failures),
        },
        headers=_security_headers(operations.config),
    )


async def _refresh_operational_state(
    *,
    engine: AsyncEngine,
    control_sessions: RuntimeWebGatewayControlSessions,
    state: RuntimeWebGatewayOperationalState,
    resident_memory_sampler: RuntimeWebResidentMemorySampler,
) -> None:
    """Refresh durable authority, exact peer, event-loop, and RSS evidence."""
    loop = asyncio.get_running_loop()
    expected = loop.time()
    while True:
        expected += 0.25
        await asyncio.sleep(max(0.0, expected - loop.time()))
        observed = loop.time()
        lag_milliseconds = max(0.0, (observed - expected) * 1000)
        state.update_process_pressure(
            event_loop_lag_milliseconds=lag_milliseconds,
            resident_memory_bytes=resident_memory_sampler.current_bytes(),
        )
        if int(observed * 4) % 20 != 0:
            continue
        try:
            async with engine.connect() as connection:
                await connection.execute(sql_text("SELECT 1"))
            authority_available = True
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("Runtime Web authority readiness query failed")
            authority_available = False
        fingerprints = await control_sessions.compatible_fingerprints()
        state.update_dependencies(
            evidence=RuntimeWebGatewayDependencyEvidence.from_observation(
                authority_query_succeeded=authority_available,
                control_protocol_fingerprints=fingerprints,
            ),
            redis_available=True,
        )


async def _dispatch(request: web.Request) -> web.StreamResponse:
    state = request.app[_STATE]
    if state.operational_state.health.maintenance:
        return _bounded_error(
            request,
            state.config,
            status=503,
            code="maintenance",
        )
    if state.operational_state.health.draining:
        return _bounded_error(
            request,
            state.config,
            status=503,
            code=CloseReason.SERVICE_DRAIN.value,
        )
    if state.operational_state.current_pressure().value >= 1.0:
        return _bounded_error(
            request,
            state.config,
            status=429,
            code=CloseReason.RESOURCE_EXHAUSTED.value,
        )
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
            referrer_policy="strict-origin",
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
    form = await request.post()
    ticket = form.get("ticket")
    if not isinstance(ticket, str):
        raise RuntimeWebPolicyError(RuntimeWebPolicyCode.BAD_REQUEST)
    try:
        identity = await state.auth.redeem_ticket(
            ticket_secret=ticket,
            broker_binding_secret=broker_binding,
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
    identity_secret = _exact_cookie(
        request,
        state.config.identity_cookie_name,
    )
    protocol = (
        StreamProtocol.WEBSOCKET
        if request.headers.get("Upgrade", "").lower() == "websocket"
        else StreamProtocol.HTTP
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
    try:
        authority = await state.authority.authorize(
            hostname_key=endpoint_key,
            identity_secret=identity_secret,
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
    headers = normalize_request_headers(
        request.raw_headers,
        port=endpoint.port,
        target_origin=target_origin,
        maximum_bytes=state.config.request_header_bytes,
    )
    target = request.raw_path.encode("ascii", errors="strict")
    if not target.startswith(b"/") or target.startswith(b"//"):
        raise RuntimeWebPolicyError(RuntimeWebPolicyCode.BAD_REQUEST)
    stream_authority = _stream_authority(
        authority=authority,
        protocol=protocol,
        now=now,
    )
    head = RequestHead(
        protocol=protocol,
        method=request.method.encode("ascii"),
        target=target,
        headers=tuple(Header(name=name, value=value) for name, value in headers),
    )
    bridge_box: list[RuntimeWebBrowserStreamBridge | None] = [None]

    async def _graceful_close(reason: CloseReason) -> None:
        bridge = bridge_box[0]
        if bridge is not None:
            await bridge.cancel(reason)

    registration = await state.operations.drain_coordinator.register(
        kind=(
            RuntimeWebDrainStreamKind.LONG_LIVED
            if protocol is StreamProtocol.WEBSOCKET
            else RuntimeWebDrainStreamKind.FINITE_HTTP
        ),
        request_graceful_close=_graceful_close,
        force_close=_graceful_close,
    )
    if registration is None:
        return _bounded_error(
            request,
            state.config,
            status=429,
            code=CloseReason.RESOURCE_EXHAUSTED.value,
        )
    try:
        bridge = await RuntimeWebBrowserStreamBridge.open(
            pool=state.control_sessions.pool,
            stream_id=state.next_stream_id(),
            authority=stream_authority,
            request_head=head,
        )
        bridge_box[0] = bridge
        await bridge.wait_accepted(
            timeout_seconds=max(
                0.001,
                (stream_authority.open_deadline_at - now).total_seconds(),
            ),
        )
        assert bridge.route is not None
        state.operational_state.record_route(bridge.route)
        if protocol is StreamProtocol.WEBSOCKET:
            return await _proxy_websocket(
                request,
                state,
                bridge=bridge,
                head=head,
                cors=cors,
                target_origin=target_origin,
                authority=authority,
            )
        return await _proxy_http(
            request,
            state,
            bridge=bridge,
            head=head,
            registration=registration,
            cors=cors,
            target_origin=target_origin,
            authority=authority,
        )
    except RuntimeWebOpenRejected as error:
        return _stream_error(request, state.config, error.reason)
    except RuntimeWebGatewayResourceExhausted:
        return _stream_error(request, state.config, CloseReason.RESOURCE_EXHAUSTED)
    except RuntimeError, TimeoutError:
        return _bounded_error(
            request,
            state.config,
            status=503,
            code=CloseReason.TRANSPORT_UNAVAILABLE.value,
        )
    finally:
        try:
            bridge = bridge_box[0]
            if bridge is not None and not bridge.released:
                with contextlib.suppress(RuntimeError):
                    await bridge.cancel()
        finally:
            await state.operations.drain_coordinator.release(registration)


async def _proxy_http(
    request: web.Request,
    state: _GatewayState,
    *,
    bridge: RuntimeWebBrowserStreamBridge,
    head: RequestHead,
    registration: RuntimeWebDrainRegistration,
    cors: RuntimeWebCorsDecision,
    target_origin: str,
    authority: RuntimeWebGatewayAuthorityData,
) -> web.StreamResponse:
    response: web.StreamResponse | None = None
    body_task: asyncio.Task[None] | None = None
    event_task: asyncio.Task[BrowserStreamEvent] | None = None
    guard_task: asyncio.Task[None] | None = None
    try:
        guard_task = asyncio.create_task(
            _guard_identity_and_access(state.authority, authority, bridge),
            name=f"runtime-web-authority-guard:{bridge.binding.stream_id}",
        )
        body_task = asyncio.create_task(
            _send_request_body(
                request,
                bridge,
                state.operational_state.resources,
                state.config.request_body_bytes,
            ),
            name=f"runtime-web-request-body:{bridge.binding.stream_id}",
        )
        while True:
            event_task = asyncio.create_task(bridge.next_event())
            if body_task is not None:
                done, _ = await asyncio.wait(
                    (body_task, event_task),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if body_task in done:
                    await body_task
                    body_task = None
            event = await event_task
            event_task = None
            if event.payload == "response_head":
                try:
                    if response is not None:
                        raise RuntimeError("Runtime Web response head was duplicated")
                    if event.status is None:
                        raise RuntimeError("Runtime Web response status is absent")
                    if _response_is_sse(event.headers):
                        await state.operations.drain_coordinator.reclassify(
                            registration,
                            kind=RuntimeWebDrainStreamKind.LONG_LIVED,
                        )
                    response = web.StreamResponse(
                        status=event.status,
                        headers=normalize_response_headers(
                            ((header.name, header.value) for header in event.headers),
                            config=state.config,
                            cors=cors,
                            target_origin=target_origin,
                            port=authority.endpoint.port,
                        ),
                    )
                    await response.prepare(request)
                finally:
                    await bridge.release_event(event)
                continue
            if event.payload == "data":
                if response is None:
                    raise RuntimeError("Runtime Web response body preceded headers")
                written = False
                try:
                    await response.write(event.data)
                    written = True
                finally:
                    if written:
                        await bridge.release_event(event)
                    else:
                        await bridge.discard_event(event)
                continue
            if event.payload == "direction_end":
                await bridge.release_event(event)
                continue
            if event.payload == "terminal":
                await bridge.release_event(event)
                if event.terminal_reason is not None and response is None:
                    return _stream_error(request, state.config, event.terminal_reason)
                break
            await bridge.release_event(event)
            raise RuntimeError("Runtime Web HTTP event is invalid")
        if response is None:
            return _bounded_error(
                request,
                state.config,
                status=502,
                code=CloseReason.APPLICATION_UNAVAILABLE.value,
            )
        await response.write_eof()
        return response
    finally:
        if event_task is not None:
            if not event_task.done():
                event_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await event_task
            elif not event_task.cancelled() and event_task.exception() is None:
                await bridge.discard_event(event_task.result())
        if body_task is not None and not body_task.done():
            body_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await body_task
        if guard_task is not None:
            guard_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await guard_task
        await bridge.discard_buffered_events()


def _response_is_sse(headers: tuple[Header, ...]) -> bool:
    """Return whether the normalized response is an SSE stream."""
    for header in headers:
        if header.name.lower() == b"content-type":
            return (
                header.value.split(b";", 1)[0].strip().lower() == b"text/event-stream"
            )
    return False


def _websocket_subprotocol_tokens(
    headers: tuple[tuple[bytes, bytes], ...],
) -> tuple[str, ...]:
    """Return ordered case-preserved RFC tokens from subprotocol fields."""
    tokens: list[str] = []
    seen: set[str] = set()
    field_seen = False
    for name, value in headers:
        if name.lower() != _WEBSOCKET_SUBPROTOCOL_HEADER:
            continue
        if field_seen:
            raise _RuntimeWebSocketSubprotocolError(
                "Runtime WebSocket subprotocol field is repeated"
            )
        field_seen = True
        for item in value.split(b","):
            token = item.strip(b" \t")
            if not token or any(byte not in _WEBSOCKET_TOKEN_BYTES for byte in token):
                raise _RuntimeWebSocketSubprotocolError(
                    "Runtime WebSocket subprotocol is invalid"
                )
            protocol = token.decode("ascii")
            if protocol in seen:
                raise _RuntimeWebSocketSubprotocolError(
                    "Runtime WebSocket subprotocol is duplicated"
                )
            seen.add(protocol)
            tokens.append(protocol)
    return tuple(tokens)


def _selected_websocket_subprotocol(
    *,
    offered: tuple[str, ...],
    response_headers: tuple[Header, ...],
) -> str | None:
    """Validate one exact replacement-selected browser subprotocol."""
    selected = _websocket_subprotocol_tokens(
        tuple((header.name, header.value) for header in response_headers)
    )
    if len(selected) > 1:
        raise _RuntimeWebSocketSubprotocolError(
            "Runtime WebSocket selected subprotocol is duplicated"
        )
    if not selected:
        return None
    protocol = selected[0]
    if protocol not in offered:
        raise _RuntimeWebSocketSubprotocolError(
            "Runtime WebSocket selected subprotocol was not offered"
        )
    return protocol


def _stream_authority(
    *,
    authority: RuntimeWebGatewayAuthorityData,
    protocol: StreamProtocol,
    now: datetime.datetime,
) -> StreamAuthority:
    """Create one exact non-replayable replacement stream authority."""
    cycle = authority.cycle
    runtime_id = authority.runtime_id
    desired_generation = authority.desired_generation
    runner_generation = authority.runner_generation
    if (
        cycle is None
        or runtime_id is None
        or desired_generation is None
        or runner_generation is None
    ):
        raise RuntimeWebGatewayAuthorityError(
            RuntimeWebGatewayAuthorityCode.RUNTIME_UNAVAILABLE
        )
    transport_deadline = (
        min(cycle.expires_at, now + datetime.timedelta(minutes=30))
        if protocol is StreamProtocol.HTTP
        else cycle.expires_at
    )
    return StreamAuthority(
        correlation_id=secrets.token_hex(32),
        endpoint_id=authority.endpoint.id,
        cycle_id=cycle.id,
        endpoint_authority_revision=authority.endpoint.authority_revision,
        close_barrier=authority.endpoint.close_barrier,
        identity_id=authority.identity.id,
        authentication_session_id=authority.identity.auth_session_id,
        user_id=authority.identity.user_id,
        agent_session_id=authority.endpoint.agent_session_id,
        runtime_id=runtime_id,
        desired_generation=desired_generation,
        runner_generation=runner_generation,
        port=authority.endpoint.port,
        open_deadline_at=min(
            cycle.expires_at,
            now + datetime.timedelta(seconds=10),
        ),
        approval_deadline_at=cycle.expires_at,
        transport_deadline_at=transport_deadline,
    )


async def _send_request_body(
    request: web.Request,
    bridge: RuntimeWebBrowserStreamBridge,
    resources: RuntimeWebGatewayResourceTracker,
    maximum_bytes: int,
) -> None:
    total = 0
    async for data in request.content.iter_chunked(MANDATORY_DATA_FRAME_BYTES):
        total += len(data)
        if total > maximum_bytes:
            await bridge.cancel(CloseReason.PROTOCOL_VIOLATION)
            raise RuntimeWebPolicyError(RuntimeWebPolicyCode.BAD_REQUEST)
        if not await resources.reserve_application_buffer(len(data)):
            await bridge.cancel(CloseReason.RESOURCE_EXHAUSTED)
            raise RuntimeError("Runtime Web application buffer is exhausted")
        try:
            await bridge.send_request_data(data)
        finally:
            await resources.release_application_buffer(len(data))
    await bridge.finish_request()


async def _proxy_websocket(
    request: web.Request,
    state: _GatewayState,
    *,
    bridge: RuntimeWebBrowserStreamBridge,
    head: RequestHead,
    cors: RuntimeWebCorsDecision,
    target_origin: str,
    authority: RuntimeWebGatewayAuthorityData,
) -> web.StreamResponse:
    websocket: web.WebSocketResponse | None = None
    client_task: asyncio.Task[None] | None = None
    guard_task: asyncio.Task[None] | None = None
    try:
        try:
            offered_subprotocols = _websocket_subprotocol_tokens(request.raw_headers)
        except _RuntimeWebSocketSubprotocolError:
            await bridge.cancel(CloseReason.PROTOCOL_VIOLATION)
            return _stream_error(
                request,
                state.config,
                CloseReason.PROTOCOL_VIOLATION,
            )
        guard_task = asyncio.create_task(
            _guard_identity_and_access(state.authority, authority, bridge),
            name=f"runtime-web-authority-guard:{bridge.binding.stream_id}",
        )
        while True:
            event = await bridge.next_event()
            if event.payload == "response_head":
                try:
                    if event.status is None:
                        raise RuntimeError("Runtime Web response status is absent")
                    if event.status != 101:
                        return web.Response(
                            status=event.status,
                            headers=normalize_response_headers(
                                (
                                    (header.name, header.value)
                                    for header in event.headers
                                ),
                                config=state.config,
                                cors=cors,
                                target_origin=target_origin,
                                port=authority.endpoint.port,
                            ),
                        )
                    try:
                        selected_subprotocol = _selected_websocket_subprotocol(
                            offered=offered_subprotocols,
                            response_headers=event.headers,
                        )
                    except _RuntimeWebSocketSubprotocolError:
                        await bridge.cancel(CloseReason.PROTOCOL_VIOLATION)
                        return _stream_error(
                            request,
                            state.config,
                            CloseReason.PROTOCOL_VIOLATION,
                        )
                    websocket = web.WebSocketResponse(
                        autoping=False,
                        heartbeat=None,
                        protocols=(
                            (selected_subprotocol,)
                            if selected_subprotocol is not None
                            else ()
                        ),
                        max_msg_size=MAX_WEBSOCKET_MESSAGE_BYTES,
                        compress=False,
                    )
                    await websocket.prepare(request)
                    client_task = asyncio.create_task(
                        _send_websocket_frames(websocket, bridge),
                        name=f"runtime-web-websocket-input:{bridge.binding.stream_id}",
                    )
                finally:
                    await bridge.release_event(event)
                continue
            if event.payload == "websocket":
                if websocket is None:
                    raise RuntimeError("Runtime WebSocket frame preceded upgrade")
                written = False
                try:
                    await _write_websocket_event(websocket, event)
                    written = True
                finally:
                    if written:
                        await bridge.release_event(event)
                    else:
                        await bridge.discard_event(event)
                continue
            if event.payload == "terminal":
                await bridge.release_event(event)
                break
            await bridge.release_event(event)
            raise RuntimeError("Runtime WebSocket event is invalid")
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
    finally:
        if client_task is not None and not client_task.done():
            client_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await client_task
        if guard_task is not None:
            guard_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await guard_task
        await bridge.discard_buffered_events()


async def _guard_identity_and_access(
    authority_service: RuntimeWebGatewayAuthorityProvider,
    authority: RuntimeWebGatewayAuthorityData,
    bridge: RuntimeWebBrowserStreamBridge,
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
        await bridge.cancel(CloseReason.AUTHORITY_REVOKED)
        return


async def _send_websocket_frames(
    websocket: web.WebSocketResponse,
    bridge: RuntimeWebBrowserStreamBridge,
) -> None:
    async for message in websocket:
        opcode = {
            WSMsgType.TEXT: WebSocketOpcode.TEXT,
            WSMsgType.BINARY: WebSocketOpcode.BINARY,
            WSMsgType.PING: WebSocketOpcode.PING,
            WSMsgType.PONG: WebSocketOpcode.PONG,
            WSMsgType.CLOSE: WebSocketOpcode.CLOSE,
        }.get(message.type)
        if opcode is None:
            if message.type in {WSMsgType.CLOSED, WSMsgType.CLOSING}:
                break
            if message.type is WSMsgType.ERROR:
                raise RuntimeError("Browser WebSocket failed")
            continue
        data = _websocket_data(message, opcode)
        if data and not await bridge.resources.reserve_application_buffer(len(data)):
            await bridge.cancel(CloseReason.RESOURCE_EXHAUSTED)
            raise RuntimeWebGatewayResourceExhausted(
                "Runtime Web browser input buffer is exhausted"
            )
        try:
            chunks = _websocket_chunks(data, text=opcode is WebSocketOpcode.TEXT)
            for index, chunk in enumerate(chunks):
                await bridge.send_websocket(
                    opcode=(opcode if index == 0 else WebSocketOpcode.CONTINUATION),
                    final=index == len(chunks) - 1,
                    data=chunk,
                )
        finally:
            if data:
                await bridge.resources.release_application_buffer(len(data))
        if opcode is WebSocketOpcode.CLOSE:
            break
    await bridge.finish_request()


async def _write_websocket_event(
    websocket: web.WebSocketResponse,
    event: BrowserStreamEvent,
) -> None:
    opcode = event.websocket_opcode
    if opcode is WebSocketOpcode.TEXT:
        await websocket.send_str(event.data.decode("utf-8"))
    elif opcode is WebSocketOpcode.BINARY:
        await websocket.send_bytes(event.data)
    elif opcode is WebSocketOpcode.PING:
        await websocket.ping(event.data)
    elif opcode is WebSocketOpcode.PONG:
        await websocket.pong(event.data)
    elif opcode is WebSocketOpcode.CLOSE:
        code = int.from_bytes(event.data[:2], "big") if len(event.data) >= 2 else 1000
        await websocket.close(code=code, message=event.data[2:125])


def _websocket_data(
    message: WSMessage,
    opcode: WebSocketOpcode,
) -> bytes:
    if opcode is WebSocketOpcode.TEXT:
        if not isinstance(message.data, str):
            raise RuntimeError("Browser WebSocket text is invalid")
        return message.data.encode()
    if opcode is WebSocketOpcode.CLOSE:
        code = message.data if isinstance(message.data, int) else 1000
        reason = message.extra if isinstance(message.extra, str) else ""
        return code.to_bytes(2, "big") + reason.encode()
    if not isinstance(message.data, (bytes, bytearray, memoryview)):
        raise RuntimeError("Browser WebSocket bytes are invalid")
    return bytes(message.data)


def _websocket_chunks(data: bytes, *, text: bool) -> tuple[bytes, ...]:
    if not data:
        return (b"",)
    chunks: list[bytes] = []
    offset = 0
    while offset < len(data):
        end = min(offset + MANDATORY_DATA_FRAME_BYTES, len(data))
        if text:
            while end < len(data) and data[end] & 0xC0 == 0x80:
                end -= 1
            if end == offset:
                raise RuntimeError("Browser WebSocket text cannot be fragmented")
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
    }[code]
    return _bounded_error(request, config, status=status, code=code.value)


def _stream_error(
    request: web.Request,
    config: RuntimeWebGatewayConfig,
    code: CloseReason,
) -> web.Response:
    status = {
        CloseReason.APPLICATION_UNAVAILABLE: 502,
        CloseReason.TRANSPORT_UNAVAILABLE: 503,
        CloseReason.OWNER_LOST: 503,
        CloseReason.RESOURCE_EXHAUSTED: 429,
        CloseReason.DEADLINE: 410,
        CloseReason.APPROVAL_EXPIRED: 410,
    }.get(code, 409)
    return _bounded_error(request, config, status=status, code=code.value)


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
    referrer_policy: str = "no-referrer",
) -> dict[str, str]:
    csp = _SECURITY_CSP.replace("form-action 'self'", f"form-action {form_action}")
    return {
        "Cache-Control": "no-store",
        "Referrer-Policy": referrer_policy,
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
