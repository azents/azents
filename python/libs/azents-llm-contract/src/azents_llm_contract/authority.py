"""Closed payloads for the private authority channel, never inference bodies."""

from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    SecretStr,
    SerializationInfo,
)


def _serialize_secret(value: SecretStr, info: SerializationInfo) -> str:
    if info.context == {"protected_transport": True}:
        return value.get_secret_value()
    return "**********"


def _validate_secret(value: SecretStr) -> SecretStr:
    if not value.get_secret_value():
        raise ValueError("Credential must be nonempty.")
    return value


ProtectedSecret = Annotated[
    SecretStr, AfterValidator(_validate_secret), PlainSerializer(_serialize_secret)
]
Identifier = Annotated[str, Field(min_length=1, max_length=256)]
TargetId = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
ModelName = Annotated[str, Field(min_length=1, max_length=2048)]


class AuthorityPayload(BaseModel):
    """Reject unknown fields and redact secrets in ordinary representations."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    def protected_json(self) -> str:
        """Serialize secrets ONLY for the authenticated encrypted wire channel.

        Never pass this result to logs, caches, or exception diagnostics.
        """
        return self.model_dump_json(context={"protected_transport": True})


class ModelListRequest(AuthorityPayload):
    agent_token: ProtectedSecret = Field(repr=False)


class ResolveRequest(ModelListRequest):
    model: ModelName
    target_id: TargetId


class AuthenticatedIdentity(AuthorityPayload):
    agent_id: Identifier
    workspace_id: Identifier
    supply_id: Identifier
    token_id: Identifier


class ModelListResponse(AuthorityPayload):
    identity: AuthenticatedIdentity
    models: tuple[ModelName, ...]


class ApiKeyCredential(AuthorityPayload):
    kind: Literal["api_key"]
    provider: Literal["openai", "anthropic", "google_gemini", "xai", "openrouter"]
    api_key: ProtectedSecret = Field(repr=False)


class ChatGPTCredential(AuthorityPayload):
    kind: Literal["chatgpt_oauth"]
    access_token: ProtectedSecret = Field(repr=False)
    account_id: Identifier | None


class XaiCredential(AuthorityPayload):
    kind: Literal["xai_oauth"]
    access_token: ProtectedSecret = Field(repr=False)


class KimiCredential(AuthorityPayload):
    kind: Literal["kimi_oauth"]
    access_token: ProtectedSecret = Field(repr=False)
    device_id: ProtectedSecret = Field(repr=False)


class BedrockCredential(AuthorityPayload):
    kind: Literal["aws_bedrock"]
    access_key_id: ProtectedSecret = Field(repr=False)
    secret_access_key: ProtectedSecret = Field(repr=False)
    region: Identifier
    role_arn: str | None
    role_session_name: str | None


class VertexCredential(AuthorityPayload):
    kind: Literal["google_vertex_ai"]
    service_account_json: ProtectedSecret = Field(repr=False)
    project_id: Identifier
    location: Identifier


ProviderCredential = Annotated[
    ApiKeyCredential
    | ChatGPTCredential
    | XaiCredential
    | KimiCredential
    | BedrockCredential
    | VertexCredential,
    Field(discriminator="kind"),
]


class TargetBinding(AuthorityPayload):
    """Server-verified route identity; client metadata cannot create this value."""

    identity: AuthenticatedIdentity
    integration_id: Identifier
    target_id: TargetId
    public_model: ModelName
    model_identifier: ModelName
    credential: ProviderCredential = Field(repr=False)


class TokenIssueRequest(AuthorityPayload):
    """Privileged issuer input, not an Agent-authenticated operation."""

    agent_id: Identifier
    supply_subject: Identifier


class TokenRotateRequest(AuthorityPayload):
    supply_id: Identifier
    expected_token_id: Identifier


class IssuedToken(AuthorityPayload):
    supply_id: Identifier
    token_id: Identifier
    agent_token: ProtectedSecret = Field(repr=False)
    expires_at: AwareDatetime
    predecessor_expires_at: AwareDatetime | None
