"""Prepare explicit AWS role sessions before the final inference admission."""

import asyncio
from dataclasses import dataclass
from typing import Annotated

from aioboto3 import Session
from aiobotocore.config import AioConfig
from azents_llm_contract.authority import BedrockCredential
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import Depends
from pydantic import SecretStr

from azents.core.credentials import AwsConfig, AwsSecrets


class BedrockSessionUnavailable(Exception):
    """Role preparation failed without exposing provider credential diagnostics."""


def sts_session() -> Session:
    return Session()


@dataclass
class BedrockSessionPreparer:
    session: Annotated[Session, Depends(sts_session)]

    async def prepare(
        self, *, config: AwsConfig, secret: AwsSecrets, session_name: str
    ) -> BedrockCredential:
        if (
            not config.role_arn
            or not config.access_key_id
            or not secret.secret_access_key
        ):
            raise BedrockSessionUnavailable("Explicit role credentials are required.")
        try:
            async with self.session.client(
                "sts",
                region_name=config.region,
                aws_access_key_id=config.access_key_id,
                aws_secret_access_key=secret.secret_access_key,
                config=AioConfig(
                    retries={"total_max_attempts": 1},
                    connect_timeout=10,
                    read_timeout=10,
                    proxies={},
                    ignore_configured_endpoint_urls=True,
                ),
            ) as client:
                result = await client.assume_role(
                    RoleArn=config.role_arn,
                    RoleSessionName=session_name,
                    DurationSeconds=900,
                )
        except asyncio.CancelledError:
            raise
        except BotoCoreError, ClientError:
            raise BedrockSessionUnavailable(
                "Provider role session preparation failed."
            ) from None
        credentials = result["Credentials"]
        return BedrockCredential(
            kind="aws_bedrock",
            access_key_id=SecretStr(credentials["AccessKeyId"]),
            secret_access_key=SecretStr(credentials["SecretAccessKey"]),
            session_token=SecretStr(credentials["SessionToken"]),
            expires_at=credentials["Expiration"],
            region=config.region,
        )
