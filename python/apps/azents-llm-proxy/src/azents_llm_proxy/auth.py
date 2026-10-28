"""Official custom-auth callable with request-private approved authority."""

import json
from dataclasses import dataclass

from azents_llm_contract.authority import AuthenticatedIdentity, TargetBinding
from fastapi import Request
from litellm.proxy._types import ProxyException, UserAPIKeyAuth
from pydantic import PrivateAttr, SecretStr

from azents_llm_proxy.authority import (
    AuthorityClient,
    AuthorityDenied,
    AuthorityUnavailable,
)
from azents_llm_proxy.context import RequestContext
from azents_llm_proxy.request import InferenceRequest, RequestRejected, decode_request


class BoundAuth(UserAPIKeyAuth):
    """Secrets and prompt data never become ordinary auth/logging fields."""

    _binding: TargetBinding | None = PrivateAttr(default=None)
    _request: InferenceRequest | None = PrivateAttr(default=None)

    def inference(self) -> TargetBinding:
        if self._binding is None or self._request is None:
            raise ProxyException(
                message="Approved inference context is missing.",
                type="permission_error",
                param="azents_authority",
                code=403,
            )
        return self._binding

    def selectors(self) -> InferenceRequest:
        if self._request is None:
            raise ProxyException(
                message="Approved request context is missing.",
                type="permission_error",
                param="azents_authority",
                code=403,
            )
        return self._request

    def release(self) -> None:
        """Release request-owned references without claiming secure memory erasure."""
        self._binding = None
        self._request = None


def _bearer(request: Request) -> SecretStr:
    values = request.headers.getlist("authorization")
    aliases = (
        "x-api-key",
        "api-key",
        "x-goog-api-key",
        "anthropic-api-key",
        "x-litellm-api-key",
        "openai-organization",
        "openai-project",
        "chatgpt-account-id",
        "x-msh-device-id",
    )
    routing_header = any(
        name.startswith(("x-litellm-", "litellm-")) for name in request.headers
    )
    if (
        len(values) != 1
        or any(alias in request.headers for alias in aliases)
        or routing_header
    ):
        raise ProxyException(
            message="One Agent bearer is required.",
            type="authentication_error",
            param="authorization",
            code=401,
        )
    scheme, separator, token = values[0].partition(" ")
    if (
        scheme.lower() != "bearer"
        or not separator
        or not token
        or len(token) > 512
        or any(character.isspace() for character in token)
        or "," in token
    ):
        raise ProxyException(
            message="Invalid Agent bearer.",
            type="authentication_error",
            param="authorization",
            code=401,
        )
    return SecretStr(token)


def _auth(identity: AuthenticatedIdentity, models: list[str]) -> BoundAuth:
    return BoundAuth(
        # A nonsecret durable token ID is sufficient for accounting. The raw
        # Agent bearer must not enter UserAPIKeyAuth's serialized api_key field.
        api_key=identity.token_id,
        user_id=identity.agent_id,
        team_id=identity.workspace_id,
        models=models,
        metadata={
            "azents_agent_id": identity.agent_id,
            "azents_workspace_id": identity.workspace_id,
            "azents_supply_id": identity.supply_id,
            "azents_token_id": identity.token_id,
        },
    )


@dataclass(frozen=True)
class AgentAuthentication:
    authority: AuthorityClient
    context: RequestContext

    async def authenticate(self, request: Request, api_key: str) -> BoundAuth:
        # Inspect the real header, not provider-specific aliases accepted by the
        # upstream auth extractor. Exact normalized paths close alternate APIs.
        operation = (request.method, request.url.path)
        if (
            operation not in {("POST", "/v1/responses"), ("GET", "/v1/models")}
            or request.url.query
        ):
            raise ProxyException(
                message="Operation is not available to Agent credentials.",
                type="permission_error",
                param="route",
                code=403,
            )
        token = _bearer(request)
        try:
            if operation == ("GET", "/v1/models"):
                listing = await self.authority.list_models(token)
                auth = _auth(listing.identity, list(listing.models))
                self.context.bind(auth)
                return auth
            try:
                body = await request.json()
            except json.JSONDecodeError, UnicodeDecodeError:
                raise RequestRejected("Invalid Responses request.") from None
            selected = decode_request(body)
            binding = await self.authority.resolve(
                token, model=selected.model, target_id=selected.target_id
            )
            auth = _auth(binding.identity, [binding.public_model])
            auth._binding = binding
            auth._request = selected
            self.context.bind(auth)
            return auth
        except RequestRejected:
            raise ProxyException(
                message="Invalid or unsupported Responses request.",
                type="invalid_request_error",
                param="request",
                code=400,
            ) from None
        except AuthorityDenied as error:
            raise ProxyException(
                message="Inference authority denied this request.",
                type="authentication_error"
                if error.status == 401
                else "permission_error",
                param="azents_authority",
                code=error.status,
            ) from None
        except AuthorityUnavailable:
            raise ProxyException(
                message="Inference authority preparation is unavailable.",
                type="service_unavailable_error",
                param="azents_authority",
                code=503,
            ) from None
