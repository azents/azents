"""Storage admission journals cover native HTTP/WebSocket continuation retries."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal
from unittest.mock import Mock

import httpx2
import pytest
from openai import BadRequestError
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
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.agent import AgentModelSelection
from azents.core.enums import EventKind, LLMProvider
from azents.core.model_capability_contract import (
    CapabilitySupport,
    DefaultEffortEvidence,
    SupportPredicate,
)
from azents.core.model_capability_projection import project_capabilities
from azents.core.openai_client_config import OpenAIResponsesClientConfig
from azents.engine.events.model_messages import transient_model_message
from azents.engine.events.openai_responses import (
    OpenAIResponsesModelAdapter,
    OpenAIResponsesRequest,
    OpenAIResponsesWebSocketConnection,
)
from azents.engine.events.tools import ToolCatalog
from azents.engine.events.types import UserMessagePayload
from azents.engine.model_factory_types import ModelSDKFactories
from azents.engine.providers.model_factory import ProviderModelFactory
from azents.engine.run.types import FunctionTool, FunctionToolSpec
from azents.rdb.models.historical_memory_consolidation import (
    RDBConsolidationAttempt,
    RDBConsolidationModelDispatch,
)
from azents.rdb.session import SessionManager
from azents.repos.historical_memory_consolidation.budget import (
    ConsolidationBudgetRepository,
)
from azents.repos.historical_memory_consolidation.drafts import (
    ConsolidationDraftRepository,
)
from azents.repos.historical_memory_consolidation.ownership import (
    ConsolidationOwnershipRepository,
)
from azents.repos.historical_memory_consolidation.recovery import (
    ConsolidationRecoveryRepository,
)
from azents.repos.historical_memory_consolidation.sources import (
    ConsolidationSourceRepository,
)
from azents.repos.historical_memory_consolidation.work import (
    ConsolidationWorkRepository,
)
from azents.services.historical_memory.consolidation_dispatch import (
    ConsolidationDispatchAdmission,
)
from azents.services.historical_memory.consolidation_model import (
    ConsolidationModelCapabilityError,
    ConsolidationProviderModel,
    bind_consolidation_provider_model,
)
from azents.services.historical_memory.consolidation_tools import (
    ConsolidationToolBindings,
    _catalog,
)
from azents.services.historical_memory.draft_vfs import ConsolidationVfsObservations
from azents.testing.consolidation import seed_consolidation_corpus
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_model_settings,
)
from azents.testing.model_stream import make_test_model_stream_watchdog
from azents.testing.types import require_instance


def _function_catalog(selection: AgentModelSelection) -> ToolCatalog:
    """Use the real consolidation catalog producer without storage side effects."""

    async def scoped_handler(arguments: str) -> str:
        del arguments
        return "scoped result"

    return _catalog(
        [
            FunctionTool(
                spec=FunctionToolSpec(
                    name="read_scoped_source",
                    description="Read one scoped source.",
                    input_schema={
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                ),
                handler=scoped_handler,
            )
        ],
        selection,
    )


def _preparation_model(selection: AgentModelSelection) -> ConsolidationProviderModel:
    """Run actual consumer preparation; any transport call is a test failure."""
    adapter = require_instance(
        Mock(spec=OpenAIResponsesModelAdapter), OpenAIResponsesModelAdapter
    )
    return ConsolidationProviderModel(
        selection=selection,
        settings=make_test_model_settings(),
        credential_kwargs={},
        effective_input_tokens=128000,
        adapter=adapter,
        watchdog=make_test_model_stream_watchdog(),
    )


@pytest.mark.parametrize(
    ("state", "default_effort", "function_condition", "legacy_view", "allowed"),
    [
        ("unknown", None, None, False, True),
        ("supported", None, None, False, True),
        ("unsupported", None, None, True, False),
        ("conditional", None, True, False, False),
        ("conditional", "none", True, False, True),
        ("conditional", "high", True, False, False),
        ("conditional", "none", False, True, False),
    ],
)
def test_consolidation_uses_saved_function_semantics_and_actual_default_context(
    state: Literal["unknown", "supported", "unsupported", "conditional"],
    default_effort: Literal["none", "high"] | None,
    function_condition: bool | None,
    legacy_view: bool,
    allowed: bool,
) -> None:
    selection = make_test_model_selection()
    capabilities = project_capabilities(
        provider=selection.provider,
        exact_model=selection.model_identifier,
        source_model=None,
        evidence=None,
        model_developer=selection.model_developer,
    )
    assert capabilities.semantic_contract is not None
    contract = capabilities.semantic_contract
    capabilities.semantic_contract = contract.model_copy(
        update={
            "function_calling": CapabilitySupport(
                state=state,
                origin=None if state == "unknown" else "explicit",
                predicate=SupportPredicate(
                    reasoning_efforts=("none",),
                    function_tools=function_condition,
                )
                if state == "conditional"
                else None,
            ),
            "reasoning": contract.reasoning.model_copy(
                update={
                    "default_effort": (
                        DefaultEffortEvidence(level=default_effort, origin="explicit")
                        if default_effort is not None
                        else None
                    )
                }
            ),
        }
    )
    # Exercise the real consumer even when its old display view is stale.
    # The v2 descriptor, rather than that boolean, owns request authorization.
    capabilities.tool_calling.supported = legacy_view
    selection.normalized_capabilities = capabilities
    before = selection.model_dump(mode="json")
    model = _preparation_model(selection)
    catalog = _function_catalog(selection)
    assert catalog.direct_tool_names == ["read_scoped_source"]
    if not allowed:
        with pytest.raises(
            ConsolidationModelCapabilityError,
            match="Lightweight tool calling is unavailable",
        ):
            model.prepare([], catalog, system_prompt="Scoped task", output_tokens=256)
    else:
        prepared = model.prepare(
            [], catalog, system_prompt="Scoped task", output_tokens=256
        )
        assert isinstance(prepared.request, OpenAIResponsesRequest)
        assert prepared.request.tools == catalog.native_tools_for(
            catalog.direct_tool_names
        )
        assert prepared.request.tools[0]["name"] == "read_scoped_source"
        assert "reasoning" not in prepared.request.options
    assert selection.model_dump(mode="json") == before
    assert isinstance(model.adapter, Mock)
    model.adapter.stream.assert_not_called()


@pytest.mark.parametrize("supported", [False, True])
def test_consolidation_preserves_descriptor_absent_function_gate(
    supported: bool,
) -> None:
    selection = make_test_model_selection()
    assert selection.normalized_capabilities.semantic_contract is None
    selection.normalized_capabilities.tool_calling.supported = supported
    model = _preparation_model(selection)
    catalog = _function_catalog(selection)
    if not supported:
        with pytest.raises(ConsolidationModelCapabilityError):
            model.prepare([], catalog, system_prompt="Scoped task", output_tokens=256)
    else:
        prepared = model.prepare(
            [], catalog, system_prompt="Scoped task", output_tokens=256
        )
        assert isinstance(prepared.request, OpenAIResponsesRequest)
        assert prepared.request.tools[0]["name"] == "read_scoped_source"


def _completed(number: int) -> ResponseCompletedEvent:
    response = Response(
        id=f"synthetic-response-{number}",
        created_at=1.0,
        model="gpt-4o",
        object="response",
        output=[
            ResponseOutputMessage(
                id=f"synthetic-message-{number}",
                role="assistant",
                type="message",
                status="completed",
                content=[
                    ResponseOutputText(
                        type="output_text",
                        text="Completed scoped work.",
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
    )
    return ResponseCompletedEvent(
        type="response.completed", response=response, sequence_number=1
    )


@dataclass
class _Stream:
    event: ResponseStreamEvent

    async def __aiter__(self) -> AsyncIterator[ResponseStreamEvent]:
        yield self.event

    async def aclose(self) -> None:
        pass


class _JournalClient:
    def __init__(self, manager: SessionManager[AsyncSession], attempt_id: str) -> None:
        self.manager = manager
        self.attempt_id = attempt_id
        self.requests: list[dict[str, object]] = []
        self.admitted_numbers: list[int] = []
        self.pending: list[ResponseStreamEvent] = []
        self.socket_connected = False
        self.closed = False

    async def _dispatch(
        self, kwargs: dict[str, object], *, socket_cache: bool
    ) -> ResponseStreamEvent:
        async with self.manager() as session:
            attempt = await session.get(RDBConsolidationAttempt, self.attempt_id)
            assert attempt is not None
            self.admitted_numbers.append(attempt.model_requests)
        self.requests.append(kwargs)
        if not socket_cache and isinstance(kwargs.get("previous_response_id"), str):
            raise BadRequestError(
                "Synthetic expired stored response",
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
        return _Stream(await self._dispatch(kwargs, socket_cache=False))

    async def connect_websocket(self) -> OpenAIResponsesWebSocketConnection:
        self.socket_connected = True
        return _Socket(self)

    async def close(self) -> None:
        self.closed = True


@dataclass
class _Socket:
    client: _JournalClient

    async def create_response(self, **kwargs: object) -> None:
        self.client.pending.append(
            await self.client._dispatch(kwargs, socket_cache=True)
        )

    async def receive_event(self) -> ResponseStreamEvent:
        return self.client.pending.pop(0)

    async def close(self) -> None:
        pass


def _unused_provider(
    *, provider: LLMProvider, credential_kwargs: dict[str, object]
) -> ProviderModelFactory:
    raise AssertionError("Only the native Responses SDK boundary is expected.")


@pytest.mark.parametrize("websocket", [False, True])
async def test_http_retry_and_websocket_sends_are_independently_reserved(
    rdb_session_manager: SessionManager[AsyncSession],
    websocket: bool,
) -> None:
    corpus = await seed_consolidation_corpus(rdb_session_manager)
    ownership = ConsolidationOwnershipRepository(rdb_session_manager)
    claim = await ownership.claim(corpus.team)
    assert claim is not None
    await ConsolidationRecoveryRepository(rdb_session_manager).prepare(claim.principal)
    client = _JournalClient(rdb_session_manager, claim.principal.attempt_id)

    def factory(*, config: OpenAIResponsesClientConfig) -> _JournalClient:
        return client

    selection = make_test_model_selection()
    selection.normalized_capabilities.tool_calling.supported = True
    model = bind_consolidation_provider_model(
        selection=selection,
        settings=make_test_model_settings(),
        credential_kwargs={"api_key": "synthetic-unused"},
        effective_input_tokens=128000,
        sdk_factories=ModelSDKFactories(factory, _unused_provider),
        watchdog=make_test_model_stream_watchdog(),
        websocket_enabled=websocket,
    )
    assert model.max_output_tokens == 4000
    bindings = ConsolidationToolBindings(
        ConsolidationVfsObservations(claim.principal),
        ConsolidationDraftRepository(rdb_session_manager),
        ConsolidationSourceRepository(rdb_session_manager),
        ConsolidationWorkRepository(rdb_session_manager),
        ownership,
    )
    catalog = bindings.catalog(selection, writer=bindings.observations.snapshot())
    messages = [
        transient_model_message(
            EventKind.USER_MESSAGE,
            UserMessagePayload(sender_user_id=None, content="Scoped source input."),
        )
    ]
    budgets = ConsolidationBudgetRepository(rdb_session_manager)
    second: ConsolidationDispatchAdmission | None = None
    try:
        for number in range(2):
            prepared = model.prepare(
                messages,
                catalog,
                system_prompt="Independent internal Agent task",
                output_tokens=4000,
            )
            dispatch = ConsolidationDispatchAdmission(
                claim.principal, budgets, prepared.input_tokens, prepared.output_tokens
            )
            output = await model.invoke(
                prepared,
                context=dispatch.context(
                    unit_id=claim.unit_id,
                    provider=selection.provider.value,
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
                        sender_user_id=None, content="Continue scoped work."
                    ),
                )
            )
            if number == 1:
                second = dispatch
    finally:
        await model.close()
    assert client.closed and client.socket_connected == websocket
    assert second is not None
    assert isinstance(client.requests[1]["previous_response_id"], str)
    if websocket:
        assert client.admitted_numbers == [1, 2]
        assert len(second.reservations) == 1
        remaining = await budgets.remaining(claim.principal)
        assert remaining.model_requests == 30 and remaining.output_tokens == 15990
        return
    assert client.admitted_numbers == [1, 2, 3]
    assert len(second.reservations) == 2
    assert not isinstance(client.requests[2]["previous_response_id"], str)
    async with rdb_session_manager() as session:
        failed = await session.get(
            RDBConsolidationModelDispatch,
            (claim.principal.attempt_id, second.reservations[0].dispatch_id),
        )
        succeeded = await session.get(
            RDBConsolidationModelDispatch,
            (claim.principal.attempt_id, second.reservations[1].dispatch_id),
        )
        assert (
            failed is not None and failed.usage_recorded and failed.usage_json is None
        )
        assert succeeded is not None and succeeded.usage_json is not None
        assert "raw" not in succeeded.usage_json
    remaining = await budgets.remaining(claim.principal)
    assert remaining.model_requests == 29 and remaining.output_tokens == 11990
