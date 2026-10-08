"""Public model translation for the existing Bedrock structured-text contract."""

import dataclasses
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime

from pydantic_ai import RunContext
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    ModelResponseStreamEvent,
    PartEndEvent,
    PartStartEvent,
    TextPart,
    ToolCallPart,
)
from pydantic_ai.models import Model, ModelRequestParameters, StreamedResponse
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.usage import RequestUsage

from azents.engine.events.effective_model_request import (
    prepare_effective_model_parameters,
)

_OUTPUT_TOOL_NAME = "json_tool_call"


def lower_bedrock_structured_parameters(
    parameters: ModelRequestParameters,
) -> ModelRequestParameters:
    """Expose the complete tool-schema request before admission or dispatch."""
    output = parameters.output_object
    if parameters.output_mode != "native" or output is None:
        return parameters
    return dataclasses.replace(
        parameters,
        output_mode="tool",
        output_object=None,
        output_tools=[
            ToolDefinition(
                name=_OUTPUT_TOOL_NAME,
                description=output.description,
                parameters_json_schema=output.json_schema,
                kind="output",
                strict=None,
            )
        ],
        allow_text_output=False,
    )


class _StructuredTextStream(StreamedResponse):
    """Retain stock SDK assembly while exposing an output tool as JSON text."""

    def __init__(
        self, *, upstream: StreamedResponse, parameters: ModelRequestParameters
    ) -> None:
        super().__init__(model_request_parameters=parameters)
        self.upstream = upstream
        self.final_response: ModelResponse | None = None

    def __aiter__(self) -> AsyncIterator[ModelResponseStreamEvent]:
        return self._get_event_iterator()

    async def _get_event_iterator(self) -> AsyncIterator[ModelResponseStreamEvent]:
        # Native observation independently exposes every parsed provider event.
        async for _ in self.upstream:
            pass
        response = self.upstream.get()
        parts = list(response.parts)
        for index, part in enumerate(parts):
            if isinstance(part, ToolCallPart) and part.tool_name == _OUTPUT_TOOL_NAME:
                text = (
                    part.args if isinstance(part.args, str) else json.dumps(part.args)
                )
                parts[index] = TextPart(content=text)
        self.final_response = dataclasses.replace(response, parts=parts)
        for index, part in enumerate(parts):
            if isinstance(part, TextPart):
                yield PartStartEvent(index=index, part=part)
                yield PartEndEvent(index=index, part=part)

    def get(self) -> ModelResponse:
        if self.final_response is None:
            return self.upstream.get()
        return self.final_response

    @property
    def usage(self) -> RequestUsage:
        return self.upstream.usage

    @property
    def model_name(self) -> str:
        return self.upstream.model_name

    @property
    def provider_name(self) -> str | None:
        return self.upstream.provider_name

    @property
    def provider_url(self) -> str | None:
        return self.upstream.provider_url

    @property
    def timestamp(self) -> datetime:
        return self.upstream.timestamp

    async def close_stream(self) -> None:
        await self.upstream.close_stream()


class BedrockOutputCompatibilityModel(Model):
    """Preserve structured text using the SDK's supported tool-schema boundary."""

    def __init__(self, *, stock: Model) -> None:
        self.stock = stock
        super().__init__(profile=stock.profile)

    @property
    def model_name(self) -> str:
        return self.stock.model_name

    @property
    def system(self) -> str:
        return self.stock.system

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: RunContext[object] | None = None,
    ) -> ModelResponse:
        async with self.request_stream(
            messages, model_settings, model_request_parameters, run_context
        ) as stream:
            async for _ in stream:
                pass
            return stream.get()

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: RunContext[object] | None = None,
    ) -> AsyncIterator[StreamedResponse]:
        output = model_request_parameters.output_object
        if model_request_parameters.output_mode != "native" or output is None:
            async with self.stock.request_stream(
                messages, model_settings, model_request_parameters, run_context
            ) as stream:
                yield stream
            return
        # The current SDK lacks Converse outputConfig. The existing integration
        # emulates response_format using this synthetic output tool; it is not a
        # client tool and is never admitted for execution by the engine.
        parameters = prepare_effective_model_parameters(
            lower_bedrock_structured_parameters(model_request_parameters)
        )
        async with self.stock.request_stream(
            messages, model_settings, parameters, run_context
        ) as stream:
            yield _StructuredTextStream(
                upstream=stream, parameters=model_request_parameters
            )
