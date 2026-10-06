"""Real Runner ownership fences remain admission failures at official SDK wires."""

import asyncio
import dataclasses

import httpx2
import pytest

from azents.broker.memory import InMemoryBroker, InMemoryBrokerState
from azents.core.agent import SelectableModelCandidate
from azents.core.enums import EventKind, LLMModelDeveloper, LLMProvider
from azents.engine.events.model_messages import transient_model_message
from azents.engine.events.types import UserMessagePayload
from azents.engine.model_factories import get_model_sdk_factories
from azents.engine.model_stream import ModelDispatchAdmissionError
from azents.engine.provider_model_operation import bind_provider_model_operation
from azents.engine.providers.bedrock_lifecycle_test import bedrock_call, nominal_body
from azents.engine.providers.model_factory import (
    ProviderModelFactory,
    ProviderTransports,
)
from azents.engine.run.model_transport import InMemoryModelTransportState
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.services.historical_memory.consolidation_dispatch import (
    ConsolidationDispatchAdmission,
)
from azents.services.historical_memory.consolidation_host_test import (
    _host,
    _ScriptedModel,
)
from azents.services.historical_memory.execution_context import (
    MemoryExecutionContextService,
)
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_model_settings,
)
from azents.testing.model_stream import make_test_model_stream_watchdog
from azents.testing.provider_native_envelopes import core_native_response
from azents.worker.run.memory_execution import _MemorySummaryCall
from azents.worker.session.memory_runner_integration_test import _lifecycle
from azents.worker.worker_test import _Host, _make_session_runner


@pytest.mark.parametrize("work_kind", ["dispatch", "compaction"])
@pytest.mark.parametrize("wire", ["anthropic_http", "bedrock"])
async def test_real_runner_stale_owner_is_preserved_at_native_memory_wire(
    rdb_session_manager: SessionManager[WriteSession],
    work_kind: str,
    wire: str,
) -> None:
    """Takeover between admission and I/O must never become an SDK transport retry."""
    host = await _host(
        rdb_session_manager, _ScriptedModel([], close_failure=False), max_turns=5
    )
    principal = host.principal
    broker_state = InMemoryBrokerState(clock=asyncio.get_running_loop().time)
    broker = InMemoryBroker(broker_state, worker_id="native-memory-worker")
    lifecycle = _lifecycle(rdb_session_manager, broker)
    runner = _make_session_runner(_Host())
    runner.session_lifecycle = lifecycle
    runner.owner_generation = principal.owner.owner_generation
    runner.running_session_id = principal.owner.session_id
    runner.internal_execution = True
    runner_check_stop = runner._make_check_stop_fn(principal.owner.session_id)
    checks = 0

    async def takeover_at_physical_dispatch() -> bool:
        nonlocal checks
        checks += 1
        if checks == 2:
            generation = await lifecycle.claim_owner_generation(
                principal.owner.session_id
            )
            assert generation > principal.owner.owner_generation
        return await runner_check_stop()

    captured: list[httpx2.Request] = []
    model_name = "anthropic.claude-3-haiku-20240307-v1:0"
    boto = bedrock_call(model=model_name, chunks=[nominal_body(model_name)])
    envelope = core_native_response(
        protocol="anthropic", model="claude-sonnet-4-5", text="Scoped current evidence"
    )

    def respond(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        return httpx2.Response(
            200, headers={"content-type": envelope.content_type}, content=envelope.body
        )

    defaults = get_model_sdk_factories()

    def factory(
        *, provider: LLMProvider, credential_kwargs: dict[str, object]
    ) -> ProviderModelFactory:
        result = defaults.provider_model(
            provider=provider, credential_kwargs=credential_kwargs
        )
        result.transports = (
            ProviderTransports(bedrock_client=boto.boundary.client)
            if wire == "bedrock"
            else ProviderTransports(httpx2=httpx2.MockTransport(respond))
        )
        return result

    selection = make_test_model_selection(
        provider=LLMProvider.AWS_BEDROCK
        if wire == "bedrock"
        else LLMProvider.ANTHROPIC,
        model_identifier=model_name if wire == "bedrock" else "claude-sonnet-4-5",
        model_developer=LLMModelDeveloper.ANTHROPIC,
    )
    settings = make_test_model_settings()
    credentials: dict[str, object] = (
        {
            "aws_region_name": "us-east-1",
            "aws_access_key_id": "synthetic-sdk-key",
            "aws_secret_access_key": "synthetic-sdk-secret",
        }
        if wire == "bedrock"
        else {"api_key": "synthetic", "base_url": "https://synthetic.invalid"}
    )
    sdk_factories = dataclasses.replace(defaults, provider_model=factory)
    watchdog = make_test_model_stream_watchdog()
    transport = InMemoryModelTransportState(websocket_enabled=False)
    model = bind_provider_model_operation(
        selection=selection,
        settings=settings,
        credential_kwargs=credentials,
        effective_input_tokens=128_000,
        sdk_factories=sdk_factories,
        watchdog=watchdog,
        websocket_enabled=False,
        transport_state=transport,
    )
    context = host.context_port
    assert isinstance(context, MemoryExecutionContextService)
    try:
        async with asyncio.timeout(8):
            if work_kind == "compaction":
                candidate = SelectableModelCandidate(
                    model_selection=selection, settings=settings
                )
                summary = _MemorySummaryCall(
                    principal,
                    candidate,
                    credentials,
                    128_000,
                    sdk_factories,
                    watchdog,
                    False,
                    context,
                    host.execution_repository,
                    takeover_at_physical_dispatch,
                )
                with pytest.raises(ModelDispatchAdmissionError) as failure:
                    await summary(
                        candidate=candidate,
                        credential_kwargs=credentials,
                        effective_input_tokens=128_000,
                        transport_state=transport,
                        system_prompt="Compact only the current private execution.",
                        user_prompt="Summarize the supplied execution context.",
                        conversation_text="The current scoped task is unfinished.",
                        session_id=principal.owner.session_id,
                    )
            else:
                admission = ConsolidationDispatchAdmission(
                    principal,
                    host.execution_repository,
                    context,
                    takeover_at_physical_dispatch,
                )
                await admission.admit()
                prepared = model.prepare(
                    [
                        transient_model_message(
                            EventKind.USER_MESSAGE,
                            UserMessagePayload(
                                sender_user_id=None, content="Current authorized input"
                            ),
                        )
                    ],
                    None,
                    system_prompt="Private Memory task",
                    output_tokens=None,
                )
                with pytest.raises(ModelDispatchAdmissionError) as failure:
                    await model.invoke(
                        prepared,
                        context=admission.context(
                            provider=selection.provider.value,
                            integration_id=selection.llm_provider_integration_id,
                            model=selection.model_identifier,
                        ),
                    )
            assert failure.value.reason == "ownership"
            assert (
                str(failure.value) == "Internal model dispatch admission was rejected."
            )
            assert checks == 2
            assert captured == [] and boto.boundary.paths == []
    finally:
        boto.boundary.release_all()
        await model.close()
        await boto.adapter.close()
        await asyncio.to_thread(boto.boundary.client.close)
        await broker_state.aclose()
