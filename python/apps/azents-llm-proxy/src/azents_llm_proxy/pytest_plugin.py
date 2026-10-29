"""Offline SDK prerequisites; unknown alternative HTTP paths fail closed."""

import socket
from collections.abc import AsyncIterator
from typing import NoReturn

import httpx2
import pytest
import pytest_asyncio
import requests

from azents_llm_proxy import bootstrap
from azents_llm_proxy.egress import ProviderClients


@pytest.fixture(autouse=True)
def deny_external_fallbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    def deny_request(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("An unmocked SDK credential request was attempted.")

    def deny_httpx2(request: httpx2.Request) -> NoReturn:
        raise AssertionError("An unmocked SDK HTTPX2 request was attempted.")

    def mock_transport(**kwargs: object) -> httpx2.AsyncBaseTransport:
        return httpx2.MockTransport(deny_httpx2)

    monkeypatch.setattr(requests.Session, "request", deny_request)
    monkeypatch.setattr(httpx2, "AsyncHTTPTransport", mock_transport)
    monkeypatch.setattr(socket.socket, "connect", deny_request)


@pytest_asyncio.fixture
async def protected_provider_clients() -> AsyncIterator[None]:
    async with ProviderClients.open(bootstrap.context) as clients:
        bootstrap.context.clients = clients
        try:
            yield
        finally:
            bootstrap.context.clients = None
