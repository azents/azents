"""Native HTTP/WebSocket and Pydantic AI wires admit the common Memory owner."""

import dataclasses
from collections.abc import AsyncIterator

import httpx2
import pytest
from openai import BadRequestError, omit
from openai.types.responses import (
    Response,
    ResponseCompletedEvent,
    ResponseOutputMessage,
    ResponseOutputText,
    ResponseStreamEvent,
    ResponseUsage,
)
from openai.types.responses.response_usage import (
    InputTokensDetails,
    OutputTokensDetails,
)

from azents.core.enums import EventKind, LLMModelDeveloper, LLMProvider
from azents.core.historical_memory_consolidation import MemoryExecutionPrincipal
from azents.core.openai_client_config import OpenAIResponsesClientConfig
from azents.engine.events.model_messages import transient_model_message
from azents.engine.events.openai_responses import OpenAIResponsesWebSocketConnection
from azents.engine.events.types import UserMessagePayload
from azents.engine.model_factories import get_model_sdk_factories
from azents.engine.model_factory_types import ModelSDKFactories
from azents.engine.model_stream import ModelDispatchAdmissionError
from azents.engine.provider_model_operation import bind_provider_model_operation
from azents.engine.providers.model_factory import (
    ProviderModelFactory,
    ProviderTransports,
)
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.session_execution_record import SessionExecutionRecordRepository
from azents.services.historical_memory.consolidation_dispatch import (
    ConsolidationDispatchAdmission,
)
from azents.services.historical_memory.consolidation_host_test import (
    _host,
    _never_stop,
    _ScriptedModel,
)
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_model_settings,
)
from azents.testing.model_stream import make_test_model_stream_watchdog
from azents.testing.provider_native_envelopes import core_native_response


def _completed(number: int) -> ResponseCompletedEvent:
    return ResponseCompletedEvent(
        type="response.completed",
        sequence_number=1,
        response=Response(
            id=f"response-{number}",
            created_at=1,
            model="gpt-4o",
            object="response",
            output=[
                ResponseOutputMessage(
                    id=f"message-{number}",
                    role="assistant",
                    type="message",
                    status="completed",
                    content=[
                        ResponseOutputText(
                            type="output_text",
                            text="Scoped Memory prose",
                            annotations=[],
                        )
                    ],
                )
            ],
            parallel_tool_calls=True,
            tool_choice="auto",
            tools=[],
            status="completed",
            usage=ResponseUsage(
                input_tokens=10,
                output_tokens=5,
                total_tokens=15,
                input_tokens_details=InputTokensDetails(
                    cached_tokens=0, cache_write_tokens=0
                ),
                output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
            ),
        ),
    )


@dataclasses.dataclass
class _Stream:
    event: ResponseStreamEvent

    async def __aiter__(self) -> AsyncIterator[ResponseStreamEvent]:
        yield self.event

    async def aclose(self) -> None:
        pass


class _BoundaryClient:
    def __init__(
        self,
        manager: SessionManager[WriteSession],
        principal: MemoryExecutionPrincipal,
        *,
        lose_owner: bool,
    ) -> None:
        self.manager = manager
        self.principal = principal
        self.lose_owner = lose_owner
        self.requests: list[dict[str, object]] = []
        self.pending: list[ResponseStreamEvent] = []
        self.socket_connected = False
        self.closed = False

    async def _dispatch(
        self, kwargs: dict[str, object], *, websocket: bool
    ) -> ResponseStreamEvent:
        self.requests.append(kwargs)
        if not websocket and isinstance(kwargs.get("previous_response_id"), str):
            if self.lose_owner:
                async with self.manager() as session:
                    await SessionExecutionRecordRepository().claim_owner_generation(
                        session, self.principal.owner.session_id
                    )
            raise BadRequestError(
                "Synthetic expired response",
                response=httpx2.Response(
                    400,
                    request=httpx2.Request(
                        "POST", "https://synthetic.invalid/responses"
                    ),
                ),
                body={"code": "previous_response_not_found"},
            )
        return _completed(len(self.requests))

    async def create_response(self, **kwargs: object) -> object:
        return _Stream(await self._dispatch(kwargs, websocket=False))

    async def connect_websocket(self) -> OpenAIResponsesWebSocketConnection:
        self.socket_connected = True
        return _Socket(self)

    async def close(self) -> None:
        self.closed = True


@dataclasses.dataclass
class _Socket:
    client: _BoundaryClient

    async def create_response(self, **kwargs: object) -> None:
        self.client.pending.append(await self.client._dispatch(kwargs, websocket=True))

    async def receive_event(self) -> ResponseStreamEvent:
        return self.client.pending.pop(0)

    async def close(self) -> None:
        pass


def _unused_provider(
    *, provider: LLMProvider, credential_kwargs: dict[str, object]
) -> ProviderModelFactory:
    raise AssertionError("Native test must use its captured client.")


@pytest.mark.parametrize("websocket", [False, True])
@pytest.mark.parametrize("output_tokens", [None, 20_000])
async def test_native_continuation_preserves_common_admission_and_settings(
    rdb_session_manager: SessionManager[WriteSession],
    websocket: bool,
    output_tokens: int | None,
) -> None:
    host = await _host(
        rdb_session_manager, _ScriptedModel([], close_failure=False), max_turns=5
    )
    client = _BoundaryClient(rdb_session_manager, host.principal, lose_owner=False)

    def factory(*, config: OpenAIResponsesClientConfig) -> _BoundaryClient:
        return client

    selection = make_test_model_selection()
    selection.normalized_capabilities.tool_calling.supported = True
    selection.normalized_capabilities.parameters.max_output_tokens = True
    model = bind_provider_model_operation(
        selection=selection,
        settings=make_test_model_settings().model_copy(
            update={"max_output_tokens": output_tokens}
        ),
        credential_kwargs={"api_key": "synthetic"},
        effective_input_tokens=128_000,
        sdk_factories=ModelSDKFactories(factory, _unused_provider),
        watchdog=make_test_model_stream_watchdog(),
        websocket_enabled=websocket,
        transport_state=None,
    )
    catalog = host.tools.catalog(selection, writer=host.tools.observations.snapshot())
    messages = [
        transient_model_message(
            EventKind.USER_MESSAGE,
            UserMessagePayload(
                sender_user_id=None, content="Current scoped summaries."
            ),
        )
    ]
    try:
        for _ in range(2):
            prepared = model.prepare(
                messages,
                catalog,
                system_prompt="Current private Memory task",
                output_tokens=model.max_output_tokens,
            )
            dispatch = ConsolidationDispatchAdmission(
                host.principal,
                host.execution_repository,
                host.context_port,
                _never_stop,
            )
            await dispatch.admit()
            output = await model.invoke(
                prepared,
                context=dispatch.context(
                    provider="openai",
                    integration_id=selection.llm_provider_integration_id,
                    model=selection.model_identifier,
                ),
            )
            await dispatch.settle(output.usage)
            messages.extend(output.events)
            messages.append(
                transient_model_message(
                    EventKind.USER_MESSAGE,
                    UserMessagePayload(
                        sender_user_id=None, content="Continue without accepting prose."
                    ),
                )
            )
    finally:
        await model.close()
    assert client.closed and client.socket_connected == websocket
    assert len(client.requests) == (2 if websocket else 3)
    assert isinstance(client.requests[1]["previous_response_id"], str)
    assert all(
        request["max_output_tokens"]
        == (omit if output_tokens is None else output_tokens)
        for request in client.requests
    )


async def test_native_retry_rechecks_owner_before_full_request_resend(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    host = await _host(
        rdb_session_manager, _ScriptedModel([], close_failure=False), max_turns=5
    )
    client = _BoundaryClient(rdb_session_manager, host.principal, lose_owner=True)

    def factory(*, config: OpenAIResponsesClientConfig) -> _BoundaryClient:
        return client

    selection = make_test_model_selection()
    model = bind_provider_model_operation(
        selection=selection,
        settings=make_test_model_settings(),
        credential_kwargs={"api_key": "synthetic"},
        effective_input_tokens=128_000,
        sdk_factories=ModelSDKFactories(factory, _unused_provider),
        watchdog=make_test_model_stream_watchdog(),
        websocket_enabled=False,
        transport_state=None,
    )
    messages = [
        transient_model_message(
            EventKind.USER_MESSAGE,
            UserMessagePayload(sender_user_id=None, content="Scoped evidence"),
        )
    ]
    try:
        first = model.prepare(
            messages, None, system_prompt="Scoped Memory", output_tokens=None
        )
        dispatch = ConsolidationDispatchAdmission(
            host.principal, host.execution_repository, host.context_port, _never_stop
        )
        output = await model.invoke(
            first,
            context=dispatch.context(
                provider="openai",
                integration_id=selection.llm_provider_integration_id,
                model=selection.model_identifier,
            ),
        )
        messages.extend(output.events)
        messages.append(
            transient_model_message(
                EventKind.USER_MESSAGE,
                UserMessagePayload(sender_user_id=None, content="Continue"),
            )
        )
        second = model.prepare(
            messages, None, system_prompt="Scoped Memory", output_tokens=None
        )
        with pytest.raises(ModelDispatchAdmissionError):
            await model.invoke(
                second,
                context=dispatch.context(
                    provider="openai",
                    integration_id=selection.llm_provider_integration_id,
                    model=selection.model_identifier,
                ),
            )
    finally:
        await model.close()
    assert len(client.requests) == 2, (
        "No stale full-request retry may reach provider I/O."
    )


async def test_pydantic_ai_official_native_wire_refuses_lost_common_owner(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    host = await _host(
        rdb_session_manager, _ScriptedModel([], close_failure=False), max_turns=5
    )
    captured: list[httpx2.Request] = []
    envelope = core_native_response(
        protocol="anthropic", model="claude-sonnet-4-5", text="Observed scoped evidence"
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
        result.transports = ProviderTransports(httpx2=httpx2.MockTransport(respond))
        return result

    selection = make_test_model_selection(
        provider=LLMProvider.ANTHROPIC,
        model_identifier="claude-sonnet-4-5",
        model_developer=LLMModelDeveloper.ANTHROPIC,
    )
    model = bind_provider_model_operation(
        selection=selection,
        settings=make_test_model_settings(),
        credential_kwargs={
            "api_key": "synthetic",
            "base_url": "https://synthetic.invalid",
        },
        effective_input_tokens=128_000,
        sdk_factories=dataclasses.replace(defaults, provider_model=factory),
        watchdog=make_test_model_stream_watchdog(),
        websocket_enabled=False,
        transport_state=None,
    )
    messages = [
        transient_model_message(
            EventKind.USER_MESSAGE,
            UserMessagePayload(sender_user_id=None, content="Current scoped input"),
        )
    ]
    prepared = model.prepare(
        messages, None, system_prompt="Private task", output_tokens=None
    )
    dispatch = ConsolidationDispatchAdmission(
        host.principal, host.execution_repository, host.context_port, _never_stop
    )
    await dispatch.admit()
    async with rdb_session_manager() as session:
        await SessionExecutionRecordRepository().claim_owner_generation(
            session, host.principal.owner.session_id
        )
    try:
        with pytest.raises(ModelDispatchAdmissionError):
            await model.invoke(
                prepared,
                context=dispatch.context(
                    provider="anthropic",
                    integration_id=selection.llm_provider_integration_id,
                    model=selection.model_identifier,
                ),
            )
    finally:
        await model.close()
    assert captured == [], (
        "Official provider transport must not see a stale owner request."
    )
