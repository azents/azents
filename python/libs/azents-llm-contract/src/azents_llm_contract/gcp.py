"""Google service-account call material, never OAuth refresh configurations."""

import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

Nonempty = Annotated[str, Field(min_length=1)]


class ServiceAccountKey(BaseModel):
    """Decode the official key-file shape before discarding unused metadata."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, frozen=True)

    type: Literal["service_account"]
    private_key: SecretStr = Field(min_length=1, repr=False)
    client_email: Nonempty
    token_uri: Literal["https://oauth2.googleapis.com/token"]
    project_id: Nonempty | None = None
    private_key_id: Nonempty | None = None
    client_id: Nonempty | None = None
    auth_uri: Nonempty | None = None
    auth_provider_x509_cert_url: Nonempty | None = None
    client_x509_cert_url: Nonempty | None = None
    universe_domain: Literal["googleapis.com"] | None = None
    quota_project_id: Nonempty | None = None


_CALL_FIELDS = frozenset(
    {
        "type",
        "private_key",
        "client_email",
        "token_uri",
        "project_id",
        "private_key_id",
        "universe_domain",
        "quota_project_id",
    }
)


def service_account_call_json(value: str) -> str:
    """Explicit protected egress; caller must never log this return value.

    Ordinary model dumps remain redacted. Only fields used by the service-account
    call credential constructor cross the private channel, not auth/cert UI URLs.
    Google user/external-account configurations and refresh-token fields fail closed.
    """
    material = ServiceAccountKey.model_validate_json(value)
    document = material.model_dump(
        mode="json", include=set(_CALL_FIELDS), exclude_none=True
    )
    document["private_key"] = material.private_key.get_secret_value()
    return json.dumps(document, ensure_ascii=False, separators=(",", ":"))
