"""Docker-compatible Unix-socket gateway server."""

import asyncio
import dataclasses
import json
import logging
from typing import Literal, Protocol

import aiohttp
from aiohttp import web

from azents_container_policy_gateway.authorization import (
    authorize_request,
    max_request_bytes,
    request_body_limit,
)
from azents_container_policy_gateway.config import GatewayConfig
from azents_container_policy_gateway.models import (
    AuthorizedEngineRequest,
    EngineContainerUsage,
    EngineResponse,
    EngineStreamResponse,
    GatewayAuthorizationDenied,
)

_LOGGER = logging.getLogger(__name__)
_MAX_CONCURRENT_REQUESTS = 8
_MAX_CONCURRENT_BUILDS = 1
_MAX_CONCURRENT_STREAMS = 8


class EngineExecutor(Protocol):
    """Execute one typed, authorized private Engine request."""

    async def __call__(
        self,
        request: AuthorizedEngineRequest,
    ) -> EngineResponse | EngineStreamResponse: ...


class EngineCompatibilityCheck(Protocol):
    """Check the fixed private Engine compatibility tuple."""

    async def __call__(self) -> bool: ...


class EngineContainerUsageCheck(Protocol):
    """Return Runtime-owned nested-container resource usage."""

    async def __call__(self, runtime_id: str) -> EngineContainerUsage: ...


class EngineResourceOwnership(Protocol):
    """Check one Runtime-owned named Engine resource."""

    async def __call__(
        self,
        resource_type: Literal["container", "network", "volume"],
        name: str,
        runtime_id: str,
    ) -> bool: ...


@dataclasses.dataclass(frozen=True)
class _DockerDispatch:
    authorized: AuthorizedEngineRequest
    response: EngineResponse | EngineStreamResponse


_CONFIG_KEY = web.AppKey("gateway_config", GatewayConfig)
_ENGINE_EXECUTE_KEY = web.AppKey("engine_execute", EngineExecutor)
_ENGINE_COMPATIBLE_KEY = web.AppKey("engine_compatible", EngineCompatibilityCheck)
_ENGINE_CONTAINER_USAGE_KEY = web.AppKey(
    "engine_container_usage",
    EngineContainerUsageCheck,
)
_ENGINE_RESOURCE_OWNED_KEY = web.AppKey(
    "engine_resource_owned",
    EngineResourceOwnership,
)
_CONTAINER_CREATE_LOCK_KEY = web.AppKey("container_create_lock", asyncio.Lock)
_REQUEST_SEMAPHORE_KEY = web.AppKey("request_semaphore", asyncio.Semaphore)
_BUILD_SEMAPHORE_KEY = web.AppKey("build_semaphore", asyncio.Semaphore)
_STREAM_SEMAPHORE_KEY = web.AppKey("stream_semaphore", asyncio.Semaphore)


def create_application(
    config: GatewayConfig,
    *,
    engine_execute: EngineExecutor,
    engine_compatible: EngineCompatibilityCheck,
    engine_container_usage: EngineContainerUsageCheck,
    engine_resource_owned: EngineResourceOwnership,
) -> web.Application:
    """Create the default-deny gateway application."""
    application = web.Application(client_max_size=max_request_bytes(config.policy))
    application[_CONFIG_KEY] = config
    application[_ENGINE_EXECUTE_KEY] = engine_execute
    application[_ENGINE_COMPATIBLE_KEY] = engine_compatible
    application[_ENGINE_CONTAINER_USAGE_KEY] = engine_container_usage
    application[_ENGINE_RESOURCE_OWNED_KEY] = engine_resource_owned
    application[_CONTAINER_CREATE_LOCK_KEY] = asyncio.Lock()
    application[_REQUEST_SEMAPHORE_KEY] = asyncio.Semaphore(_MAX_CONCURRENT_REQUESTS)
    application[_BUILD_SEMAPHORE_KEY] = asyncio.Semaphore(_MAX_CONCURRENT_BUILDS)
    application[_STREAM_SEMAPHORE_KEY] = asyncio.Semaphore(_MAX_CONCURRENT_STREAMS)
    application.router.add_route("*", "/{path_info:.*}", _handle)
    return application


async def _handle(request: web.Request) -> web.StreamResponse:
    config = request.app[_CONFIG_KEY]
    if _is_events_request(request):
        async with request.app[_STREAM_SEMAPHORE_KEY]:
            async with request.app[_REQUEST_SEMAPHORE_KEY]:
                dispatch = await _dispatch_docker_request(request, config)
            return await _render_docker_dispatch(request, dispatch)
    async with request.app[_REQUEST_SEMAPHORE_KEY]:
        if request.path == "/azents/v1/readiness":
            return await _handle_readiness(request, config)
        if _is_build_request(request):
            async with request.app[_BUILD_SEMAPHORE_KEY]:
                return await _handle_docker_request(request, config)
        return await _handle_docker_request(request, config)


async def _handle_readiness(
    request: web.Request,
    config: GatewayConfig,
) -> web.StreamResponse:
    if request.method != "GET" or request.query or request.can_read_body:
        return web.json_response(
            {"message": "The readiness request is invalid."},
            status=403,
        )
    if not await request.app[_ENGINE_COMPATIBLE_KEY]():
        return web.json_response(
            {"message": "The private Docker Engine is not compatible."},
            status=503,
        )
    return web.json_response(
        {
            "runtime_id": config.runtime_id,
            "desired_generation": config.desired_generation,
            "snapshot_id": config.snapshot_id,
            "policy_digest": config.policy_digest,
        }
    )


async def _handle_docker_request(
    request: web.Request,
    config: GatewayConfig,
) -> web.StreamResponse:
    dispatch = await _dispatch_docker_request(request, config)
    return await _render_docker_dispatch(request, dispatch)


async def _dispatch_docker_request(
    request: web.Request,
    config: GatewayConfig,
) -> _DockerDispatch | web.StreamResponse:
    try:
        body = await _read_bounded_body(
            request,
            limit=request_body_limit(
                config.policy,
                method=request.method,
                raw_path=request.rel_url.raw_path,
            ),
        )
        authorized = authorize_request(
            policy=config.policy,
            runtime_id=config.runtime_id,
            method=request.method,
            raw_path=request.rel_url.raw_path,
            query=tuple(request.query.items()),
            headers=request.headers,
            body=body,
        )
        response = await _execute_authorized(request, config, authorized)
    except GatewayAuthorizationDenied as error:
        _LOGGER.warning(
            "Container policy gateway request denied",
            extra={
                "runtime_id": config.runtime_id,
                "desired_generation": config.desired_generation,
                "policy_digest": config.policy_digest,
                "method": request.method,
                "path": request.path,
                "reason_code": error.reason_code,
            },
        )
        return web.json_response({"message": error.message}, status=403)
    _LOGGER.info(
        "Container policy gateway request allowed",
        extra={
            "runtime_id": config.runtime_id,
            "desired_generation": config.desired_generation,
            "policy_digest": config.policy_digest,
            "correlation_id": authorized.correlation_id,
            "operation": authorized.operation,
            "method": authorized.method,
            "path": authorized.path,
            "status": response.status,
        },
    )
    return _DockerDispatch(authorized=authorized, response=response)


async def _render_docker_dispatch(
    request: web.Request,
    dispatch: _DockerDispatch | web.StreamResponse,
) -> web.StreamResponse:
    if isinstance(dispatch, web.StreamResponse):
        return dispatch
    response = dispatch.response
    if isinstance(response, EngineStreamResponse):
        stream = web.StreamResponse(
            status=response.status,
            headers=response.headers,
        )
        try:
            await stream.prepare(request)
            async for chunk in response.body:
                await stream.write(chunk)
            await stream.write_eof()
        finally:
            response.release()
        return stream
    return web.Response(
        status=response.status,
        headers=response.headers,
        body=response.body,
        content_type=None,
    )


def _is_build_request(request: web.Request) -> bool:
    return request.method == "POST" and request.rel_url.raw_path == "/v1.51/build"


def _is_events_request(request: web.Request) -> bool:
    return request.method == "GET" and request.rel_url.raw_path == "/v1.51/events"


async def _read_bounded_body(request: web.Request, *, limit: int) -> bytes:
    content_length = request.content_length
    if content_length is not None and content_length > limit:
        raise GatewayAuthorizationDenied(
            "request_body_too_large",
            "The Docker API request body exceeds the gateway limit.",
        )
    body = bytearray()
    async for chunk in request.content.iter_chunked(64 * 1024):
        body.extend(chunk)
        if len(body) > limit:
            raise GatewayAuthorizationDenied(
                "request_body_too_large",
                "The Docker API request body exceeds the gateway limit.",
            )
    return bytes(body)


async def check_readiness(
    *,
    socket_path: str,
    runtime_id: str,
    desired_generation: int,
    snapshot_id: str,
    policy_digest: str,
) -> bool:
    """Check that the gateway acknowledges exact immutable policy evidence."""
    connector = aiohttp.UnixConnector(path=socket_path)
    try:
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get("http://gateway/azents/v1/readiness") as response:
                if response.status != 200:
                    return False
                data = await response.json()
    except aiohttp.ClientError, OSError, ValueError:
        return False
    return data == {
        "runtime_id": runtime_id,
        "desired_generation": desired_generation,
        "snapshot_id": snapshot_id,
        "policy_digest": policy_digest,
    }


def docker_error(message: str) -> bytes:
    """Serialize one Docker-compatible error body."""
    return json.dumps({"message": message}, separators=(",", ":")).encode()


async def _execute_authorized(
    request: web.Request,
    config: GatewayConfig,
    authorized: AuthorizedEngineRequest,
) -> EngineResponse | EngineStreamResponse:
    for resource_type, name in _path_resource_requirements(authorized):
        await _require_owned_resource(
            request,
            config,
            resource_type=resource_type,
            name=name,
        )
    for container in authorized.required_containers:
        await _require_owned_resource(
            request,
            config,
            resource_type="container",
            name=container,
        )
    if authorized.operation != "containers.create":
        return await request.app[_ENGINE_EXECUTE_KEY](authorized)
    async with request.app[_CONTAINER_CREATE_LOCK_KEY]:
        ceiling = config.policy.resources.container_count
        if ceiling is None:
            raise GatewayAuthorizationDenied(
                "container_count_denied",
                "The execution policy has no container-count ceiling.",
            )
        usage = await request.app[_ENGINE_CONTAINER_USAGE_KEY](config.runtime_id)
        if usage.count >= ceiling:
            raise GatewayAuthorizationDenied(
                "container_count_exceeded",
                "The execution-policy container-count ceiling has been reached.",
            )
        pids_ceiling = config.policy.resources.pids
        pids_limit = authorized.requested_pids_limit
        if pids_ceiling is None or pids_limit is None:
            raise GatewayAuthorizationDenied(
                "pids_limit_denied",
                "The execution policy has no enforceable PID ceiling.",
            )
        if usage.pids_limit + pids_limit > pids_ceiling:
            raise GatewayAuthorizationDenied(
                "pids_limit_exceeded",
                "The execution-policy aggregate PID ceiling has been reached.",
            )
        for volume in authorized.required_volumes:
            await _require_owned_resource(
                request,
                config,
                resource_type="volume",
                name=volume,
            )
        for network in authorized.required_networks:
            await _require_owned_resource(
                request,
                config,
                resource_type="network",
                name=network,
            )
        return await request.app[_ENGINE_EXECUTE_KEY](authorized)


def _path_resource_requirements(
    authorized: AuthorizedEngineRequest,
) -> tuple[
    tuple[Literal["container", "network", "volume"], str],
    ...,
]:
    resource_type: Literal["container", "network", "volume"] | None = None
    if authorized.operation.startswith("containers.") and authorized.operation not in {
        "containers.create",
        "containers.list",
    }:
        resource_type = "container"
    elif authorized.operation.startswith("networks.") and authorized.operation not in {
        "networks.create",
        "networks.list",
    }:
        resource_type = "network"
    elif authorized.operation.startswith("volumes.") and authorized.operation not in {
        "volumes.create",
        "volumes.list",
    }:
        resource_type = "volume"
    if resource_type is None:
        return ()
    parts = authorized.path.split("/")
    if len(parts) < 3 or not parts[2]:
        raise AssertionError("authorized resource path is invalid")
    return ((resource_type, parts[2]),)


async def _require_owned_resource(
    request: web.Request,
    config: GatewayConfig,
    *,
    resource_type: Literal["container", "network", "volume"],
    name: str,
) -> None:
    owned = await request.app[_ENGINE_RESOURCE_OWNED_KEY](
        resource_type,
        name,
        config.runtime_id,
    )
    if not owned:
        raise GatewayAuthorizationDenied(
            f"{resource_type}_ownership_denied",
            f"The {resource_type} is not owned by this Runtime.",
        )
