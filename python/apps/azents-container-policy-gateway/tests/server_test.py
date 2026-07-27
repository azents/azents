"""Gateway server and private Unix Engine transport tests."""

import asyncio
import dataclasses
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Literal, Never

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer, unused_port
from azents_runtime_control.execution_policy import RuntimeExecutionPolicy
from conftest import build_context

from azents_container_policy_gateway.compatibility import (
    DOCKER_API_VERSION_VALUE,
    DOCKER_ENGINE_VERSION,
)
from azents_container_policy_gateway.config import GatewayConfig
from azents_container_policy_gateway.engine_client import EngineClient
from azents_container_policy_gateway.main import create_application_runner
from azents_container_policy_gateway.models import (
    AuthorizedEngineRequest,
    EngineContainerUsage,
    EngineResponse,
    EngineStreamResponse,
)
from azents_container_policy_gateway.server import (
    EngineCompatibilityCheck,
    EngineContainerUsageCheck,
    EngineExecutor,
    EngineResourceOwnership,
    check_readiness,
    create_application,
)


async def _compatible() -> bool:
    return True


async def _container_usage(runtime_id: str) -> EngineContainerUsage:
    assert runtime_id == "runtime-1"
    return EngineContainerUsage(count=0, pids_limit=0)


async def _resource_owned(
    resource_type: Literal["container", "network", "volume"],
    name: str,
    runtime_id: str,
) -> bool:
    assert resource_type in {"container", "network", "volume"}
    assert name
    assert runtime_id == "runtime-1"
    return True


def _application(
    config: GatewayConfig,
    *,
    execute: EngineExecutor,
    compatible: EngineCompatibilityCheck = _compatible,
    container_usage: EngineContainerUsageCheck = _container_usage,
    resource_owned: EngineResourceOwnership = _resource_owned,
) -> web.Application:
    return create_application(
        config,
        engine_execute=execute,
        engine_compatible=compatible,
        engine_container_usage=container_usage,
        engine_resource_owned=resource_owned,
    )


@pytest.mark.asyncio
async def test_denied_request_never_reaches_engine(
    gateway_config: GatewayConfig,
) -> None:
    calls: list[AuthorizedEngineRequest] = []

    async def execute(request: AuthorizedEngineRequest) -> EngineResponse:
        calls.append(request)
        return EngineResponse(status=200, headers={}, body=b"{}")

    client = TestClient(TestServer(_application(gateway_config, execute=execute)))
    await client.start_server()
    try:
        response = await client.post(
            "/v1.51/containers/create",
            json={"Image": "busybox", "HostConfig": {"Privileged": True}},
        )
    finally:
        await client.close()

    assert response.status == 403
    assert calls == []


@pytest.mark.asyncio
async def test_allowed_request_reaches_engine_as_typed_request(
    gateway_config: GatewayConfig,
) -> None:
    calls: list[AuthorizedEngineRequest] = []

    async def execute(request: AuthorizedEngineRequest) -> EngineResponse:
        calls.append(request)
        return EngineResponse(
            status=201,
            headers={"Content-Type": "application/json"},
            body=b'{"Id":"container-1"}',
        )

    client = TestClient(TestServer(_application(gateway_config, execute=execute)))
    await client.start_server()
    try:
        response = await client.post(
            "/v1.51/containers/create",
            json={"Image": "busybox", "HostConfig": {}},
        )
    finally:
        await client.close()

    assert response.status == 201
    assert len(calls) == 1
    assert calls[0].operation == "containers.create"
    forwarded = json.loads(calls[0].body)
    assert forwarded["Labels"]["azents/runtime-id"] == "runtime-1"
    assert forwarded["HostConfig"]["PidsLimit"] == 32
    assert calls[0].requested_pids_limit == 32


@pytest.mark.asyncio
async def test_container_count_denial_makes_zero_authorized_engine_requests(
    gateway_config: GatewayConfig,
) -> None:
    calls: list[AuthorizedEngineRequest] = []

    async def execute(request: AuthorizedEngineRequest) -> EngineResponse:
        calls.append(request)
        return EngineResponse(status=201, headers={}, body=b"{}")

    async def usage(runtime_id: str) -> EngineContainerUsage:
        assert runtime_id == "runtime-1"
        return EngineContainerUsage(count=8, pids_limit=256)

    client = TestClient(
        TestServer(
            _application(
                gateway_config,
                execute=execute,
                container_usage=usage,
            )
        )
    )
    await client.start_server()
    try:
        response = await client.post(
            "/v1.51/containers/create",
            json={"Image": "busybox", "HostConfig": {}},
        )
    finally:
        await client.close()

    assert response.status == 403
    assert calls == []


@pytest.mark.asyncio
async def test_aggregate_pids_denial_makes_zero_authorized_engine_requests(
    gateway_config: GatewayConfig,
) -> None:
    calls: list[AuthorizedEngineRequest] = []

    async def execute(request: AuthorizedEngineRequest) -> EngineResponse:
        calls.append(request)
        return EngineResponse(status=201, headers={}, body=b"{}")

    async def usage(runtime_id: str) -> EngineContainerUsage:
        assert runtime_id == "runtime-1"
        return EngineContainerUsage(count=2, pids_limit=240)

    client = TestClient(
        TestServer(
            _application(
                gateway_config,
                execute=execute,
                container_usage=usage,
            )
        )
    )
    await client.start_server()
    try:
        response = await client.post(
            "/v1.51/containers/create",
            json={"Image": "busybox", "HostConfig": {}},
        )
    finally:
        await client.close()

    assert response.status == 403
    assert calls == []


@pytest.mark.asyncio
async def test_null_nested_container_ceilings_skip_aggregate_enforcement(
    gateway_config: GatewayConfig,
) -> None:
    calls: list[AuthorizedEngineRequest] = []

    async def execute(request: AuthorizedEngineRequest) -> EngineResponse:
        calls.append(request)
        return EngineResponse(status=201, headers={}, body=b"{}")

    async def usage(runtime_id: str) -> EngineContainerUsage:
        assert runtime_id == "runtime-1"
        return EngineContainerUsage(count=10_000, pids_limit=1_000_000)

    unbounded = dataclasses.replace(
        gateway_config,
        policy=dataclasses.replace(
            gateway_config.policy,
            resources=dataclasses.replace(
                gateway_config.policy.resources,
                pids=None,
                container_count=None,
            ),
        ),
    )
    client = TestClient(
        TestServer(
            _application(
                unbounded,
                execute=execute,
                container_usage=usage,
            )
        )
    )
    await client.start_server()
    try:
        response = await client.post(
            "/v1.51/containers/create",
            json={"Image": "busybox", "HostConfig": {"PidsLimit": 1_024}},
        )
    finally:
        await client.close()

    assert response.status == 201
    assert len(calls) == 1
    assert calls[0].requested_pids_limit == 1_024


@pytest.mark.asyncio
@pytest.mark.parametrize("denied_type", ["network", "volume"])
async def test_unowned_compose_resource_makes_zero_authorized_engine_requests(
    compose_gateway_config: GatewayConfig,
    denied_type: str,
) -> None:
    calls: list[AuthorizedEngineRequest] = []

    async def execute(request: AuthorizedEngineRequest) -> EngineResponse:
        calls.append(request)
        return EngineResponse(status=201, headers={}, body=b"{}")

    async def owned(
        resource_type: Literal["container", "network", "volume"],
        name: str,
        runtime_id: str,
    ) -> bool:
        assert name in {"demo_default", "demo_data"}
        assert runtime_id == "runtime-1"
        return resource_type != denied_type

    client = TestClient(
        TestServer(
            _application(
                compose_gateway_config,
                execute=execute,
                resource_owned=owned,
            )
        )
    )
    await client.start_server()
    try:
        response = await client.post(
            "/v1.51/containers/create",
            json={
                "Image": "busybox",
                "HostConfig": {
                    "NetworkMode": "demo_default",
                    "Mounts": [
                        {
                            "Type": "volume",
                            "Source": "demo_data",
                            "Target": "/data",
                        }
                    ],
                },
                "NetworkingConfig": {
                    "EndpointsConfig": {"demo_default": {"Aliases": ["app"]}}
                },
            },
        )
    finally:
        await client.close()

    assert response.status == 403
    assert calls == []


@pytest.mark.asyncio
async def test_unowned_lifecycle_target_makes_zero_authorized_engine_requests(
    gateway_config: GatewayConfig,
) -> None:
    calls: list[AuthorizedEngineRequest] = []

    async def execute(request: AuthorizedEngineRequest) -> EngineResponse:
        calls.append(request)
        return EngineResponse(status=204, headers={}, body=b"")

    async def not_owned(
        resource_type: Literal["container", "network", "volume"],
        name: str,
        runtime_id: str,
    ) -> bool:
        assert resource_type == "container"
        assert name == "demo"
        assert runtime_id == "runtime-1"
        return False

    client = TestClient(
        TestServer(
            _application(
                gateway_config,
                execute=execute,
                resource_owned=not_owned,
            )
        )
    )
    await client.start_server()
    try:
        response = await client.post("/v1.51/containers/demo/start")
    finally:
        await client.close()

    assert response.status == 403
    assert calls == []


@pytest.mark.asyncio
async def test_engine_client_uses_only_private_unix_socket(tmp_path: Path) -> None:
    socket_path = tmp_path / "engine.sock"
    requests: list[str] = []

    async def handler(request: web.Request) -> web.Response:
        requests.append(request.path)
        return web.json_response(
            {
                "ApiVersion": DOCKER_API_VERSION_VALUE,
                "Version": DOCKER_ENGINE_VERSION,
            }
        )

    application = web.Application()
    application.router.add_get("/version", handler)
    runner = web.AppRunner(application)
    await runner.setup()
    site = web.UnixSite(runner, str(socket_path))
    await site.start()
    client = EngineClient(str(socket_path))
    try:
        response = await client.execute(
            AuthorizedEngineRequest(
                operation="version",
                correlation_id="test",
                method="GET",
                path="/version",
                query=(),
                headers={},
                body=b"",
                required_containers=(),
                required_volumes=(),
                required_networks=(),
                requested_pids_limit=None,
            )
        )
        compatible = await client.compatible()
    finally:
        await client.close()
        await runner.cleanup()

    assert response.status == 200
    assert compatible is True
    assert requests == ["/version", "/version"]


@pytest.mark.asyncio
async def test_engine_client_rejects_oversized_buffered_response(
    tmp_path: Path,
) -> None:
    socket_path = tmp_path / "engine.sock"

    async def info(request: web.Request) -> web.Response:
        del request
        return web.Response(body=b"x" * (4 * 1024 * 1024 + 1))

    application = web.Application()
    application.router.add_get("/info", info)
    runner = web.AppRunner(application)
    await runner.setup()
    site = web.UnixSite(runner, str(socket_path))
    await site.start()
    client = EngineClient(str(socket_path))
    try:
        with pytest.raises(RuntimeError, match="exceeded the gateway limit"):
            await client.execute(
                AuthorizedEngineRequest(
                    operation="info",
                    correlation_id="test",
                    method="GET",
                    path="/info",
                    query=(),
                    headers={},
                    body=b"",
                    required_containers=(),
                    required_volumes=(),
                    required_networks=(),
                    requested_pids_limit=None,
                )
            )
    finally:
        await client.close()
        await runner.cleanup()


@pytest.mark.asyncio
async def test_events_stream_incrementally_through_private_unix_socket(
    tmp_path: Path,
    compose_gateway_config: GatewayConfig,
) -> None:
    socket_path = tmp_path / "engine.sock"
    release_second_chunk = asyncio.Event()

    async def events(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(headers={"Content-Type": "application/json"})
        await response.prepare(request)
        await response.write(b'{"status":"first"}\n')
        await release_second_chunk.wait()
        await response.write(b'{"status":"second"}\n')
        await response.write_eof()
        return response

    engine_application = web.Application()
    engine_application.router.add_get("/v1.51/events", events)
    engine_runner = web.AppRunner(engine_application)
    await engine_runner.setup()
    engine_site = web.UnixSite(engine_runner, str(socket_path))
    await engine_site.start()
    engine_client = EngineClient(str(socket_path))
    gateway_client = TestClient(
        TestServer(
            _application(
                compose_gateway_config,
                execute=engine_client.execute,
            )
        )
    )
    await gateway_client.start_server()
    try:
        response = await gateway_client.get("/v1.51/events")
        first = await asyncio.wait_for(
            response.content.readline(),
            timeout=1,
        )
        assert first == b'{"status":"first"}\n'
        release_second_chunk.set()
        second = await asyncio.wait_for(
            response.content.readline(),
            timeout=1,
        )
        assert second == b'{"status":"second"}\n'
        assert await response.read() == b""
    finally:
        release_second_chunk.set()
        await gateway_client.close()
        await engine_client.close()
        await engine_runner.cleanup()


@pytest.mark.asyncio
async def test_stream_release_runs_when_response_prepare_fails(
    monkeypatch: pytest.MonkeyPatch,
    compose_gateway_config: GatewayConfig,
) -> None:
    released = False

    async def body() -> AsyncIterator[bytes]:
        yield b'{"status":"unused"}\n'

    def release() -> None:
        nonlocal released
        released = True

    async def execute(
        request: AuthorizedEngineRequest,
    ) -> EngineStreamResponse:
        assert request.operation == "events"
        return EngineStreamResponse(
            status=200,
            headers={"Content-Type": "application/json"},
            body=body(),
            release=release,
        )

    async def fail_prepare(
        self: web.StreamResponse,
        request: web.Request,
    ) -> Never:
        del self, request
        raise ConnectionResetError("client disconnected before prepare")

    monkeypatch.setattr(web.StreamResponse, "prepare", fail_prepare)
    client = TestClient(
        TestServer(
            _application(
                compose_gateway_config,
                execute=execute,
            )
        )
    )
    await client.start_server()
    try:
        with pytest.raises(aiohttp.ServerDisconnectedError):
            await client.get("/v1.51/events")
    finally:
        await client.close()

    assert released is True


@pytest.mark.asyncio
async def test_production_runner_releases_quiet_stream_on_disconnect(
    compose_gateway_config: GatewayConfig,
) -> None:
    released = asyncio.Event()
    wait_forever = asyncio.Event()

    async def body() -> AsyncIterator[bytes]:
        yield b'{"status":"first"}\n'
        await wait_forever.wait()

    async def execute(
        request: AuthorizedEngineRequest,
    ) -> EngineStreamResponse:
        assert request.operation == "events"
        return EngineStreamResponse(
            status=200,
            headers={"Content-Type": "application/json"},
            body=body(),
            release=released.set,
        )

    runner = create_application_runner(
        _application(compose_gateway_config, execute=execute)
    )
    await runner.setup()
    port = unused_port()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    try:
        async with aiohttp.ClientSession() as session:
            response = await session.get(f"http://127.0.0.1:{port}/v1.51/events")
            assert await response.content.readline() == b'{"status":"first"}\n'
            response.close()
        await asyncio.wait_for(released.wait(), timeout=1)
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_gateway_bounds_concurrent_engine_requests(
    gateway_config: GatewayConfig,
) -> None:
    entered = 0
    eight_entered = asyncio.Event()
    release = asyncio.Event()

    async def execute(request: AuthorizedEngineRequest) -> EngineResponse:
        nonlocal entered
        assert request.operation == "containers.list"
        entered += 1
        if entered == 8:
            eight_entered.set()
        await release.wait()
        return EngineResponse(status=200, headers={}, body=b"[]")

    client = TestClient(TestServer(_application(gateway_config, execute=execute)))
    await client.start_server()
    tasks = [
        asyncio.create_task(client.get("/v1.51/containers/json")) for _ in range(9)
    ]
    try:
        await asyncio.wait_for(eight_entered.wait(), timeout=1)
        await asyncio.sleep(0)
        assert entered == 8
        release.set()
        responses = await asyncio.gather(*tasks)
        assert all(response.status == 200 for response in responses)
    finally:
        release.set()
        await client.close()


@pytest.mark.asyncio
async def test_gateway_bounds_concurrent_readiness_requests(
    gateway_config: GatewayConfig,
) -> None:
    entered = 0
    eight_entered = asyncio.Event()
    release = asyncio.Event()

    async def compatible() -> bool:
        nonlocal entered
        entered += 1
        if entered == 8:
            eight_entered.set()
        await release.wait()
        return True

    async def execute(request: AuthorizedEngineRequest) -> EngineResponse:
        raise AssertionError(request)

    client = TestClient(
        TestServer(
            _application(
                gateway_config,
                execute=execute,
                compatible=compatible,
            )
        )
    )
    await client.start_server()
    tasks = [asyncio.create_task(client.get("/azents/v1/readiness")) for _ in range(9)]
    try:
        await asyncio.wait_for(eight_entered.wait(), timeout=1)
        await asyncio.sleep(0)
        assert entered == 8
        release.set()
        responses = await asyncio.gather(*tasks)
        assert all(response.status == 200 for response in responses)
    finally:
        release.set()
        await client.close()


@pytest.mark.asyncio
async def test_event_stream_limit_preserves_general_request_capacity(
    compose_gateway_config: GatewayConfig,
) -> None:
    streams_entered = 0
    eight_entered = asyncio.Event()
    release_streams = asyncio.Event()

    async def execute(
        request: AuthorizedEngineRequest,
    ) -> EngineResponse | EngineStreamResponse:
        nonlocal streams_entered
        if request.operation == "containers.list":
            return EngineResponse(status=200, headers={}, body=b"[]")
        assert request.operation == "events"
        streams_entered += 1
        if streams_entered == 8:
            eight_entered.set()

        async def body() -> AsyncIterator[bytes]:
            yield b'{"status":"ready"}\n'
            await release_streams.wait()

        return EngineStreamResponse(
            status=200,
            headers={"Content-Type": "application/json"},
            body=body(),
            release=lambda: None,
        )

    client = TestClient(
        TestServer(_application(compose_gateway_config, execute=execute))
    )
    await client.start_server()
    stream_tasks = [asyncio.create_task(client.get("/v1.51/events")) for _ in range(9)]
    try:
        await asyncio.wait_for(eight_entered.wait(), timeout=1)
        await asyncio.sleep(0)
        assert streams_entered == 8

        ordinary = await asyncio.wait_for(
            client.get("/v1.51/containers/json"),
            timeout=1,
        )
        readiness = await asyncio.wait_for(
            client.get("/azents/v1/readiness"),
            timeout=1,
        )
        assert ordinary.status == 200
        assert readiness.status == 200
        assert streams_entered == 8

        release_streams.set()
        streams = await asyncio.gather(*stream_tasks)
        assert all(stream.status == 200 for stream in streams)
        assert streams_entered == 9
    finally:
        release_streams.set()
        await client.close()


@pytest.mark.asyncio
async def test_gateway_serializes_build_requests(
    gateway_config: GatewayConfig,
    build_policy: RuntimeExecutionPolicy,
) -> None:
    entered = 0
    first_entered = asyncio.Event()
    release_first = asyncio.Event()

    async def execute(request: AuthorizedEngineRequest) -> EngineResponse:
        nonlocal entered
        assert request.operation == "images.build"
        entered += 1
        if entered == 1:
            first_entered.set()
            await release_first.wait()
        return EngineResponse(status=200, headers={}, body=b"{}")

    config = dataclasses.replace(gateway_config, policy=build_policy)
    client = TestClient(TestServer(_application(config, execute=execute)))
    await client.start_server()
    context = build_context()
    tasks = [
        asyncio.create_task(
            client.post(
                "/v1.51/build",
                data=context,
                headers={"Content-Type": "application/x-tar"},
            )
        )
        for _ in range(2)
    ]
    try:
        await asyncio.wait_for(first_entered.wait(), timeout=1)
        await asyncio.sleep(0)
        assert entered == 1
        release_first.set()
        responses = await asyncio.gather(*tasks)
        assert entered == 2
        assert all(response.status == 200 for response in responses)
    finally:
        release_first.set()
        await client.close()


@pytest.mark.asyncio
async def test_engine_client_uses_typed_count_and_ownership_requests(
    tmp_path: Path,
) -> None:
    socket_path = tmp_path / "engine.sock"
    requests: list[tuple[str, str]] = []

    async def containers(request: web.Request) -> web.Response:
        requests.append((request.path, request.query["filters"]))
        return web.json_response([{"Id": "container-1"}])

    async def resource(request: web.Request) -> web.Response:
        requests.append((request.path, ""))
        if request.path.startswith("/v1.51/containers/"):
            return web.json_response(
                {
                    "Config": {"Labels": {"azents/runtime-id": "runtime-1"}},
                    "HostConfig": {"PidsLimit": 32},
                }
            )
        return web.json_response({"Labels": {"azents/runtime-id": "runtime-1"}})

    application = web.Application()
    application.router.add_get("/v1.51/containers/json", containers)
    application.router.add_get("/v1.51/containers/{name}/json", resource)
    application.router.add_get("/v1.51/networks/{name}", resource)
    application.router.add_get("/v1.51/volumes/{name}", resource)
    runner = web.AppRunner(application)
    await runner.setup()
    site = web.UnixSite(runner, str(socket_path))
    await site.start()
    client = EngineClient(str(socket_path))
    try:
        assert await client.container_usage("runtime-1") == EngineContainerUsage(
            count=1,
            pids_limit=32,
        )
        assert await client.resource_owned(
            "container",
            "demo",
            "runtime-1",
        )
        assert await client.resource_owned(
            "network",
            "demo_default",
            "runtime-1",
        )
        assert await client.resource_owned(
            "volume",
            "demo_data",
            "runtime-1",
        )
    finally:
        await client.close()
        await runner.cleanup()

    assert requests[0][0] == "/v1.51/containers/json"
    assert "azents/runtime-id=runtime-1" in requests[0][1]
    assert requests[1:] == [
        ("/v1.51/containers/container-1/json", ""),
        ("/v1.51/containers/demo/json", ""),
        ("/v1.51/networks/demo_default", ""),
        ("/v1.51/volumes/demo_data", ""),
    ]


@pytest.mark.asyncio
async def test_readiness_requires_exact_policy_evidence(
    tmp_path: Path,
    gateway_config: GatewayConfig,
) -> None:
    socket_path = tmp_path / "gateway.sock"

    async def execute(request: AuthorizedEngineRequest) -> EngineResponse:
        raise AssertionError(request)

    application = _application(gateway_config, execute=execute)
    runner = web.AppRunner(application)
    await runner.setup()
    site = web.UnixSite(runner, str(socket_path))
    await site.start()
    try:
        assert await check_readiness(
            socket_path=str(socket_path),
            runtime_id="runtime-1",
            desired_generation=3,
            snapshot_id="snapshot-1",
            policy_digest="d" * 64,
        )
        assert not await check_readiness(
            socket_path=str(socket_path),
            runtime_id="runtime-1",
            desired_generation=4,
            snapshot_id="snapshot-1",
            policy_digest="d" * 64,
        )
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_readiness_fails_when_engine_tuple_is_incompatible(
    tmp_path: Path,
    gateway_config: GatewayConfig,
) -> None:
    socket_path = tmp_path / "gateway.sock"

    async def execute(request: AuthorizedEngineRequest) -> EngineResponse:
        raise AssertionError(request)

    async def incompatible() -> bool:
        return False

    application = _application(
        gateway_config,
        execute=execute,
        compatible=incompatible,
    )
    runner = web.AppRunner(application)
    await runner.setup()
    site = web.UnixSite(runner, str(socket_path))
    await site.start()
    try:
        assert not await check_readiness(
            socket_path=str(socket_path),
            runtime_id="runtime-1",
            desired_generation=3,
            snapshot_id="snapshot-1",
            policy_digest="d" * 64,
        )
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_readiness_fails_when_socket_is_absent(tmp_path: Path) -> None:
    assert not await check_readiness(
        socket_path=str(tmp_path / "missing.sock"),
        runtime_id="runtime-1",
        desired_generation=3,
        snapshot_id="snapshot-1",
        policy_digest="d" * 64,
    )
