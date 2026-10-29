"""Supported SDK transports with fixed-origin admission and no hidden replay."""

from __future__ import annotations

import asyncio
import ssl
from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from http.cookiejar import Cookie, CookieJar, DefaultCookiePolicy
from typing import TYPE_CHECKING
from urllib.request import Request as CookieRequest

import httpx
import httpx2
from azents_llm_contract.authority import KimiCredential, TargetBinding
from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler
from openai import AsyncOpenAI

from azents_llm_proxy.provider import ProviderInvocation

if TYPE_CHECKING:
    from azents_llm_proxy.context import RequestContext

ProviderClient = AsyncHTTPHandler | AsyncOpenAI


class NoReplayTransportError(httpx.TransportError):
    """Fixed diagnostic outside the SDK handler's ConnectError resend branch."""


class NoReplayStream(httpx.AsyncByteStream):
    def __init__(self, inner: httpx.AsyncByteStream) -> None:
        self.inner = inner
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        try:
            async for chunk in self.inner:
                yield chunk
        except asyncio.CancelledError:
            raise
        except httpx.ConnectError, httpx.RemoteProtocolError:
            raise NoReplayTransportError(
                "Provider transport failed; not replayed."
            ) from None
        finally:
            await self.aclose()

    async def aclose(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            await self.inner.aclose()
        except asyncio.CancelledError:
            raise
        except httpx.ConnectError, httpx.RemoteProtocolError:
            raise NoReplayTransportError(
                "Provider stream close failed; not replayed."
            ) from None


class NoReplayTransport(httpx.AsyncBaseTransport):
    def __init__(
        self,
        inner: httpx.AsyncBaseTransport,
        approve: Callable[[str, str], None],
    ) -> None:
        self.inner = inner
        self.approve = approve

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.approve(request.method, str(request.url))
        try:
            response = await self.inner.handle_async_request(request)
        except asyncio.CancelledError:
            raise
        except httpx.ConnectError, httpx.RemoteProtocolError:
            # LiteLLM's handler has a hard-coded ConnectError resend independent
            # of num_retries. Keep HTTPX transport ownership without that resend.
            raise NoReplayTransportError(
                "Provider transport failed; not replayed."
            ) from None
        if not isinstance(response.stream, httpx.AsyncByteStream):
            raise NoReplayTransportError("Provider asynchronous stream is unavailable.")
        response.stream = NoReplayStream(response.stream)
        return response

    async def aclose(self) -> None:
        await self.inner.aclose()


class OriginTransport2(httpx2.AsyncBaseTransport):
    """The OpenAI SDK owns retries (configured zero) on its HTTPX2 client."""

    def __init__(
        self,
        inner: httpx2.AsyncBaseTransport,
        approve: Callable[[str, str], None],
    ) -> None:
        self.inner = inner
        self.approve = approve

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        self.approve(request.method, str(request.url))
        return await self.inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self.inner.aclose()


class _NoCookies(DefaultCookiePolicy):
    def set_ok(self, cookie: Cookie, request: CookieRequest) -> bool:
        return False

    def return_ok(self, cookie: Cookie, request: CookieRequest) -> bool:
        return False


@dataclass(repr=False)
class ProviderClients:
    handler: AsyncHTTPHandler
    tls: ssl.SSLContext
    context: RequestContext

    @classmethod
    @asynccontextmanager
    async def open(cls, context: RequestContext) -> AsyncIterator[ProviderClients]:
        tls = ssl.create_default_context()
        transport = NoReplayTransport(
            httpx.AsyncHTTPTransport(verify=tls, retries=0, trust_env=False),
            context.approve_egress,
        )
        handler = AsyncHTTPHandler(transport=transport, follow_redirects=False)
        try:
            yield cls(handler=handler, tls=tls, context=context)
        finally:
            await handler.client.aclose()

    def for_call(
        self,
        binding: TargetBinding,
        invocation: ProviderInvocation,
        resources: AsyncExitStack | None,
    ) -> ProviderClient:
        if not isinstance(binding.credential, KimiCredential):
            return self.handler
        if resources is None:
            raise NoReplayTransportError(
                "Inference client resource scope is unavailable."
            )
        transport = OriginTransport2(
            httpx2.AsyncHTTPTransport(verify=self.tls, retries=0, trust_env=False),
            self.context.approve_egress,
        )
        http = httpx2.AsyncClient(
            transport=transport,
            follow_redirects=False,
            trust_env=False,
            cookies=CookieJar(policy=_NoCookies()),
        )
        client = AsyncOpenAI(
            api_key=binding.credential.access_token.get_secret_value(),
            base_url=invocation.arguments["api_base"],
            max_retries=0,
            http_client=http,
        )
        resources.push_async_callback(client.close)
        return client
