"""Private, online authority client; never accepts or relays inference content."""

import ssl
from dataclasses import dataclass, field
from typing import TypeVar

import httpx
from azents_llm_contract.authority import (
    AuthorityPayload,
    ModelListRequest,
    ModelListResponse,
    ResolveRequest,
    TargetBinding,
)
from pydantic import SecretStr, ValidationError

from azents_llm_proxy.config import Settings

Payload = TypeVar("Payload", bound=AuthorityPayload)


class AuthorityDenied(Exception):
    """Safe denial without exposing service/Agent/target existence details."""

    def __init__(self, status: int) -> None:
        super().__init__("Inference authority denied this request.")
        self.status = status


class AuthorityUnavailable(Exception):
    """Preparation failed; never classify this as an invalid Agent credential."""


@dataclass(frozen=True, repr=False)
class AuthorityClient:
    client: httpx.AsyncClient
    resolver_key: SecretStr = field(repr=False)

    async def list_models(self, agent_token: SecretStr) -> ModelListResponse:
        return await self._post(
            "models", ModelListRequest(agent_token=agent_token), ModelListResponse
        )

    async def resolve(
        self, agent_token: SecretStr, *, model: str, target_id: str
    ) -> TargetBinding:
        result = await self._post(
            "resolve",
            ResolveRequest(agent_token=agent_token, model=model, target_id=target_id),
            TargetBinding,
        )
        # A successful response must bind the original selectors, not substitute a
        # different account/model after request parsing or an upstream redirect.
        if (
            result.public_model != model
            or result.model_identifier != model
            or result.target_id != target_id
        ):
            raise AuthorityUnavailable("Authority returned an inconsistent binding.")
        return result

    async def _post(
        self, operation: str, payload: AuthorityPayload, response_type: type[Payload]
    ) -> Payload:
        try:
            response = await self.client.post(
                operation,
                content=payload.protected_json(),
                headers={
                    "X-Azents-LLM-Resolver": self.resolver_key.get_secret_value(),
                    "Content-Type": "application/json",
                },
                follow_redirects=False,
            )
        except httpx.HTTPError:
            raise AuthorityUnavailable("Inference authority is unavailable.") from None
        if response.status_code in (401, 403):
            # 403 may mean a rejected resolver service key, not an invalid Agent.
            raise AuthorityDenied(response.status_code)
        if response.status_code != 200:
            raise AuthorityUnavailable("Inference authority preparation failed.")
        try:
            return response_type.model_validate_json(response.content)
        except ValidationError:
            # Never log validation input or authority response bodies.
            raise AuthorityUnavailable(
                "Inference authority returned an invalid contract."
            ) from None


def create_http_client(settings: Settings) -> httpx.AsyncClient:
    """Composition-root resource; caller owns closure, TLS verification stays on."""
    tls = ssl.create_default_context(cafile=settings.authority_ca_file)
    return httpx.AsyncClient(
        base_url=settings.authority_url,
        timeout=settings.authority_timeout_seconds,
        follow_redirects=False,
        trust_env=False,
        transport=httpx.AsyncHTTPTransport(verify=tls, retries=0, trust_env=False),
    )
