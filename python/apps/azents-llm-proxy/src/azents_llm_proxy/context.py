"""Injected request-local context for callbacks without an HTTP Request argument."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import AsyncExitStack, asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from azents_llm_contract.authority import TargetBinding
from litellm.proxy._types import ProxyException

from azents_llm_proxy.provider import ProviderInvocation, provider_invocation

if TYPE_CHECKING:
    from azents_llm_proxy.auth import BoundAuth
    from azents_llm_proxy.egress import ProviderClient, ProviderClients


@dataclass(repr=False)
class RequestScope:
    auth: BoundAuth | None
    resources: AsyncExitStack | None
    provider_client: ProviderClient | None


class RequestContext:
    """One holder per application; values belong to each outer ASGI call.

    The scope carrier is created per request, so copied asyncio contexts share
    only that request's approved binding. There is no process-global credential.
    """

    def __init__(self, clients: ProviderClients | None) -> None:
        self.clients = clients
        self.current: ContextVar[RequestScope | None] = ContextVar(
            "azents_inference_scope", default=None
        )

    @contextmanager
    def scope(self) -> Iterator[RequestScope]:
        state = RequestScope(auth=None, resources=None, provider_client=None)
        token = self.current.set(state)
        try:
            yield state
        finally:
            if state.auth is not None:
                state.auth.release()
            state.auth = None
            state.provider_client = None
            state.resources = None
            self.current.reset(token)

    @asynccontextmanager
    async def request_scope(self) -> AsyncIterator[RequestScope]:
        with self.scope() as state:
            async with AsyncExitStack() as resources:
                state.resources = resources
                yield state

    def client_for(
        self,
        binding: TargetBinding,
        invocation: ProviderInvocation,
    ) -> ProviderClient:
        state = self.current.get()
        if state is None or self.clients is None:
            raise ProxyException(
                message="Inference transport is unavailable.",
                type="service_unavailable_error",
                param="azents_authority",
                code=503,
            )
        if state.provider_client is None:
            state.provider_client = self.clients.for_call(
                binding,
                invocation,
                state.resources,
            )
        return state.provider_client

    def approve_egress(self, method: str, url: str) -> None:
        """Check the actual SDK URL after its provider transformation."""
        binding = self.require_auth().inference()
        base = urlsplit(provider_invocation(binding).arguments["api_base"])
        actual = urlsplit(url)
        prefix = base.path.rstrip("/")
        if (
            method != "POST"
            or actual.scheme != "https"
            or actual.hostname != base.hostname
            or (actual.port or 443) != (base.port or 443)
            or actual.username is not None
            or actual.password is not None
            or (prefix and not actual.path.startswith(prefix + "/"))
        ):
            raise ProxyException(
                message="Unapproved provider endpoint reached dispatch.",
                type="permission_error",
                param="azents_authority",
                code=403,
            )

    def bind(self, auth: BoundAuth) -> None:
        state = self.current.get()
        if state is None:
            raise ProxyException(
                message="Inference request scope is unavailable.",
                type="service_unavailable_error",
                param="azents_authority",
                code=503,
            )
        if state.auth is not None:
            raise ProxyException(
                message="Inference authority was already bound.",
                type="permission_error",
                param="azents_authority",
                code=403,
            )
        state.auth = auth

    def require_auth(self) -> BoundAuth:
        state = self.current.get()
        if state is None or state.auth is None:
            raise ProxyException(
                message="Approved inference context is unavailable.",
                type="permission_error",
                param="azents_authority",
                code=403,
            )
        return state.auth
