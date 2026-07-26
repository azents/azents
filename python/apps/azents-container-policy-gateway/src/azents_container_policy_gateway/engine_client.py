"""Private Docker Engine Unix-socket client."""

import json
from collections.abc import Mapping
from typing import Literal
from urllib.parse import quote

import aiohttp

from azents_container_policy_gateway.compatibility import (
    DOCKER_API_VERSION,
    DOCKER_API_VERSION_VALUE,
    DOCKER_ENGINE_VERSION,
)
from azents_container_policy_gateway.models import (
    AuthorizedEngineRequest,
    EngineContainerUsage,
    EngineResponse,
    EngineStreamResponse,
)

_MAX_ENGINE_RESPONSE_BYTES = 4 * 1024 * 1024


class EngineClient:
    """Execute only pre-authorized requests against one private Unix socket."""

    def __init__(self, socket_path: str) -> None:
        self._connector = aiohttp.UnixConnector(path=socket_path)
        self._session = aiohttp.ClientSession(connector=self._connector)

    async def execute(
        self,
        request: AuthorizedEngineRequest,
    ) -> EngineResponse | EngineStreamResponse:
        """Execute a typed authorized request."""
        response = await self._session.request(
            request.method,
            f"http://docker{_engine_path(request)}",
            params=request.query,
            headers=request.headers,
            data=request.body,
            allow_redirects=False,
        )
        if request.operation == "events" and response.status < 400:
            return EngineStreamResponse(
                status=response.status,
                headers=_response_headers(response.headers),
                body=response.content.iter_chunked(64 * 1024),
                release=response.release,
            )
        try:
            body = await _bounded_response_body(response)
            return EngineResponse(
                status=response.status,
                headers=_response_headers(response.headers),
                body=body,
            )
        finally:
            response.release()

    async def compatible(self) -> bool:
        """Return whether the private Engine matches the fixed tuple."""
        status, value = await self._get_json("/version")
        return (
            status == 200
            and isinstance(value, dict)
            and value.get("ApiVersion") == DOCKER_API_VERSION_VALUE
            and value.get("Version") == DOCKER_ENGINE_VERSION
        )

    async def container_usage(self, runtime_id: str) -> EngineContainerUsage:
        """Return Runtime-owned container count and aggregate PID limits."""
        filters = json.dumps(
            {"label": [f"azents/runtime-id={runtime_id}"]},
            separators=(",", ":"),
        )
        status, value = await self._get_json(
            f"/{DOCKER_API_VERSION}/containers/json",
            query=(("all", "1"), ("filters", filters)),
        )
        if status != 200 or not isinstance(value, list):
            raise RuntimeError("Docker Engine container usage query failed")
        pids_limit = 0
        for item in value:
            if not isinstance(item, dict):
                raise RuntimeError("Docker Engine returned invalid container usage")
            container_id = item.get("Id")
            if not isinstance(container_id, str) or not container_id:
                raise RuntimeError("Docker Engine returned invalid container ID")
            inspect_status, inspected = await self._get_json(
                f"/{DOCKER_API_VERSION}/containers/{quote(container_id, safe='')}/json"
            )
            if inspect_status != 200 or not isinstance(inspected, dict):
                raise RuntimeError("Docker Engine container inspection failed")
            host_config = inspected.get("HostConfig")
            limit = (
                host_config.get("PidsLimit") if isinstance(host_config, dict) else None
            )
            if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
                raise RuntimeError("Docker Engine returned an unbounded PID limit")
            pids_limit += limit
        return EngineContainerUsage(count=len(value), pids_limit=pids_limit)

    async def resource_owned(
        self,
        resource_type: Literal["container", "network", "volume"],
        name: str,
        runtime_id: str,
    ) -> bool:
        """Check that a named Engine resource carries the Runtime label."""
        encoded_name = quote(name, safe="")
        if resource_type == "container":
            path = f"/{DOCKER_API_VERSION}/containers/{encoded_name}/json"
        elif resource_type == "network":
            path = f"/{DOCKER_API_VERSION}/networks/{encoded_name}"
        else:
            path = f"/{DOCKER_API_VERSION}/volumes/{encoded_name}"
        status, value = await self._get_json(path)
        if status == 404:
            return False
        if status != 200 or not isinstance(value, dict):
            raise RuntimeError(f"Docker Engine {resource_type} inspection failed")
        if resource_type == "container":
            config = value.get("Config")
            labels = config.get("Labels") if isinstance(config, dict) else None
        else:
            labels = value.get("Labels")
        return (
            isinstance(labels, dict) and labels.get("azents/runtime-id") == runtime_id
        )

    async def close(self) -> None:
        """Close the private Engine connection pool."""
        await self._session.close()

    async def _get_json(
        self,
        path: str,
        *,
        query: tuple[tuple[str, str], ...] = (),
    ) -> tuple[int, object]:
        async with self._session.get(
            f"http://docker{path}",
            params=query,
            allow_redirects=False,
        ) as response:
            body = await _bounded_response_body(response)
            status = response.status
        if not body:
            return status, {}
        try:
            return status, json.loads(body)
        except json.JSONDecodeError as error:
            raise RuntimeError("Docker Engine returned invalid JSON") from error


async def _bounded_response_body(response: aiohttp.ClientResponse) -> bytes:
    body = bytearray()
    async for chunk in response.content.iter_chunked(64 * 1024):
        body.extend(chunk)
        if len(body) > _MAX_ENGINE_RESPONSE_BYTES:
            raise RuntimeError("Docker Engine response exceeded the gateway limit")
    return bytes(body)


def _response_headers(headers: Mapping[str, str]) -> dict[str, str]:
    allowed = {"content-type", "docker-content-digest", "api-version"}
    return {key: value for key, value in headers.items() if key.lower() in allowed}


def _engine_path(request: AuthorizedEngineRequest) -> str:
    if request.operation in {"ping", "version", "info"}:
        return request.path
    return f"/{DOCKER_API_VERSION}{request.path}"
