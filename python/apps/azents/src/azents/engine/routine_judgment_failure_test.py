"""Routine judgment failure and cancellation preserve provider cleanup semantics."""

import asyncio
import dataclasses

import httpx2
import pytest
from openai import AsyncOpenAI

from azents.core.enums import LLMProvider
from azents.core.openai_client_config import OpenAIResponsesClientConfig
from azents.core.routine_judgment_test import candidate
from azents.engine.events.openai_responses import (
    OpenAIResponsesClient,
    OpenAISDKResponsesClient,
)
from azents.engine.model_factories import get_model_sdk_factories
from azents.engine.routine_judgment import call_routine_judgment
from azents.engine.routine_judgment_test import context, prepared, selection
from azents.engine.run.provider_failure import ModelProviderFailure
from azents.testing.model_stream import make_test_model_stream_watchdog


@pytest.mark.parametrize("outcome", ["provider_failure", "cancelled", "bad_candidates"])
async def test_failure_propagates_without_retry_or_synthetic_no_action(
    outcome: str,
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    clients: list[httpx2.AsyncClient] = []
    calls: list[httpx2.Request] = []

    async def respond(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        started.set()
        if outcome == "cancelled":
            await release.wait()
        return httpx2.Response(
            401,
            json={"error": {"message": "Synthetic rejection", "type": "auth_error"}},
        )

    def factory(*, config: OpenAIResponsesClientConfig) -> OpenAIResponsesClient:
        client = httpx2.AsyncClient(transport=httpx2.MockTransport(respond))
        clients.append(client)
        return OpenAISDKResponsesClient(
            AsyncOpenAI(api_key="synthetic", http_client=client, max_retries=0),
            websocket_headers=None,
        )

    model = selection(LLMProvider.OPENAI)
    watchdog = make_test_model_stream_watchdog()
    task = asyncio.create_task(
        call_routine_judgment(
            judgment_id="failed-operation",
            candidates=(candidate(), candidate())
            if outcome == "bad_candidates"
            else (candidate(),),
            selection=model,
            request=prepared(model),
            sdk_factories=dataclasses.replace(
                get_model_sdk_factories(), openai_responses=factory
            ),
            credential_kwargs={},
            pricing=None,
            watchdog=watchdog,
            timeout_policy=watchdog.resolve_policy(
                provider="openai", model="fixture", inference_profile=None
            ),
            call_context=context(model),
        )
    )
    try:
        if outcome == "cancelled":
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        elif outcome == "bad_candidates":
            with pytest.raises(ValueError, match="duplicate candidates"):
                await task
        else:
            with pytest.raises(ModelProviderFailure):
                await task
        assert len(calls) == (0 if outcome == "bad_candidates" else 1)
        assert len(clients) == (0 if outcome == "bad_candidates" else 1)
        assert all(client.is_closed for client in clients)
    finally:
        release.set()
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
