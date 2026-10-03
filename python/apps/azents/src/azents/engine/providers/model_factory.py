"""Explicit official SDK composition from an authorized integration view."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import threading
from collections.abc import Awaitable, Callable, Iterator
from typing import TYPE_CHECKING, assert_never

import anyio.to_thread
import boto3
import httpx2
from anthropic import AsyncAnthropic, AsyncAnthropicVertex
from botocore.client import BaseClient
from botocore.config import Config as AWSClientConfig
from botocore.eventstream import EventStream
from botocore.model import StructureShape
from google.auth.credentials import Credentials
from google.genai.types import HttpRetryOptions
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from httpx2 import AsyncBaseTransport as HTTPX2AsyncTransport
from openai import AsyncOpenAI
from pydantic_ai.exceptions import UserError
from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.bedrock import BedrockConverseModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.bedrock import BedrockProvider
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.google_cloud import GoogleCloudProvider
from pydantic_ai.providers.openai import OpenAIProvider

from azents.core.enums import LLMProvider
from azents.core.type_guards import is_string_object_dict, is_string_string_dict
from azents.engine.events.pydantic_ai_types import NativeModelProtocol, SDKFailureMapper
from azents.engine.providers.bedrock_output import BedrockOutputCompatibilityModel
from azents.engine.providers.http_observation import ObservedHTTPX2Transport
from azents.engine.providers.model_profiles import (
    protocol_for_provider,
    resolve_runtime_model_profile,
    vertex_model_family,
)
from azents.engine.providers.observation_state import NativeObservationState

if TYPE_CHECKING:
    from azents.engine.model_assembly import ModelAssemblyMetadata


@dataclasses.dataclass(frozen=True)
class ProviderTransports:
    """SDK composition for deterministic fixtures, never a product option."""

    httpx2: HTTPX2AsyncTransport | None = None
    bedrock_client: BaseClient | None = None
    google_credentials: Credentials | None = None
    boto_session: boto3.Session | None = None


@dataclasses.dataclass(frozen=True)
class ProviderModelBinding:
    """A public model and the resources owned by exactly one model call."""

    model: Model
    close: Callable[[], Awaitable[None]]


class _NamedResponsesProvider(OpenAIProvider):
    """Use an explicit compatible SDK without renaming integration identity."""

    def __init__(self, *, name: str, client: AsyncOpenAI) -> None:
        self.provider_name = name
        super().__init__(openai_client=client)

    @property
    def name(self) -> str:
        return self.provider_name


def _bedrock_cache_points(params: dict[str, object]) -> Iterator[dict[str, object]]:
    """Visit only modeled Converse cache blocks, never nested tool JSON."""
    blocks: list[object] = []
    system = params.get("system")
    if isinstance(system, list):
        blocks.extend(system)
    messages = params.get("messages")
    if isinstance(messages, list):
        for message in messages:
            if is_string_object_dict(message):
                content = message.get("content")
                if isinstance(content, list):
                    blocks.extend(content)
    tools = params.get("toolConfig")
    if is_string_object_dict(tools):
        definitions = tools.get("tools")
        if isinstance(definitions, list):
            blocks.extend(definitions)
    for block in blocks:
        if is_string_object_dict(block):
            point = block.get("cachePoint")
            if is_string_object_dict(point):
                yield point


def register_bedrock_cache_ttl_compatibility(client: BaseClient) -> None:
    """Preserve default cache regions with the installed type-only AWS schema."""
    shape = client.meta.service_model.shape_for("CachePointBlock")
    if not isinstance(shape, StructureShape) or set(shape.members) != {"type"}:
        return

    def before_parameter_build(*, params: dict[str, object], **_: object) -> None:
        for point in _bedrock_cache_points(params):
            if "ttl" not in point:
                continue
            if point.get("type") != "default" or point["ttl"] != "5m":
                raise UserError(
                    "The installed Bedrock SDK supports only the implicit "
                    "five-minute cache TTL."
                )
            # CachePoint() emits 5m explicitly; the pinned service schema models
            # that same default implicitly. Keep the block and its exact region.
            del point["ttl"]

    for operation in ("Converse", "ConverseStream"):
        client.meta.events.register(
            f"before-parameter-build.bedrock-runtime.{operation}",
            before_parameter_build,
        )


def _required_text(values: dict[str, object], key: str) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"The authorized integration requires {key}.")
    return value


def _optional_text(values: dict[str, object], key: str) -> str | None:
    value = values.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"The integration field {key} must be nonempty text.")
    return value


def _api_key(values: dict[str, object]) -> str:
    key = _required_text(values, "api_key")
    if not key.isascii() or "\r" in key or "\n" in key:
        raise ValueError("The integration credential cannot form a valid header.")
    return key


def _headers(values: dict[str, object]) -> dict[str, str]:
    headers = values.get("extra_headers")
    if headers is None:
        return {}
    if not is_string_string_dict(headers):
        raise ValueError("Integration headers must contain string values.")
    return dict(headers)


def _vertex_anthropic_sdk_id(model: str, *, project: str, location: str) -> str:
    """Translate only the documented resource accepted by this SDK operation."""
    prefix = f"projects/{project}/locations/{location}/publishers/anthropic/models/"
    short_prefix = "publishers/anthropic/models/"
    if model.startswith(prefix):
        identifier = model[len(prefix) :]
    elif model.startswith(short_prefix):
        identifier = model[len(short_prefix) :]
    elif "/" not in model:
        return model
    else:
        raise ValueError("The Vertex resource does not match its integration.")
    if not identifier or "/" in identifier:
        raise ValueError("The Vertex Anthropic model identifier is malformed.")
    return identifier


class _ObservedBedrockStream:
    """Observe public EventStream iteration on the SDK's worker thread."""

    def __init__(self, *, source: EventStream, state: NativeObservationState) -> None:
        self.source = source
        self.state = state

    def __iter__(self) -> Iterator[dict[str, object]]:
        for event in self.source:
            if not is_string_object_dict(event):
                raise ValueError("The Bedrock event is not an object.")
            self.state.observe_from_thread(event)
            yield event

    def close(self) -> None:
        self.source.close()


class _OwnedCredentialOperation:
    """Own credential work and its client separately from generation dispatch."""

    def __init__(self, client: BaseClient) -> None:
        self.client = client
        self.loop = asyncio.get_running_loop()
        self.thread_started = threading.Event()
        self.thread_completed = asyncio.Event()
        self.task: asyncio.Task[object] | None = None
        self.close_task: asyncio.Task[None] | None = None

    async def run[T](self, call: Callable[[], T]) -> T:
        """Shield the physical credential operation from caller cancellation."""
        if self.task is not None or self.close_task is not None:
            raise RuntimeError("The credential operation has already been used.")
        task = asyncio.create_task(self._run(call))
        self.task = task
        task.add_done_callback(_consume_credential_result)
        return await asyncio.shield(task)

    async def _run[T](self, call: Callable[[], T]) -> T:
        def physical_call() -> T:
            self.thread_started.set()
            try:
                return call()
            finally:
                self.loop.call_soon_threadsafe(self.thread_completed.set)

        try:
            return await anyio.to_thread.run_sync(physical_call)
        finally:
            if not self.thread_started.is_set():
                self.thread_completed.set()

    async def aclose(self) -> None:
        """Close only after the actual SDK worker has relinquished the client."""
        if self.close_task is None:
            self.close_task = asyncio.create_task(self._close())
        await asyncio.shield(self.close_task)

    async def _close(self) -> None:
        try:
            if self.task is not None:
                await self.thread_completed.wait()
        finally:
            await asyncio.to_thread(self.client.close)


def _consume_credential_result(task: asyncio.Task[object]) -> None:
    # The normal factory await receives the original SDK result/failure. Stop
    # can leave that await behind, so retrieve its outcome without logging raw
    # credentials or replacing the already-selected cancellation outcome.
    if not task.cancelled():
        task.exception()


class ProviderModelFactory:
    """Create official operation-scoped clients without ambient credentials."""

    def __init__(
        self,
        *,
        provider: LLMProvider,
        credential_kwargs: dict[str, object],
        sdk_failure_mapper: SDKFailureMapper,
        sdk_error_types: tuple[type[Exception], ...],
        transports: ProviderTransports | None,
    ) -> None:
        self.provider = provider
        self.credential_kwargs = credential_kwargs
        self.sdk_failure_mapper = sdk_failure_mapper
        self.sdk_error_types = sdk_error_types
        self.transports = transports

    def protocol(self, *, model: str) -> NativeModelProtocol:
        return protocol_for_provider(provider=self.provider, model=model)

    async def create(
        self,
        *,
        model: str,
        assembly_metadata: ModelAssemblyMetadata | None,
        state: NativeObservationState,
    ) -> ProviderModelBinding:
        """Bind a resolved model to public SDKs for this authorized operation."""
        # SDK debug bodies must remain below the existing operational boundary.
        for name in (
            "openai",
            "anthropic",
            "httpx",
            "httpx2",
            "httpcore",
            "botocore",
            "google.genai",
        ):
            logging.getLogger(name).setLevel(logging.WARNING)
        match self.provider:
            case LLMProvider.AWS_BEDROCK:
                return await self._bedrock(
                    model=model, assembly_metadata=assembly_metadata, state=state
                )
            case LLMProvider.GOOGLE_GEMINI | LLMProvider.GOOGLE_VERTEX_AI:
                if (
                    self.provider is LLMProvider.GOOGLE_VERTEX_AI
                    and vertex_model_family(model) == "anthropic"
                ):
                    return self._anthropic(model=model, state=state, vertex=True)
                return self._google(model=model, state=state)
            case LLMProvider.ANTHROPIC:
                return self._anthropic(model=model, state=state, vertex=False)
            case (
                LLMProvider.XAI
                | LLMProvider.XAI_OAUTH
                | LLMProvider.OPENROUTER
                | LLMProvider.KIMI_OAUTH
            ):
                return self._compatible(model=model, state=state)
            case LLMProvider.OPENAI | LLMProvider.CHATGPT_OAUTH:
                raise ValueError("Native OpenAI providers retain their own adapter.")
            case _:
                assert_never(self.provider)

    def _httpx2(self, state: NativeObservationState) -> httpx2.AsyncClient:
        delegate = (
            self.transports.httpx2
            if self.transports is not None and self.transports.httpx2 is not None
            else httpx2.AsyncHTTPTransport(retries=0)
        )
        client = httpx2.AsyncClient(
            transport=ObservedHTTPX2Transport(delegate=delegate, state=state),
            timeout=httpx2.Timeout(None),
        )
        state.close_callbacks.append(client.aclose)
        return client

    def _compatible(
        self, *, model: str, state: NativeObservationState
    ) -> ProviderModelBinding:
        values = self.credential_kwargs
        key = _api_key(values)
        endpoint = _required_text(values, "base_url")
        sdk = AsyncOpenAI(
            api_key=key,
            base_url=endpoint,
            default_headers=_headers(values),
            http_client=self._httpx2(state),
            max_retries=0,
            timeout=httpx2.Timeout(None),
        )
        state.close_callbacks.append(sdk.close)
        provider = _NamedResponsesProvider(name=self.provider.value, client=sdk)
        resolution = resolve_runtime_model_profile(
            provider=self.provider,
            model=model,
            profile_model=model,
            assembly_metadata=None,
            context_window=None,
            context_window_explicit=False,
            source_model=None,
        )
        public_model = (
            OpenAIChatModel(model, provider=provider, profile=resolution.profile)
            if self.provider is LLMProvider.KIMI_OAUTH
            else OpenAIResponsesModel(
                model,
                provider=provider,
                profile=resolution.profile,
            )
        )
        return ProviderModelBinding(model=public_model, close=sdk.close)

    def _gcp_credentials(self) -> Credentials:
        encoded = _required_text(self.credential_kwargs, "vertex_credentials")
        if (
            self.transports is not None
            and self.transports.google_credentials is not None
        ):
            return self.transports.google_credentials
        try:
            payload = json.loads(encoded)
        except json.JSONDecodeError:
            raise ValueError(
                "The integration service account is invalid JSON."
            ) from None
        if not is_string_object_dict(payload):
            raise ValueError("The integration service account must be an object.")
        return ServiceAccountCredentials.from_service_account_info(
            payload, scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )

    def _anthropic(
        self, *, model: str, state: NativeObservationState, vertex: bool
    ) -> ProviderModelBinding:
        values = self.credential_kwargs
        if vertex:
            project = _required_text(values, "vertex_project")
            location = _required_text(values, "vertex_location")
            sdk = AsyncAnthropicVertex(
                project_id=project,
                region=location,
                credentials=self._gcp_credentials(),
                http_client=self._httpx2(state),
                default_headers=_headers(values),
                max_retries=0,
                timeout=httpx2.Timeout(None),
            )
            sdk_model = _vertex_anthropic_sdk_id(
                model, project=project, location=location
            )
        else:
            sdk = AsyncAnthropic(
                api_key=_api_key(values),
                base_url=_optional_text(values, "base_url")
                or "https://api.anthropic.com",
                http_client=self._httpx2(state),
                default_headers=_headers(values),
                max_retries=0,
                timeout=httpx2.Timeout(None),
            )
            sdk_model = model
        state.close_callbacks.append(sdk.close)
        resolution = resolve_runtime_model_profile(
            provider=self.provider,
            model=model,
            profile_model=sdk_model,
            assembly_metadata=None,
            context_window=None,
            context_window_explicit=False,
            source_model=None,
        )
        public_model = AnthropicModel(
            sdk_model,
            provider=AnthropicProvider(anthropic_client=sdk),
            profile=resolution.profile,
        )
        return ProviderModelBinding(model=public_model, close=sdk.close)

    def _google(
        self, *, model: str, state: NativeObservationState
    ) -> ProviderModelBinding:
        values = self.credential_kwargs
        client = self._httpx2(state)
        retry_options = HttpRetryOptions(attempts=1)
        if self.provider is LLMProvider.GOOGLE_VERTEX_AI:
            provider = GoogleCloudProvider(
                project=_required_text(values, "vertex_project"),
                location=_required_text(values, "vertex_location"),
                credentials=self._gcp_credentials(),
                http_client=client,
                retry_options=retry_options,
            )
        else:
            provider = GoogleProvider(
                api_key=_api_key(values),
                http_client=client,
                retry_options=retry_options,
            )
        close = provider.client.aio.aclose
        state.close_callbacks.append(close)
        resolution = resolve_runtime_model_profile(
            provider=self.provider,
            model=model,
            profile_model=model,
            assembly_metadata=None,
            context_window=None,
            context_window_explicit=False,
            source_model=None,
        )
        public_model = GoogleModel(
            model,
            provider=provider,
            profile=resolution.profile,
        )
        return ProviderModelBinding(model=public_model, close=close)

    async def _bedrock(
        self,
        *,
        model: str,
        assembly_metadata: ModelAssemblyMetadata | None,
        state: NativeObservationState,
    ) -> ProviderModelBinding:
        values = self.credential_kwargs
        region = _required_text(values, "aws_region_name")
        access_key = _required_text(values, "aws_access_key_id")
        secret_key = _required_text(values, "aws_secret_access_key")
        session_token = _optional_text(values, "aws_session_token")
        if self.transports is not None and self.transports.bedrock_client is not None:
            client = self.transports.bedrock_client
        else:
            session = (
                self.transports.boto_session
                if self.transports is not None
                and self.transports.boto_session is not None
                else boto3.Session(
                    aws_access_key_id=access_key,
                    aws_secret_access_key=secret_key,
                    aws_session_token=session_token,
                    region_name=region,
                )
            )
            role = _optional_text(values, "aws_role_name")
            if role is not None:
                sts = session.client("sts")
                owned = _OwnedCredentialOperation(sts)
                state.close_callbacks.append(owned.aclose)
                try:
                    response = await owned.run(
                        lambda: sts.assume_role(
                            RoleArn=role,
                            RoleSessionName=_required_text(values, "aws_session_name"),
                        )
                    )
                finally:
                    await owned.aclose()
                credentials = response["Credentials"]
                access_key = credentials["AccessKeyId"]
                secret_key = credentials["SecretAccessKey"]
                session_token = credentials["SessionToken"]
            client = session.client(
                "bedrock-runtime",
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                aws_session_token=session_token,
                region_name=region,
                config=AWSClientConfig(
                    connect_timeout=state.timeout_policy.connect_timeout_seconds,
                    read_timeout=None,
                    retries={"total_max_attempts": 1, "mode": "standard"},
                ),
            )

        register_bedrock_cache_ttl_compatibility(client)

        def before_send(**_: object) -> None:
            state.authorize_dispatch_from_thread()
            state.worker_started()

        def after_call(*, parsed: dict[str, object], **_: object) -> None:
            try:
                state.acquired_from_thread()
                metadata = parsed.get("ResponseMetadata")
                if is_string_object_dict(metadata):
                    status = metadata.get("HTTPStatusCode")
                    if isinstance(status, int) and status >= 400:
                        state.retain_http_failure(status_code=status, body=parsed)
                stream = parsed.get("stream")
                if isinstance(stream, EventStream):
                    observed = _ObservedBedrockStream(source=stream, state=state)
                    parsed["stream"] = observed

                    async def close_stream() -> None:
                        await asyncio.to_thread(observed.close)

                    state.close_callbacks.append(close_stream)
                    if state.closing:
                        observed.close()
            finally:
                state.worker_finished()

        def after_call_error(**_: object) -> None:
            state.worker_finished()

        client.meta.events.register_first(
            "before-send.bedrock-runtime.ConverseStream", before_send
        )
        client.meta.events.register(
            "after-call.bedrock-runtime.ConverseStream", after_call
        )
        client.meta.events.register(
            "after-call-error.bedrock-runtime.ConverseStream", after_call_error
        )

        async def close() -> None:
            await asyncio.to_thread(client.close)

        state.close_callbacks.append(close)
        provider = BedrockProvider(bedrock_client=client)
        resolution = resolve_runtime_model_profile(
            provider=self.provider,
            model=model,
            profile_model=model,
            assembly_metadata=assembly_metadata,
            context_window=None,
            context_window_explicit=False,
            source_model=None,
        )
        # Preserve public SDK family dialects for tool choice, opaque replay,
        # caching and tool-result layout. These assembly defaults do not select
        # semantic tools/settings: the saved-snapshot lowerer owns that request.
        # Documented resource IDs are read only for assembly; the exact ARN is
        # still dispatched. Opaque resources use only typed saved family traits.
        stock = BedrockConverseModel(
            model,
            provider=provider,
            profile=resolution.profile,
        )
        return ProviderModelBinding(
            model=BedrockOutputCompatibilityModel(stock=stock),
            close=close,
        )
