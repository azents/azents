"""Official OpenRouter transport and application evidence codec contracts."""

import asyncio
import datetime
import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import replace

import httpx
import pytest
from openrouter import OpenRouter
from openrouter.errors.openroutererror import OpenRouterError
from pydantic import ValidationError

from azents.core.credentials import ApiKeySecrets
from azents.core.enums import LLMProvider
from azents.repos.llm_provider_integration.data import LLMProviderIntegrationWithSecrets
from azents.services.model_listing import providers


def _integration() -> LLMProviderIntegrationWithSecrets:
    now = datetime.datetime.now(datetime.UTC)
    return LLMProviderIntegrationWithSecrets(
        id="openrouter-integration-id",
        workspace_id="workspace-id",
        provider=LLMProvider.OPENROUTER,
        name="OpenRouter",
        config=None,
        enabled=True,
        created_at=now,
        updated_at=now,
        secrets=ApiKeySecrets(api_key="synthetic-key"),
        catalog_configuration_version=1,
    )


class _ObservedClients:
    """Retain actual HTTP and SDK resource observations without replacing dispatch."""

    def __init__(
        self,
        handler: Callable[[httpx.Request], httpx.Response],
    ) -> None:
        self.handler = handler
        self.http_clients: list[httpx.AsyncClient] = []
        self.sdk_clients: list[OpenRouter] = []
        self.factories = replace(
            providers.create_listing_client_factories(),
            http=self.http,
            openrouter=self.sdk,
        )

    def http(self, *, timeout: float) -> httpx.AsyncClient:
        assert timeout == 20.0
        client = httpx.AsyncClient(
            timeout=timeout,
            transport=httpx.MockTransport(self.handler),
        )
        self.http_clients.append(client)
        return client

    @asynccontextmanager
    async def sdk(self, *, client: httpx.AsyncClient) -> AsyncIterator[OpenRouter]:
        async with providers.create_openrouter_listing_client(client=client) as sdk:
            self.sdk_clients.append(sdk)
            yield sdk


async def test_native_sdk_retains_account_route_filter_and_sparse_evidence() -> None:
    requests: list[httpx.Request] = []
    wire = {
        "data": [
            {
                "id": "publisher/model",
                "architecture": {
                    "input_modalities": [],
                    "output_modalities": None,
                },
                "top_provider": None,
                "supported_parameters": ["tools", "structured_outputs"],
                "future": {"ignored": True},
            },
            None,
            ["invalid"],
            {"name": "missing identity"},
            {
                "id": "publisher/image-only",
                "architecture": {"output_modalities": ["image"]},
            },
        ],
        "future_envelope": True,
    }

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=wire)

    observed = _ObservedClients(respond)
    output = await providers.list_openrouter_models_for_integration(
        _integration(), clients=observed.factories
    )
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET"
    assert str(request.url) == (
        "https://openrouter.ai/api/v1/models/user?output_modalities=text"
    )
    assert request.headers["Authorization"] == "Bearer synthetic-key"
    assert request.extensions["timeout"] == {
        "connect": 20.0,
        "read": 20.0,
        "write": 20.0,
        "pool": 20.0,
    }
    assert output.summary.returned_count == 1
    assert output.summary.skipped_count == 4
    model = output.models[0]
    assert model.model_identifier == "publisher/model"
    assert model.source_metadata is not None
    assert model.source_metadata["architecture"] == {
        "input_modalities": [],
        "output_modalities": None,
    }
    assert model.source_metadata["top_provider"] is None
    assert "context_length" not in model.source_metadata
    assert "future" not in model.source_metadata
    assert len(observed.sdk_clients) == 1
    assert all(client.is_closed for client in observed.http_clients)


@pytest.mark.parametrize("status", [401, 403, 408, 409, 425, 429, 500, 503])
async def test_native_sdk_http_failure_has_existing_retry_policy(status: int) -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            status,
            json={"error": {"code": status, "message": "Provider unavailable"}},
        )

    observed = _ObservedClients(respond)
    with pytest.raises(providers.ListingProviderError) as caught:
        await providers.list_openrouter_models_for_integration(
            _integration(), clients=observed.factories
        )
    assert len(requests) == 1
    assert isinstance(caught.value.__cause__, OpenRouterError)
    assert caught.value.automatic_retry_blocked == (
        status not in {408, 409, 425, 429} and status < 500
    )
    assert all(client.is_closed for client in observed.http_clients)


@pytest.mark.parametrize("wire", [None, [], {}, {"data": None}, {"data": "wrong"}])
async def test_native_response_codec_rejects_bad_envelopes(wire: object) -> None:
    observed = _ObservedClients(lambda request: httpx.Response(200, json=wire))
    with pytest.raises(providers.ListingProviderError) as caught:
        await providers.list_openrouter_models_for_integration(
            _integration(), clients=observed.factories
        )
    assert caught.value.automatic_retry_blocked is False
    assert isinstance(caught.value.__cause__, (ValidationError, json.JSONDecodeError))
    assert all(client.is_closed for client in observed.http_clients)


async def test_native_response_codec_keeps_invalid_consumed_evidence_visible() -> None:
    observed = _ObservedClients(
        lambda request: httpx.Response(
            200,
            json={"data": [{"id": "valid", "context_length": "invalid"}]},
        )
    )
    with pytest.raises(providers.ListingProviderError) as caught:
        await providers.list_openrouter_models_for_integration(
            _integration(), clients=observed.factories
        )
    assert caught.value.automatic_retry_blocked is False
    assert isinstance(caught.value.__cause__, ValidationError)


async def test_native_response_codec_keeps_malformed_json_visible() -> None:
    observed = _ObservedClients(
        lambda request: httpx.Response(
            200, content=b"{invalid", headers={"Content-Type": "application/json"}
        )
    )
    with pytest.raises(providers.ListingProviderError) as caught:
        await providers.list_openrouter_models_for_integration(
            _integration(), clients=observed.factories
        )
    assert isinstance(caught.value.__cause__, json.JSONDecodeError)


@pytest.mark.parametrize(
    "failure", [asyncio.CancelledError(), RuntimeError("unexpected")]
)
async def test_native_sdk_unexpected_and_cancelled_dispatch_propagates(
    failure: BaseException,
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        raise failure

    observed = _ObservedClients(respond)
    with pytest.raises(type(failure)) as caught:
        await providers.list_openrouter_models_for_integration(
            _integration(), clients=observed.factories
        )
    assert caught.value is failure
    assert all(client.is_closed for client in observed.http_clients)


async def test_native_response_state_is_local_to_each_operation() -> None:
    payloads = [{"data": [{"id": "first"}]}, {"data": [{"id": "second"}]}]

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payloads.pop(0))

    observed = _ObservedClients(respond)
    first = await providers.list_openrouter_models_for_integration(
        _integration(), clients=observed.factories
    )
    second = await providers.list_openrouter_models_for_integration(
        _integration(), clients=observed.factories
    )
    assert first.models[0].model_identifier == "first"
    assert second.models[0].model_identifier == "second"
    assert len(observed.sdk_clients) == 2
    assert len(observed.http_clients) == 2
    assert all(client.is_closed for client in observed.http_clients)


async def test_sdk_debug_environment_does_not_log_provider_credentials(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("OPENROUTER_DEBUG", "true")
    observed = _ObservedClients(
        lambda request: httpx.Response(
            403,
            json={"error": {"code": 403, "message": "provider-body-secret"}},
        )
    )
    with pytest.raises(providers.ListingProviderError):
        await providers.list_openrouter_models_for_integration(
            _integration(), clients=observed.factories
        )
    assert "synthetic-key" not in caplog.text
    assert "provider-body-secret" not in caplog.text


async def test_native_sdk_transport_failure_is_not_retried() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise httpx.ReadTimeout("Provider read timed out", request=request)

    observed = _ObservedClients(respond)
    with pytest.raises(providers.ListingProviderError) as caught:
        await providers.list_openrouter_models_for_integration(
            _integration(), clients=observed.factories
        )
    assert len(requests) == 1
    assert caught.value.automatic_retry_blocked is False
    assert isinstance(caught.value.__cause__, httpx.ReadTimeout)
    assert all(client.is_closed for client in observed.http_clients)
