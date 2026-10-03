"""STS credential lifetime through public Boto events and native XML parsing."""

import asyncio
import dataclasses
import logging
import threading
from collections.abc import Iterator
from typing import Literal

import boto3
import pytest
from botocore.awsrequest import AWSPreparedRequest, AWSResponse
from botocore.client import BaseClient
from botocore.compat import HTTPHeaders
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models import ModelRequestParameters

from azents.core.enums import LLMProvider
from azents.engine.events.pydantic_ai_adapter import PydanticAIModelAdapter
from azents.engine.events.pydantic_ai_adapter_test import context_for_test
from azents.engine.events.pydantic_ai_types import (
    PydanticAIRequest,
    PydanticAIStreamEvent,
)
from azents.engine.model_stream import (
    ModelStreamTimeoutPolicy,
    ModelStreamTimeoutPolicyResolver,
    ModelStreamWatchdog,
)
from azents.engine.model_stream_test import ControlledClock, ObservableCleanupRegistry
from azents.engine.provider_errors import SDK_PROVIDER_ERRORS, map_model_provider_error
from azents.engine.providers.bedrock_cache_compatibility_test import (
    ParameterValidationConfig,
)
from azents.engine.providers.bedrock_lifecycle_test import GatedAWSBody, nominal_body
from azents.engine.providers.model_factory import (
    ProviderModelFactory,
    ProviderTransports,
)
from azents.engine.run.errors import ModelStreamTimeoutError
from azents.engine.run.provider_failure import ModelProviderFailure
from azents.engine.run.types import USER_STOP_CANCEL_MESSAGE

_MODEL = "anthropic.claude-3-haiku-20240307-v1:0"
_ASSUMED_KEY = "ASIASYNTHETICROLEKEY1"
_SECRET = "synthetic-assumed-secret-canary-never-log"
_TOKEN = "synthetic-assumed-session-token-canary-never-log"
_SUCCESS_XML = f"""<AssumeRoleResponse xmlns="https://sts.amazonaws.com/doc/2011-06-15/">
<AssumeRoleResult><Credentials><AccessKeyId>{_ASSUMED_KEY}</AccessKeyId>
<SecretAccessKey>{_SECRET}</SecretAccessKey><SessionToken>{_TOKEN}</SessionToken>
<Expiration>2099-01-01T00:00:00Z</Expiration></Credentials>
<AssumedRoleUser><AssumedRoleId>synthetic-role:synthetic-session</AssumedRoleId>
<Arn>arn:aws:sts::123456789012:assumed-role/synthetic-role/synthetic-session</Arn>
</AssumedRoleUser></AssumeRoleResult><ResponseMetadata><RequestId>synthetic-sts</RequestId>
</ResponseMetadata></AssumeRoleResponse>""".encode()
_ERROR_XML = f"""<ErrorResponse xmlns="https://sts.amazonaws.com/doc/2011-06-15/">
<Error><Type>Sender</Type><Code>AccessDenied</Code>
<Message>Synthetic role access denied</Message>
<Detail>{_SECRET}</Detail></Error><RequestId>synthetic-sts</RequestId></ErrorResponse>""".encode()


class XMLBody:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def stream(
        self, amt: int | None = None, decode_content: bool = False
    ) -> Iterator[bytes]:
        yield self.body


class STSBoundary:
    """Public session/class/HTTP hooks; no SDK globals or private patches."""

    def __init__(self, *, gated: bool, failed: bool) -> None:
        self.loop = asyncio.get_running_loop()
        self.failed = failed
        self.sent = asyncio.Event()
        self.sdk_parsed = asyncio.Event()
        self.closed = asyncio.Event()
        self.close_requested = asyncio.Event()
        self.release = threading.Event()
        self.sts_calls = 0
        self.generation_calls = 0
        self.close_calls = 0
        self.validation_enabled = False
        self.assumed_key_used = False
        if not gated:
            self.release.set()
        self.body = GatedAWSBody(
            [nominal_body(_MODEL)], gate_body=False, gate_close=False
        )
        self.session = boto3.Session(
            aws_access_key_id="synthetic-source-key",
            aws_secret_access_key="synthetic-source-secret",
            region_name="us-east-1",
        )
        self.session.events.register("creating-client-class.sts", self.client_class)
        # before-send publicly accepts AWSResponse, unlike the installed stubs'
        # over-narrow Callable[..., None] signature.
        self.session.events.register(
            "before-send.sts.AssumeRole",
            self.sts_response,  # ty: ignore[invalid-argument-type]
        )
        self.session.events.register("after-call.sts.AssumeRole", self.sts_parsed)
        self.session.events.register(
            "before-send.bedrock-runtime.ConverseStream",
            self.bedrock_response,  # ty: ignore[invalid-argument-type]
        )

    def client_class(self, *, base_classes: list[type], **_: object) -> None:
        boundary = self

        class ObservedSTSClient(BaseClient):
            def close(self) -> None:
                config = self.meta.config
                assert isinstance(config, ParameterValidationConfig)
                assert config.parameter_validation
                boundary.validation_enabled = True
                boundary.close_calls += 1
                boundary.loop.call_soon_threadsafe(boundary.close_requested.set)
                super().close()
                boundary.loop.call_soon_threadsafe(boundary.closed.set)

        base_classes.insert(0, ObservedSTSClient)

    def sts_response(self, *, request: AWSPreparedRequest, **_: object) -> AWSResponse:
        self.sts_calls += 1
        self.loop.call_soon_threadsafe(self.sent.set)
        self.release.wait()
        headers = HTTPHeaders()
        headers["content-type"] = "text/xml"
        return AWSResponse(
            request.url,
            403 if self.failed else 200,
            headers,
            XMLBody(_ERROR_XML if self.failed else _SUCCESS_XML),
        )

    def sts_parsed(self, **_: object) -> None:
        self.loop.call_soon_threadsafe(self.sdk_parsed.set)

    def bedrock_response(
        self, *, request: AWSPreparedRequest, **_: object
    ) -> AWSResponse:
        self.generation_calls += 1
        authorization = request.headers.get("Authorization")
        if isinstance(authorization, bytes):
            authorization = authorization.decode()
        self.assumed_key_used = (
            isinstance(authorization, str) and _ASSUMED_KEY in authorization
        )
        headers = HTTPHeaders()
        headers["content-type"] = "application/vnd.amazon.eventstream"
        return AWSResponse(request.url, 200, headers, self.body)


@dataclasses.dataclass
class STSCall:
    boundary: STSBoundary
    adapter: PydanticAIModelAdapter
    clock: ControlledClock
    registry: ObservableCleanupRegistry
    watchdog: ModelStreamWatchdog
    policy: ModelStreamTimeoutPolicy

    async def collect(self) -> list[PydanticAIStreamEvent]:
        return [
            event
            async for event in self.adapter.stream(
                PydanticAIRequest(
                    native_replay_context=None,
                    provider="aws_bedrock",
                    model=_MODEL,
                    assembly_metadata=None,
                    messages=[ModelRequest(parts=[UserPromptPart("Synthetic input")])],
                    settings={},
                    parameters=ModelRequestParameters(),
                ),
                watchdog=self.watchdog,
                timeout_policy=self.policy,
                call_context=dataclasses.replace(
                    context_for_test(), provider="aws_bedrock", model=_MODEL
                ),
            )
        ]


def sts_call(*, gated: bool, failed: bool, absolute: bool) -> STSCall:
    boundary = STSBoundary(gated=gated, failed=failed)
    clock = ControlledClock()
    policy = ModelStreamTimeoutPolicy(
        connect_timeout_seconds=10 if absolute else 2,
        parsed_event_idle_timeout_seconds=5,
        absolute_attempt_timeout_seconds=1 if absolute else 30,
    )
    registry = ObservableCleanupRegistry(clock=clock)
    watchdog = ModelStreamWatchdog(
        resolver=ModelStreamTimeoutPolicyResolver(
            default=policy, provider_overrides=(), specific_overrides=()
        ),
        cleanup_registry=registry,
        close_grace_seconds=1,
        clock=clock,
    )
    factory = ProviderModelFactory(
        provider=LLMProvider.AWS_BEDROCK,
        credential_kwargs={
            "aws_access_key_id": "synthetic-source-key",
            "aws_secret_access_key": "synthetic-source-secret",
            "aws_region_name": "us-east-1",
            "aws_role_name": "arn:aws:iam::123456789012:role/synthetic-role",
            "aws_session_name": "synthetic-session",
        },
        sdk_failure_mapper=map_model_provider_error,
        sdk_error_types=SDK_PROVIDER_ERRORS,
        transports=ProviderTransports(boto_session=boundary.session),
    )
    return STSCall(
        boundary,
        PydanticAIModelAdapter(factory=factory),
        clock,
        registry,
        watchdog,
        policy,
    )


async def test_actual_sts_xml_success_closes_client_and_uses_assumed_credentials(
    caplog: pytest.LogCaptureFixture,
) -> None:
    call = sts_call(gated=False, failed=False, absolute=False)
    with caplog.at_level(logging.WARNING):
        events = await call.collect()
    await call.boundary.closed.wait()
    assert call.boundary.sts_calls == 1
    assert call.boundary.generation_calls == 1
    assert call.boundary.assumed_key_used
    assert call.boundary.close_calls == 1
    assert any(
        event.observation is not None and event.observation.terminal == "success"
        for event in events
    )
    assert _SECRET not in caplog.text and _TOKEN not in caplog.text


async def test_actual_sts_xml_failure_closes_client_without_generation_or_secret_leak(
    caplog: pytest.LogCaptureFixture,
) -> None:
    call = sts_call(gated=False, failed=True, absolute=False)
    with (
        caplog.at_level(logging.WARNING),
        pytest.raises(ModelProviderFailure) as raised,
    ):
        await call.collect()
    await call.boundary.closed.wait()
    assert call.boundary.close_calls == 1
    assert call.boundary.generation_calls == 0
    assert raised.value.status_code == 403
    assert raised.value.provider_code == "AccessDenied"
    assert raised.value.provider_message == "Synthetic role access denied"
    assert _SECRET not in str(raised.value) and _TOKEN not in str(raised.value)
    assert _SECRET not in caplog.text and _TOKEN not in caplog.text


@pytest.mark.parametrize("outcome", ["stop", "connect", "absolute"])
@pytest.mark.parametrize("failed", [False, True])
async def test_noncooperative_sts_worker_remains_owned_until_sdk_and_client_settle(
    outcome: Literal["stop", "connect", "absolute"],
    failed: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    call = sts_call(gated=True, failed=failed, absolute=outcome == "absolute")
    operation = asyncio.create_task(call.collect())
    try:
        await call.boundary.sent.wait()
        if outcome == "stop":
            operation.cancel(USER_STOP_CANCEL_MESSAGE)
            with pytest.raises(asyncio.CancelledError):
                await operation
            assert call.clock.time() == 0
        else:
            deadline = 1 if outcome == "absolute" else 2
            await call.clock.wait_until(
                lambda: deadline in call.clock.sleeper_deadlines
            )
            call.clock.advance(deadline)
            for _ in range(2):
                await call.clock.wait_until(
                    lambda: call.clock.time() + 1 in call.clock.sleeper_deadlines
                )
                call.clock.advance(1)
            with pytest.raises(ModelStreamTimeoutError) as raised:
                await operation
            assert raised.value.failure_code == (
                "model_attempt_timeout"
                if outcome == "absolute"
                else "model_connect_timeout"
            )
        assert call.registry.active_count > 0
        assert not call.boundary.close_requested.is_set()
        assert not call.boundary.closed.is_set()
        assert call.boundary.generation_calls == 0
        call.boundary.release.set()
        await call.boundary.sdk_parsed.wait()
        await call.boundary.closed.wait()
        await call.registry.settled.wait()
        assert call.registry.active_count == 0
        assert call.boundary.close_calls == 1
        assert call.boundary.generation_calls == 0
        assert _SECRET not in caplog.text and _TOKEN not in caplog.text
    finally:
        call.boundary.release.set()
