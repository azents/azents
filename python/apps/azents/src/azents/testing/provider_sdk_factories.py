"""Same-process public SDK fixture composition for core provider E2E.

Only explicitly synthetic fixture credentials select these native transports.
Ordinary E2E credentials retain the standard constructors and existing proxies.
"""

from collections.abc import AsyncIterator

import httpx2
from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field

from azents.core.enums import LLMProvider
from azents.core.openai_client_config import OpenAIResponsesClientConfig
from azents.engine.events.openai_responses import (
    OpenAIResponsesClient,
    OpenAISDKResponsesClient,
    create_openai_responses_client,
)
from azents.engine.model_factories import build_provider_model_factory
from azents.engine.model_factory_types import ModelSDKFactories
from azents.engine.provider_errors import SDK_PROVIDER_ERRORS, map_model_provider_error
from azents.engine.providers.model_factory import (
    ProviderModelFactory,
    ProviderTransports,
)
from azents.testing.provider_native_envelopes import (
    NativeFixtureProtocol,
    NativeFixtureResponse,
    core_google_image_response,
    core_native_response,
)

FIXTURE_CREDENTIAL_PREFIX = "e2e-provider-cutover-"
_CORE_TEXT = '{"title":"Provider cutover core"}'


class _GoogleGenerationConfig(BaseModel):
    """Decode only the documented image output request, without retaining input."""

    model_config = ConfigDict(extra="ignore")
    response_modalities: list[str] | None = Field(
        default=None, alias="responseModalities"
    )


class _InferenceIdentity(BaseModel):
    """Decode the model identity without retaining prompt or credential bodies."""

    model_config = ConfigDict(extra="ignore")
    model: str | None = None
    generation_config: _GoogleGenerationConfig | None = Field(
        default=None, alias="generationConfig"
    )


class _HTTPX2FixtureStream(httpx2.AsyncByteStream):
    """Expose bytes for the SDK's single live transport consumption."""

    def __init__(self, body: bytes) -> None:
        self.body = body

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield self.body


def fixture_model_sdk_factories() -> ModelSDKFactories:
    """Provide the same official constructors with scoped native fixture I/O."""
    return ModelSDKFactories(
        openai_responses=_openai_client,
        provider_model=_provider_factory,
    )


def _openai_client(*, config: OpenAIResponsesClientConfig) -> OpenAIResponsesClient:
    key = config.api_key
    if key is None or not key.startswith(FIXTURE_CREDENTIAL_PREFIX):
        return create_openai_responses_client(config=config)
    sdk_client = AsyncOpenAI(
        api_key=key,
        base_url=config.base_url,
        websocket_base_url="ws://openai-proxy:8081/provider-core/chatgpt",
        organization=config.organization,
        project=config.project,
        default_headers=config.default_headers,
        max_retries=0,
        http_client=httpx2.AsyncClient(
            transport=httpx2.MockTransport(_httpx2_response)
        ),
    )
    return OpenAISDKResponsesClient(
        sdk_client,
        websocket_headers=config.default_headers,
    )


def _provider_factory(
    *, provider: LLMProvider, credential_kwargs: dict[str, object]
) -> ProviderModelFactory:
    if not _fixture_credentials(credential_kwargs):
        return build_provider_model_factory(
            provider=provider, credential_kwargs=credential_kwargs
        )
    return ProviderModelFactory(
        provider=provider,
        credential_kwargs=credential_kwargs,
        sdk_failure_mapper=map_model_provider_error,
        sdk_error_types=SDK_PROVIDER_ERRORS,
        transports=ProviderTransports(
            httpx2=httpx2.MockTransport(_httpx2_response),
        ),
    )


def _fixture_credentials(credentials: dict[str, object]) -> bool:
    for name in ("api_key", "aws_access_key_id"):
        value = credentials.get(name)
        if isinstance(value, str) and value.startswith(FIXTURE_CREDENTIAL_PREFIX):
            return True
    service_account = credentials.get("vertex_credentials")
    return (
        isinstance(service_account, str) and "provider-cutover-core@" in service_account
    )


def _native_envelope(*, path: str, body: bytes) -> NativeFixtureResponse:
    if path.endswith("/responses"):
        protocol: NativeFixtureProtocol = "responses"
    elif path.endswith("/messages") or "publishers/anthropic/" in path:
        protocol = "anthropic"
    elif path.endswith("/chat/completions"):
        protocol = "chat_completions"
    elif "streamGenerateContent" in path:
        protocol = "google"
    else:
        raise AssertionError(f"Unexpected native fixture inference path: {path}")
    identity = _InferenceIdentity.model_validate_json(body)
    model = identity.model
    if model is None:
        model = path.rsplit("/", 1)[-1].partition(":")[0]
    if protocol == "google" and (
        model == "gemini-3.1-flash-image-preview"
        or (
            identity.generation_config is not None
            and identity.generation_config.response_modalities is not None
            and "IMAGE" in identity.generation_config.response_modalities
        )
    ):
        return core_google_image_response(model=model, text=_CORE_TEXT)
    return core_native_response(protocol=protocol, model=model, text=_CORE_TEXT)


def _httpx2_response(request: httpx2.Request) -> httpx2.Response:
    if request.method != "POST":
        raise AssertionError("Native inference fixture expects POST")
    envelope = _native_envelope(path=request.url.path, body=request.content)
    return httpx2.Response(
        200,
        headers={"content-type": envelope.content_type},
        stream=_HTTPX2FixtureStream(envelope.body),
        request=request,
    )
