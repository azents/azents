"""Shared lowerers, normalizers and native transports for an independent Agent host."""

import dataclasses
import datetime
import math
from collections.abc import Sequence
from typing import Protocol

from azents.core.agent import AgentModelSelection, SelectableModelSettings
from azents.core.enums import LLMProvider
from azents.core.historical_memory_budget import CONSOLIDATION_OUTPUT_TOKEN_LIMIT
from azents.core.model_pricing import capture_model_pricing
from azents.core.openai_client_config import openai_responses_client_config
from azents.engine.events.model_messages import TransientModelMessage
from azents.engine.events.model_support_contract import (
    model_support_allowed,
    resolve_model_support_context,
)
from azents.engine.events.openai_responses import (
    OpenAIResponsesLowerer,
    OpenAIResponsesModelAdapter,
    OpenAIResponsesOutputNormalizer,
    OpenAIResponsesRequest,
    openai_responses_websocket_endpoint_eligible,
)
from azents.engine.events.protocols import NormalizedAdapterOutput
from azents.engine.events.pydantic_ai_adapter import PydanticAIModelAdapter
from azents.engine.events.pydantic_ai_lowering import PydanticAILowerer
from azents.engine.events.pydantic_ai_output import PydanticAIOutputNormalizer
from azents.engine.events.pydantic_ai_types import PydanticAIRequest
from azents.engine.events.responses_continuation import ResponsesContinuationPlanner
from azents.engine.events.tools import ToolCatalog
from azents.engine.model_assembly import ModelAssemblyMetadata
from azents.engine.model_factory_types import ModelSDKFactories
from azents.engine.model_stream import (
    InternalModelStreamCallContext,
    ModelStreamWatchdog,
)
from azents.engine.run.model_transport import (
    InMemoryModelTransportState,
    ModelTransportKey,
)


class ConsolidationModelCapabilityError(ValueError):
    """The selected Lightweight candidate cannot execute the required closed tools."""


@dataclasses.dataclass(frozen=True)
class PreparedConsolidationRequest:
    """A neutral host preflight envelope, not a durable foreground event."""

    request: OpenAIResponsesRequest | PydanticAIRequest
    input_tokens: int
    output_tokens: int


class ConsolidationModelPort(Protocol):
    """Small shared-core host boundary supporting native providers and test proxies."""

    @property
    def selection(self) -> AgentModelSelection: ...
    @property
    def effective_input_tokens(self) -> int: ...
    @property
    def max_output_tokens(self) -> int: ...

    def prepare(
        self,
        messages: Sequence[TransientModelMessage],
        catalog: ToolCatalog,
        *,
        system_prompt: str,
        output_tokens: int,
    ) -> PreparedConsolidationRequest: ...

    async def invoke(
        self,
        prepared: PreparedConsolidationRequest,
        *,
        context: InternalModelStreamCallContext,
    ) -> NormalizedAdapterOutput[TransientModelMessage]: ...

    async def close(self) -> None: ...


@dataclasses.dataclass
class ConsolidationProviderModel:
    """Own one authorized candidate's SDK lifecycle and RAM continuation state."""

    selection: AgentModelSelection
    settings: SelectableModelSettings
    credential_kwargs: dict[str, object]
    effective_input_tokens: int
    adapter: OpenAIResponsesModelAdapter | PydanticAIModelAdapter
    watchdog: ModelStreamWatchdog

    @property
    def max_output_tokens(self) -> int:
        # Reserve a bounded share per turn so an unknown-usage failed dispatch
        # does not consume the entire cumulative attempt allowance. The Agent
        # can author the independently bounded document through multiple edits.
        values = [CONSOLIDATION_OUTPUT_TOKEN_LIMIT // 4]
        if self.settings.max_output_tokens is not None:
            values.append(self.settings.max_output_tokens)
        maximum = (
            self.selection.normalized_capabilities.context_window.max_output_tokens
        )
        if maximum is not None:
            values.append(maximum)
        return min(values)

    def prepare(
        self,
        messages: Sequence[TransientModelMessage],
        catalog: ToolCatalog,
        *,
        system_prompt: str,
        output_tokens: int,
    ) -> PreparedConsolidationRequest:
        selection = self.selection
        capabilities = selection.normalized_capabilities
        contract = capabilities.semantic_contract
        function_support = (
            capabilities.tool_calling.supported
            if contract is None
            else model_support_allowed(
                contract.function_calling,
                context=resolve_model_support_context(
                    capabilities,
                    requested_effort=None,
                    function_tools=True,
                ),
            )
        )
        if function_support is False:
            raise ConsolidationModelCapabilityError(
                "Lightweight tool calling is unavailable."
            )
        lowerer_type = (
            OpenAIResponsesLowerer
            if isinstance(self.adapter, OpenAIResponsesModelAdapter)
            else PydanticAILowerer
        )
        lowerer = lowerer_type(
            provider=selection.provider.value,
            provider_id=selection.provider,
            model=selection.model_identifier,
            tools=catalog.native_tools_for(catalog.direct_tool_names),
            supported_execution_options=selection.supported_execution_options,
            enabled_execution_options=(),
            top_k=None,
            max_output_tokens=output_tokens,
            model_developer=selection.model_developer,
            model_capabilities=selection.normalized_capabilities,
        )
        request = lowerer.lower(
            messages,
            model=selection.model_identifier,
            native_replay_context=None,
            system_prompt=system_prompt,
        )
        # Same conservative character preflight as source preparation, including
        # tools and instructions. Actual provider usage settles this reservation.
        estimate = math.ceil(request.native_request_input_chars() / 0.75)
        return PreparedConsolidationRequest(request, estimate, output_tokens)

    async def invoke(
        self,
        prepared: PreparedConsolidationRequest,
        *,
        context: InternalModelStreamCallContext,
    ) -> NormalizedAdapterOutput[TransientModelMessage]:
        pricing = capture_model_pricing(
            provider=self.selection.provider,
            model_identifier=self.selection.model_identifier,
            definition=self.selection.pricing,
            request_timestamp=datetime.datetime.now(datetime.UTC),
        )
        policy = self.watchdog.resolve_policy(
            provider=context.provider, model=context.model, inference_profile=None
        )
        if isinstance(prepared.request, OpenAIResponsesRequest):
            if not isinstance(self.adapter, OpenAIResponsesModelAdapter):
                raise TypeError("Internal request and transport do not match.")
            output = (
                OpenAIResponsesOutputNormalizer(
                    provider=context.provider,
                    model=context.model,
                    pricing=pricing,
                    operation="historical_memory",
                    integration=context.provider_integration_id,
                    requested_service_tier=None,
                )
                .for_native_replay(prepared.request.native_replay_schema_version())
                .start_transient()
            )
            async for event in self.adapter.stream(
                prepared.request,
                watchdog=self.watchdog,
                timeout_policy=policy,
                call_context=context,
            ):
                output.process_event(event)
            return output.complete()
        if not isinstance(self.adapter, PydanticAIModelAdapter):
            raise TypeError("Internal request and transport do not match.")
        prepared_request = dataclasses.replace(
            prepared.request,
            assembly_metadata=ModelAssemblyMetadata.from_selection(self.selection),
        )
        normalized = (
            PydanticAIOutputNormalizer(
                provider=context.provider,
                model=context.model,
                pricing=pricing,
                operation="historical_memory",
                integration=context.provider_integration_id,
            )
            .for_native_replay(prepared_request.native_replay_schema_version())
            .start_transient()
        )
        async for event in self.adapter.stream(
            prepared_request,
            watchdog=self.watchdog,
            timeout_policy=policy,
            call_context=context,
        ):
            normalized.process_event(event)
        return normalized.complete()

    async def close(self) -> None:
        await self.adapter.close()


def bind_consolidation_provider_model(
    *,
    selection: AgentModelSelection,
    settings: SelectableModelSettings,
    credential_kwargs: dict[str, object],
    effective_input_tokens: int,
    sdk_factories: ModelSDKFactories,
    watchdog: ModelStreamWatchdog,
    websocket_enabled: bool,
) -> ConsolidationProviderModel:
    if selection.provider in {LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH}:
        config = openai_responses_client_config(
            provider=selection.provider, credential_kwargs=credential_kwargs
        )
        adapter = OpenAIResponsesModelAdapter(
            client=sdk_factories.openai_responses(config=config),
            continuation_planner=ResponsesContinuationPlanner()
            if selection.provider is LLMProvider.OPENAI
            else None,
            transport_state=InMemoryModelTransportState(
                websocket_enabled=websocket_enabled
            ),
            transport_key=ModelTransportKey(
                family="openai_responses",
                provider=selection.provider.value,
                provider_integration_id=selection.llm_provider_integration_id,
            ),
            websocket_endpoint_eligible=openai_responses_websocket_endpoint_eligible(
                provider=selection.provider, config=config
            ),
        )
    else:
        adapter = PydanticAIModelAdapter(
            factory=sdk_factories.provider_model(
                provider=selection.provider, credential_kwargs=credential_kwargs
            )
        )
    return ConsolidationProviderModel(
        selection,
        settings,
        credential_kwargs,
        effective_input_tokens,
        adapter,
        watchdog,
    )
