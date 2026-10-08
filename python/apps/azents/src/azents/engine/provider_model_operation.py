"""Internal model operations using the foreground request and transport contracts."""

import dataclasses
import datetime
import math
from collections.abc import Sequence

from azents.core.agent import AgentModelSelection, SelectableModelSettings
from azents.core.enums import EventKind, LLMProvider
from azents.core.model_pricing import capture_model_pricing
from azents.core.openai_client_config import openai_responses_client_config
from azents.engine.events.model_messages import (
    TransientModelMessage,
    transient_model_message,
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
from azents.engine.events.types import (
    AssistantMessagePayload,
    OutputTextPart,
    UserMessagePayload,
)
from azents.engine.model_assembly import ModelAssemblyMetadata
from azents.engine.model_factory_types import ModelSDKFactories
from azents.engine.model_stream import ModelStreamCallContext, ModelStreamWatchdog
from azents.engine.model_text import ProviderTextResult
from azents.engine.run.model_transport import (
    InMemoryModelTransportState,
    ModelTransportKey,
    ModelTransportState,
)
from azents.engine.run.resolve import effective_model_output_tokens


@dataclasses.dataclass(frozen=True)
class PreparedModelOperation:
    """Native request and content-free preflight for a purpose-owned internal host."""

    request: OpenAIResponsesRequest | PydanticAIRequest
    input_tokens: int
    output_tokens: int | None


def prepare_model_operation_request(
    *,
    selection: AgentModelSelection,
    messages: Sequence[TransientModelMessage],
    catalog: ToolCatalog | None,
    system_prompt: str,
    output_tokens: int | None,
) -> PreparedModelOperation:
    """Lower the complete operation input without acquiring a provider SDK."""
    lowerer_type = (
        OpenAIResponsesLowerer
        if selection.provider in {LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH}
        else PydanticAILowerer
    )
    lowerer = lowerer_type(
        provider=selection.provider.value,
        provider_id=selection.provider,
        model=selection.model_identifier,
        tools=catalog.native_tools_for(catalog.direct_tool_names)
        if catalog is not None
        else None,
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
    return PreparedModelOperation(
        request, math.ceil(request.native_request_input_chars() / 0.75), output_tokens
    )


@dataclasses.dataclass
class ProviderModelOperation:
    """Own one captured model's SDK lifecycle and RAM-only continuation state."""

    selection: AgentModelSelection
    settings: SelectableModelSettings
    credential_kwargs: dict[str, object]
    effective_input_tokens: int
    adapter: OpenAIResponsesModelAdapter | PydanticAIModelAdapter
    watchdog: ModelStreamWatchdog

    @property
    def max_output_tokens(self) -> int | None:
        return effective_model_output_tokens(self.selection, self.settings)

    def prepare(
        self,
        messages: Sequence[TransientModelMessage],
        catalog: ToolCatalog | None,
        *,
        system_prompt: str,
        output_tokens: int | None,
    ) -> PreparedModelOperation:
        return prepare_model_operation_request(
            selection=self.selection,
            messages=messages,
            catalog=catalog,
            system_prompt=system_prompt,
            output_tokens=output_tokens,
        )

    async def invoke(
        self,
        prepared: PreparedModelOperation,
        *,
        context: ModelStreamCallContext,
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
                    operation=context.call_kind,
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
        request = dataclasses.replace(
            prepared.request,
            assembly_metadata=ModelAssemblyMetadata.from_selection(self.selection),
        )
        normalized = (
            PydanticAIOutputNormalizer(
                provider=context.provider,
                model=context.model,
                pricing=pricing,
                operation=context.call_kind,
                integration=context.provider_integration_id,
            )
            .for_native_replay(request.native_replay_schema_version())
            .start_transient()
        )
        async for event in self.adapter.stream(
            request, watchdog=self.watchdog, timeout_policy=policy, call_context=context
        ):
            normalized.process_event(event)
        return normalized.complete()

    async def close(self) -> None:
        await self.adapter.close()


def bind_provider_model_operation(
    *,
    selection: AgentModelSelection,
    settings: SelectableModelSettings,
    credential_kwargs: dict[str, object],
    effective_input_tokens: int,
    sdk_factories: ModelSDKFactories,
    watchdog: ModelStreamWatchdog,
    websocket_enabled: bool,
    transport_state: ModelTransportState | None,
) -> ProviderModelOperation:
    adapter: OpenAIResponsesModelAdapter | PydanticAIModelAdapter
    if selection.provider in {LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH}:
        config = openai_responses_client_config(
            provider=selection.provider, credential_kwargs=credential_kwargs
        )
        adapter = OpenAIResponsesModelAdapter(
            client=sdk_factories.openai_responses(config=config),
            continuation_planner=ResponsesContinuationPlanner()
            if selection.provider is LLMProvider.OPENAI
            else None,
            transport_state=(
                transport_state
                if transport_state is not None
                else InMemoryModelTransportState(websocket_enabled=websocket_enabled)
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
    return ProviderModelOperation(
        selection,
        settings,
        credential_kwargs,
        effective_input_tokens,
        adapter,
        watchdog,
    )


async def call_model_operation_text_with_usage(
    *,
    selection: AgentModelSelection,
    settings: SelectableModelSettings,
    credential_kwargs: dict[str, object],
    effective_input_tokens: int,
    sdk_factories: ModelSDKFactories,
    watchdog: ModelStreamWatchdog,
    websocket_enabled: bool,
    instructions: str,
    input_text: str,
    call_context: ModelStreamCallContext,
    transport_state: ModelTransportState | None,
) -> ProviderTextResult:
    """Run one text task through the same request contracts as a tool-using host."""
    model = bind_provider_model_operation(
        selection=selection,
        settings=settings,
        credential_kwargs=credential_kwargs,
        effective_input_tokens=effective_input_tokens,
        sdk_factories=sdk_factories,
        watchdog=watchdog,
        websocket_enabled=websocket_enabled,
        transport_state=transport_state,
    )
    try:
        prepared = model.prepare(
            [
                transient_model_message(
                    EventKind.USER_MESSAGE,
                    UserMessagePayload(sender_user_id=None, content=input_text),
                )
            ],
            None,
            system_prompt=instructions,
            output_tokens=model.max_output_tokens,
        )
        output = await model.invoke(prepared, context=call_context)
    finally:
        await model.close()
    parts: list[str] = []
    for event in output.events:
        if isinstance(event.payload, AssistantMessagePayload):
            content = event.payload.content
            if isinstance(content, str):
                parts.append(content)
            else:
                parts.extend(
                    part.text for part in content if isinstance(part, OutputTextPart)
                )
    return ProviderTextResult(text="\n".join(parts), usage=output.usage)
