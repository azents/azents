"""Final provider invariants and request-private credential lifetime."""

from collections.abc import AsyncIterator
from contextvars import copy_context
from unittest.mock import AsyncMock

import pytest
from litellm.proxy._types import ProxyException
from litellm.types.utils import CallTypes

from azents_llm_proxy.auth import AgentAuthentication
from azents_llm_proxy.auth_test import incoming
from azents_llm_proxy.authority import AuthorityClient
from azents_llm_proxy.authority_test import AGENT, binding
from azents_llm_proxy.context import RequestContext
from azents_llm_proxy.egress import ProviderClients
from azents_llm_proxy.hooks import InvocationBoundary
from azents_llm_proxy.request_test import request


@pytest.fixture
async def transport_context() -> AsyncIterator[RequestContext]:
    context = RequestContext(clients=None)
    async with ProviderClients.open(context) as clients:
        context.clients = clients
        yield context


@pytest.mark.parametrize(
    "key,value",
    [
        ("model", "openai/foreign"),
        ("api_key", "foreign-account"),
        ("api_base", "https://foreign.invalid"),
        ("extra_headers", {"Authorization": "foreign"}),
        ("extra_body", {"api_key": "foreign"}),
        ("user_config", {"api_key": "foreign"}),
        ("fallbacks", ["foreign"]),
        ("custom_llm_provider", "anthropic"),
        ("aws_profile_name", "foreign"),
        ("vertex_credentials", "foreign"),
        ("num_retries", 1),
        ("max_retries", 1),
        ("caching", True),
        ("drop_params", True),
    ],
)
async def test_final_hook_denies_mutation_or_new_authority(
    key: str,
    value: object,
    transport_context: RequestContext,
) -> None:
    context = transport_context
    authority = AsyncMock(spec=AuthorityClient)
    authority.resolve.return_value = binding()
    boundary = InvocationBoundary(context)
    with context.scope():
        await AgentAuthentication(authority, context).authenticate(
            incoming(
                method="POST",
                path="/v1/responses",
                headers=[(b"authorization", f"Bearer {AGENT}".encode())],
                payload=request(),
            ),
            api_key=AGENT,
        )
        kwargs = boundary.approved()
        kwargs[key] = value
        with pytest.raises(ProxyException):
            await boundary.async_pre_call_deployment_hook(kwargs, CallTypes.aresponses)


async def test_scope_release_removes_credentials_from_copied_context() -> None:
    context = RequestContext(clients=None)
    authority = AsyncMock(spec=AuthorityClient)
    authority.resolve.return_value = binding()
    with context.scope():
        auth = await AgentAuthentication(authority, context).authenticate(
            incoming(
                method="POST",
                path="/v1/responses",
                headers=[(b"authorization", f"Bearer {AGENT}".encode())],
                payload=request(),
            ),
            api_key=AGENT,
        )
        copied = copy_context()
        assert copied.run(context.require_auth) is auth
    with pytest.raises(ProxyException):
        auth.inference()
    with pytest.raises(ProxyException):
        copied.run(context.require_auth)
    assert context.current.get() is None


@pytest.mark.parametrize("call_type", [CallTypes.aresponses, CallTypes.acompletion])
async def test_no_physical_boundary_can_run_outside_approved_asgi_scope(
    call_type: CallTypes,
) -> None:
    boundary = InvocationBoundary(RequestContext(clients=None))
    with pytest.raises(ProxyException):
        await boundary.async_pre_call_deployment_hook({}, call_type)
