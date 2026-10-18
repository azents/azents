"""Purpose-owned canonical-context Routine judgment without ordinary Run effects."""

import dataclasses
from collections.abc import Sequence

from pydantic import ValidationError
from pydantic_ai.output import OutputObjectDefinition

from azents.core.enums import EventKind, LLMProvider
from azents.core.model_execution_options import ModelExecutionOptionId
from azents.core.model_pricing import CapturedModelPricing
from azents.core.openai_client_config import openai_responses_client_config
from azents.core.routine_judgment import (
    RoutineJudgmentCandidate,
    RoutineJudgmentConsidered,
    RoutineJudgmentDecision,
    render_judgment_input,
)
from azents.engine.events.file_parts import ModelFileResolver
from azents.engine.events.model_messages import (
    ModelTranscriptMessage,
    TransientModelMessage,
    transient_model_message,
)
from azents.engine.events.openai_responses import (
    OpenAIResponsesLowerer,
    OpenAIResponsesModelAdapter,
    OpenAIResponsesOutputNormalizer,
    OpenAIResponsesRequest,
)
from azents.engine.events.protocols import NormalizedAdapterOutput
from azents.engine.events.pydantic_ai_adapter import PydanticAIModelAdapter
from azents.engine.events.pydantic_ai_lowering import PydanticAILowerer
from azents.engine.events.pydantic_ai_output import PydanticAIOutputNormalizer
from azents.engine.events.pydantic_ai_types import PydanticAIRequest
from azents.engine.events.types import (
    AssistantMessagePayload,
    ClientToolCallPayload,
    OutputTextPart,
    ProviderToolCallPayload,
    RoutineJudgmentPayload,
    UserMessagePayload,
)
from azents.engine.model_assembly import ModelAssemblyMetadata
from azents.engine.model_factory_types import ModelSDKFactories
from azents.engine.model_stream import (
    ModelStreamCallContext,
    ModelStreamTimeoutPolicy,
    ModelStreamWatchdog,
)
from azents.engine.run.client_tool_compatibility import (
    ClientToolRoute,
    resolve_client_tool_adapter_profile,
)


@dataclasses.dataclass(frozen=True)
class RoutineJudgmentModel:
    """Already resolved ordinary Session selection, not another model setting."""

    provider: LLMProvider
    model: str
    assembly: ModelAssemblyMetadata
    temperature: float | None
    max_output_tokens: int | None
    top_p: float | None
    top_k: int | None
    stop: list[str] | None
    reasoning_effort: str | None
    supported_execution_options: tuple[ModelExecutionOptionId, ...]
    enabled_execution_options: tuple[ModelExecutionOptionId, ...]


RoutineJudgmentRequest = OpenAIResponsesRequest | PydanticAIRequest


def prepare_routine_judgment_request(
    *,
    selection: RoutineJudgmentModel,
    transcript: Sequence[ModelTranscriptMessage],
    system_prompt: str,
    candidates: tuple[RoutineJudgmentCandidate, ...],
    session_id: str,
    native_replay_context: str | None,
    model_file_resolver: ModelFileResolver | None,
) -> RoutineJudgmentRequest:
    """Append the judgment request to canonical history without flattening it."""
    final_input = transient_model_message(
        EventKind.USER_MESSAGE,
        UserMessagePayload(
            sender_user_id=None,
            content=render_judgment_input(candidates),
        ),
    )
    messages = [*transcript, final_input]
    output = OutputObjectDefinition(
        json_schema=RoutineJudgmentDecision.model_json_schema(),
        name="routine_judgment",
        description="One action decision for every supplied Routine candidate.",
        strict=True,
    )
    if selection.provider in {LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH}:
        history_profile = resolve_client_tool_adapter_profile(
            route=ClientToolRoute(
                provider=selection.provider,
                adapter=OpenAIResponsesLowerer.adapter,
                native_format=OpenAIResponsesLowerer.native_format,
            )
        )
        lowerer = OpenAIResponsesLowerer(
            provider=selection.provider.value,
            provider_id=selection.provider,
            model=selection.model,
            tools=None,
            hosted_tools=None,
            model_capabilities=selection.assembly.capabilities,
            model_developer=selection.assembly.model_developer,
            temperature=selection.temperature,
            max_output_tokens=selection.max_output_tokens,
            top_p=selection.top_p,
            top_k=selection.top_k,
            stop=selection.stop,
            reasoning_effort=selection.reasoning_effort,
            supported_execution_options=selection.supported_execution_options,
            enabled_execution_options=selection.enabled_execution_options,
            prompt_cache_scope=session_id,
            model_file_resolver=model_file_resolver,
            historical_plaintext_custom_supported=(
                history_profile is not None
                and history_profile.supports_wire_dialect("plaintext_custom")
            ),
        )
        return lowerer.lower_structured(
            messages,
            model=selection.model,
            native_replay_context=native_replay_context,
            system_prompt=system_prompt,
            output=output,
        )
    pydantic_lowerer = PydanticAILowerer(
        provider=selection.provider.value,
        provider_id=selection.provider,
        model=selection.model,
        tools=None,
        hosted_tools=None,
        model_capabilities=selection.assembly.capabilities,
        model_developer=selection.assembly.model_developer,
        temperature=selection.temperature,
        max_output_tokens=selection.max_output_tokens,
        top_p=selection.top_p,
        top_k=selection.top_k,
        stop=selection.stop,
        reasoning_effort=selection.reasoning_effort,
        supported_execution_options=selection.supported_execution_options,
        enabled_execution_options=selection.enabled_execution_options,
        prompt_cache_scope=session_id,
        model_file_resolver=model_file_resolver,
    )
    request = pydantic_lowerer.lower_structured(
        messages,
        model=selection.model,
        native_replay_context=native_replay_context,
        system_prompt=system_prompt,
        output=output,
    )
    return dataclasses.replace(request, assembly_metadata=selection.assembly)


async def call_routine_judgment(
    *,
    judgment_id: str,
    candidates: tuple[RoutineJudgmentCandidate, ...],
    selection: RoutineJudgmentModel,
    request: RoutineJudgmentRequest,
    sdk_factories: ModelSDKFactories,
    credential_kwargs: dict[str, object],
    pricing: CapturedModelPricing | None,
    watchdog: ModelStreamWatchdog,
    timeout_policy: ModelStreamTimeoutPolicy,
    call_context: ModelStreamCallContext,
) -> RoutineJudgmentPayload:
    """Dispatch once; normalize to RAM-only output and retain call-specific usage.

    Provider, capability, cancellation and transport failures propagate to the
    judgment owner for its normal failed/cancelled observation. Invalid completed
    Structured output returns a failed observation with any observed usage. No
    ordinary Run/turn marker, event append or provider retry is performed here.
    """
    if (
        call_context.call_kind != "routine_judgment"
        or call_context.run_id is not None
        or call_context.session_id is None
        or call_context.provider != selection.provider.value
        or call_context.model != selection.model
        or request.model != selection.model
    ):
        raise ValueError(
            "Routine judgment requires its own Session model-call identity."
        )
    # Validate the candidate set before spending any provider call.
    render_judgment_input(candidates)
    completed: NormalizedAdapterOutput[TransientModelMessage]
    if isinstance(request, OpenAIResponsesRequest):
        if selection.provider not in {LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH}:
            raise ValueError("Routine judgment request does not match its provider.")
        client = sdk_factories.openai_responses(
            config=openai_responses_client_config(
                provider=selection.provider,
                credential_kwargs=credential_kwargs,
                session_id=call_context.session_id,
            )
        )
        adapter = OpenAIResponsesModelAdapter(
            client=client,
            continuation_planner=None,
            transport_state=None,
            transport_key=None,
            websocket_endpoint_eligible=False,
        )
        output = (
            OpenAIResponsesOutputNormalizer(
                provider=selection.provider.value,
                model=selection.model,
                pricing=pricing,
                operation="routine_judgment",
                integration=call_context.provider_integration_id,
                requested_service_tier=request.options.get("service_tier"),
            )
            .for_native_replay(request.native_replay_schema_version())
            .start_transient()
        )
        try:
            async for event in adapter.stream(
                request,
                watchdog=watchdog,
                timeout_policy=timeout_policy,
                call_context=call_context,
            ):
                output.process_event(event)
            completed = output.complete()
        finally:
            await adapter.close()
    else:
        if request.provider != selection.provider.value:
            raise ValueError("Routine judgment request does not match its provider.")
        factory = sdk_factories.provider_model(
            provider=selection.provider, credential_kwargs=credential_kwargs
        )
        pydantic_adapter = PydanticAIModelAdapter(factory=factory)
        pydantic_output = (
            PydanticAIOutputNormalizer(
                provider=selection.provider.value,
                model=selection.model,
                pricing=pricing,
                operation="routine_judgment",
                integration=call_context.provider_integration_id,
            )
            .for_native_replay(request.native_replay_schema_version())
            .start_transient()
        )
        try:
            async for pydantic_event in pydantic_adapter.stream(
                request,
                watchdog=watchdog,
                timeout_policy=timeout_policy,
                call_context=call_context,
            ):
                pydantic_output.process_event(pydantic_event)
            completed = pydantic_output.complete()
        finally:
            await pydantic_adapter.close()
    considered = tuple(
        RoutineJudgmentConsidered(
            routine_id=candidate.routine_id,
            slug=candidate.slug,
            title=candidate.content.title,
        )
        for candidate in candidates
    )
    text: list[str] = []
    invalid_tool = completed.needs_follow_up or bool(completed.pending_provider_files)
    for message in completed.events:
        payload = message.payload
        if isinstance(payload, ClientToolCallPayload | ProviderToolCallPayload):
            invalid_tool = True
        elif isinstance(payload, AssistantMessagePayload):
            if isinstance(payload.content, str):
                text.append(payload.content)
            else:
                text.extend(
                    part.text
                    for part in payload.content
                    if isinstance(part, OutputTextPart)
                )
    decision: RoutineJudgmentDecision | None = None
    if not invalid_tool:
        try:
            decision = RoutineJudgmentDecision.model_validate_json("\n".join(text))
            decision.validate_candidates(candidates)
        except ValidationError, ValueError:
            decision = None
    return RoutineJudgmentPayload(
        judgment_id=judgment_id,
        considered=considered,
        status="completed" if decision is not None else "failed",
        decision=decision,
        error=(
            None
            if decision is not None
            else "The model returned invalid Routine judgment output."
        ),
        usage=completed.usage,
    )
