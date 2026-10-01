"""Deterministic OAuth connection helpers for public E2E scenarios."""

import azentspublicclient
import requests
from azentspublicclient.api.chat_gpto_auth_v1_api import ChatGPTOAuthV1Api
from azentspublicclient.api.llm_provider_integration_v1_api import (
    LLMProviderIntegrationV1Api,
)
from azentspublicclient.api.xaio_auth_v1_api import XAIOAuthV1Api
from azentspublicclient.models.llm_provider_integration_update_request import (
    LLMProviderIntegrationUpdateRequest,
)

_OAUTH_CONNECTION_SCENARIO_PATH = "/v1/_oauth_connection_scenarios"


def _headers(token: str) -> dict[str, str]:
    """Build bearer headers."""
    return {"Authorization": f"Bearer {token}"}


def _queue_oauth_connection(
    *,
    proxy_url: str,
    provider: str,
    scenario: str,
    access_token: str,
    refresh_token: str,
) -> None:
    """Prepare one fake provider account without exposing it through Azents."""
    response = requests.post(
        f"{proxy_url}{_OAUTH_CONNECTION_SCENARIO_PATH}",
        json={
            "provider": provider,
            "scenario": scenario,
            "access_token": access_token,
            "refresh_token": refresh_token,
        },
        timeout=10,
    )
    response.raise_for_status()


def _update_integration_metadata(
    *,
    api: LLMProviderIntegrationV1Api,
    handle: str,
    token: str,
    integration_id: str,
    name: str,
    enabled: bool,
) -> None:
    """Apply public mutable fields after server-owned OAuth connection."""
    api.llm_provider_integration_v1_update_integration(
        integration_id=integration_id,
        handle=handle,
        llm_provider_integration_update_request=LLMProviderIntegrationUpdateRequest(
            name=name,
            enabled=enabled,
        ),
        _headers=_headers(token),
    )


def connect_chatgpt_oauth(
    *,
    public_api_client: azentspublicclient.ApiClient,
    proxy_url: str,
    handle: str,
    token: str,
    scenario: str,
    access_token: str,
    refresh_token: str,
    name: str,
    enabled: bool,
) -> str:
    """Connect a deterministic ChatGPT account through the public device flow."""
    _queue_oauth_connection(
        proxy_url=proxy_url,
        provider="chatgpt",
        scenario=scenario,
        access_token=access_token,
        refresh_token=refresh_token,
    )
    oauth_api = ChatGPTOAuthV1Api(public_api_client)
    started = oauth_api.chatgpt_oauth_v1_start_device(
        handle=handle,
        _headers=_headers(token),
    )
    completed = oauth_api.chatgpt_oauth_v1_poll_device(
        session_id=started.session_id,
        handle=handle,
        _headers=_headers(token),
    )
    if completed.integration is None:
        raise AssertionError("ChatGPT device flow did not create an integration")
    integration_id = completed.integration.id
    _update_integration_metadata(
        api=LLMProviderIntegrationV1Api(public_api_client),
        handle=handle,
        token=token,
        integration_id=integration_id,
        name=name,
        enabled=enabled,
    )
    return integration_id


def connect_xai_oauth(
    *,
    public_api_client: azentspublicclient.ApiClient,
    proxy_url: str,
    handle: str,
    token: str,
    scenario: str,
    access_token: str,
    refresh_token: str,
    name: str,
    enabled: bool,
) -> str:
    """Connect a deterministic xAI account through the public device flow."""
    _queue_oauth_connection(
        proxy_url=proxy_url,
        provider="xai",
        scenario=scenario,
        access_token=access_token,
        refresh_token=refresh_token,
    )
    oauth_api = XAIOAuthV1Api(public_api_client)
    started = oauth_api.xai_oauth_v1_start_device(
        handle=handle,
        _headers=_headers(token),
    )
    completed = oauth_api.xai_oauth_v1_poll_device(
        session_id=started.session_id,
        handle=handle,
        _headers=_headers(token),
    )
    if completed.integration is None:
        raise AssertionError("xAI device flow did not create an integration")
    integration_id = completed.integration.id
    _update_integration_metadata(
        api=LLMProviderIntegrationV1Api(public_api_client),
        handle=handle,
        token=token,
        integration_id=integration_id,
        name=name,
        enabled=enabled,
    )
    return integration_id
