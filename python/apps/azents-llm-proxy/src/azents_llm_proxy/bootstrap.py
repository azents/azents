"""Single-process composition root for the official Proxy configuration exports."""

from dataclasses import dataclass
from pathlib import Path

from fastapi import Request
from litellm.proxy._types import ProxyException

from azents_llm_proxy.auth import AgentAuthentication, BoundAuth
from azents_llm_proxy.authority import AuthorityClient
from azents_llm_proxy.context import RequestContext
from azents_llm_proxy.hooks import InvocationBoundary


@dataclass
class Composition:
    authentication: AgentAuthentication | None


composition = Composition(authentication=None)
context = RequestContext(clients=None)
boundary = InvocationBoundary(context)
CONFIG = Path(__file__).with_name("proxy.yaml")


def configure(authority: AuthorityClient) -> None:
    """Called only by the process composition root before accepting requests."""
    composition.authentication = AgentAuthentication(
        authority=authority, context=context
    )


async def authenticate(request: Request, api_key: str) -> BoundAuth:
    authentication = composition.authentication
    if authentication is None:
        raise ProxyException(
            message="Inference authority is not configured.",
            type="service_unavailable_error",
            param="azents_authority",
            code=503,
        )
    return await authentication.authenticate(request, api_key)
