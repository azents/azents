"""AWS role preparation uses explicit source identity and bounded SDK lifetime."""

import asyncio
import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from unittest.mock import AsyncMock, Mock

import pytest
from aioboto3 import Session
from aiobotocore.stub import AioStubber
from azcommon.result import Success
from azents_llm_contract.authority import BedrockCredential
from pydantic import SecretStr
from types_aiobotocore_sts.client import STSClient

from azents.core.credentials import AwsConfig, AwsSecrets
from azents.core.enums import LLMProvider
from azents.repos.llm_authority import LLMAuthorityRepository, PreparedLLMAuthority
from azents.services.engine_runtime_tokens import EngineRuntimeTokenResolver
from azents.services.llm_authority import LLMAuthorityService, LLMCredentialUnavailable
from azents.services.llm_authority_test import integration, prepared
from azents.services.llm_bedrock_sessions import (
    BedrockSessionPreparer,
    BedrockSessionUnavailable,
)

ROLE = "arn:aws:iam::123456789012:role/fixture"


def config() -> AwsConfig:
    return AwsConfig(access_key_id="AKIA" + "S" * 16, region="us-east-1", role_arn=ROLE)


def session_credential(expiry: datetime.datetime) -> BedrockCredential:
    return BedrockCredential(
        kind="aws_bedrock",
        access_key_id=SecretStr("ASIA" + "A" * 16),
        secret_access_key=SecretStr("session-secret-sentinel"),
        session_token=SecretStr("session-token-sentinel"),
        region="us-east-1",
        expires_at=expiry,
    )


@pytest.mark.parametrize("failure", [False, True])
async def test_sts_sdk_uses_explicit_source_and_redacts_error(
    monkeypatch: pytest.MonkeyPatch,
    failure: bool,
) -> None:
    session = Session()
    value = config()
    secret = AwsSecrets(secret_access_key="S" * 40)
    original = session.client
    observed = []
    async with original(
        "sts",
        region_name=value.region,
        aws_access_key_id=value.access_key_id,
        aws_secret_access_key=secret.secret_access_key,
    ) as client:
        stub = AioStubber(client)
        parameters = {
            "RoleArn": ROLE,
            "RoleSessionName": "azents-fixture",
            "DurationSeconds": 900,
        }
        expiry = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=15)
        if failure:
            stub.add_client_error(
                "assume_role",
                service_error_code="AccessDenied",
                service_message="provider-private-sentinel",
                expected_params=parameters,
            )
        else:
            stub.add_response(
                "assume_role",
                {
                    "Credentials": {
                        "AccessKeyId": "ASIA" + "A" * 16,
                        "SecretAccessKey": "A" * 40,
                        "SessionToken": "session-token-sentinel",
                        "Expiration": expiry,
                    },
                    "AssumedRoleUser": {
                        "AssumedRoleId": "AROAEXAMPLE:fixture",
                        "Arn": (
                            "arn:aws:sts::123456789012:assumed-role/fixture/azents-fixture"
                        ),
                    },
                },
                parameters,
            )

        @asynccontextmanager
        async def controlled(
            *args: object, **kwargs: object
        ) -> AsyncIterator[STSClient]:
            observed.append((args, kwargs))
            yield client

        monkeypatch.setattr(session, "client", controlled)
        with stub:
            subject = BedrockSessionPreparer(session)
            if failure:
                with pytest.raises(BedrockSessionUnavailable) as caught:
                    await subject.prepare(
                        config=value, secret=secret, session_name="azents-fixture"
                    )
                assert "provider-private-sentinel" not in str(caught.value)
                assert caught.value.__suppress_context__
            else:
                result = await subject.prepare(
                    config=value, secret=secret, session_name="azents-fixture"
                )
                assert result.session_token == SecretStr("session-token-sentinel")
                assert result.expires_at == expiry
                assert "session-token-sentinel" not in result.model_dump_json()
                assert "role_arn" not in result.protected_json()
            stub.assert_no_pending_responses()
    assert len(observed) == 1
    _, options = observed[0]
    assert options["aws_access_key_id"] == value.access_key_id
    assert options["aws_secret_access_key"] == secret.secret_access_key
    assert options["region_name"] == value.region


@pytest.mark.parametrize("expired", [False, True])
async def test_role_preparation_precedes_final_revalidation_and_expiry_check(
    expired: bool,
) -> None:
    value = replace(prepared(), integration=integration(LLMProvider.AWS_BEDROCK))
    value.integration.config = config()
    repository = AsyncMock(spec=LLMAuthorityRepository)
    repository.prepare.return_value = value
    tokens = AsyncMock(spec=EngineRuntimeTokenResolver)
    tokens.ensure.return_value = Success(value.integration)
    bedrock = AsyncMock(spec=BedrockSessionPreparer)
    expiry = datetime.datetime.now(datetime.UTC) + datetime.timedelta(
        minutes=-1 if expired else 15
    )
    credential = session_credential(expiry)
    bedrock.prepare.return_value = credential

    async def finalize(**kwargs: object) -> PreparedLLMAuthority:
        bedrock.prepare.assert_awaited_once()
        assert kwargs["refreshed"] is value.integration
        return value

    repository.finalize.side_effect = finalize
    subject = LLMAuthorityService(repository, tokens, bedrock)
    if expired:
        with pytest.raises(LLMCredentialUnavailable, match="expired"):
            await subject.resolve(
                agent_token="fixture", model="model", target_id="a" * 64
            )
    else:
        result = await subject.resolve(
            agent_token="fixture", model="model", target_id="a" * 64
        )
        assert result.credential == credential
    repository.finalize.assert_awaited_once()


async def test_sts_failure_never_reaches_final_admission() -> None:
    value = replace(prepared(), integration=integration(LLMProvider.AWS_BEDROCK))
    value.integration.config = config()
    repository = AsyncMock(spec=LLMAuthorityRepository)
    repository.prepare.return_value = value
    tokens = AsyncMock(spec=EngineRuntimeTokenResolver)
    tokens.ensure.return_value = Success(value.integration)
    bedrock = AsyncMock(spec=BedrockSessionPreparer)
    bedrock.prepare.side_effect = BedrockSessionUnavailable("Role session unavailable.")
    with pytest.raises(BedrockSessionUnavailable):
        await LLMAuthorityService(repository, tokens, bedrock).resolve(
            agent_token="fixture",
            model="model",
            target_id="a" * 64,
        )
    repository.finalize.assert_not_called()


async def test_cancelled_sts_preparation_closes_owned_sdk_context() -> None:
    entered, never = asyncio.Event(), asyncio.Event()
    session = Mock(spec=Session)
    manager = AsyncMock()
    client = AsyncMock(spec=STSClient)
    manager.__aenter__.return_value = client
    manager.__aexit__.return_value = False
    session.client.return_value = manager

    async def wait_for_cancel(**kwargs: object) -> None:
        entered.set()
        await never.wait()

    client.assume_role.side_effect = wait_for_cancel
    task = asyncio.create_task(
        BedrockSessionPreparer(session).prepare(
            config=config(),
            secret=AwsSecrets(secret_access_key="S" * 40),
            session_name="azents-fixture",
        )
    )
    async with asyncio.timeout(5):
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    manager.__aexit__.assert_awaited_once()
