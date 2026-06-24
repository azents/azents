"""Credential loaders for Bedrock integration tests.

External credentials are stored as SecureString values in AWS SSM Parameter Store
under `/testenv/azents/*` and pulled at runtime.

SSM path convention: kebab-case
    /testenv/azents/bedrock/{access-key-id, secret-access-key, region}

This can later be replaced by another backend such as 1Password or SOPS. The
important boundary is that environment files do not store raw credentials.

Related document: ``docs/azents/design/integrations-e2e.md`` §data model
"""

import subprocess
from configparser import RawConfigParser
from dataclasses import dataclass
from pathlib import Path

DEFAULT_SSM_REGION = "us-west-2"


def _ssm_get(name: str, region: str = DEFAULT_SSM_REGION) -> str:
    """Fetch and decrypt a SecureString value from SSM Parameter Store.

    This uses the AWS CLI through subprocess rather than boto3. Failures are
    raised as ``subprocess.CalledProcessError``.
    """
    result = subprocess.run(
        [
            "aws",
            "ssm",
            "get-parameter",
            "--region",
            region,
            "--name",
            name,
            "--with-decryption",
            "--query",
            "Parameter.Value",
            "--output",
            "text",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@dataclass(frozen=True)
class BedrockCredentials:
    """IAM credentials for AWS Bedrock LLM integration tests.

    Used by ``create_bedrock_integration`` in live LLM-call QA. The access key
    belongs to an IAM user allowed to call Bedrock APIs, and the azents backend
    stores the value encrypted with ``AZ_CREDENTIAL_ENCRYPTION_KEY``.

    ``region`` is not sensitive, but it is stored in SSM as a String under the
    same prefix for consistency.
    """

    access_key_id: str
    secret_access_key: str
    region: str

    @classmethod
    def from_ssm(cls, region: str = DEFAULT_SSM_REGION) -> "BedrockCredentials":
        """Load SSM `/testenv/azents/bedrock/*` values.

        ``region`` is the AWS region used for the SSM fetch. The returned
        ``BedrockCredentials.region`` is the Bedrock call region stored in SSM.
        The two values may differ.
        """
        prefix = "/testenv/azents/bedrock"
        return cls(
            access_key_id=_ssm_get(f"{prefix}/access-key-id", region=region),
            secret_access_key=_ssm_get(f"{prefix}/secret-access-key", region=region),
            region=_ssm_get(f"{prefix}/region", region=region),
        )

    @classmethod
    def from_aws_credentials(cls, profile: str = "azents-bedrock") -> "BedrockCredentials":
        """Load Bedrock IAM credentials from the AWS shared credentials file.

        CI and agent environments may not have permission to fetch SSM directly,
        so they can provide the Bedrock key through a shared credentials profile.
        If the requested profile is missing, fall back to ``default``.
        """
        credentials_path = Path.home() / ".aws" / "credentials"
        config_path = Path.home() / ".aws" / "config"
        credentials = RawConfigParser()
        config = RawConfigParser()
        credentials.read(credentials_path)
        config.read(config_path)

        section = profile if credentials.has_section(profile) else "default"
        if not credentials.has_section(section):
            raise FileNotFoundError(
                f"AWS credentials profile not found: {profile} or default in {credentials_path}",
            )

        access_key_id = credentials.get(section, "aws_access_key_id", fallback=None)
        secret_access_key = credentials.get(section, "aws_secret_access_key", fallback=None)
        if access_key_id is None or secret_access_key is None:
            raise ValueError(f"AWS credentials profile is missing access keys: {section}")

        profile_section = f"profile {section}"
        region = (
            config.get(profile_section, "region", fallback=None)
            or config.get(section, "region", fallback=None)
            or "us-east-1"
        )
        return cls(
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            region=region,
        )
