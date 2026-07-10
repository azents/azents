"""Credential type definitions by LLM provider.

Separates Secrets, stored encrypted, from Config, stored as plaintext JSONB.
"""

import datetime
import re
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

from azents.core.enums import LLMProvider

# ---------------------------------------------------------------------------
# Secrets, stored encrypted
# ---------------------------------------------------------------------------


class ApiKeySecrets(BaseModel):
    """API key based secrets for OpenAI, Anthropic, and Google Gemini."""

    type: Literal["api_key"] = "api_key"
    api_key: str = Field(description="API key")


class AwsSecrets(BaseModel):
    """AWS IAM based secrets for AWS Bedrock."""

    type: Literal["aws_credentials"] = "aws_credentials"
    secret_access_key: str = Field(description="AWS Secret Access Key")


class GcpSecrets(BaseModel):
    """GCP service account based secrets for Google Vertex AI."""

    type: Literal["gcp_service_account"] = "gcp_service_account"
    service_account_json: str = Field(description="Service account JSON")


class ChatGPTOAuthSecrets(BaseModel):
    """ChatGPT OAuth token secrets."""

    type: Literal["chatgpt_oauth"] = "chatgpt_oauth"
    access_token: str = Field(description="ChatGPT access token")
    refresh_token: str = Field(description="ChatGPT refresh token")
    id_token: str | None = Field(default=None, description="ChatGPT ID token")
    expires_at: datetime.datetime = Field(description="Access token expiration time")


class XaiOAuthSecrets(BaseModel):
    """xAI OAuth token secrets."""

    type: Literal["xai_oauth"] = "xai_oauth"
    access_token: str = Field(description="xAI access token")
    refresh_token: str = Field(description="xAI refresh token")
    id_token: str | None = Field(default=None, description="xAI ID token")
    expires_at: datetime.datetime = Field(description="Access token expiration time")


ProviderSecrets = Annotated[
    ApiKeySecrets | AwsSecrets | GcpSecrets | ChatGPTOAuthSecrets | XaiOAuthSecrets,
    Field(discriminator="type"),
]

# ---------------------------------------------------------------------------
# Config, stored as plaintext JSONB
# ---------------------------------------------------------------------------


class AwsConfig(BaseModel):
    """AWS Bedrock settings, stored as plaintext."""

    type: Literal["aws_credentials"] = "aws_credentials"
    access_key_id: str = Field(description="AWS Access Key ID")
    region: str = Field(description="AWS region")
    role_arn: str | None = Field(
        default=None, description="IAM Role ARN for STS AssumeRole"
    )

    @field_validator("role_arn")
    @classmethod
    def _validate_role_arn(cls, v: str | None) -> str | None:
        """Validate IAM Role ARN format."""
        if v is not None and not re.fullmatch(r"arn:aws:iam::\d{12}:role/.+", v):
            msg = "Invalid IAM Role ARN format"
            raise ValueError(msg)
        return v


class GcpConfig(BaseModel):
    """Google Vertex AI settings, stored as plaintext."""

    type: Literal["gcp_service_account"] = "gcp_service_account"
    project_id: str = Field(description="GCP project ID")
    region: str = Field(description="GCP region")


class ChatGPTOAuthConfig(BaseModel):
    """ChatGPT OAuth display and status settings."""

    type: Literal["chatgpt_oauth"] = "chatgpt_oauth"
    account_id: str | None = Field(default=None, description="ChatGPT account ID")
    email: str | None = Field(default=None, description="ChatGPT account email")
    plan_type: str | None = Field(default=None, description="ChatGPT plan type")
    connection_method: Literal["callback", "device"] = Field(
        description="Connection method"
    )
    status: Literal[
        "connected",
        "refresh_required",
        "temporarily_unavailable",
        "disabled",
    ] = Field(description="Connection status")
    connected_at: datetime.datetime | None = Field(
        default=None, description="Connected time"
    )
    last_refreshed_at: datetime.datetime | None = Field(
        default=None, description="Last refresh time"
    )
    last_failed_at: datetime.datetime | None = Field(
        default=None, description="Last failure time"
    )
    last_failure_reason: str | None = Field(
        default=None, description="Last failure reason"
    )


class XaiOAuthConfig(BaseModel):
    """xAI OAuth display and status settings."""

    type: Literal["xai_oauth"] = "xai_oauth"
    account_id: str | None = Field(default=None, description="xAI account ID")
    email: str | None = Field(default=None, description="xAI account email")
    connection_method: Literal["device"] = Field(description="Connection method")
    status: Literal[
        "connected",
        "refresh_required",
        "temporarily_unavailable",
        "entitlement_denied",
        "disabled",
    ] = Field(description="Connection status")
    entitlement_status: Literal["denied"] | None = Field(
        default=None, description="xAI OAuth API entitlement state"
    )
    connected_at: datetime.datetime | None = Field(
        default=None, description="Connected time"
    )
    last_refreshed_at: datetime.datetime | None = Field(
        default=None, description="Last refresh time"
    )
    last_failed_at: datetime.datetime | None = Field(
        default=None, description="Last failure time"
    )
    last_failure_reason: str | None = Field(
        default=None, description="Last failure reason"
    )


ProviderConfig = Annotated[
    AwsConfig | GcpConfig | ChatGPTOAuthConfig | XaiOAuthConfig,
    Field(discriminator="type"),
]

# ---------------------------------------------------------------------------
# Provider mapping constants
# ---------------------------------------------------------------------------

# Secret type mapping by provider
PROVIDER_SECRET_TYPES: dict[LLMProvider, str] = {
    LLMProvider.OPENAI: "api_key",
    LLMProvider.CHATGPT_OAUTH: "chatgpt_oauth",
    LLMProvider.XAI: "api_key",
    LLMProvider.XAI_OAUTH: "xai_oauth",
    LLMProvider.ANTHROPIC: "api_key",
    LLMProvider.GOOGLE_GEMINI: "api_key",
    LLMProvider.AWS_BEDROCK: "aws_credentials",
    LLMProvider.GOOGLE_VERTEX_AI: "gcp_service_account",
}

# Provider set requiring Config
PROVIDERS_WITH_CONFIG: set[LLMProvider] = {
    LLMProvider.AWS_BEDROCK,
    LLMProvider.CHATGPT_OAUTH,
    LLMProvider.XAI_OAUTH,
    LLMProvider.GOOGLE_VERTEX_AI,
}
