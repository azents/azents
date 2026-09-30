"""Single-dispatch text operations using the authorized public model boundary."""

import uuid

from openai.types.responses.response_text_config_param import ResponseTextConfigParam
from pydantic import TypeAdapter
from pydantic_ai.messages import ModelRequest, SystemPromptPart, UserPromptPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.output import OutputObjectDefinition
from pydantic_ai.settings import ModelSettings

from azents.core.enums import LLMProvider
from azents.engine.events.pydantic_ai_adapter import PydanticAIModelAdapter
from azents.engine.events.pydantic_ai_output import PydanticAIOutputNormalizer
from azents.engine.events.pydantic_ai_types import PydanticAIRequest
from azents.engine.events.types import AssistantMessagePayload, OutputTextPart
from azents.engine.model_assembly import ModelAssemblyMetadata
from azents.engine.model_factory_types import ModelSDKFactories
from azents.engine.model_stream import (
    ModelStreamCallContext,
    ModelStreamTimeoutPolicy,
    ModelStreamWatchdog,
)

_OUTPUT_OBJECT_ADAPTER = TypeAdapter(OutputObjectDefinition)


async def call_provider_text(
    *,
    sdk_factories: ModelSDKFactories,
    provider: LLMProvider,
    model: str,
    credential_kwargs: dict[str, object],
    assembly_metadata: ModelAssemblyMetadata | None,
    input_text: str,
    instructions: str,
    max_output_tokens: int | None,
    watchdog: ModelStreamWatchdog,
    timeout_policy: ModelStreamTimeoutPolicy,
    call_context: ModelStreamCallContext,
    text: ResponseTextConfigParam | None,
    extra_body: dict[str, object] | None,
) -> str:
    """Run one text operation with native terminal proof and owned cleanup."""
    settings: ModelSettings = {}
    if max_output_tokens is not None and max_output_tokens > 0:
        settings["max_tokens"] = max_output_tokens
    if extra_body is not None:
        settings["extra_body"] = extra_body
    parameters = ModelRequestParameters()
    output_format = text.get("format") if text is not None else None
    if output_format is not None and output_format["type"] == "json_schema":
        parameters = ModelRequestParameters(
            output_mode="native",
            output_object=_OUTPUT_OBJECT_ADAPTER.validate_python(
                {
                    "json_schema": output_format["schema"],
                    "name": output_format.get("name"),
                    "description": output_format.get("description"),
                    "strict": output_format.get("strict"),
                }
            ),
        )
    request = PydanticAIRequest(
        provider=provider.value,
        model=model,
        messages=[
            ModelRequest(
                parts=[SystemPromptPart(instructions), UserPromptPart(input_text)]
            )
        ],
        settings=settings,
        parameters=parameters,
        assembly_metadata=assembly_metadata,
    )
    adapter = PydanticAIModelAdapter(
        factory=sdk_factories.provider_model(
            provider=provider,
            credential_kwargs=credential_kwargs,
        )
    )
    output = PydanticAIOutputNormalizer(
        provider=provider.value,
        model=model,
        pricing=None,
        operation=call_context.call_kind,
        integration=call_context.provider_integration_id,
    ).start(call_context.session_id or uuid.uuid4().hex)
    try:
        async for event in adapter.stream(
            request,
            watchdog=watchdog,
            timeout_policy=timeout_policy,
            call_context=call_context,
        ):
            output.process_event(event)
        completed = output.complete()
        parts: list[str] = []
        for event in completed.events:
            if not isinstance(event.payload, AssistantMessagePayload):
                continue
            content = event.payload.content
            if isinstance(content, str):
                parts.append(content)
            else:
                parts.extend(
                    part.text for part in content if isinstance(part, OutputTextPart)
                )
        return "\n".join(parts)
    finally:
        await adapter.close()
