"""Offline FastAPI dependency container regression tests."""

from collections.abc import AsyncGenerator
from typing import Annotated

import pytest
from fastapi import Depends

from .di import Container


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
