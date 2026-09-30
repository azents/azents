"""Offline FastAPI dependency container regression tests."""

from collections.abc import AsyncGenerator
from typing import Annotated
from unittest.mock import patch

import pytest
from fastapi import Depends, FastAPI, WebSocket
from fastapi.dependencies.utils import get_dependant
from starlette.requests import HTTPConnection
from starlette.types import Message, Scope

from .di import Container, get_container


@pytest.mark.asyncio
async def test_container_resolves_class_dependency_graph_and_caches_values() -> None:
    """Class dependency graphs use FastAPI's current cache key semantics."""
    dependency_calls = 0
    service_calls = 0
    dependency_value = object()

    def get_dependency() -> object:
        nonlocal dependency_calls
        dependency_calls += 1
        return dependency_value

    class Service:
        def __init__(
            self,
            dependency: Annotated[object, Depends(get_dependency)],
        ) -> None:
            nonlocal service_calls
            service_calls += 1
            self.dependency = dependency

    async with Container() as container:
        first = await container.solve(Service)
        second = await container.solve(Service)

    assert first is second
    assert first.dependency is dependency_value
    assert dependency_calls == 1
    assert service_calls == 1


@pytest.mark.asyncio
async def test_container_closes_async_generator_dependency() -> None:
    """Async generator dependencies remain active until the container drains."""
    events: list[str] = []
    resource = object()

    async def get_resource() -> AsyncGenerator[object]:
        events.append("entered")
        yield resource
        events.append("closed")

    async with Container() as container:
        assert await container.solve(get_resource) is resource
        assert events == ["entered"]

    assert events == ["entered", "closed"]


@pytest.mark.asyncio
async def test_container_reuses_unmodified_graph_with_an_overridden_child() -> None:
    """Changed callables rebuild graphs while retaining cache and cleanup."""
    resource = object()
    events: list[str] = []

    def get_original_resource() -> object:
        raise AssertionError("The original resource dependency must be overridden.")

    async def get_overridden_resource() -> AsyncGenerator[object]:
        events.append("entered")
        yield resource
        events.append("closed")

    def get_middle(
        value: Annotated[object, Depends(get_original_resource)],
    ) -> object:
        return value

    def get_root(value: Annotated[object, Depends(get_middle)]) -> object:
        return value

    with patch("azcommon.di.get_dependant", wraps=get_dependant) as build_graph:
        async with Container(
            dependency_overrides={
                get_original_resource: get_overridden_resource,
                get_middle: get_middle,
            }
        ) as container:
            assert await container.solve(get_root) is resource
            assert await container.solve(get_root) is resource
            assert events == ["entered"]

    assert events == ["entered", "closed"]
    calls = [call.kwargs["call"] for call in build_graph.call_args_list]
    assert len(calls) == 4
    assert calls[1] is get_overridden_resource
    assert calls[3] is get_overridden_resource
    assert get_root not in calls
    assert get_middle not in calls
    assert get_original_resource not in calls


@pytest.mark.asyncio
async def test_offline_container_still_supplies_its_own_binding() -> None:
    """Offline composition overrides the request-only Container lookup."""

    def get_current(
        container: Annotated[Container, Depends(get_container)],
    ) -> Container:
        return container

    async with Container() as container:
        assert await container.solve(get_current) is container


@pytest.mark.parametrize("connection_type", ["http", "websocket"])
def test_get_container_requires_application_binding(connection_type: str) -> None:
    """Missing application state fails explicitly for both request transports."""
    app = FastAPI()
    connection = HTTPConnection({"type": connection_type, "app": app})

    with pytest.raises(RuntimeError, match="Container was not configured"):
        get_container(connection)


@pytest.mark.parametrize("connection_type", ["http", "websocket"])
@pytest.mark.parametrize("binding", [None, object()])
def test_get_container_rejects_invalid_application_binding(
    connection_type: str,
    binding: object,
) -> None:
    """A configured state value must be the real Container type."""
    app = FastAPI()
    app.state.di_container = binding
    connection = HTTPConnection({"type": connection_type, "app": app})

    with pytest.raises(RuntimeError, match="Container binding is invalid"):
        get_container(connection)


@pytest.mark.asyncio
@pytest.mark.parametrize("connection_type", ["http", "websocket"])
async def test_fastapi_resolves_shared_container_without_overrides(
    connection_type: str,
) -> None:
    """FastAPI injects one borrowed application Container for HTTP and WebSockets."""
    container = Container()
    app = FastAPI()
    app.state.di_container = container
    resolved: list[Container] = []
    resource_events: list[str] = []
    resource = object()

    async def get_resource() -> AsyncGenerator[object]:
        resource_events.append("entered")
        yield resource
        resource_events.append("closed")

    @app.get("/")
    async def http_route(
        current: Annotated[Container, Depends(get_container)],
    ) -> dict[str, bool]:
        resolved.append(current)
        return {"resolved": True}

    @app.websocket("/")
    async def websocket_route(
        websocket: WebSocket,
        current: Annotated[Container, Depends(get_container)],
    ) -> None:
        resolved.append(current)
        await websocket.accept()
        await websocket.send_text("resolved")
        await websocket.close()

    scope: Scope = {
        "type": connection_type,
        "path": "/",
        "root_path": "",
        "query_string": b"",
        "headers": [],
    }
    if connection_type == "http":
        scope.update(method="GET", scheme="http", http_version="1.1")
    else:
        scope.update(scheme="ws", subprotocols=[])
    messages: list[Message] = []

    async def receive() -> Message:
        if connection_type == "http":
            return {"type": "http.request", "body": b"", "more_body": False}
        return {"type": "websocket.connect"}

    async def send(message: Message) -> None:
        messages.append(message)

    async with container:
        assert await container.solve(get_resource) is resource
        await app(scope, receive, send)
        assert resolved == [container]
        assert container.dependency_overrides[get_container]() is container
        assert resource_events == ["entered"]

    assert resource_events == ["entered", "closed"]
    assert app.dependency_overrides == {}
    if connection_type == "http":
        assert messages[0]["type"] == "http.response.start"
        assert messages[0]["status"] == 200
        assert messages[1]["body"] == b'{"resolved":true}'
    else:
        assert [message["type"] for message in messages] == [
            "websocket.accept",
            "websocket.send",
            "websocket.close",
        ]
        assert messages[1]["text"] == "resolved"
